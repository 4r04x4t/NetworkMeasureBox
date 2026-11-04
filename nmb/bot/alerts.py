"""Proactive alert monitor for NetworkMeasureBox Telegram integration.

Monitors:
- Outages (all probe targets down) & recovery
- Rolling packet loss spikes & recovery
- Core daemon crashes & automated self-healing triggers
- Hardware temperature spikes (Raspberry Pi thermal zone)
- Critically low disk space (< 500 MB)
- Dual-WAN automatic failover & link recovery

Tracks active alert state in SQLite to eliminate alert spamming.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from nmb.bot.client import TelegramClient
from nmb.config import Config
from nmb.db import database as db
import nmb.common.heal as heal

log = logging.getLogger("nmb.bot.alerts")


class AlertMonitor:
    def __init__(self, cfg: Config, client: TelegramClient):
        self.cfg = cfg
        self.client = client
        self.recipients = cfg.telegram.allowed_chat_ids

    def _broadcast(self, msg: str) -> None:
        for chat_id in self.recipients:
            try:
                self.client.send_message(chat_id, msg)
            except Exception as e:
                log.warning("failed to send alert to %d: %s", chat_id, e)

    def _get_alert_state(self, conn: sqlite3.Connection, rule: str) -> Optional[str]:
        row = conn.execute(
            "SELECT state FROM alert WHERE rule = ? ORDER BY ts DESC LIMIT 1",
            (rule,)
        ).fetchone()
        return row["state"] if row else None

    def _set_alert_state(self, conn: sqlite3.Connection, rule: str, state: str, message: str) -> None:
        with db.tx(conn):
            conn.execute(
                "INSERT INTO alert (ts, rule, state, message) VALUES (?, ?, ?, ?)",
                (db.now_ms(), rule, state, message)
            )

    # =========================================================================
    # 1. Network Outages & Connectivity
    # =========================================================================

    def check_outages(self, conn: sqlite3.Connection) -> None:
        """Check for ongoing or recently resolved outages."""
        ongoing = conn.execute(
            "SELECT id, start_ts, cause FROM outage WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
        ).fetchone()

        cur_state = self._get_alert_state(conn, "outage")

        if ongoing and cur_state != "firing":
            cause = ongoing["cause"] or "No probe targets reachable"
            msg = (
                f"🚨 <b>CRITICAL NETWORK OUTAGE DETECTED</b>\n\n"
                f"All probe targets unreachable.\n"
                f"Cause: <i>{cause}</i>\n"
                f"Box ID: <code>{self.cfg.system.box_id}</code>"
            )
            self._broadcast(msg)
            self._set_alert_state(conn, "outage", "firing", msg)
            log.warning("broadcast outage start alert")

        elif not ongoing and cur_state == "firing":
            last_out = conn.execute(
                "SELECT start_ts, end_ts FROM outage ORDER BY end_ts DESC LIMIT 1"
            ).fetchone()
            dur_sec = int((last_out["end_ts"] - last_out["start_ts"]) / 1000) if last_out else 0
            msg = (
                f"✅ <b>NETWORK OUTAGE RESOLVED</b>\n\n"
                f"Internet connectivity restored.\n"
                f"Total downtime: <b>{dur_sec}s</b>\n"
                f"Box ID: <code>{self.cfg.system.box_id}</code>"
            )
            self._broadcast(msg)
            self._set_alert_state(conn, "outage", "resolved", msg)
            log.info("broadcast outage resolved alert")

    # =========================================================================
    # 2. Rolling Packet Loss Spikes
    # =========================================================================

    def check_packet_loss(self, conn: sqlite3.Connection) -> None:
        """Check 5-minute rolling packet loss against configured threshold."""
        now = db.now_ms()
        row = conn.execute(
            """SELECT SUM(sent) as s, SUM(lost) as l
               FROM ping_minute
               WHERE ts >= ?""",
            (now - 300_000,)
        ).fetchone()

        if not row or not row["s"] or row["s"] < 20:
            return

        sent = row["s"]
        lost = row["l"] or 0
        loss_pct = (lost / sent) * 100.0

        cur_state = self._get_alert_state(conn, "packet_loss")
        threshold = self.cfg.telegram.alert_loss_threshold_pct

        if loss_pct >= threshold and cur_state != "firing":
            msg = (
                f"⚠️ <b>HIGH PACKET LOSS ALERT</b>\n\n"
                f"Rolling loss: <b>{loss_pct:.1f}%</b> (threshold: {threshold:.1f}%)\n"
                f"Packets: {lost} lost / {sent} sent (past 5 min)\n"
                f"Box ID: <code>{self.cfg.system.box_id}</code>"
            )
            self._broadcast(msg)
            self._set_alert_state(conn, "packet_loss", "firing", msg)

        elif loss_pct < (threshold * 0.5) and cur_state == "firing":
            msg = f"✅ <b>PACKET LOSS RECOVERED</b>\n\nPacket loss normalized to <b>{loss_pct:.1f}%</b>."
            self._broadcast(msg)
            self._set_alert_state(conn, "packet_loss", "resolved", msg)

    # =========================================================================
    # 3. Core Daemon Health & Self-Healing
    # =========================================================================

    def check_service_health(self, conn: sqlite3.Connection) -> None:
        """Monitor core system daemons. Trigger automatic self-healing on failure."""
        core_services = ["nmb-netd", "nmb-web", "nmb-probe", "nmb-scheduler"]
        failed = []

        systemctl = shutil.which("systemctl")
        if not systemctl:
            return

        for svc in core_services:
            try:
                res = subprocess.run([systemctl, "is-active", svc], capture_output=True, text=True, timeout=2)
                if res.stdout.strip() != "active":
                    failed.append(svc)
            except Exception:
                pass

        cur_state = self._get_alert_state(conn, "service_failure")

        if failed and cur_state != "firing":
            svc_list = ", ".join(f"<code>{s}</code>" for s in failed)
            msg = (
                f"🚨 <b>SYSTEM SERVICE FAILURE DETECTED</b>\n\n"
                f"Failed service(s): {svc_list}\n"
                f"Triggering automated Self-Healing Tier 1 recovery..."
            )
            self._broadcast(msg)
            self._set_alert_state(conn, "service_failure", "firing", msg)

            # Trigger automated repair
            try:
                heal.auto_heal_all(self.cfg, tier=1)
            except Exception as e:
                log.warning("automated self-heal invocation error: %s", e)

        elif not failed and cur_state == "firing":
            msg = "✅ <b>ALL SYSTEM SERVICES RESTORED</b>\n\nAll core daemons are active and operational."
            self._broadcast(msg)
            self._set_alert_state(conn, "service_failure", "resolved", msg)

    # =========================================================================
    # 4. Hardware Resources & Thermal Overheating
    # =========================================================================

    def check_system_resources(self, conn: sqlite3.Connection) -> None:
        """Monitor CPU temperature and disk free space."""
        # A. Thermal Overheating
        temp_c: Optional[float] = None
        try:
            temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
            if temp_path.exists():
                raw = temp_path.read_text().strip()
                if raw.isdigit():
                    temp_c = float(raw) / 1000.0
        except Exception:
            pass

        cur_thermal_state = self._get_alert_state(conn, "hardware_overheat")
        if temp_c is not None:
            if temp_c >= 82.0 and cur_thermal_state != "firing":
                msg = (
                    f"🔥 <b>HARDWARE OVERHEATING WARNING</b>\n\n"
                    f"SoC / CPU Temperature: <b>{temp_c:.1f}°C</b> (limit: 82°C)\n"
                    f"Check ambient airflow or cooling."
                )
                self._broadcast(msg)
                self._set_alert_state(conn, "hardware_overheat", "firing", msg)
            elif temp_c < 72.0 and cur_thermal_state == "firing":
                msg = f"✅ <b>TEMPERATURE NORMALIZED</b>\n\nCPU temperature returned to safe range: <b>{temp_c:.1f}°C</b>."
                self._broadcast(msg)
                self._set_alert_state(conn, "hardware_overheat", "resolved", msg)

        # B. Low Disk Space (< 500 MB)
        try:
            stat = shutil.disk_usage("/")
            free_mb = stat.free / (1024 * 1024)
            cur_disk_state = self._get_alert_state(conn, "low_disk")

            if free_mb < 500 and cur_disk_state != "firing":
                msg = (
                    f"💾 <b>LOW DISK STORAGE WARNING</b>\n\n"
                    f"Free space on root partition: <b>{free_mb:.0f} MB</b> (&lt; 500 MB)\n"
                    f"Consider clearing old backups: <code>/backup list</code>"
                )
                self._broadcast(msg)
                self._set_alert_state(conn, "low_disk", "firing", msg)
            elif free_mb >= 1000 and cur_disk_state == "firing":
                msg = f"✅ <b>DISK STORAGE RECOVERED</b>\n\nFree disk space: <b>{free_mb:.0f} MB</b>."
                self._broadcast(msg)
                self._set_alert_state(conn, "low_disk", "resolved", msg)
        except Exception:
            pass

    # =========================================================================
    # 5. Dual-WAN Failover
    # =========================================================================

    def check_wan_failover(self, conn: sqlite3.Connection) -> None:
        """Monitor active WAN uplink and alert on automatic failover events."""
        primary_iface = self.cfg.network.wan_interface
        wan_row = conn.execute("SELECT v FROM kv WHERE k = 'active_wan_iface'").fetchone()
        active_iface = wan_row["v"] if wan_row else primary_iface

        cur_state = self._get_alert_state(conn, "wan_failover")

        if active_iface != primary_iface and cur_state != "firing":
            msg = (
                f"🔀 <b>WAN FAILOVER ENGAGED</b>\n\n"
                f"Primary WAN (<code>{primary_iface}</code>) link failed.\n"
                f"Switched to backup interface: <code>{active_iface}</code>."
            )
            self._broadcast(msg)
            self._set_alert_state(conn, "wan_failover", "firing", msg)
        elif active_iface == primary_iface and cur_state == "firing":
            msg = (
                f"✅ <b>PRIMARY WAN LINK RESTORED</b>\n\n"
                f"Traffic routed back to primary interface: <code>{primary_iface}</code>."
            )
            self._broadcast(msg)
            self._set_alert_state(conn, "wan_failover", "resolved", msg)

    # =========================================================================
    # Main Periodic Execution Loop
    # =========================================================================

    def run_checks(self) -> None:
        try:
            conn = db.connect()
            self.check_outages(conn)
            self.check_packet_loss(conn)
            self.check_service_health(conn)
            self.check_system_resources(conn)
            self.check_wan_failover(conn)
            conn.close()
        except Exception as e:
            log.error("error during alert check: %s", e)
