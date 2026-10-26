"""Telegram command dispatcher and response formatters.

Implements /status, /ping, /test, /report, /mode, and /help.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

from nmb.bot.client import TelegramClient
from nmb.config import Config
from nmb.db import database as db
from nmb.netd import interfaces
from nmb.report.dossier import generate_html_dossier
from nmb.report.metrics import aggregate_report_data
from nmb.speed.runner import run_measurement_cycle

log = logging.getLogger("nmb.bot.commands")


class CommandHandler:
    def __init__(self, cfg: Config, client: TelegramClient):
        self.cfg = cfg
        self.client = client

    def handle_command(self, chat_id: int, text: str) -> None:
        parts = text.strip().split()
        if not parts:
            return
        cmd = parts[0].lower().split("@")[0]  # strip @bot_name if present
        args = parts[1:]

        if cmd in ("/start", "/help"):
            self._cmd_help(chat_id)
        elif cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd == "/ping":
            self._cmd_ping(chat_id)
        elif cmd == "/test":
            self._cmd_test(chat_id)
        elif cmd == "/report":
            self._cmd_report(chat_id)
        elif cmd == "/mode":
            self._cmd_mode(chat_id, args)
        else:
            self.client.send_message(
                chat_id,
                f"Unknown command: <code>{cmd}</code>. Type /help to see available commands."
            )

    def _cmd_help(self, chat_id: int) -> None:
        msg = f"""<b>NetworkMeasureBox Management Bot</b>
<i>Unit ID: {self.cfg.system.box_id}</i>

<b>Available Commands:</b>
/status - Network mode, link carrier & SLA summary
/ping - Real-time latency and packet loss across probe targets
/test - Trigger an immediate bandwidth speedtest
/report - Compile and receive the 24-hour HTML telemetry dossier
/mode <code>[auto|mode_a|mode_b]</code> - View or switch operational mode
/help - Show this manual
"""
        self.client.send_message(chat_id, msg)

    def _cmd_status(self, chat_id: int) -> None:
        try:
            conn = db.connect(readonly=True)
            mode_row = conn.execute("SELECT v FROM kv WHERE k = 'active_mode'").fetchone()
            wan_row = conn.execute("SELECT v FROM kv WHERE k = 'active_wan_iface'").fetchone()
            active_mode = (mode_row["v"] if mode_row else "unknown").upper()
            wan_iface = wan_row["v"] if wan_row else self.cfg.network.wan_interface

            # 24h report summary
            rep = aggregate_report_data(conn, self.cfg, window_hours=24.0)
            conn.close()

            wan_carrier = "UP" if interfaces.get_carrier(self.cfg.network.wan_interface) else "DOWN"
            lan_carrier = "UP" if interfaces.get_carrier(self.cfg.network.lan_interface) else "DOWN"

            msg = f"""<b>System Status & Health</b> [<code>{self.cfg.system.box_id}</code>]

<b>Operational Mode:</b> <code>{active_mode}</code>
<b>Physical Links:</b> WAN: <b>{wan_carrier}</b> | LAN: <b>{lan_carrier}</b>
<b>Active Gateway IF:</b> <code>{wan_iface}</code>

<b>24h Availability:</b> <b>{rep.uptime_pct:.2f}%</b> ({len(rep.outages)} outages)
<b>Packet Loss:</b> <b>{rep.ping_summary.loss_pct:.2f}%</b>
<b>Mean Latency:</b> {rep.ping_summary.rtt_avg_ms or '-'} ms (P95: {rep.ping_summary.rtt_p95_ms or '-'} ms)
<b>SLA Verdict:</b> <b>{rep.sla_verdict}</b>
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            log.error("error in /status: %s", e)
            self.client.send_message(chat_id, f"Error generating status: {e}")

    def _cmd_ping(self, chat_id: int) -> None:
        try:
            conn = db.connect(readonly=True)
            now = db.now_ms()
            # Fetch samples from last 60 seconds
            rows = conn.execute(
                """SELECT t.addr, t.label, AVG(p.rtt_us) as avg_us,
                          COUNT(*) as count,
                          SUM(CASE WHEN p.rtt_us IS NULL THEN 1 ELSE 0 END) as lost
                   FROM target t
                   LEFT JOIN ping_sample p ON t.id = p.target_id AND p.ts >= ?
                   GROUP BY t.id""",
                (now - 60_000,)
            ).fetchall()
            conn.close()

            lines = ["<b>Real-Time Probe Latency (Past 60s):</b>\n"]
            for r in rows:
                cnt = r["count"]
                lost = r["lost"]
                loss_pct = (lost / cnt * 100.0) if cnt > 0 else 0.0
                avg_ms = f"{(r['avg_us'] / 1000.0):.1f} ms" if r["avg_us"] else "No Reply"
                loss_str = f"loss: {loss_pct:.0f}%"
                lines.append(f"• <b>{r['label']}</b> (<code>{r['addr']}</code>): <b>{avg_ms}</b> ({loss_str})")

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Error querying pings: {e}")

    def _cmd_test(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Initiating bandwidth speedtest... (may take up to 20 seconds)</i>")
        try:
            # Run test with force=True for immediate execution
            ok = run_measurement_cycle(self.cfg, trigger="telegram", force=True, run_port_check=True)

            conn = db.connect(readonly=True)
            row = conn.execute(
                """SELECT down_bps, up_bps, ping_us, jitter_us, loss_pct, server_name, status
                   FROM speedtest ORDER BY ts DESC LIMIT 1"""
            ).fetchone()
            conn.close()

            if not row or row["status"] != "ok":
                self.client.send_message(chat_id, "Speedtest failed or was deferred.")
                return

            down_mbps = (row["down_bps"] or 0) / 1_000_000.0
            up_mbps = (row["up_bps"] or 0) / 1_000_000.0
            ping_ms = (row["ping_us"] or 0) / 1000.0

            down_compliance = (down_mbps / self.cfg.isp.contract_down_mbps) * 100.0
            up_compliance = (up_mbps / self.cfg.isp.contract_up_mbps) * 100.0

            msg = f"""<b>Speedtest Results:</b>

<b>Download:</b> <b>{down_mbps:.1f} Mbps</b> ({down_compliance:.0f}% of plan)
<b>Upload:</b> <b>{up_mbps:.1f} Mbps</b> ({up_compliance:.0f}% of plan)
<b>Latency:</b> {ping_ms:.1f} ms (jitter: {(row['jitter_us'] or 0)/1000.0:.1f} ms)
<b>Server:</b> {row['server_name'] or 'Edge Mirror'}
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Speedtest error: {e}")

    def _cmd_report(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Compiling 24-hour telemetry dossier and charts...</i>")
        try:
            conn = db.connect()
            report = aggregate_report_data(conn, self.cfg, window_hours=24.0)
            conn.close()

            html_doc = generate_html_dossier(report)
            filename = f"dossier_{self.cfg.system.box_id}_{int(time.time())}.html"

            caption = (
                f"<b>Network Telemetry Dossier (24h)</b>\n"
                f"SLA Verdict: <b>{report.sla_verdict}</b> | Availability: <b>{report.uptime_pct:.2f}%</b>"
            )

            ok = self.client.send_document(chat_id, filename, html_doc.encode("utf-8"), caption=caption)
            if not ok:
                self.client.send_message(chat_id, "Dossier compiled, but sending attachment failed.")
        except Exception as e:
            self.client.send_message(chat_id, f"Report compilation error: {e}")

    def _cmd_mode(self, chat_id: int, args: list[str]) -> None:
        if not args:
            conn = db.connect(readonly=True)
            row = conn.execute("SELECT v FROM kv WHERE k = 'active_mode'").fetchone()
            ovr = conn.execute("SELECT v FROM kv WHERE k = 'override_mode'").fetchone()
            conn.close()
            cur_mode = row["v"] if row else "unknown"
            cur_ovr = ovr["v"] if ovr else "none"
            self.client.send_message(
                chat_id,
                f"Current mode: <b>{cur_mode}</b> (override: <code>{cur_ovr}</code>)\n"
                f"To switch, use: <code>/mode auto</code>, <code>/mode standalone</code>, <code>/mode mode_a</code>, or <code>/mode mode_b</code>."
            )
            return

        target_mode = args[0].lower()
        if target_mode not in ("auto", "standalone", "mode_a", "mode_b"):
            self.client.send_message(chat_id, "Invalid mode. Choose: <code>auto</code>, <code>standalone</code>, <code>mode_a</code>, or <code>mode_b</code>.")
            return

        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                "INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('override_mode', ?, ?)",
                (target_mode, db.now_ms())
            )
        conn.close()

        self.client.send_message(
            chat_id,
            f"Override mode updated to <b>{target_mode}</b>. The network daemon will transition shortly."
        )
