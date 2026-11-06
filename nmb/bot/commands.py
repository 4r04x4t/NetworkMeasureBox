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
import nmb.netd.tailscale as tailscale
import nmb.netd.geoip as geoip
import nmb.report.llm_bundle as llm_bundle

log = logging.getLogger("nmb.bot.commands")

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Gyors Sebességmérés"}, {"text": "📈 NMHH Riport Letöltése"}],
        [{"text": "📡 Ping & Telemetria"}, {"text": "🛡️ Reklámblokkoló"}],
        [{"text": "🦎 Tailscale & VPN"}, {"text": "📶 Wi-Fi Kliensszonda"}],
        [{"text": "⚙️ Rendszerállapot"}, {"text": "ℹ️ Parancsok & Súgó"}]
    ],
    "resize_keyboard": True,
    "persistent": True
}


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
        raw_text = text.strip()
        if not raw_text:
            return

        # Friendly Hungarian menu button aliases
        menu_aliases = {
            "📊 gyors sebességmérés": "/test",
            "📊 gyorsmérés": "/test",
            "📈 nmhh riport letöltése": "/report",
            "📈 nmhh riport": "/report",
            "📡 ping & telemetria": "/ping",
            "🛡️ reklámblokkoló": "/adblock",
            "🦎 tailscale & vpn": "/vpn",
            "📶 wi-fi kliensszonda": "/wifi",
            "⚙️ rendszerállapot": "/status",
            "ℹ️ parancsok & súgó": "/help",
            "ℹ️ menü": "/help",
            "menü": "/help",
            "menu": "/help",
        }
        if raw_text.lower() in menu_aliases:
            raw_text = menu_aliases[raw_text.lower()]

        parts = raw_text.split()
        cmd = parts[0].lower().split("@")[0]  # strip @bot_name if present
        args = parts[1:]

        # Dispatch table
        if cmd in ("/start", "/help", "/menu"):
            self._cmd_help(chat_id)
        elif cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd == "/ping":
            self._cmd_ping(chat_id)
        elif cmd in ("/test", "/speedtest", "/speed"):
            self._cmd_test(chat_id, args)
        elif cmd in ("/report", "/nmhh", "/dossier"):
            self._cmd_report(chat_id)
        elif cmd in ("/tailscale", "/mesh"):
            self._cmd_tailscale(chat_id)
        elif cmd in ("/ai", "/diag", "/llm"):
            self._cmd_ai(chat_id)
        elif cmd == "/mode":
            self._cmd_mode(chat_id, args)
        elif cmd in ("/vpn", "/wireguard", "/pivpn"):
            self._cmd_vpn(chat_id, args)
        elif cmd in ("/dyndns", "/duckdns"):
            self._cmd_dyndns(chat_id, args)
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
                f"Ismeretlen parancs: <code>{html.escape(cmd)}</code>. Nyomd meg a menü gombok egyikét vagy írd be a /help parancsot.",
                reply_markup=MAIN_KEYBOARD
            )

    # =========================================================================
    # 1. Help & Navigation
    # =========================================================================

    def _cmd_help(self, chat_id: int) -> None:
        box_id = html.escape(str(self.cfg.system.box_id))
        msg = f"""<b>NetworkMeasureBox Irányító Chatbot</b>
<i>Eszközazonosító: {box_id}</i>

<b>📡 Hálózati Mérések & Diagnosztika:</b>
• /status - Rendszerállapot, Uptime, CPU és SLA megfelelőség
• /ping - Valós idejű késleltetés és csomagvesztés referencia csomópontok felé
• /test (vagy /speed) <code>[ookla|cloudflare|rtr]</code> - Sebességmérés futtatása
• /report - 24 órás NMHH Szélessáv.net riport letöltése (.html fájl)
• /ai - AI diagnosztikai naplócsomag letöltése LLM-ekhez (.md fájl)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - Üzemmód váltás

<b>🛡️ Biztonság, VPN & Tailscale:</b>
• /tailscale - Tailscale mesh VPN állapot, WebGUI link & belépés
• /vpn - WireGuard & OpenVPN állapot és kliensek
• /vpn clients - Csatlakozott kliensek és adatforgalom
• /vpn add <code>&lt;név&gt;</code> - Új WireGuard kliens + azonnali QR kód és .conf!
• /vpn qr <code>&lt;név&gt;</code> - QR kód újraküldése mobil párosításhoz
• /vpn conf <code>&lt;név&gt;</code> - Konfigurációs profil letöltése

<b>🦆 Dinamikus DNS (DuckDNS / dynv6):</b>
• /dyndns - DynDNS státusz, nyilvános IP és frissítési visszaszámláló
• /dyndns update - Azonnali kézi szinkronizáció

<b>🛡️ DNS Reklámblokkoló (Pi-hole Sinkhole):</b>
• /adblock - Blokkolt hirdetések, Gravity adatbázis és arány
• /adblock on | /adblock off - Reklámblokkolás ki/be kapcsolása
• /adblock block <code>&lt;domain&gt;</code> - Domain tiltása
• /adblock unblock <code>&lt;domain&gt;</code> - Domain engedélyezése
• /adblock update - Gravitáció blokklisták letöltése és frissítése

<b>📶 Wi-Fi & Vendég Wi-Fi Szonda:</b>
• /wifi - Wi-Fi szonda telemetria, jelerősség és izolációs riasztás
• /wifi scan - Környező 2.4/5 GHz-es Wi-Fi hálózatok keresése

<b>⚙️ Rendszer & Erőforrások:</b>
• /tasks (vagy /top) - CPU, RAM, Disk, Hőmérséklet és top folyamatok
• /heal - Autonóm öngyógyító és hibajavító alrendszer
• /reboot - Eszköz biztonságos újraindítása
"""
        self.client.send_message(chat_id, msg, reply_markup=MAIN_KEYBOARD)

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

            # Check Tailscale status
            try:
                ts_stat = tailscale.get_tailscale_status()
                ts_badge = f"🟢 UP ({ts_stat.get('tailscale_ip', '--')})" if ts_stat.get("logged_in") else ("🟡 LOGIN REQ" if ts_stat.get("auth_url") else "⚫ STOPPED")
            except Exception:
                ts_badge = "⚫ N/A"

            # Check WireGuard & Adblock quick states safely
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

            # Determine client IP and ISP
            client_ip = "--"
            try:
                dual = interfaces.get_dual_stack_ips()
                client_ip = dual.get("public_ipv4") or dual.get("ipv4") or "--"
            except Exception:
                pass
            isp_name = getattr(self.cfg.isp, "name", "Internet Provider")

            latest_st = rep.speed_tests[0] if rep.speed_tests else {}
            st_down = f"{latest_st.get('down_mbps', 0):.1f} Mb/s" if latest_st.get("down_mbps") else "--"
            st_up = f"{latest_st.get('up_mbps', 0):.1f} Mb/s" if latest_st.get("up_mbps") else "--"

            msg = f"""<b>📊 NetworkMeasureBox Rendszerállapot</b> [<code>{html.escape(self.cfg.system.box_id)}</code>]

🌐 <b>Nyilvános IP:</b> <code>{html.escape(client_ip)}</code>
🏢 <b>Szolgáltató (ISP):</b> <b>{html.escape(isp_name)}</b>
⚙️ <b>Üzemmód:</b> <code>{active_mode}</code> (WAN: <b>{wan_carrier}</b> | LAN: <b>{lan_carrier}</b>)

📈 <b>24h Rendelkezésre állás:</b> <b>{rep.uptime_pct:.2f}%</b> ({len(rep.outages)} kiesés)
⏱️ <b>Késleltetés (RTT):</b> {rep.ping_summary.rtt_avg_ms or '-'} ms (Jitter: {rep.ping_summary.jitter_avg_ms or '-'} ms)
📉 <b>Csomagvesztés:</b> <b>{rep.ping_summary.loss_pct:.2f}%</b>
⚖️ <b>SLA Hatósági Minősítés:</b> <b>{html.escape(str(rep.sla_verdict))}</b> (Megfelelőség: {rep.speed_summary.sla_compliance_pct:.0f}%)
🚀 <b>Legutóbbi Sebesség:</b> ↓ <b>{st_down}</b> | ↑ <b>{st_up}</b>

🛡️ <b>Szolgáltatások & Biztonság:</b>
• Tailscale Mesh VPN: <b>{ts_badge}</b>
• WireGuard VPN: <b>{wg_badge}</b>
• DNS Reklámblokkoló: <b>{ab_badge}</b>
"""
            inline_status = {
                "inline_keyboard": [
                    [{"text": "📊 Gyorsmérés", "callback_data": "/test"}, {"text": "📈 NMHH Riport", "callback_data": "/report"}],
                    [{"text": "📡 Ping Részletek", "callback_data": "/ping"}, {"text": "⚙️ Erőforrások (Top)", "callback_data": "/tasks"}],
                    [{"text": "🦎 Tailscale", "callback_data": "/tailscale"}, {"text": "🛡️ Reklámblokkoló", "callback_data": "/adblock"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_status)
        except Exception as e:
            log.error("error in /status: %s", e)
            self.client.send_message(chat_id, f"Error generating status: {html.escape(str(e))}", reply_markup=MAIN_KEYBOARD)

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

            lines = ["<b>📡 Valós Idejű Válaszidő & Csomagvesztés (Elmúlt 60 mp):</b>\n"]
            for r in rows:
                cnt = r["count"]
                lost = r["lost"]
                loss_pct = (lost / cnt * 100.0) if cnt > 0 else 0.0
                avg_ms = f"{(r['avg_us'] / 1000.0):.1f} ms" if r["avg_us"] else "Nincs válasz"
                loss_str = f"vesztés: {loss_pct:.0f}%"
                lines.append(f"• <b>{html.escape(r['label'])}</b> (<code>{html.escape(r['addr'])}</code>): <b>{avg_ms}</b> ({loss_str})")

            inline_ping = {
                "inline_keyboard": [
                    [{"text": "🔄 Frissítés (Ping)", "callback_data": "/ping"}, {"text": "🚀 Sebességmérés", "callback_data": "/test"}],
                    [{"text": "📊 Rendszerállapot", "callback_data": "/status"}, {"text": "🏠 Főmenü", "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, "\n".join(lines), reply_markup=inline_ping)
        except Exception as e:
            self.client.send_message(chat_id, f"Ping lekérdezési hiba: {html.escape(str(e))}")

    def _cmd_test(self, chat_id: int, args: list[str]) -> None:
        engine = args[0].lower() if args else None
        engine_str = f" (Motor: <b>{html.escape(engine.upper())}</b>)" if engine else ""
        self.client.send_chat_action(chat_id, "typing")
        self.client.send_message(chat_id, f"<i>🚀 Sebességmérés indítása{engine_str}... Kérlek várj kb. 15-25 másodpercet!</i>")
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
                """SELECT down_bps, up_bps, ping_us, jitter_us, loss_pct, server_name, status, engine, error
                   FROM speedtest ORDER BY ts DESC LIMIT 1"""
            ).fetchone()
            conn.close()

            if not row or row["status"] != "ok":
                err = row["error"] if row and row["error"] else "Mérés meghiúsult vagy elhalasztva."
                self.client.send_message(chat_id, f"⚠️ Sebességmérés hiba: {html.escape(str(err))}")
                return

            down_mbps = (row["down_bps"] or 0) / 1_000_000.0
            up_mbps = (row["up_bps"] or 0) / 1_000_000.0
            ping_ms = (row["ping_us"] or 0) / 1000.0
            jitter_ms = (row["jitter_us"] or 0) / 1000.0

            # Resolving IP and ISP
            client_ip = "--"
            try:
                dual = interfaces.get_dual_stack_ips()
                client_ip = dual.get("public_ipv4") or dual.get("ipv4") or "--"
            except Exception:
                pass
            isp_name = getattr(self.cfg.isp, "name", "Internet Provider")

            c_down = self.cfg.isp.contract_down_mbps or 1000.0
            c_up = self.cfg.isp.contract_up_mbps or 300.0
            g_down = self.cfg.isp.guaranteed_down_mbps or (c_down * 0.8)
            g_up = self.cfg.isp.guaranteed_up_mbps or (c_up * 0.8)

            down_compliance = (down_mbps / c_down) * 100.0 if c_down else 0.0
            up_compliance = (up_mbps / c_up) * 100.0 if c_up else 0.0

            # NMHH Status Code calculation
            if down_mbps >= g_down and up_mbps >= g_up:
                nmhh_code = 1
                nmhh_text = "1: Sikeres mérés (Megfelel a garantált értékeknek)"
                nmhh_badge = "🟢 MEGFELELŐ"
            elif down_mbps < g_down and up_mbps < g_up:
                nmhh_code = 6
                nmhh_text = "6: Letöltés és feltöltés elmaradás a garantált értéktől"
                nmhh_badge = "🔴 NEM MEGFELELŐ"
            elif down_mbps < g_down:
                nmhh_code = 14
                nmhh_text = "14: Letöltés elmaradás a garantált értéktől"
                nmhh_badge = "🟡 LETÖLTÉS HIBA"
            else:
                nmhh_code = 15
                nmhh_text = "15: Feltöltés elmaradás a garantált értéktől"
                nmhh_badge = "🟡 FELTÖLTÉS HIBA"

            active_engine = (row["engine"] if "engine" in row.keys() else engine) or "RTR-NetTest"

            msg = f"""<b>📊 Sebességmérés Eredmény ({html.escape(str(active_engine)).upper()})</b>

🌐 <b>Nyilvános IP:</b> <code>{html.escape(client_ip)}</code>
🏢 <b>Szolgáltató (ISP):</b> <b>{html.escape(isp_name)}</b>

📥 <b>Letöltés:</b> <b>{down_mbps:.1f} Mbps</b> ({down_compliance:.0f}% a szerződöttből | Min: {g_down:.0f} Mbps)
📤 <b>Feltöltés:</b> <b>{up_mbps:.1f} Mbps</b> ({up_compliance:.0f}% a szerződöttből | Min: {g_up:.0f} Mbps)
⏱️ <b>Késleltetés:</b> {ping_ms:.1f} ms (Jitter: {jitter_ms:.1f} ms)
🖥️ <b>Mérőszerver:</b> {html.escape(str(row['server_name'] or 'Edge Server'))}

⚖️ <b>NMHH Minősítés:</b> {nmhh_badge}
<i>{nmhh_text}</i>
"""
            inline_kb = {
                "inline_keyboard": [
                    [{"text": "🔄 RTR-NetTest", "callback_data": "/test rtr"}, {"text": "⚡ Ookla", "callback_data": "/test ookla"}, {"text": "☁️ Cloudflare", "callback_data": "/test cloudflare"}],
                    [{"text": "📈 NMHH Riport (.html)", "callback_data": "/report"}, {"text": "📊 Rendszerállapot", "callback_data": "/status"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_kb)
        except Exception as e:
            self.client.send_message(chat_id, f"Sebességmérés hiba: {html.escape(str(e))}")

    def _cmd_report(self, chat_id: int) -> None:
        self.client.send_chat_action(chat_id, "upload_document")
        self.client.send_message(chat_id, "<i>📊 24 órás NMHH Szélessáv.net hitelesített vizsgálati jegyzőkönyv generálása...</i>")
        try:
            conn = db.connect()
            report = aggregate_report_data(conn, self.cfg, window_hours=24.0)
            conn.close()

            html_doc = generate_html_dossier(report)
            date_str = time.strftime('%Y%m%d_%H%M%S')
            filename = f"NMHH_Szelessav_Riport_{self.cfg.system.box_id}_{date_str}.html"

            caption = (
                f"<b>📋 NMHH Szélessáv.net Vizsgálati Jegyzőkönyv (24h)</b>\n"
                f"Eszköz: <code>{html.escape(self.cfg.system.box_id)}</code> | Szolgáltató: <b>{html.escape(report.isp_name)}</b>\n"
                f"Hatósági minősítés: <b>{html.escape(str(report.sla_verdict))}</b>\n"
                f"SLA Megfelelőség: <b>{report.speed_summary.sla_compliance_pct:.0f}%</b> | Elérhetőség: <b>{report.uptime_pct:.2f}%</b>"
            )

            ok = self.client.send_document(chat_id, filename, html_doc.encode("utf-8"), caption=caption)
            if not ok:
                self.client.send_message(chat_id, "A jegyzőkönyv elkészült, de a fájlküldés nem sikerült.")
        except Exception as e:
            self.client.send_message(chat_id, f"Riport generálási hiba: {html.escape(str(e))}")

    def _cmd_tailscale(self, chat_id: int) -> None:
        try:
            ts_stat = tailscale.get_tailscale_status()
            logged_in = ts_stat.get("logged_in", False)
            ts_ip = ts_stat.get("tailscale_ip", "--")
            magic_dns = ts_stat.get("magic_dns", "--")
            auth_url = ts_stat.get("auth_url")
            backend_state = ts_stat.get("backend_state", "Unknown")

            if logged_in:
                badge = "🟢 AKTÍV ÉS CSATLAKOZVA"
                status_desc = f"A mérődoboz sikeresen csatlakozott a Tailscale hálózathoz. Bárhonnan biztonságosan elérheted a WebGUI-t ezen az IP-n:\n👉 <code>http://{ts_ip}:8080</code>"
            elif auth_url:
                badge = "🟡 HITELESÍTÉS SZÜKSÉGES"
                status_desc = f"Az eszköz vár a hitelesítésre. Nyisd meg a linket a jóváhagyáshoz:\n👉 <a href=\"{auth_url}\">{auth_url}</a>"
            else:
                badge = f"⚫ INAKTÍV ({backend_state})"
                status_desc = "A Tailscale jelenleg nincs csatlakoztatva vagy nincs bejelentkezve."

            msg = f"""<b>🦎 Tailscale Mesh VPN Állapot</b>

• Állapot: <b>{badge}</b>
• Tailscale IP: <code>{html.escape(ts_ip)}</code>
• MagicDNS Név: <code>{html.escape(magic_dns)}</code>
• Szerepkör: Adminisztráció & WebGUI távoli elérés (nem NAT-ol vagy irányít át internet forgalmat)

{status_desc}
"""
            buttons = []
            if auth_url:
                buttons.append([{"text": "🔑 Hitelesítés Megnyitása", "url": auth_url}])
            buttons.append([{"text": "🔄 Frissítés", "callback_data": "/tailscale"}, {"text": "📊 Rendszerállapot", "callback_data": "/status"}])
            buttons.append([{"text": "🛡️ VPN Hub (WireGuard)", "callback_data": "/vpn"}, {"text": "🏠 Főmenü", "callback_data": "/menu"}])

            self.client.send_message(chat_id, msg, reply_markup={"inline_keyboard": buttons})
        except Exception as e:
            self.client.send_message(chat_id, f"Tailscale lekérdezési hiba: {html.escape(str(e))}")

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
            inline_vpn = {
                "inline_keyboard": [
                    [{"text": "👥 Kliensek Listája", "callback_data": "/vpn clients"}, {"text": "🦎 Tailscale Állapot", "callback_data": "/tailscale"}],
                    [{"text": "📊 Rendszerállapot", "callback_data": "/status"}, {"text": "🏠 Főmenü", "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_vpn)
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
    # 3b. DuckDNS Dynamic DNS (DynDNS)
    # =========================================================================

    def _cmd_dyndns(self, chat_id: int, args: list[str]) -> None:
        import nmb.netd.duckdns as dd
        from nmb.config import save_config

        subcmd = args[0].lower() if args else ""
        d_cfg = self.cfg.duckdns

        if subcmd in ("update", "sync", "now", "force"):
            if not d_cfg.domain or not d_cfg.token:
                self.client.send_message(
                    chat_id,
                    "⚠️ <b>DuckDNS not configured</b>: Subdomain and token must be set before synchronizing.\n"
                    "Use: <code>/dyndns domain &lt;subdomain&gt;</code> and <code>/dyndns token &lt;token&gt;</code>"
                )
                return

            self.client.send_message(chat_id, "⏳ <i>Triggering DuckDNS synchronization...</i>")
            detected_v6 = None
            try:
                from nmb.netd.wireguard import get_device_addresses
                _, v6_addrs = get_device_addresses()
                if v6_addrs:
                    detected_v6 = v6_addrs[0][1]
            except Exception:
                pass

            res = dd.update_duckdns(
                domain=d_cfg.domain,
                token=d_cfg.token,
                ip=d_cfg.custom_ip if d_cfg.custom_ip else None,
                ipv6=detected_v6,
            )
            dd.wake_duckdns_daemon()

            if res.get("status") == "ok" or res.get("success"):
                ip = res.get("ip") or "detected WAN IP"
                fqdn = res.get("fqdn") or f"{dd.clean_domain(d_cfg.domain)}.duckdns.org"
                updated_tag = " (IP Updated)" if res.get("updated") else " (IP Unchanged)"
                self.client.send_message(
                    chat_id,
                    f"✅ <b>DuckDNS Synced Successfully!</b>\n\n"
                    f"• <b>Hostname:</b> <code>{html.escape(fqdn)}</code>\n"
                    f"• <b>Public IP:</b> <code>{html.escape(ip)}</code>{updated_tag}\n"
                    f"• <b>Status:</b> <code>{html.escape(res.get('message', 'OK'))}</code>"
                )
            else:
                self.client.send_message(
                    chat_id,
                    f"❌ <b>DuckDNS Update Failed:</b>\n\n"
                    f"<code>{html.escape(res.get('message', 'Unknown error'))}</code>"
                )
            return

        if subcmd in ("interval", "every", "time"):
            if len(args) < 2:
                curr_int = d_cfg.update_interval_min
                self.client.send_message(
                    chat_id,
                    f"ℹ️ Current DuckDNS update interval is <b>{curr_int} minutes</b>.\n"
                    f"Usage to change: <code>/dyndns interval &lt;minutes&gt;</code> (e.g. <code>/dyndns interval 5</code>)"
                )
                return
            try:
                new_int = max(1, min(1440, int(args[1])))
            except ValueError:
                self.client.send_message(chat_id, "❌ Invalid interval. Please specify a number between 1 and 1440.")
                return

            d_cfg.update_interval_min = new_int
            save_config(self.cfg)
            dd.wake_duckdns_daemon()

            self.client.send_message(
                chat_id,
                f"✅ <b>DuckDNS Interval Updated!</b>\n\n"
                f"• <b>New Interval:</b> <code>{new_int} minutes</code>\n"
                f"• <b>Saved to:</b> <code>/etc/nmb/nmb.conf</code>\n"
                f"• <b>Daemon Status:</b> Woken up immediately; new schedule active."
            )
            return

        if subcmd in ("on", "enable", "start"):
            d_cfg.enabled = True
            save_config(self.cfg)
            dd.start_duckdns_service(lambda: self.cfg)
            dd.wake_duckdns_daemon()
            self.client.send_message(
                chat_id,
                "✅ <b>DuckDNS updater enabled and started!</b>\n"
                f"Hostname: <code>{html.escape(dd.clean_domain(d_cfg.domain))}.duckdns.org</code> (Interval: {d_cfg.update_interval_min}m)"
            )
            return

        if subcmd in ("off", "disable", "stop"):
            d_cfg.enabled = False
            save_config(self.cfg)
            dd.stop_duckdns_service()
            self.client.send_message(chat_id, "⚪ <b>DuckDNS updater disabled and stopped.</b>")
            return

        if subcmd in ("domain", "host", "subdomain"):
            if len(args) < 2:
                curr_dom = d_cfg.domain
                self.client.send_message(
                    chat_id,
                    f"ℹ️ Current DuckDNS domain: <code>{html.escape(curr_dom or '(none)')}</code>\n"
                    f"Usage: <code>/dyndns domain &lt;subdomain&gt;</code>"
                )
                return
            new_dom = dd.clean_domain(args[1])
            d_cfg.domain = new_dom
            save_config(self.cfg)
            dd.wake_duckdns_daemon()
            self.client.send_message(
                chat_id,
                f"✅ <b>DuckDNS Subdomain set to:</b> <code>{html.escape(new_dom)}.duckdns.org</code>"
            )
            return

        if subcmd == "token":
            if len(args) < 2:
                is_set = "Configured" if d_cfg.token else "Not configured"
                self.client.send_message(
                    chat_id,
                    f"ℹ️ DuckDNS Token: <b>{is_set}</b>\n"
                    f"Usage: <code>/dyndns token &lt;token&gt;</code>"
                )
                return
            new_tok = args[1].strip()
            d_cfg.token = new_tok
            save_config(self.cfg)
            dd.wake_duckdns_daemon()
            self.client.send_message(
                chat_id,
                "✅ <b>DuckDNS Token updated & securely saved in /etc/nmb/nmb.conf!</b>"
            )
            return

        # Default: Status overview
        st = dd.get_duckdns_status(self.cfg)
        status_badge = "🟢 ENABLED (Running)" if st.get("enabled") else "⚪ DISABLED"
        last_st = st.get("last_status", "Never Run")
        last_st_badge = "🟢 OK" if last_st == "OK" else ("🔴 KO" if last_st == "KO" else html.escape(str(last_st)))
        fqdn = st.get("fqdn") or (f"{st.get('domain')}.duckdns.org" if st.get("domain") else "<i>(Not configured)</i>")
        wan_ip = st.get("last_ip") or st.get("detected_ip") or "<i>(Pending detection)</i>"
        interval_m = st.get("update_interval_min", 10)
        last_up = st.get("last_update") or "Never"
        next_secs = st.get("next_update_seconds", 0)
        if next_secs > 0:
            nm = next_secs // 60
            ns = next_secs % 60
            next_str = f"in {nm}m {ns}s ({st.get('next_update', '')})"
        else:
            next_str = st.get("next_update") or "--"

        msg = f"""<b>🦆 DuckDNS Dynamic DNS (DynDNS)</b>
<b>Daemon Status:</b> {status_badge}

• <b>FQDN:</b> <code>{fqdn}</code>
• <b>Public WAN IP:</b> <code>{wan_ip}</code>
• <b>Update Interval:</b> <code>{interval_m} minutes</code>
• <b>Last Update:</b> <code>{html.escape(last_up)}</code> ({last_st_badge})
• <b>Next Scheduled Sync:</b> <code>{html.escape(next_str)}</code>
• <b>Token Configured:</b> {"Yes (Configured)" if st.get("token_set") else "No"}
• <b>Last Message:</b> <i>{html.escape(st.get("last_message") or "Ready")}</i>

<b>Quick Commands:</b>
• <code>/dyndns update</code> - Force immediate sync
• <code>/dyndns interval &lt;minutes&gt;</code> - Change sync interval
• <code>/dyndns on</code> | <code>/dyndns off</code> - Toggle updater
• <code>/dyndns domain &lt;name&gt;</code> - Change subdomain"""
        self.client.send_message(chat_id, msg)

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
   👉 <code>{html.escape(guide.get('primary_dns_ip') or guide.get('box_ip') or '192.168.1.100')}</code>
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
            inline_ab = {
                "inline_keyboard": [
                    [{"text": "🟢 Bekapcsolás" if not is_enabled else "🔴 Kikapcsolás", "callback_data": "/adblock off" if is_enabled else "/adblock on"},
                     {"text": "🔄 Blokklisták Frissítése", "callback_data": "/adblock update"}],
                    [{"text": "📊 Rendszerállapot", "callback_data": "/status"}, {"text": "🏠 Főmenü", "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_ab)
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
            inline_tasks = {
                "inline_keyboard": [
                    [{"text": "🔄 Frissítés", "callback_data": "/tasks"}, {"text": "📊 Rendszerállapot", "callback_data": "/status"}],
                    [{"text": "🏠 Főmenü", "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_tasks)
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
            inline_wifi = {
                "inline_keyboard": [
                    [{"text": "🔍 Wi-Fi Keresés", "callback_data": "/wifi scan"}, {"text": "🔄 Szonda Frissítés", "callback_data": "/wifi"}],
                    [{"text": "📊 Rendszerállapot", "callback_data": "/status"}, {"text": "🏠 Főmenü", "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_wifi)
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
