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
from nmb.bot.i18n import ALERT_TEMPLATES, format_alert, get_chat_lang
from nmb.config import Config
from nmb.db import database as db
import nmb.common.heal as heal

log = logging.getLogger("nmb.bot.alerts")


class AlertMonitor:
    def __init__(self, cfg: Config, client: TelegramClient):
        self.cfg = cfg
        self.client = client
        self.recipients = cfg.telegram.allowed_chat_ids

    def _broadcast(self, msg_or_key: str, **kwargs) -> None:
        for chat_id in self.recipients:
            try:
                if kwargs or msg_or_key in ALERT_TEMPLATES.get("en", {}):
                    lang = get_chat_lang(chat_id, self.cfg)
                    msg = format_alert(msg_or_key, lang, **kwargs)
                else:
                    msg = msg_or_key
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
            "SELECT id, start_ts, end_ts, cause FROM outage WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
        ).fetchone()
        if ongoing:
            # A row left open by a probe that stopped is over once pings are answered again; otherwise the alert
            # stayed "firing" and a real outage later sent no alert (2026-11-10).
            from nmb.report.metrics import effective_outage_ends
            if effective_outage_ends(conn, [ongoing], db.now_ms()).get(ongoing["id"]):
                ongoing = None

        cur_state = self._get_alert_state(conn, "outage")

        if ongoing and cur_state != "firing":
            cause = ongoing["cause"] or "No probe targets reachable"
            self._broadcast("outage_start", cause=cause, box_id=self.cfg.system.box_id)
            self._set_alert_state(conn, "outage", "firing", f"Outage start: {cause}")
            log.warning("broadcast outage start alert")

        elif not ongoing and cur_state == "firing":
            last_out = conn.execute(
                "SELECT start_ts, end_ts FROM outage ORDER BY end_ts DESC LIMIT 1"
            ).fetchone()
            dur_sec = int((last_out["end_ts"] - last_out["start_ts"]) / 1000) if last_out and last_out["end_ts"] else 0
            self._broadcast("outage_resolved", dur=dur_sec, box_id=self.cfg.system.box_id)
            self._set_alert_state(conn, "outage", "resolved", f"Outage resolved ({dur_sec}s)")
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
            self._broadcast(
                "packet_loss_firing",
                loss=loss_pct,
                threshold=threshold,
                lost=lost,
                sent=sent,
                box_id=self.cfg.system.box_id
            )
            self._set_alert_state(conn, "packet_loss", "firing", f"Loss {loss_pct:.1f}%")

        elif loss_pct < (threshold * 0.5) and cur_state == "firing":
            self._broadcast("packet_loss_resolved", loss=loss_pct)
            self._set_alert_state(conn, "packet_loss", "resolved", f"Loss recovered {loss_pct:.1f}%")

    def check_latency_and_jitter(self, conn: sqlite3.Connection) -> None:
        """Alert when the 5-minute average latency or jitter stays above its threshold."""
        now = int(time.time() * 1000)
        row = conn.execute(
            "SELECT AVG(rtt_avg), AVG(jitter_us), SUM(sent) FROM ping_minute WHERE ts >= ? AND rtt_avg IS NOT NULL",
            (now - 300_000,),
        ).fetchone()
        if not row or not row[2] or row[2] < 20:
            return
        checks = (
            ("latency", (row[0] or 0) / 1000.0, self.cfg.telegram.alert_latency_threshold_ms),
            ("jitter", (row[1] or 0) / 1000.0, getattr(self.cfg.telegram, "alert_jitter_threshold_ms", 30.0)),
        )
        for name, value, threshold in checks:
            if threshold <= 0:
                continue
            state = self._get_alert_state(conn, name)
            if value >= threshold and state != "firing":
                self._broadcast(f"{name}_firing", value=value, threshold=threshold, box_id=self.cfg.system.box_id)
                self._set_alert_state(conn, name, "firing", f"{name} {value:.1f} ms")
            elif value < threshold * 0.7 and state == "firing":
                self._broadcast(f"{name}_resolved", value=value)
                self._set_alert_state(conn, name, "resolved", f"{name} recovered {value:.1f} ms")

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
                log.debug("suppressed exception", exc_info=True)

        cur_state = self._get_alert_state(conn, "service_failure")

        if failed and cur_state != "firing":
            svc_list = ", ".join(f"<code>{s}</code>" for s in failed)
            self._broadcast("service_failure_firing", services=svc_list)
            self._set_alert_state(conn, "service_failure", "firing", f"Failed: {svc_list}")

            # Trigger automated repair
            try:
                heal.auto_heal_all(force_tier=1)
            except Exception as e:
                log.warning("automated self-heal invocation error: %s", e)

        elif not failed and cur_state == "firing":
            self._broadcast("service_failure_resolved")
            self._set_alert_state(conn, "service_failure", "resolved", "All services active")

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
            log.debug("suppressed exception", exc_info=True)

        cur_thermal_state = self._get_alert_state(conn, "hardware_overheat")
        if temp_c is not None:
            if temp_c >= 82.0 and cur_thermal_state != "firing":
                self._broadcast("overheat_firing", temp=temp_c)
                self._set_alert_state(conn, "hardware_overheat", "firing", f"Overheat {temp_c:.1f}C")
            elif temp_c < 72.0 and cur_thermal_state == "firing":
                self._broadcast("overheat_resolved", temp=temp_c)
                self._set_alert_state(conn, "hardware_overheat", "resolved", f"Temp normalized {temp_c:.1f}C")

        # B. Low Disk Space (< 500 MB)
        try:
            stat = shutil.disk_usage("/")
            free_mb = stat.free / (1024 * 1024)
            cur_disk_state = self._get_alert_state(conn, "low_disk")

            if free_mb < 500 and cur_disk_state != "firing":
                self._broadcast("low_disk_firing", free=free_mb)
                self._set_alert_state(conn, "low_disk", "firing", f"Low disk: {free_mb:.0f} MB")
            elif free_mb >= 1000 and cur_disk_state == "firing":
                self._broadcast("low_disk_resolved", free=free_mb)
                self._set_alert_state(conn, "low_disk", "resolved", f"Disk recovered: {free_mb:.0f} MB")
        except Exception:
            log.debug("suppressed exception", exc_info=True)

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
            self._broadcast("wan_failover_firing", primary=primary_iface, active=active_iface)
            self._set_alert_state(conn, "wan_failover", "firing", f"Failover to {active_iface}")
        elif active_iface == primary_iface and cur_state == "firing":
            self._broadcast("wan_failover_resolved", primary=primary_iface)
            self._set_alert_state(conn, "wan_failover", "resolved", f"WAN restored {primary_iface}")

    def check_data_cap(self, conn: sqlite3.Connection) -> None:
        """Tell the owner when a data cap stopped the automatic tests on a link, and when they run again."""
        from nmb.speed import data_cap
        try:
            u = data_cap.usage(conn, self.cfg)
        except Exception:
            log.debug("data cap usage not read", exc_info=True)
            return
        reached = [l for l in u["links"] if l["reached"]]
        cur_state = self._get_alert_state(conn, "data_cap")
        if reached and cur_state != "firing":
            links = ", ".join(
                f"{l['link']} ({l['used_mb']:.0f} of {l['cap_mb']} MB)" if l["cap_mb"] and l["used_mb"] >= l["cap_mb"]
                else f"{l['link']} ({l['type']}: {l['type_used_mb']:.0f} of {l['type_cap_mb']} MB)"
                for l in reached)
            self._broadcast("data_cap_firing", links=links, next=u["next_reset"])
            self._set_alert_state(conn, "data_cap", "firing", f"Data cap reached: {links}")
        elif not reached and cur_state == "firing":
            self._broadcast("data_cap_resolved")
            self._set_alert_state(conn, "data_cap", "resolved", "Automatic tests run again")

    # =========================================================================
    # Main Periodic Execution Loop
    # =========================================================================

    def run_checks(self) -> None:
        try:
            conn = db.connect()
            self.check_outages(conn)
            self.check_packet_loss(conn)
            self.check_latency_and_jitter(conn)
            self.check_service_health(conn)
            self.check_system_resources(conn)
            self.check_wan_failover(conn)
            self.check_data_cap(conn)
            conn.close()
        except Exception as e:
            log.error("error during alert check: %s", e)
