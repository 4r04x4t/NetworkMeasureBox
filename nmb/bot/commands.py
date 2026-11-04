"""Telegram command dispatcher and response formatters for NetworkMeasureBox.

Comprehensive command suite covering:
- 📡 Diagnostics & Performance: /status, /ping, /test, /report, /ai, /mode
- 🛡️ VPN Server (WireGuard & OpenVPN): /vpn, /wireguard, /pivpn
- 🛡️ DNS Ad-Blocker (Pi-hole Sinkhole): /adblock, /pihole
- 🩺 Self-Healing & System Audit: /heal, /repair, /audit
- 📊 Tasks & Resource Load: /tasks, /top, /kill
- 📶 Wi-Fi & Guest Wi-Fi Probe: /wifi
- 📦 Backups & Disaster Recovery: /backup
- 🔧 Hardware Drivers & Controllers: /drivers
- 🔄 System Power: /reboot
"""
from __future__ import annotations

import html
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from nmb.bot.client import TelegramClient
from nmb.config import Config
from nmb.db import database as db
from nmb.netd import interfaces
from nmb.report.dossier import generate_html_dossier
from nmb.report.metrics import aggregate_report_data
from nmb.speed.runner import run_measurement_cycle

# Modular subsystem imports
import nmb.netd.wireguard as wg
import nmb.netd.openvpn as ovpn
import nmb.netd.adblock as ab
import nmb.common.heal as heal
import nmb.common.tasks as tasks
import nmb.netd.guest_wifi as gw
import nmb.common.backup as backup
import nmb.netd.drivers as drivers
import nmb.report.llm_bundle as llm_bundle

log = logging.getLogger("nmb.bot.commands")


def format_bytes(num_bytes: int | float) -> str:
    """Format bytes into human-readable string (B, KB, MB, GB, TB)."""
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(val) < 1024.0:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


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

        # Dispatch table
        if cmd in ("/start", "/help"):
            self._cmd_help(chat_id)
        elif cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd == "/ping":
            self._cmd_ping(chat_id)
        elif cmd in ("/test", "/speedtest"):
            self._cmd_test(chat_id, args)
        elif cmd == "/report":
            self._cmd_report(chat_id)
        elif cmd in ("/ai", "/diag", "/llm"):
            self._cmd_ai(chat_id)
        elif cmd == "/mode":
            self._cmd_mode(chat_id, args)
        elif cmd in ("/vpn", "/wireguard", "/pivpn"):
            self._cmd_vpn(chat_id, args)
        elif cmd in ("/adblock", "/pihole", "/sinkhole"):
            self._cmd_adblock(chat_id, args)
        elif cmd in ("/heal", "/repair", "/audit"):
            self._cmd_heal(chat_id, args)
        elif cmd in ("/tasks", "/top", "/htop", "/ps"):
            self._cmd_tasks(chat_id)
        elif cmd == "/kill":
            self._cmd_kill(chat_id, args)
        elif cmd in ("/wifi", "/wlan"):
            self._cmd_wifi(chat_id, args)
        elif cmd in ("/backup", "/backups"):
            self._cmd_backup(chat_id, args)
        elif cmd in ("/drivers", "/driver"):
            self._cmd_drivers(chat_id)
        elif cmd == "/reboot":
            self._cmd_reboot(chat_id, args)
        else:
            self.client.send_message(
                chat_id,
                f"Unknown command: <code>{html.escape(cmd)}</code>. Type /help to see all available commands."
            )

    # =========================================================================
    # 1. Help & Navigation
    # =========================================================================

    def _cmd_help(self, chat_id: int) -> None:
        box_id = html.escape(str(self.cfg.system.box_id))
        msg = f"""<b>NetworkMeasureBox Management Bot</b>
<i>Unit ID: {box_id}</i>

<b>📡 Diagnostics & Network:</b>
• /status - Mode, carrier link & 24h SLA summary
• /ping - Real-time latency and packet loss across targets
• /test <code>[ookla|cloudflare|rtr|iperf]</code> - Run bandwidth test
• /report - Compile & receive 24h HTML telemetry dossier
• /ai - Receive full AI LLM Diagnostic Bundle (.md)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - View/switch mode

<b>🛡️ VPN Server (WireGuard & OpenVPN):</b>
• /vpn - WireGuard & OpenVPN status & client count
• /vpn clients - List connected clients, handshake & transfer
• /vpn add <code>&lt;name&gt;</code> - Create WireGuard client + send QR & .conf!
• /vpn conf <code>&lt;name&gt;</code> - Download .conf or .ovpn profile file
• /vpn qr <code>&lt;name&gt;</code> - Receive QR code image for mobile pairing
• /vpn start <code>[wg|ovpn]</code> / /vpn stop <code>[wg|ovpn]</code> - Toggle servers
• /vpn del <code>&lt;name&gt;</code> - Delete/revoke client peer

<b>🛡️ DNS Ad-Blocker (Pi-hole Sinkhole):</b>
• /adblock - Sinkhole status, blocked queries today, gravity size
• /adblock on / /adblock off - Enable or disable ad blocking
• /adblock block <code>&lt;domain&gt;</code> - Add domain to custom blacklist
• /adblock unblock <code>&lt;domain&gt;</code> - Remove from blacklist / whitelist
• /adblock update - Trigger Gravity blocklist update
• /adblock guide - View router DHCP DNS setup instructions

<b>🩺 Self-Healing & System Health:</b>
• /heal - Audit daemons, database, services, and disk
• /heal fix <code>[tier]</code> - Trigger automated self-healing repair
• /heal updates - Check for verified stable system updates
• /heal apply - Apply stable update with safety rollback

<b>📊 System Tasks & Resource Load:</b>
• /tasks (or /top) - CPU, RAM, Disk, Temp, and top processes
• /kill <code>&lt;pid&gt; [signal]</code> - Terminate rogue process

<b>📶 Wi-Fi & Guest Wi-Fi Station:</b>
• /wifi - AP status & guest Wi-Fi probe telemetry
• /wifi scan - Scan nearby wireless networks
• /wifi connect <code>&lt;ssid&gt; [password]</code> - Connect guest probe
• /wifi saved - View saved Wi-Fi profiles

<b>📦 Backups & Recovery:</b>
• /backup - List locally stored system backup archives
• /backup create <code>[label]</code> - Create atomic checkpoint backup
• /backup send <code>&lt;filename&gt;</code> - Download .tar.gz archive via Telegram

<b>🔧 Hardware & Power:</b>
• /drivers - Detected network controllers and driver status
• /reboot <code>now</code> - Safely reboot NetworkMeasureBox
"""
        self.client.send_message(chat_id, msg)

    # =========================================================================
    # 2. Status & Network Telemetry
    # =========================================================================

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

            # Check VPN & Adblock quick states safely
            try:
                wg_stat = wg.get_wireguard_status(port=self.cfg.wireguard.port, subnet=self.cfg.wireguard.subnet)
            except Exception:
                wg_stat = {"active": False}

            try:
                ab_stat = ab.get_full_adblock_status()
            except Exception:
                ab_stat = {"enabled": False}

            wg_badge = "🟢 UP" if wg_stat.get("active") else "⚫ STOPPED"
            ab_badge = f"🟢 ON ({ab_stat.get('domains_on_blocklist', 0):,} domains)" if ab_stat.get("enabled") else "🔴 OFF"

            msg = f"""<b>System Status & Health</b> [<code>{html.escape(self.cfg.system.box_id)}</code>]

<b>Operational Mode:</b> <code>{active_mode}</code>
<b>Physical Links:</b> WAN ({html.escape(self.cfg.network.wan_interface)}): <b>{wan_carrier}</b> | LAN ({html.escape(self.cfg.network.lan_interface)}): <b>{lan_carrier}</b>
<b>Active Gateway IF:</b> <code>{html.escape(wan_iface)}</code>

<b>24h Availability:</b> <b>{rep.uptime_pct:.2f}%</b> ({len(rep.outages)} outages)
<b>Packet Loss:</b> <b>{rep.ping_summary.loss_pct:.2f}%</b>
<b>Mean Latency:</b> {rep.ping_summary.rtt_avg_ms or '-'} ms (P95: {rep.ping_summary.rtt_p95_ms or '-'} ms)
<b>SLA Verdict:</b> <b>{html.escape(str(rep.sla_verdict))}</b>

<b>Security & Services:</b>
• WireGuard VPN: <b>{wg_badge}</b>
• DNS Ad-Blocker: <b>{ab_badge}</b>
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            log.error("error in /status: %s", e)
            self.client.send_message(chat_id, f"Error generating status: {html.escape(str(e))}")

    def _cmd_ping(self, chat_id: int) -> None:
        try:
            conn = db.connect(readonly=True)
            now = db.now_ms()
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
                lines.append(f"• <b>{html.escape(r['label'])}</b> (<code>{html.escape(r['addr'])}</code>): <b>{avg_ms}</b> ({loss_str})")

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Error querying pings: {html.escape(str(e))}")

    def _cmd_test(self, chat_id: int, args: list[str]) -> None:
        engine = args[0].lower() if args else None
        engine_str = f" using <b>{html.escape(engine.upper())}</b>" if engine else ""
        self.client.send_message(chat_id, f"<i>Initiating bandwidth speedtest{engine_str}... (may take up to 25 seconds)</i>")
        try:
            ok = run_measurement_cycle(
                self.cfg,
                trigger="telegram",
                force=True,
                run_port_check=True,
                engine=engine
            )

            conn = db.connect(readonly=True)
            row = conn.execute(
                """SELECT down_bps, up_bps, ping_us, jitter_us, loss_pct, server_name, status, engine
                   FROM speedtest ORDER BY ts DESC LIMIT 1"""
            ).fetchone()
            conn.close()

            if not row or row["status"] != "ok":
                self.client.send_message(chat_id, "⚠️ Speedtest failed or was deferred.")
                return

            down_mbps = (row["down_bps"] or 0) / 1_000_000.0
            up_mbps = (row["up_bps"] or 0) / 1_000_000.0
            ping_ms = (row["ping_us"] or 0) / 1000.0

            down_compliance = (down_mbps / self.cfg.isp.contract_down_mbps) * 100.0 if self.cfg.isp.contract_down_mbps else 0.0
            up_compliance = (up_mbps / self.cfg.isp.contract_up_mbps) * 100.0 if self.cfg.isp.contract_up_mbps else 0.0

            active_engine = (row["engine"] if "engine" in row.keys() else engine) or "Ookla"

            msg = f"""<b>Speedtest Results ({html.escape(str(active_engine)).upper()}):</b>

<b>Download:</b> <b>{down_mbps:.1f} Mbps</b> ({down_compliance:.0f}% of plan)
<b>Upload:</b> <b>{up_mbps:.1f} Mbps</b> ({up_compliance:.0f}% of plan)
<b>Latency:</b> {ping_ms:.1f} ms (jitter: {(row['jitter_us'] or 0)/1000.0:.1f} ms)
<b>Server:</b> {html.escape(str(row['server_name'] or 'Edge Mirror'))}
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Speedtest error: {html.escape(str(e))}")

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
                f"SLA Verdict: <b>{html.escape(str(report.sla_verdict))}</b> | Availability: <b>{report.uptime_pct:.2f}%</b>"
            )

            ok = self.client.send_document(chat_id, filename, html_doc.encode("utf-8"), caption=caption)
            if not ok:
                self.client.send_message(chat_id, "Dossier compiled, but sending attachment failed.")
        except Exception as e:
            self.client.send_message(chat_id, f"Report compilation error: {html.escape(str(e))}")

    def _cmd_ai(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Generating AI LLM Diagnostic Markdown Bundle...</i>")
        try:
            conn = db.connect(readonly=True)
            bundle_md = llm_bundle.generate_llm_diagnostic_bundle(self.cfg, conn)
            conn.close()

            filename = f"nmb_diagnostic_bundle_{self.cfg.system.box_id}_{int(time.time())}.md"
            caption = (
                f"<b>AI Diagnostic Bundle (LLM Snapshot)</b>\n"
                f"Formatted for ChatGPT, Claude, and Gemini deep network analysis."
            )
            ok = self.client.send_document(chat_id, filename, bundle_md.encode("utf-8"), caption=caption)
            if not ok:
                self.client.send_message(chat_id, "Diagnostic bundle generated, but sending document failed.")
        except Exception as e:
            self.client.send_message(chat_id, f"AI bundle error: {html.escape(str(e))}")

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
                f"Current mode: <b>{html.escape(cur_mode)}</b> (override: <code>{html.escape(cur_ovr)}</code>)\n"
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
            f"Override mode updated to <b>{html.escape(target_mode)}</b>. The network daemon will transition shortly."
        )

    # =========================================================================
    # 3. VPN Management (WireGuard & OpenVPN)
    # =========================================================================

    def _cmd_vpn(self, chat_id: int, args: list[str]) -> None:
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._vpn_status(chat_id)
        elif subcmd in ("peers", "clients", "list"):
            self._vpn_list_clients(chat_id)
        elif subcmd == "add":
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/vpn add &lt;client_name&gt; [wg|ovpn]</code>")
                return
            name = args[1].strip()
            proto = args[2].lower() if len(args) > 2 else "wg"
            self._vpn_add_client(chat_id, name, proto)
        elif subcmd == "qr":
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/vpn qr &lt;client_name&gt;</code>")
                return
            self._vpn_send_qr(chat_id, args[1].strip())
        elif subcmd in ("conf", "config", "profile"):
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/vpn conf &lt;client_name&gt;</code>")
                return
            self._vpn_send_conf(chat_id, args[1].strip())
        elif subcmd == "start":
            proto = args[1].lower() if len(args) > 1 else "wg"
            self._vpn_toggle(chat_id, proto, enable=True)
        elif subcmd == "stop":
            proto = args[1].lower() if len(args) > 1 else "wg"
            self._vpn_toggle(chat_id, proto, enable=False)
        elif subcmd in ("del", "delete", "remove"):
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/vpn del &lt;client_name&gt;</code>")
                return
            self._vpn_delete_client(chat_id, args[1].strip())
        else:
            self.client.send_message(
                chat_id,
                f"Unknown VPN command <code>{html.escape(subcmd)}</code>.\n"
                f"Supported: <code>/vpn</code>, <code>/vpn clients</code>, <code>/vpn add &lt;name&gt;</code>, "
                f"<code>/vpn qr &lt;name&gt;</code>, <code>/vpn conf &lt;name&gt;</code>, <code>/vpn start</code>, <code>/vpn stop</code>, <code>/vpn del &lt;name&gt;</code>"
            )

    def _vpn_status(self, chat_id: int) -> None:
        try:
            try:
                wg_stat = wg.get_wireguard_status(
                    port=self.cfg.wireguard.port,
                    subnet=self.cfg.wireguard.subnet,
                    public_endpoint=self.cfg.wireguard.public_endpoint
                )
            except Exception:
                wg_stat = {"active": False, "peers": []}

            try:
                ov_stat = ovpn.get_openvpn_status(
                    port=self.cfg.openvpn.port,
                    subnet=self.cfg.openvpn.subnet
                )
            except Exception:
                ov_stat = {"active": False, "clients": []}

            wg_active = wg_stat.get("active", False)
            ov_active = ov_stat.get("active", False)

            wg_peers = wg_stat.get("peers", [])
            ov_clients = ov_stat.get("clients", [])

            active_wg_peers = sum(1 for p in wg_peers if (p.get("latest_handshake") or 0) > 0 and (p.get("latest_handshake") or 0) < 180)
            active_ov_clients = sum(1 for c in ov_clients if c.get("connected"))

            msg = f"""<b>🛡️ VPN Server Hub Status</b>

<b>1. WireGuard High-Performance VPN:</b>
• Status: <b>{'🟢 ACTIVE' if wg_active else '⚫ STOPPED'}</b>
• Listen Port: <code>UDP {self.cfg.wireguard.port}</code>
• Tunnel Subnet: <code>{self.cfg.wireguard.subnet}</code>
• Configured Peers: <b>{len(wg_peers)}</b> ({active_wg_peers} connected)
• Public Endpoint: <code>{html.escape(str(wg_stat.get('endpoint') or 'Auto-detected'))}</code>

<b>2. OpenVPN Robust Fallback Server:</b>
• Status: <b>{'🟢 ACTIVE' if ov_active else '⚫ STOPPED'}</b>
• Listen Port: <code>UDP {self.cfg.openvpn.port}</code>
• Tunnel Subnet: <code>{self.cfg.openvpn.subnet}</code>
• Configured Clients: <b>{len(ov_clients)}</b> ({active_ov_clients} connected)

<b>Quick Commands:</b>
• <code>/vpn clients</code> - View client connection list & traffic
• <code>/vpn add &lt;name&gt;</code> - Generate new peer with instant QR & .conf
• <code>/vpn qr &lt;name&gt;</code> - Receive QR code image for phone pairing
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Error getting VPN status: {html.escape(str(e))}")

    def _vpn_list_clients(self, chat_id: int) -> None:
        try:
            try:
                wg_stat = wg.get_wireguard_status(
                    port=self.cfg.wireguard.port,
                    subnet=self.cfg.wireguard.subnet,
                    public_endpoint=self.cfg.wireguard.public_endpoint
                )
            except Exception:
                wg_stat = {"peers": []}

            try:
                ov_stat = ovpn.get_openvpn_status(
                    port=self.cfg.openvpn.port,
                    subnet=self.cfg.openvpn.subnet
                )
            except Exception:
                ov_stat = {"clients": []}

            wg_peers = wg_stat.get("peers", [])
            ov_clients = ov_stat.get("clients", [])

            lines = ["<b>Configured VPN Clients:</b>\n"]

            lines.append("<b>🛡️ WireGuard Peers:</b>")
            if not wg_peers:
                lines.append("<i>No WireGuard peers configured.</i>")
            else:
                for p in wg_peers:
                    hs_sec = p.get("latest_handshake") or 0
                    if hs_sec > 0 and hs_sec < 180:
                        status = f"🟢 Connected ({p.get('latest_handshake_ago') or str(hs_sec)+'s'})"
                    elif hs_sec > 0:
                        status = f"⚪ Offline ({p.get('latest_handshake_ago') or str(int(hs_sec/60))+'m'})"
                    else:
                        status = "⚪ Never Connected"

                    rx = format_bytes(p.get("transfer_rx") or 0)
                    tx = format_bytes(p.get("transfer_tx") or 0)
                    ip_str = p.get("allowed_ips") or p.get("client_ip") or "--"

                    lines.append(
                        f"• <b>{html.escape(p.get('name'))}</b>\n"
                        f"  IP: <code>{html.escape(ip_str)}</code> | Status: {status}\n"
                        f"  Transfer: ↓ {rx} / ↑ {tx}"
                    )

            lines.append("\n<b>🔒 OpenVPN Clients:</b>")
            if not ov_clients:
                lines.append("<i>No OpenVPN clients configured.</i>")
            else:
                for c in ov_clients:
                    status = "🟢 Connected" if c.get("connected") else "⚪ Offline"
                    rx = format_bytes(c.get("bytes_received") or 0)
                    tx = format_bytes(c.get("bytes_sent") or 0)
                    ip_str = c.get("virtual_ip") or "--"

                    lines.append(
                        f"• <b>{html.escape(c.get('name'))}</b>\n"
                        f"  IP: <code>{html.escape(ip_str)}</code> | Status: {status}\n"
                        f"  Transfer: ↓ {rx} / ↑ {tx}"
                    )

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Error listing VPN clients: {html.escape(str(e))}")

    def _vpn_add_client(self, chat_id: int, name: str, proto: str = "wg") -> None:
        self.client.send_message(chat_id, f"<i>Generating {proto.upper()} client profile for <b>{html.escape(name)}</b>...</i>")
        try:
            if proto in ("ovpn", "openvpn"):
                c = ovpn.add_client(name)
                ovpn_profile = ovpn.get_unified_ovpn_profile(
                    name,
                    endpoint_host=self.cfg.openvpn.public_endpoint,
                    port=self.cfg.openvpn.port
                )
                if not ovpn_profile:
                    self.client.send_message(chat_id, f"Failed to generate OpenVPN profile for {name}.")
                    return

                caption = (
                    f"✅ <b>OpenVPN Client Created</b>\n"
                    f"Client Name: <b>{html.escape(name)}</b>\n"
                    f"Assigned IP: <code>{c.get('ip') or 'DHCP Pool'}</code>"
                )
                self.client.send_document(
                    chat_id,
                    f"{name}.ovpn",
                    ovpn_profile.encode("utf-8"),
                    caption=caption
                )
            else:
                # WireGuard
                peer = wg.add_peer(
                    name,
                    port=self.cfg.wireguard.port,
                    subnet=self.cfg.wireguard.subnet
                )
                conf_str = wg.get_client_config(
                    peer.get("id", name),
                    endpoint_host=self.cfg.wireguard.public_endpoint,
                    port=self.cfg.wireguard.port
                )
                if not conf_str:
                    self.client.send_message(chat_id, f"Failed to generate WireGuard config for {name}.")
                    return

                ip_str = peer.get("allowed_ips") or peer.get("client_ip") or "10.66.66.x"
                caption = (
                    f"✅ <b>WireGuard Peer Created</b>\n"
                    f"Client Name: <b>{html.escape(name)}</b>\n"
                    f"Tunnel IP: <code>{html.escape(ip_str)}</code>\n"
                    f"Endpoint: <code>{html.escape(str(self.cfg.wireguard.public_endpoint or 'Auto'))}:{self.cfg.wireguard.port}</code>"
                )

                # 1. Send QR code image for instant mobile pairing
                qr_png = wg.get_client_qr_png_bytes(
                    peer.get("id", name),
                    endpoint_host=self.cfg.wireguard.public_endpoint,
                    port=self.cfg.wireguard.port
                )
                if qr_png:
                    self.client.send_photo(
                        chat_id,
                        qr_png,
                        caption=caption,
                        filename=f"wireguard_{name}_qr.png"
                    )
                else:
                    self.client.send_message(chat_id, caption)

                # 2. Send .conf file attachment
                self.client.send_document(
                    chat_id,
                    f"{name}.conf",
                    conf_str.encode("utf-8"),
                    caption=f"WireGuard Profile Configuration: <b>{html.escape(name)}.conf</b>"
                )
        except Exception as e:
            self.client.send_message(chat_id, f"Error creating VPN client: {html.escape(str(e))}")

    def _vpn_send_qr(self, chat_id: int, name: str) -> None:
        try:
            peers = wg.load_peers()
            target = next((p for p in peers if p.get("name", "").lower() == name.lower() or p.get("id") == name), None)
            if not target:
                self.client.send_message(chat_id, f"WireGuard peer <code>{html.escape(name)}</code> not found.")
                return

            qr_png = wg.get_client_qr_png_bytes(
                target.get("id", name),
                endpoint_host=self.cfg.wireguard.public_endpoint,
                port=self.cfg.wireguard.port
            )
            if not qr_png:
                self.client.send_message(chat_id, f"Failed to generate QR code for {name}. Ensure qrencode is installed.")
                return

            caption = (
                f"📱 <b>WireGuard QR Code</b>: <b>{html.escape(target.get('name'))}</b>\n"
                f"Tunnel IP: <code>{html.escape(target.get('allowed_ips') or '')}</code>\n"
                f"Scan this image in the WireGuard mobile app to connect instantly."
            )
            self.client.send_photo(chat_id, qr_png, caption=caption, filename=f"wireguard_{name}_qr.png")
        except Exception as e:
            self.client.send_message(chat_id, f"Error generating QR code: {html.escape(str(e))}")

    def _vpn_send_conf(self, chat_id: int, name: str) -> None:
        try:
            # Check WireGuard first
            peers = wg.load_peers()
            wg_target = next((p for p in peers if p.get("name", "").lower() == name.lower() or p.get("id") == name), None)
            if wg_target:
                conf_str = wg.get_client_config(
                    wg_target.get("id", name),
                    endpoint_host=self.cfg.wireguard.public_endpoint,
                    port=self.cfg.wireguard.port
                )
                if conf_str:
                    caption = f"WireGuard Config Profile: <b>{html.escape(wg_target.get('name'))}.conf</b>"
                    self.client.send_document(chat_id, f"{name}.conf", conf_str.encode("utf-8"), caption=caption)
                    return

            # Check OpenVPN
            clients = ovpn.load_clients()
            ov_target = next((c for c in clients if c.get("name", "").lower() == name.lower()), None)
            if ov_target:
                ovpn_profile = ovpn.get_unified_ovpn_profile(
                    ov_target.get("name"),
                    endpoint_host=self.cfg.openvpn.public_endpoint,
                    port=self.cfg.openvpn.port
                )
                if ovpn_profile:
                    caption = f"OpenVPN Config Profile: <b>{html.escape(ov_target.get('name'))}.ovpn</b>"
                    self.client.send_document(chat_id, f"{name}.ovpn", ovpn_profile.encode("utf-8"), caption=caption)
                    return

            self.client.send_message(chat_id, f"Client profile <code>{html.escape(name)}</code> not found in WireGuard or OpenVPN.")
        except Exception as e:
            self.client.send_message(chat_id, f"Error sending config profile: {html.escape(str(e))}")

    def _vpn_toggle(self, chat_id: int, proto: str, enable: bool) -> None:
        action = "Starting" if enable else "Stopping"
        self.client.send_message(chat_id, f"<i>{action} {proto.upper()} server...</i>")
        try:
            if proto in ("ovpn", "openvpn"):
                if enable:
                    ovpn.apply_configuration(
                        proto=self.cfg.openvpn.proto,
                        port=self.cfg.openvpn.port,
                        subnet=self.cfg.openvpn.subnet,
                        subnet_ipv6=self.cfg.openvpn.subnet_ipv6,
                        dns_servers=self.cfg.openvpn.dns,
                    )
                else:
                    ovpn.run_helper("openvpn-stop")
                status = "started" if enable else "stopped"
                self.client.send_message(chat_id, f"OpenVPN server {status} successfully.")
            else:
                if enable:
                    wg.apply_configuration(
                        port=self.cfg.wireguard.port,
                        subnet=self.cfg.wireguard.subnet,
                        subnet_ipv6=self.cfg.wireguard.subnet_ipv6,
                    )
                else:
                    wg.run_helper("wireguard-stop")
                status = "started" if enable else "stopped"
                self.client.send_message(chat_id, f"WireGuard server {status} successfully.")
        except Exception as e:
            self.client.send_message(chat_id, f"Error toggling VPN server: {html.escape(str(e))}")

    def _vpn_delete_client(self, chat_id: int, name: str) -> None:
        try:
            # Check WireGuard
            peers = wg.load_peers()
            wg_target = next((p for p in peers if p.get("name", "").lower() == name.lower() or p.get("id") == name), None)
            if wg_target:
                wg.delete_peer(wg_target.get("id"))
                self.client.send_message(chat_id, f"WireGuard peer <b>{html.escape(name)}</b> deleted.")
                return

            # Check OpenVPN
            clients = ovpn.load_clients()
            ov_target = next((c for c in clients if c.get("name", "").lower() == name.lower()), None)
            if ov_target:
                ovpn.delete_client(ov_target.get("name"))
                self.client.send_message(chat_id, f"OpenVPN client <b>{html.escape(name)}</b> deleted/revoked.")
                return

            self.client.send_message(chat_id, f"Client <code>{html.escape(name)}</code> not found.")
        except Exception as e:
            self.client.send_message(chat_id, f"Error deleting client: {html.escape(str(e))}")

    # =========================================================================
    # 4. DNS Ad-Blocker (Pi-hole Sinkhole)
    # =========================================================================

    def _cmd_adblock(self, chat_id: int, args: list[str]) -> None:
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._adblock_status(chat_id)
        elif subcmd in ("on", "enable", "start"):
            ab.set_adblock_enabled(True, self.cfg)
            self.client.send_message(chat_id, "🟢 <b>DNS Ad-Blocker & Sinkhole ENABLED</b>. Network ads and tracking are now actively blocked.")
        elif subcmd in ("off", "disable", "stop"):
            ab.set_adblock_enabled(False, self.cfg)
            self.client.send_message(chat_id, "🔴 <b>DNS Ad-Blocker & Sinkhole DISABLED</b>. DNS queries forwarded unfiltered.")
        elif subcmd == "block":
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/adblock block &lt;domain&gt;</code>")
                return
            domain = args[1].strip()
            ab.add_blacklist_entry(domain)
            self.client.send_message(chat_id, f"🚫 <b>Domain Blocked</b>: <code>{html.escape(domain)}</code> added to custom blacklist.")
        elif subcmd == "unblock":
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/adblock unblock &lt;domain&gt;</code>")
                return
            domain = args[1].strip()
            ab.remove_blacklist_entry(domain)
            ab.add_whitelist_entry(domain)
            self.client.send_message(chat_id, f"✅ <b>Domain Whitelisted</b>: <code>{html.escape(domain)}</code> removed from blacklist & allowed.")
        elif subcmd == "update":
            self.client.send_message(chat_id, "<i>Updating Gravity domain blocklists in the background...</i>")
            ab.trigger_gravity_update()
            self.client.send_message(chat_id, "🔄 Gravity blocklist download and compilation initiated.")
        elif subcmd == "guide":
            guide = ab.get_router_dhcp_guide()
            msg = f"""<b>📖 Home Router DHCP DNS Configuration Guide:</b>

To block ads across all smartphones, PCs, laptops, and smart TVs on your home Wi-Fi:

1. Log into your primary home router's admin page (e.g. <code>http://192.168.1.1</code>).
2. Navigate to <b>LAN / DHCP Server / DNS Settings</b>.
3. Set the <b>Primary DNS Server IP</b> to:
   👉 <code>{html.escape(guide.get('primary_dns_ip', '192.168.8.218'))}</code>
4. Save and reboot your router (or reconnect Wi-Fi on client devices).

All network devices will now instantly have ads, trackers, and telemetry sinkholed!"""
            self.client.send_message(chat_id, msg)
        else:
            self.client.send_message(
                chat_id,
                f"Unknown adblock command: <code>{html.escape(subcmd)}</code>.\n"
                f"Usage: <code>/adblock</code>, <code>/adblock on</code>, <code>/adblock off</code>, "
                f"<code>/adblock block &lt;domain&gt;</code>, <code>/adblock unblock &lt;domain&gt;</code>, "
                f"<code>/adblock update</code>, <code>/adblock guide</code>"
            )

    def _adblock_status(self, chat_id: int) -> None:
        try:
            stat = ab.get_full_adblock_status()
            is_enabled = stat.get("enabled", False)
            status_badge = "🟢 ACTIVE & BLOCKING" if is_enabled else "🔴 DISABLED"

            total_q = stat.get("total_queries_today", 0)
            blocked_q = stat.get("blocked_queries_today", 0)
            pct = stat.get("block_percentage_today", 0.0)
            gravity = stat.get("domains_on_blocklist", 0)
            upstreams = ", ".join(stat.get("upstream_dns_servers", [])) or "1.1.1.1, 8.8.8.8"

            msg = f"""<b>🛡️ DNS Ad-Blocker & Sinkhole (Pi-hole Engine)</b>

• Status: <b>{status_badge}</b>
• Listen Port: <code>UDP/TCP 53</code>
• Blocklist (Gravity): <b>{gravity:,}</b> domains loaded
• Queries Today: <b>{total_q:,}</b>
• Blocked Today: <b>{blocked_q:,}</b> (<b>{pct:.1f}%</b> sinkholed)
• Upstream Resolvers: <code>{html.escape(upstreams)}</code>

<b>Quick Commands:</b>
• <code>/adblock on</code> / <code>/adblock off</code> - Toggle blocking
• <code>/adblock block &lt;domain&gt;</code> - Add domain to custom blacklist
• <code>/adblock update</code> - Update Gravity ad sources
• <code>/adblock guide</code> - Show router DHCP DNS instructions
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Error getting adblock status: {html.escape(str(e))}")

    # =========================================================================
    # 5. Self-Healing & System Audit
    # =========================================================================

    def _cmd_heal(self, chat_id: int, args: list[str]) -> None:
        subcmd = args[0].lower() if args else "audit"

        if subcmd in ("audit", "status"):
            self._heal_audit(chat_id)
        elif subcmd in ("fix", "repair"):
            tier = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
            self._heal_fix(chat_id, tier)
        elif subcmd in ("updates", "check"):
            self._heal_check_updates(chat_id)
        elif subcmd == "apply":
            self._heal_apply_update(chat_id)
        else:
            self.client.send_message(
                chat_id,
                f"Unknown heal command: <code>{html.escape(subcmd)}</code>.\n"
                f"Supported: <code>/heal</code>, <code>/heal fix [tier]</code>, <code>/heal updates</code>, <code>/heal apply</code>"
            )

    def _heal_audit(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Auditing system daemons, database, permissions, and routing...</i>")
        try:
            res = heal.audit_system_health(self.cfg)
            issues = res.get("critical_issues", 0)
            verdict = "🟢 ALL COMPONENTS HEALTHY" if issues == 0 else f"⚠️ {issues} ISSUES DETECTED"

            services = res.get("services", {})
            svc_lines = []
            for s_name, s_info in services.items():
                active = s_info.get("active", False)
                icon = "🟢" if active else "🔴"
                svc_lines.append(f"  {icon} <code>{html.escape(s_name)}</code>")

            db_info = res.get("database", {})
            db_status = "🟢 Integrity OK" if db_info.get("integrity_ok") else "🔴 Corrupted"

            msg = f"""<b>🩺 System Health & Self-Healing Audit</b>
Verdict: <b>{verdict}</b>

<b>Core System Daemons:</b>
{chr(10).join(svc_lines)}

<b>Database & Tables:</b> {db_status} (Tables: {db_info.get('table_count', 0)})
<b>Missing Binaries:</b> {len(res.get('missing_binaries', []))}
<b>Corrupted Symlinks:</b> {len(res.get('missing_symlinks', []))}

To trigger automated repairs, use: <code>/heal fix</code>
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Audit error: {html.escape(str(e))}")

    def _heal_fix(self, chat_id: int, tier: Optional[int]) -> None:
        tier_msg = f" (Escalation Tier {tier})" if tier else " (Adaptive)"
        self.client.send_message(chat_id, f"<i>Executing automated self-healing repairs{tier_msg}...</i>")
        try:
            res = heal.auto_heal_all(self.cfg, tier=tier)
            repairs = res.get("repairs_executed", [])
            remaining = res.get("audit_after", {}).get("critical_issues", 0)

            if repairs:
                repair_list = "\n".join(f"• {html.escape(r)}" for r in repairs)
                msg = f"""✅ <b>Self-Healing Completed!</b>

<b>Repairs Executed:</b>
{repair_list}

Remaining Issues: <b>{remaining}</b>"""
            else:
                msg = "✅ <b>System is already healthy</b>. No repairs required."

            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Self-healing error: {html.escape(str(e))}")

    def _heal_check_updates(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Checking for stable releases...</i>")
        try:
            res = heal.check_stable_updates()
            cur_ver = res.get("current_version", "unknown")
            avail = res.get("update_available", False)
            latest = res.get("latest_stable_version", cur_ver)

            if avail:
                msg = f"""🔔 <b>NEW STABLE UPDATE AVAILABLE!</b>

Current Version: <code>{html.escape(cur_ver)}</code>
Latest Version: <b>{html.escape(latest)}</b>

To apply with automatic safety backup & rollback:
👉 <code>/heal apply</code>"""
            else:
                msg = f"✅ System is running the latest stable release: <b>{html.escape(cur_ver)}</b>."

            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Error checking updates: {html.escape(str(e))}")

    def _heal_apply_update(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Creating safety checkpoint and applying verified update...</i>")
        try:
            res = heal.apply_stable_update()
            if res.get("success"):
                msg = f"""🎉 <b>Update Applied Successfully!</b>

New Version: <b>{html.escape(res.get('new_version', ''))}</b>
Safety Checkpoint: <code>{html.escape(res.get('checkpoint', ''))}</code>
All automated verification unit tests passed."""
            else:
                if res.get("rolled_back"):
                    msg = f"""⚠️ <b>UPDATE FAILED — AUTOMATIC SAFETY ROLLBACK APPLIED!</b>

Reason: <i>{html.escape(res.get('error', 'Test verification failure'))}</i>
System safely restored to checkpoint: <code>{html.escape(res.get('checkpoint', ''))}</code>"""
                else:
                    msg = f"Update failed: {html.escape(res.get('error', 'Unknown error'))}"

            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Error applying update: {html.escape(str(e))}")

    # =========================================================================
    # 6. Tasks, Process Manager & Load
    # =========================================================================

    def _cmd_tasks(self, chat_id: int) -> None:
        try:
            summary = tasks.get_system_summary()
            procs_data = tasks.get_processes_list(limit=8)
            procs = procs_data[0] if isinstance(procs_data, tuple) else procs_data

            cpu_pct = summary.get("cpu_percent", 0.0)
            load_avg = summary.get("load_avg", [0, 0, 0])
            mem = summary.get("memory", {})
            swap = summary.get("swap", {})
            disk = summary.get("disk", {})
            temp = summary.get("temperature_c")
            temp_str = f" | Temp: <b>{temp:.1f}°C</b>" if temp is not None else ""

            mem_used_h = format_bytes(mem.get("used", 0))
            mem_tot_h = format_bytes(mem.get("total", 0))
            disk_used_h = format_bytes(disk.get("used", 0))
            disk_tot_h = format_bytes(disk.get("total", 0))

            proc_lines = []
            for p in procs:
                cmd_short = p.get("command", "")[:24]
                proc_lines.append(
                    f"<code>{p.get('pid'):>5} {p.get('user', '')[:6]:<6} {p.get('cpu_percent', 0.0):>4.1f}% {p.get('mem_percent', 0.0):>4.1f}% {html.escape(cmd_short)}</code>"
                )

            msg = f"""<b>📊 System Resource Load & Process Table</b>

<b>CPU Usage:</b> <b>{cpu_pct:.1f}%</b> (Load: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}){temp_str}
<b>Memory:</b> <b>{mem_used_h} / {mem_tot_h}</b> ({mem.get('percent', 0.0):.1f}%)
<b>Disk (/):</b> <b>{disk_used_h} / {disk_tot_h}</b> ({disk.get('percent', 0.0):.1f}%)
<b>Uptime:</b> {html.escape(summary.get('uptime_human', '--'))} | Tasks: {summary.get('processes_count', 0)}

<b>Top Resource-Consuming Processes:</b>
<pre>  PID USER   CPU%  MEM% COMMAND
{chr(10).join(proc_lines)}</pre>

To kill a stuck process: <code>/kill &lt;pid&gt;</code>
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Error getting tasks: {html.escape(str(e))}")

    def _cmd_kill(self, chat_id: int, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            self.client.send_message(chat_id, "Usage: <code>/kill &lt;pid&gt; [signal_num]</code> (default signal: 15 / SIGTERM)")
            return

        pid = int(args[0])
        sig = int(args[1]) if len(args) > 1 and args[1].isdigit() else 15

        try:
            res = tasks.kill_process(pid, signal_num=sig)
            if res.get("status") == "ok":
                self.client.send_message(chat_id, f"✅ Process <code>{pid}</code> terminated (signal {sig}).")
            else:
                self.client.send_message(chat_id, f"❌ Failed to kill process {pid}: {html.escape(res.get('error', 'Unknown'))}")
        except Exception as e:
            self.client.send_message(chat_id, f"Kill error: {html.escape(str(e))}")

    # =========================================================================
    # 7. Wi-Fi & Guest Wi-Fi Station
    # =========================================================================

    def _cmd_wifi(self, chat_id: int, args: list[str]) -> None:
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._wifi_status(chat_id)
        elif subcmd == "scan":
            self._wifi_scan(chat_id)
        elif subcmd == "connect":
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/wifi connect &lt;ssid&gt; [password]</code>")
                return
            ssid = args[1].strip()
            pw = args[2].strip() if len(args) > 2 else ""
            self._wifi_connect(chat_id, ssid, pw)
        elif subcmd == "saved":
            self._wifi_saved(chat_id)
        else:
            self.client.send_message(
                chat_id,
                f"Unknown wifi command: <code>{html.escape(subcmd)}</code>.\n"
                f"Supported: <code>/wifi</code>, <code>/wifi scan</code>, <code>/wifi connect &lt;ssid&gt; [password]</code>, <code>/wifi saved</code>"
            )

    def _wifi_status(self, chat_id: int) -> None:
        try:
            stat = gw.get_guest_wifi_status(self.cfg)
            is_conn = stat.get("connected", False)

            if is_conn:
                badge = "🟢 CONNECTED"
                iso_badge = " [ISOLATED SUBNET VERIFIED]" if stat.get("is_isolated_subnet") else ""
                details = (
                    f"• SSID: <b>{html.escape(stat.get('ssid', ''))}</b>\n"
                    f"• IP Address: <code>{html.escape(stat.get('ip_address', ''))}</code>\n"
                    f"• Gateway: <code>{html.escape(stat.get('gateway', ''))}</code>\n"
                    f"• Subnet: <code>{html.escape(stat.get('subnet', ''))}</code>{iso_badge}\n"
                    f"• Signal (RSSI): <b>{stat.get('signal_percent', 0)}%</b> ({html.escape(stat.get('security', ''))})\n"
                    f"• Interface: <code>{html.escape(stat.get('interface', 'wlan0'))}</code> (Metric: 600)"
                )
            else:
                badge = "⚪ NOT CONNECTED"
                details = "<i>Station interface is disconnected or idle.</i>"

            msg = f"""<b>📶 Wi-Fi & Guest Wi-Fi Station Status</b>
Status: <b>{badge}</b>

{details}

<b>Quick Commands:</b>
• <code>/wifi scan</code> - Search for nearby wireless access points
• <code>/wifi connect &lt;ssid&gt; [pw]</code> - Connect to target network
• <code>/wifi saved</code> - List saved Wi-Fi connection profiles
"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Error getting Wi-Fi status: {html.escape(str(e))}")

    def _wifi_scan(self, chat_id: int) -> None:
        self.client.send_message(chat_id, "<i>Scanning 2.4 GHz and 5 GHz wireless frequencies via wlan0...</i>")
        try:
            nets = gw.scan_wifi_networks(interface="wlan0")
            if not nets:
                self.client.send_message(chat_id, "No Wi-Fi access points detected.")
                return

            lines = [f"<b>🔍 Scanned Wi-Fi Networks ({len(nets)} found):</b>\n"]
            for n in nets[:12]:
                in_use = "🟢 " if n.get("in_use") else ""
                ssid = n.get("ssid") or "&lt;Hidden SSID&gt;"
                sig = n.get("signal", 0)
                sec = n.get("security", "")
                ch = n.get("channel", "")

                lines.append(f"• {in_use}<b>{html.escape(ssid)}</b> — <b>{sig}%</b> (Ch {ch}, {html.escape(sec)})")

            lines.append("\nTo connect: <code>/wifi connect &lt;ssid&gt; [password]</code>")
            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Scan error: {html.escape(str(e))}")

    def _wifi_connect(self, chat_id: int, ssid: str, pw: str) -> None:
        self.client.send_message(chat_id, f"<i>Connecting wlan0 to <b>{html.escape(ssid)}</b>...</i>")
        try:
            res = gw.connect_guest_wifi(
                ssid=ssid,
                password=pw,
                interface="wlan0",
                metric=600,
                save=True
            )
            if res.get("status") == "ok":
                self.client.send_message(chat_id, f"✅ Connected to <b>{html.escape(ssid)}</b> successfully!")
            else:
                self.client.send_message(chat_id, f"❌ Failed to connect to {html.escape(ssid)}: {html.escape(res.get('message', 'Unknown error'))}")
        except Exception as e:
            self.client.send_message(chat_id, f"Connect error: {html.escape(str(e))}")

    def _wifi_saved(self, chat_id: int) -> None:
        try:
            profiles = gw.list_saved_wifi_connections()
            if not profiles:
                self.client.send_message(chat_id, "No saved Wi-Fi profiles found.")
                return

            lines = ["<b>📋 Saved Wi-Fi Profiles:</b>\n"]
            for p in profiles:
                active = "🟢 Active" if p.get("in_use") else "⚪ Saved"
                lines.append(f"• <b>{html.escape(p.get('name'))}</b> ({active}) — UUID: <code>{html.escape(p.get('uuid', '--'))}</code>")

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Error listing profiles: {html.escape(str(e))}")

    # =========================================================================
    # 8. Backups & Disaster Recovery
    # =========================================================================

    def _cmd_backup(self, chat_id: int, args: list[str]) -> None:
        subcmd = args[0].lower() if args else "list"

        if subcmd == "list":
            self._backup_list(chat_id)
        elif subcmd == "create":
            label = args[1].strip() if len(args) > 1 else "telegram_snapshot"
            self._backup_create(chat_id, label)
        elif subcmd == "send":
            if len(args) < 2:
                self.client.send_message(chat_id, "Usage: <code>/backup send &lt;filename&gt;</code>")
                return
            self._backup_send(chat_id, args[1].strip())
        else:
            self.client.send_message(
                chat_id,
                f"Unknown backup command: <code>{html.escape(subcmd)}</code>.\n"
                f"Supported: <code>/backup list</code>, <code>/backup create [label]</code>, <code>/backup send &lt;filename&gt;</code>"
            )

    def _backup_list(self, chat_id: int) -> None:
        try:
            backups = backup.list_backups()
            if not backups:
                self.client.send_message(chat_id, "No local backups found in <code>/var/lib/nmb/backups/</code>.")
                return

            lines = ["<b>📦 Stored Device Backups:</b>\n"]
            for b in backups[:10]:
                sz = format_bytes(b.get("size", 0))
                dt = b.get("created_at", "")
                fname = b.get("filename", "")
                lines.append(f"• <code>{html.escape(fname)}</code>\n  {dt} | {sz} | Type: {b.get('type')}")

            lines.append("\nTo download a backup via Telegram: <code>/backup send &lt;filename&gt;</code>")
            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Error listing backups: {html.escape(str(e))}")

    def _backup_create(self, chat_id: int, label: str) -> None:
        self.client.send_message(chat_id, f"<i>Creating atomic full system backup ({html.escape(label)})...</i>")
        try:
            res = backup.create_backup(self.cfg, backup_type="full", label=label)
            fname = res.get("filename", "")
            sz = format_bytes(res.get("size", 0))

            msg = f"""✅ <b>System Backup Created!</b>

Filename: <code>{html.escape(fname)}</code>
Size: <b>{sz}</b>
Includes: Config (/etc/nmb), Database history, WireGuard & OpenVPN cryptographic keys.

To download to your phone: <code>/backup send {html.escape(fname)}</code>"""
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self.client.send_message(chat_id, f"Backup error: {html.escape(str(e))}")

    def _backup_send(self, chat_id: int, filename: str) -> None:
        clean_name = os.path.basename(filename)
        path = backup.BACKUP_DIR / clean_name
        if not path.is_file():
            self.client.send_message(chat_id, f"Backup file <code>{html.escape(clean_name)}</code> not found.")
            return

        self.client.send_message(chat_id, f"<i>Uploading {html.escape(clean_name)}...</i>")
        try:
            data = path.read_bytes()
            caption = f"📦 <b>NetworkMeasureBox Backup Archive</b>\nFilename: <code>{html.escape(clean_name)}</code> ({format_bytes(len(data))})"
            ok = self.client.send_document(chat_id, clean_name, data, caption=caption)
            if not ok:
                self.client.send_message(chat_id, "Failed to send backup archive.")
        except Exception as e:
            self.client.send_message(chat_id, f"Upload error: {html.escape(str(e))}")

    # =========================================================================
    # 9. Hardware Drivers
    # =========================================================================

    def _cmd_drivers(self, chat_id: int) -> None:
        try:
            stat = drivers.get_full_driver_status()
            controllers = stat.get("controllers", [])
            missing_fw = stat.get("missing_firmware", [])
            recommended = stat.get("recommended_packages", [])

            lines = ["<b>🔧 Hardware Network Controllers & Drivers:</b>\n"]
            if not controllers:
                lines.append("<i>No physical controllers cataloged.</i>")
            else:
                for c in controllers:
                    chip = c.get("chipset_name") or c.get("device_name") or "Network Controller"
                    iface = c.get("interface") or "N/A"
                    driver_name = c.get("driver") or "generic"
                    bus = c.get("bus_type", "pci").upper()
                    lines.append(f"• <b>{html.escape(chip)}</b>\n  Interface: <code>{html.escape(iface)}</code> | Driver: <code>{html.escape(driver_name)}</code> ({bus})")

            if missing_fw:
                lines.append(f"\n⚠️ <b>Missing Firmware Detected:</b> {len(missing_fw)} blobs")

            if recommended:
                pkg_names = [p.get("package", str(p)) if isinstance(p, dict) else str(p) for p in recommended]
                pkgs = ", ".join(f"<code>{html.escape(p)}</code>" for p in pkg_names)
                lines.append(f"\n💡 <b>Recommended Packages:</b> {pkgs}")

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self.client.send_message(chat_id, f"Error getting driver status: {html.escape(str(e))}")

    # =========================================================================
    # 10. System Reboot
    # =========================================================================

    def _cmd_reboot(self, chat_id: int, args: list[str]) -> None:
        if not args or args[0].lower() != "now":
            self.client.send_message(
                chat_id,
                "⚠️ <b>Reboot Confirmation Required</b>\n"
                "To safely restart the NetworkMeasureBox host, send:\n"
                "👉 <code>/reboot now</code>"
            )
            return

        self.client.send_message(chat_id, "🔄 <b>Rebooting NetworkMeasureBox now...</b> Connectivity will resume in ~45 seconds.")
        try:
            subprocess.Popen(["sudo", "systemctl", "reboot"])
        except Exception as e:
            self.client.send_message(chat_id, f"Reboot error: {html.escape(str(e))}")
