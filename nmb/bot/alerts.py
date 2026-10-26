"""Proactive alert monitor for outages, packet loss spikes, and latency degradation.

Tracks active alert state in the SQLite alert table to avoid alert spamming.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import List, Optional

from nmb.bot.client import TelegramClient
from nmb.config import Config
from nmb.db import database as db

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

    def check_outages(self, conn: sqlite3.Connection) -> None:
        """Check for ongoing or recently resolved outages."""
        # Ongoing outage?
        ongoing = conn.execute(
            "SELECT id, start_ts, cause FROM outage WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
        ).fetchone()

        cur_state = self._get_alert_state(conn, "outage")

        if ongoing and cur_state != "firing":
            msg = f"🚨 <b>CRITICAL NETWORK OUTAGE DETECTED</b>\n\nAll probe targets unreachable.\nCause: <i>{ongoing['cause']}</i>\nBox ID: <code>{self.cfg.system.box_id}</code>"
            self._broadcast(msg)
            self._set_alert_state(conn, "outage", "firing", msg)
            log.warning("broadcast outage start alert")

        elif not ongoing and cur_state == "firing":
            # Just resolved
            last_out = conn.execute(
                "SELECT start_ts, end_ts FROM outage ORDER BY end_ts DESC LIMIT 1"
            ).fetchone()
            dur_sec = int((last_out["end_ts"] - last_out["start_ts"]) / 1000) if last_out else 0
            msg = f"✅ <b>NETWORK OUTAGE RESOLVED</b>\n\nConnectivity restored.\nTotal downtime: <b>{dur_sec}s</b>\nBox ID: <code>{self.cfg.system.box_id}</code>"
            self._broadcast(msg)
            self._set_alert_state(conn, "outage", "resolved", msg)
            log.info("broadcast outage resolved alert")

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
            msg = f"⚠️ <b>HIGH PACKET LOSS ALERT</b>\n\nRolling loss: <b>{loss_pct:.1f}%</b> (threshold: {threshold:.1f}%)\nPackets: {lost} lost / {sent} sent (past 5 min)"
            self._broadcast(msg)
            self._set_alert_state(conn, "packet_loss", "firing", msg)

        elif loss_pct < (threshold * 0.5) and cur_state == "firing":
            msg = f"✅ <b>PACKET LOSS RECOVERED</b>\n\nPacket loss normalized to <b>{loss_pct:.1f}%</b>."
            self._broadcast(msg)
            self._set_alert_state(conn, "packet_loss", "resolved", msg)

    def run_checks(self) -> None:
        try:
            conn = db.connect()
            self.check_outages(conn)
            self.check_packet_loss(conn)
            conn.close()
        except Exception as e:
            log.error("error during alert check: %s", e)
