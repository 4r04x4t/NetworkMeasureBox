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
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from nmb.bot.client import TelegramClient
from nmb.common import net_setup, setup_texts
from nmb.config import Config
from nmb.db import database as db
from nmb.netd import interfaces
from nmb.report.dossier import generate_html_dossier
from nmb.report.metrics import SETUP_COLS, _columns, _setup_of, aggregate_report_data
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

from nmb.bot.i18n import (
    DEFAULT_LANGUAGE,
    LANG_INFO,
    SUPPORTED_LANGUAGES,
    get_chat_lang,
    get_language_keyboard,
    get_main_keyboard,
    get_menu_aliases,
    get_measurement_status,
    get_sla_verdict,
    set_chat_lang,
    t,
)

log = logging.getLogger("nmb.bot.commands")

# Backwards-compatible default keyboard
MAIN_KEYBOARD = get_main_keyboard("en")


def format_bytes(num_bytes: int | float) -> str:
    """Format bytes into human-readable string (B, KB, MB, GB, TB)."""
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(val) < 1024.0:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


def _host_usage() -> tuple:
    """CPU % (0.2 s sample), memory and root-disk usage, SoC temperature."""
    def cpu_times() -> tuple:
        with open("/proc/stat", encoding="utf-8") as f:
            vals = [int(x) for x in f.readline().split()[1:]]
        return sum(vals), vals[3] + (vals[4] if len(vals) > 4 else 0)
    cpu = 0.0
    try:
        t1, i1 = cpu_times(); time.sleep(0.2); t2, i2 = cpu_times()
        cpu = 100.0 * (1 - (i2 - i1) / max(1, t2 - t1))
    except (OSError, ValueError, IndexError):
        pass
    mem = {"used": 0, "total": 0, "percent": 0.0}
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        mem = {"used": total - avail, "total": total, "percent": 100.0 * (total - avail) / total if total else 0.0}
    except (OSError, ValueError):
        pass
    disk = {"used": 0, "total": 0, "percent": 0.0}
    try:
        du = shutil.disk_usage("/")
        disk = {"used": du.used, "total": du.total, "percent": 100.0 * du.used / du.total if du.total else 0.0}
    except OSError:
        pass
    temp = None
    try:
        temp = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
    except (OSError, ValueError):
        pass
    return cpu, mem, disk, temp


# ------------------------------------------------------------------ how the box was connected
def setup_select(conn: sqlite3.Connection, table: str = "speedtest") -> str:
    """', box_mode, uplink_kind, isp_path, setup_source' when the table has them, else ''.

    A read-only connection does not migrate, so a database not upgraded yet lacks the columns.
    """
    return ", " + ", ".join(SETUP_COLS) if set(SETUP_COLS) <= _columns(conn, table) else ""


def setup_html(row: Any, lang: str) -> str:
    """"Router · PPPoE · direct to the ISP" for Telegram HTML; a changed or reconstructed setup says so."""
    codes = _setup_of(row)
    text = html.escape(setup_texts.summary(codes, lang))
    if codes["setup_source"] in ("changed", "derived"):
        text += f" (<i>{html.escape(setup_texts.source_label(codes['setup_source'], lang))}</i>)"
    return text


def _current_link(conn: sqlite3.Connection) -> Dict[str, Optional[str]]:
    """The link netd recorded last (network_state); every value None when nothing was recorded.

    Only a recorded row tells the present: a reconstructed one describes the time before recording began.
    """
    try:
        row = conn.execute("SELECT iface, uplink_kind, isp_path FROM network_state WHERE source = 'recorded' "
                           "ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        row = None
    iface, kind, path = tuple(row) if row else (None, None, None)
    return {"iface": iface, "uplink_kind": kind if kind in net_setup.UPLINK_KINDS else None,
            "isp_path": path if path in net_setup.ISP_PATHS else None}


def _mode_words(code: Optional[str], lang: str) -> str:
    """'Router mode (mode_a)'; the code stays beside it, since /mode takes the code."""
    if code == "auto":
        return code
    if code in net_setup.MODES:
        return f"{setup_texts.mode_label(code, lang)} ({code})"
    return setup_texts.mode_label(None, lang)      # nothing recorded, or no mode code: unknown


class CommandHandler:
    def __init__(self, cfg: Config, client: TelegramClient):
        self.cfg = cfg
        self.client = client

    def _l(self, chat_id: int) -> str:
        return get_chat_lang(chat_id, self.cfg)

    def _tr(self, chat_id: int, key: str, **kwargs) -> str:
        return t(key, self._l(chat_id), **kwargs)

    def _say(self, chat_id: int, key: str, **kwargs) -> None:
        self.client.send_message(chat_id, self._tr(chat_id, key, **kwargs))

    def _say_error(self, chat_id: int, op: str, error: object) -> None:
        # Some exceptions carry no text; then the type is the most useful thing to show.
        text = str(error).strip() or type(error).__name__
        log.error("error in %s: %s", op, text)
        self._say(chat_id, "op_error", op=op, error=html.escape(text))

    def handle_command(self, chat_id: int, text: str) -> None:
        raw_text = text.strip()
        if not raw_text:
            return

        lang = get_chat_lang(chat_id, self.cfg)
        menu_aliases = get_menu_aliases()

        if raw_text.lower() in menu_aliases:
            raw_text = menu_aliases[raw_text.lower()]

        parts = raw_text.split()
        cmd = parts[0].lower().split("@")[0]  # strip @bot_name if present
        args = parts[1:]

        # Dispatch table
        if cmd in ("/start", "/help", "/menu"):
            self._cmd_help(chat_id, lang)
        elif cmd in ("/donate", "/support"):
            self._cmd_donate(chat_id, lang)
        elif cmd == "/sla":
            self._say(chat_id, "sla_explain")
        elif cmd == "/purge":
            self._cmd_purge(chat_id, args)
        elif cmd in ("/lang", "/language"):
            self._cmd_lang(chat_id, args, lang)
        elif cmd == "/status":
            self._cmd_status(chat_id, lang)
        elif cmd == "/ping":
            self._cmd_ping(chat_id, lang)
        elif cmd in ("/test", "/speedtest", "/speed"):
            self._cmd_test(chat_id, args, lang)
        elif cmd in ("/report", "/dossier"):
            self._cmd_report(chat_id, lang)
        elif cmd in ("/tailscale", "/mesh"):
            self._cmd_tailscale(chat_id, lang)
        elif cmd in ("/ai", "/diag", "/llm"):
            self._cmd_ai(chat_id, lang)
        elif cmd == "/mode":
            self._cmd_mode(chat_id, args, lang)
        elif cmd in ("/vpn", "/wireguard", "/pivpn"):
            self._cmd_vpn(chat_id, args, lang)
        elif cmd in ("/dyndns", "/duckdns"):
            self._cmd_dyndns(chat_id, args, lang)
        elif cmd in ("/adblock", "/pihole", "/sinkhole"):
            self._cmd_adblock(chat_id, args, lang)
        elif cmd in ("/heal", "/repair", "/audit"):
            self._cmd_heal(chat_id, args, lang)
        elif cmd in ("/tasks", "/top", "/htop", "/ps"):
            self._cmd_tasks(chat_id, lang)
        elif cmd == "/kill":
            self._cmd_kill(chat_id, args, lang)
        elif cmd in ("/wifi", "/wlan"):
            self._cmd_wifi(chat_id, args, lang)
        elif cmd in ("/backup", "/backups"):
            self._cmd_backup(chat_id, args, lang)
        elif cmd in ("/drivers", "/driver"):
            self._cmd_drivers(chat_id, lang)
        elif cmd == "/reboot":
            self._cmd_reboot(chat_id, args, lang)
        else:
            self.client.send_message(
                chat_id,
                t("unknown_cmd", lang, cmd=html.escape(cmd)),
                reply_markup=get_main_keyboard(lang)
            )

    # =========================================================================
    # 1. Help & Navigation & Language
    # =========================================================================

    def _cmd_help(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        box_id = html.escape(str(self.cfg.system.box_id))
        msg = t("help_message", lang, box_id=box_id) + f"\n\n❤️ {html.escape(t('donate_footer', lang))}: /donate"
        self.client.send_message(chat_id, msg, reply_markup=get_main_keyboard(lang))

    def _cmd_donate(self, chat_id: int, lang: Optional[str] = None) -> None:
        """The project's donation addresses (nmb/common/donate.py); each in <code> so a tap copies it."""
        from nmb.common import donate
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        lines = [f"❤️ <b>{html.escape(t('donate_title', lang))}</b>", html.escape(t("donate_text", lang)), ""]
        for a in donate.ADDRESSES:
            lines.append(f"<b>{html.escape(a.network)}</b>\n<code>{html.escape(a.address)}</code>")
        self.client.send_message(chat_id, "\n".join(lines), reply_markup=get_main_keyboard(lang))

    def _cmd_lang(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        if not args:
            curr_info = LANG_INFO.get(lang, LANG_INFO["en"])
            curr_label = f"{curr_info['flag']} {curr_info['name']}"
            msg = f"{t('lang_title', lang)}\n\n{t('lang_desc', lang, curr_lang=curr_label)}"
            self.client.send_message(chat_id, msg, reply_markup=get_language_keyboard())
            return

        new_lang = args[0].lower().strip()
        if new_lang not in SUPPORTED_LANGUAGES:
            valid_langs = ", ".join(f"<code>{c}</code>" for c in SUPPORTED_LANGUAGES)
            self.client.send_message(
                chat_id,
                f"Unsupported language code <code>{html.escape(new_lang)}</code>. Valid codes: {valid_langs}",
                reply_markup=get_language_keyboard()
            )
            return

        set_chat_lang(chat_id, new_lang)
        info = LANG_INFO[new_lang]
        success_msg = t("lang_updated", new_lang, flag=info["flag"], name=info["name"])
        self.client.send_message(chat_id, success_msg, reply_markup=get_main_keyboard(new_lang))

    # =========================================================================
    # 2. Status & Network Telemetry
    # =========================================================================

    def _cmd_status(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            conn = db.connect(readonly=True)
            try:
                # The mode in words; no mode code recorded is unknown, never a raw value
                mode_txt = html.escape(setup_texts.mode_label(net_setup.active_mode(conn)[0], lang, short=True))
                link = _current_link(conn)
                # 24h report summary
                rep = aggregate_report_data(conn, self.cfg, window_hours=24.0)
            finally:
                conn.close()

            wan_carrier = "UP" if interfaces.get_carrier(self.cfg.network.wan_interface) else "DOWN"
            lan_carrier = "UP" if interfaces.get_carrier(self.cfg.network.lan_interface) else "DOWN"

            # Check Tailscale status
            try:
                ts_stat = tailscale.get_tailscale_status()
                ts_badge = f"{t('badge_up', lang)} ({ts_stat.get('tailscale_ipv4') or '--'})" if ts_stat.get("active") else (t("badge_login_req", lang) if ts_stat.get("auth_url") else t("badge_stopped", lang))
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

            wg_badge = t("badge_up", lang) if wg_stat.get("active") else t("badge_stopped", lang)
            ab_badge = t("badge_on_domains", lang, count=f"{ab_stat.get('domains_on_blocklist', 0):,}") if ab_stat.get("enabled") else t("badge_off", lang)

            # Determine client IP and ISP
            client_ip = "--"
            try:
                from nmb.common.netaddr import global_ip
                dual = interfaces.get_dual_stack_ips()
                # The current public address only; a LAN address is never shown as the public one.
                client_ip = global_ip(dual.get("public_ipv4")) or global_ip(dual.get("ipv4")) or "--"
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            isp_name = getattr(self.cfg.isp, "name", "Internet Provider")

            # The newest test of the line (a LAN server's test measured the home network)
            latest_st = next((s for s in rep.speed_tests if s.get("status") == "ok" and s.get("scope") != "lan"), {})
            st_down = f"{latest_st['down_mbps']:.1f} Mb/s" if latest_st.get("down_mbps") is not None else "--"
            st_up = f"{latest_st['up_mbps']:.1f} Mb/s" if latest_st.get("up_mbps") is not None else "--"
            # How that test was connected (its own stored setup, never today's), and the link now
            st_setup = f"\n   ↳ {html.escape(t('setup_label', lang))}: {setup_html(latest_st, lang)}" if latest_st else ""
            iface_txt = f" (<code>{html.escape(str(link['iface']))}</code>)" if link["iface"] else ""
            link_line = (f"🔌 <b>{html.escape(t('setup_col_link', lang))}:</b> "
                         f"{html.escape(setup_texts.link_label(link['uplink_kind'], lang))}{iface_txt} | "
                         f"<b>{html.escape(t('setup_col_path', lang))}:</b> "
                         f"{html.escape(setup_texts.path_label(link['isp_path'], lang))}")
            loss_txt = f"{rep.ping_summary.loss_pct:.2f}%" if rep.ping_summary.total_sent else "--"
            compliance_txt = f"{rep.speed_summary.sla_compliance_pct:.0f}%" if rep.speed_summary.judged_tests else "--"

            outages_cnt = len(rep.outages)
            outages_label = t("outages_label", lang)

            rtt_avg = rep.ping_summary.rtt_avg_ms or '-'
            jitter_avg = rep.ping_summary.jitter_avg_ms or '-'
            sla_verdict_str = get_sla_verdict(str(rep.sla_verdict), lang)
            sla_reason_line = ""
            if rep.sla_reasons:
                reasons = "; ".join(t(f"sla_reason_{r}", lang) for r in rep.sla_reasons)
                sla_reason_line = "\n<i>" + t("sla_reasons_line", lang, reasons=reasons) + " (/sla)</i>"

            dc_line = ""
            try:
                # What the speed tests used in the current data cap period, per link (and the cap when set).
                from nmb.speed import data_cap
                dconn = db.connect(readonly=True)
                try:
                    u = data_cap.usage(dconn, self.cfg)
                finally:
                    dconn.close()
                parts = [f"{l['link']} {l['used_mb'] / 1000:.1f} GB" + (f" / {l['cap_mb'] / 1000:.0f} GB" if l["cap_mb"] else "")
                         + (" ⛔" if l["reached"] else "") for l in u["links"] if l["used_mb"] or l["cap_mb"]]
                if parts:
                    dc_line = f"\n📦 <b>{t('data_used_tests', lang, since=u['period_start'])}:</b> " + ", ".join(parts)
            except Exception:
                log.debug("data cap line not built", exc_info=True)

            msg = f"""<b>{t('status_title', lang)}</b> [<code>{html.escape(self.cfg.system.box_id)}</code>]

🌐 <b>{t('public_ip', lang)}:</b> <code>{html.escape(client_ip)}</code>
🏢 <b>{t('isp', lang)}:</b> <b>{html.escape(isp_name)}</b>
⚙️ <b>{t('mode', lang)}:</b> <b>{mode_txt}</b> (WAN: <b>{wan_carrier}</b> | LAN: <b>{lan_carrier}</b>)
{link_line}

📈 <b>{t('uptime_24h', lang)}:</b> <b>{f"{rep.uptime_pct:.2f}%" if rep.uptime_known else "--"}</b> ({outages_cnt} {outages_label})
⏱️ <b>{t('latency_rtt', lang)}:</b> {rtt_avg} ms (Jitter: {jitter_avg} ms)
📉 <b>{t('packet_loss', lang)}:</b> <b>{loss_txt}</b>
⚖️ <b>{t('sla_verdict', lang)}:</b> <b>{html.escape(sla_verdict_str)}</b> ({t('compliance', lang)}: {compliance_txt}){sla_reason_line}
🚀 <b>{t('latest_speed', lang)}:</b> ↓ <b>{st_down}</b> | ↑ <b>{st_up}</b>{st_setup}{dc_line}

🛡️ <b>{t('services_security', lang)}:</b>
• Tailscale Mesh VPN: <b>{ts_badge}</b>
• WireGuard VPN: <b>{wg_badge}</b>
• DNS Sinkhole: <b>{ab_badge}</b>
"""
            inline_status = {
                "inline_keyboard": [
                    [{"text": t("btn_quick_test", lang), "callback_data": "/test"}, {"text": t("btn_report", lang), "callback_data": "/report"}],
                    [{"text": t("btn_ping_details", lang), "callback_data": "/ping"}, {"text": t("btn_top_resources", lang), "callback_data": "/tasks"}],
                    [{"text": t("btn_tailscale", lang), "callback_data": "/tailscale"}, {"text": t("btn_adblock", lang), "callback_data": "/adblock"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_status)
        except Exception as e:
            log.error("error in /status: %s", e)
            self.client.send_message(chat_id, t("op_error", lang, op="Status", error=html.escape(str(e))), reply_markup=get_main_keyboard(lang))

    def _cmd_purge(self, chat_id: int, args: list[str]) -> None:
        from nmb.common import purge as purge_mod
        lang = self._l(chat_id)
        category = args[0].lower() if args else ""
        confirmed = len(args) > 1 and args[1].lower() == "confirm"
        selected = list(purge_mod.CATEGORIES) if category == "all" else [category]
        if not confirmed or not set(selected) <= set(purge_mod.CATEGORIES):
            summary = purge_mod.get_purge_summary(self.cfg)
            rows = "\n".join(
                f"• {t('purge_cat_' + c, lang)}: <b>{summary[c]['items']:,}</b> ({format_bytes(summary[c]['bytes'])})"
                for c in purge_mod.CATEGORIES
            )
            self._say(chat_id, "purge_menu", rows=rows)
            return
        try:
            result = purge_mod.purge(self.cfg, selected)
            done = [t("purge_cat_" + c, lang) for c in selected if c not in result["errors"]]
            if done:
                self._say(chat_id, "purge_done", cats=", ".join(done))
            for c, err in result["errors"].items():
                self._say_error(chat_id, t("purge_cat_" + c, lang), err)
        except Exception as e:
            self._say_error(chat_id, "Purge", e)

    def _cmd_ping(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            conn = db.connect(readonly=True)
            now = db.now_ms()
            rows = conn.execute(
                # COUNT(p.ts): a target without samples (probe stopped, switched off) has 0, not the one
                # NULL row of the LEFT JOIN that read as "100 % lost"; switched-off targets are not listed.
                """SELECT t.addr, t.label, AVG(p.rtt_us) as avg_us,
                          COUNT(p.ts) as count,
                          SUM(CASE WHEN p.ts IS NOT NULL AND p.rtt_us IS NULL THEN 1 ELSE 0 END) as lost
                   FROM target t
                   LEFT JOIN ping_sample p ON t.id = p.target_id AND p.ts >= ?
                   WHERE t.enabled = 1
                   GROUP BY t.id""",
                (now - 60_000,)
            ).fetchall()
            conn.close()

            lines = [t("ping_header", lang)]
            for r in rows:
                cnt = r["count"]
                lost = r["lost"]
                avg_ms = f"{(r['avg_us'] / 1000.0):.1f} ms" if r["avg_us"] is not None else (t("ping_no_resp", lang) if cnt else "--")
                loss_str = f"{t('ping_loss_label', lang)}: " + (f"{(lost or 0) / cnt * 100.0:.0f}%" if cnt else "--")
                lines.append(f"• <b>{html.escape(r['label'])}</b> (<code>{html.escape(r['addr'])}</code>): <b>{avg_ms}</b> ({loss_str})")

            inline_ping = {
                "inline_keyboard": [
                    [{"text": t("btn_refresh", lang), "callback_data": "/ping"}, {"text": t("btn_speedtest", lang), "callback_data": "/test"}],
                    [{"text": t("btn_status", lang), "callback_data": "/status"}, {"text": t("btn_main_menu", lang), "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, "\n".join(lines), reply_markup=inline_ping)
        except Exception as e:
            self._say_error(chat_id, "Ping", e)

    def _cmd_test(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        engine = args[0].lower() if args else None
        engine_str = f" ({html.escape(engine.upper())})" if engine else ""
        self.client.send_chat_action(chat_id, "typing")
        self.client.send_message(chat_id, t("speed_starting", lang, engine_str=engine_str))
        try:
            t0 = db.now_ms()
            outcome: dict = {}
            ok = run_measurement_cycle(
                self.cfg,
                trigger="telegram",
                force=True,
                run_port_check=True,
                engine=engine,
                outcome=outcome,
            )

            # Only this test's own rows: a scheduled test may have stored one meanwhile (2026-11-09).
            conn = db.connect(readonly=True)
            try:
                setup_cols = setup_select(conn)
                rows = conn.execute(
                    f"""SELECT down_bps, up_bps, ping_us, jitter_us, loss_pct, server_name, status, engine, error, client_ip,
                              client_ipv6, client_ip_source, server_host{setup_cols}
                       FROM speedtest WHERE ts >= ? AND trigger = 'telegram' ORDER BY id""", (t0 - 1000,)
                ).fetchall()
            finally:
                conn.close()
            ok_rows = [r for r in rows if r["status"] == "ok"]
            row = ok_rows[-1] if ok_rows else (rows[-1] if rows else None)

            if not row or row["status"] != "ok":
                err = (row["error"] if row and row["error"] else outcome.get("error")) or t("speed_cycle_failed", lang)
                self.client.send_message(chat_id, t("speed_error", lang, error=html.escape(str(err))))
                return

            # A direction the test did not measure stays unknown ("--"), never 0 and never a deficit.
            down_mbps = row["down_bps"] / 1_000_000.0 if row["down_bps"] is not None else None
            up_mbps = row["up_bps"] / 1_000_000.0 if row["up_bps"] is not None else None
            from nmb.report.status_codes import speed_scope
            lan = speed_scope(dict(row)) == "lan"
            ping_txt = f"{row['ping_us'] / 1000.0:.1f} ms" if row["ping_us"] is not None else "--"
            jitter_txt = f"{row['jitter_us'] / 1000.0:.1f} ms" if row["jitter_us"] is not None else "--"

            # The address this test had; no other address in its place (2026-11-10).
            client_ip = row["client_ip"] or row["client_ipv6"] or "--"
            isp_name = "LAN" if lan else getattr(self.cfg.isp, "name", "Internet Provider")
            if lan and client_ip != "--":
                client_ip += " (LAN)"

            # Only the speeds the owner set: nothing invented (it used 1000/300 Mbit/s and 80 % of them).
            c_down = float(self.cfg.isp.contract_down_mbps or 0.0)
            c_up = float(self.cfg.isp.contract_up_mbps or 0.0)
            g_down = float(self.cfg.isp.guaranteed_down_mbps or 0.0)
            g_up = float(self.cfg.isp.guaranteed_up_mbps or 0.0)

            def _share(got: Optional[float], offered: float, minimum: float) -> str:
                if got is None or lan:
                    return ""
                parts = []
                if offered > 0:
                    parts.append(f"{got / offered * 100.0:.0f}%")
                if minimum > 0:
                    parts.append(f"Min: {minimum:.0f} Mbps")
                return f" ({' | '.join(parts)})" if parts else ""

            down_share = _share(down_mbps, c_down, g_down)
            up_share = _share(up_mbps, c_up, g_up)

            # Result against the guaranteed speeds the owner set; 0 = none set, nothing judged
            down_low = g_down > 0 and down_mbps is not None and down_mbps < g_down
            up_low = g_up > 0 and up_mbps is not None and up_mbps < g_up
            judged = (g_down > 0 and down_mbps is not None) or (g_up > 0 and up_mbps is not None)
            if lan or (g_down <= 0 and g_up <= 0):
                status_code = 0
            elif not judged:
                status_code = "0m"     # a guaranteed speed is set, but this test did not measure that direction
            elif down_low and up_low:
                status_code = 6
            elif down_low:
                status_code = "6d"
            elif up_low:
                status_code = "6u"
            else:
                status_code = 1

            status_badge, status_text = get_measurement_status(status_code, lang)
            active_engine = (row["engine"] if "engine" in row.keys() else engine) or "RTR-NetTest"

            title_str = t("speed_result_title", lang, engine=html.escape(str(active_engine)).upper())

            # How the box was connected for this test: one line when every engine of it had the same setup,
            # else each engine's own beside its result (the columns are missing on a database not migrated yet)
            setup_label = html.escape(t("setup_label", lang))
            per_engine_setup = bool(setup_cols) and len({tuple(_setup_of(r).values()) for r in rows}) > 1
            setup_block = f"\n🔌 <b>{setup_label}:</b> {setup_html(row, lang)}" if setup_cols else ""
            if setup_cols and any(_setup_of(r)["isp_path"] == "behind_router" for r in rows):
                setup_block += f"\n<i>{html.escape(t('setup_warn_behind', lang))}</i>"

            msg = f"""{title_str}

🌐 <b>{t('public_ip', lang)}:</b> <code>{html.escape(client_ip)}</code>
🏢 <b>{t('isp', lang)}:</b> <b>{html.escape(isp_name)}</b>

📥 <b>{t('download', lang)}:</b> <b>{f"{down_mbps:.1f} Mbps" if down_mbps is not None else "--"}</b>{down_share}
📤 <b>{t('upload', lang)}:</b> <b>{f"{up_mbps:.1f} Mbps" if up_mbps is not None else "--"}</b>{up_share}
⏱️ <b>{t('latency_rtt', lang)}:</b> {ping_txt} (Jitter: {jitter_txt})
🖥️ <b>{t('server', lang)}:</b> {html.escape(str(row['server_name'] or t('edge_server', lang)))}{setup_block}

⚖️ <b>{t('speed_result_label', lang)}:</b> {status_badge}
<i>{status_text if not lan else "LAN"}</i>
"""
            if len(rows) > 1:   # all engines: one line per engine of this test
                msg += "\n" + "\n".join(
                    f"• {html.escape(str(r['engine'] or '?')).upper()}: "
                    + (" / ".join(f"{v / 1e6:.1f}" if v is not None else "--" for v in (r["down_bps"], r["up_bps"])) + " Mbps, "
                       + (f"{r['ping_us'] / 1000:.1f} ms" if r["ping_us"] is not None else "-- ms")
                       if r["status"] == "ok" else f"— {html.escape(str(r['error'] or r['status'])[:80])}")
                    + (f" | {setup_label}: {setup_html(r, lang)}" if per_engine_setup else "")
                    for r in rows)
            inline_kb = {
                "inline_keyboard": [
                    [{"text": t("btn_rtr", lang), "callback_data": "/test rtr"}, {"text": t("btn_ookla", lang), "callback_data": "/test ookla"}, {"text": t("btn_cloudflare", lang), "callback_data": "/test cloudflare"}, {"text": t("btn_fastcom", lang), "callback_data": "/test fastcom"}],
                    [{"text": t("btn_report", lang), "callback_data": "/report"}, {"text": t("btn_status", lang), "callback_data": "/status"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_kb)
        except Exception as e:
            self._say_error(chat_id, "Speedtest", e)

    def _cmd_report(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        self.client.send_chat_action(chat_id, "upload_document")
        self.client.send_message(chat_id, t("report_generating", lang))
        try:
            conn = db.connect()
            report = aggregate_report_data(conn, self.cfg, window_hours=24.0)
            conn.close()

            html_doc = generate_html_dossier(report, lang=lang)
            date_str = time.strftime('%Y%m%d_%H%M%S')
            filename = f"Broadband_SLA_Dossier_{self.cfg.system.box_id}_{date_str}.html"

            caption = t(
                "report_caption",
                lang,
                box_id=html.escape(self.cfg.system.box_id),
                isp=html.escape(report.isp_name),
                verdict=html.escape(get_sla_verdict(str(report.sla_verdict), lang)),
                # unknown is "--", never 100 % (nothing judged / no ping measured)
                sla=f"{report.speed_summary.sla_compliance_pct:.0f}%" if report.speed_summary.judged_tests else "--",
                uptime=f"{report.uptime_pct:.2f}%" if report.uptime_known else "--",
            )

            ok = self.client.send_document(chat_id, filename, html_doc.encode("utf-8"), caption=caption)
            if not ok:
                self.client.send_message(chat_id, t("report_fail", lang))
        except Exception as e:
            self._say_error(chat_id, "Report", e)

    def _cmd_tailscale(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            ts_stat = tailscale.get_tailscale_status()
            logged_in = bool(ts_stat.get("active"))
            ts_ip = ts_stat.get("tailscale_ipv4") or "--"
            magic_dns = ts_stat.get("magic_dns_name") or "--"
            auth_url = ts_stat.get("auth_url")
            backend_state = ts_stat.get("backend_state", "Unknown")

            if logged_in:
                badge = t("tailscale_active", lang)
                status_desc = t("tailscale_desc_active", lang, ip=ts_ip)
            elif auth_url:
                badge = t("tailscale_login_req", lang)
                status_desc = t("tailscale_desc_login", lang, url=auth_url)
            else:
                badge = t("tailscale_inactive", lang, backend_state=backend_state)
                status_desc = t("tailscale_desc_inactive", lang)

            msg = f"""{t('tailscale_title', lang)}

• {t('lbl_status', lang)}: <b>{badge}</b>
• Tailscale IP: <code>{html.escape(ts_ip)}</code>
• MagicDNS: <code>{html.escape(magic_dns)}</code>
• {t('tailscale_role', lang)}

{status_desc}
"""
            buttons = []
            if auth_url:
                buttons.append([{"text": t("btn_auth_open", lang), "url": auth_url}])
            buttons.append([{"text": t("btn_refresh", lang), "callback_data": "/tailscale"}, {"text": t("btn_status", lang), "callback_data": "/status"}])
            buttons.append([{"text": t("btn_vpn_hub", lang), "callback_data": "/vpn"}, {"text": t("btn_main_menu", lang), "callback_data": "/menu"}])

            self.client.send_message(chat_id, msg, reply_markup={"inline_keyboard": buttons})
        except Exception as e:
            self._say_error(chat_id, "Tailscale", e)

    def _cmd_ai(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        self._say(chat_id, "ai_generating")
        try:
            # It reads the database itself; a connection passed here landed in force_refresh (always truthy),
            # so every /ai rebuilt the bundle and never used its 60 s cache.
            bundle_md = llm_bundle.generate_llm_diagnostic_bundle(self.cfg)

            filename = f"nmb_diagnostic_bundle_{self.cfg.system.box_id}_{int(time.time())}.md"
            caption = t("ai_caption", lang)
            ok = self.client.send_document(chat_id, filename, bundle_md.encode("utf-8"), caption=caption)
            if not ok:
                self._say(chat_id, "ai_send_failed")
        except Exception as e:
            self._say_error(chat_id, "AI", e)

    def _cmd_mode(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        if not args:
            conn = db.connect(readonly=True)
            try:
                cur_mode = net_setup.active_mode(conn)[0]
                ovr = conn.execute("SELECT v FROM kv WHERE k = 'override_mode'").fetchone()
            finally:
                conn.close()
            cur_ovr = ovr["v"] if ovr else "none"
            msg = t("mode_current", lang, mode=html.escape(_mode_words(cur_mode, lang)), ovr=html.escape(cur_ovr))
            self.client.send_message(chat_id, msg)
            return

        target_mode = args[0].lower()
        if target_mode not in ("auto", "standalone", "mode_a", "mode_b"):
            err_msg = t("mode_invalid", lang)
            self.client.send_message(chat_id, err_msg)
            return

        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                "INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('override_mode', ?, ?)",
                (target_mode, db.now_ms())
            )
        conn.close()

        upd_msg = t("mode_updated", lang, mode=html.escape(_mode_words(target_mode, lang)))
        self.client.send_message(chat_id, upd_msg)

    # =========================================================================
    # 3. VPN Management (WireGuard & OpenVPN)
    # =========================================================================

    def _cmd_vpn(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._vpn_status(chat_id, lang)
        elif subcmd in ("peers", "clients", "list"):
            self._vpn_list_clients(chat_id, lang)
        elif subcmd == "add":
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/vpn add &lt;client_name&gt; [wg|ovpn]")
                return
            name = args[1].strip()
            proto = args[2].lower() if len(args) > 2 else "wg"
            self._vpn_add_client(chat_id, name, proto)
        elif subcmd == "qr":
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/vpn qr &lt;client_name&gt;")
                return
            self._vpn_send_qr(chat_id, args[1].strip())
        elif subcmd in ("conf", "config", "profile"):
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/vpn conf &lt;client_name&gt;")
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
                self._say(chat_id, "usage", cmd="/vpn del &lt;client_name&gt;")
                return
            self._vpn_delete_client(chat_id, args[1].strip())
        else:
            self._say(chat_id, "unknown_sub", cmd=html.escape(subcmd), supported="<code>/vpn</code>, <code>/vpn clients</code>, <code>/vpn add &lt;name&gt;</code>, <code>/vpn qr &lt;name&gt;</code>, <code>/vpn conf &lt;name&gt;</code>, <code>/vpn start</code>, <code>/vpn stop</code>, <code>/vpn del &lt;name&gt;</code>")

    def _vpn_status(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
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

            msg = t(
                "vpn_status_msg", lang,
                wg_status=t("badge_active", lang) if wg_active else t("badge_stopped", lang),
                wg_port=self.cfg.wireguard.port, wg_subnet=self.cfg.wireguard.subnet,
                wg_total=len(wg_peers), wg_conn=active_wg_peers,
                wg_endpoint=html.escape(str(wg_stat.get("endpoint") or t("lbl_auto_detected", lang))),
                ov_status=t("badge_active", lang) if ov_active else t("badge_stopped", lang),
                ov_port=self.cfg.openvpn.port, ov_subnet=self.cfg.openvpn.subnet,
                ov_total=len(ov_clients), ov_conn=active_ov_clients,
            )
            inline_vpn = {
                "inline_keyboard": [
                    [{"text": t("btn_vpn_clients", lang), "callback_data": "/vpn clients"}, {"text": t("btn_tailscale", lang), "callback_data": "/tailscale"}],
                    [{"text": t("btn_status", lang), "callback_data": "/status"}, {"text": t("btn_main_menu", lang), "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_vpn)
        except Exception as e:
            self._say_error(chat_id, "VPN", e)

    def _vpn_list_clients(self, chat_id: int, lang: Optional[str] = None) -> None:
        lang = lang or self._l(chat_id)
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

            lines = [t("vpn_clients_title", lang)]

            lines.append(t("vpn_wg_peers", lang))
            if not wg_peers:
                lines.append(t("vpn_no_wg", lang))
            else:
                for p in wg_peers:
                    hs_sec = p.get("latest_handshake") or 0
                    if hs_sec > 0 and hs_sec < 180:
                        status = f"{t('vpn_connected', lang)} ({p.get('latest_handshake_ago') or str(hs_sec)+'s'})"
                    elif hs_sec > 0:
                        status = f"{t('vpn_offline', lang)} ({p.get('latest_handshake_ago') or str(int(hs_sec/60))+'m'})"
                    else:
                        status = t("vpn_never", lang)

                    rx = format_bytes(p.get("transfer_rx") or 0)
                    tx = format_bytes(p.get("transfer_tx") or 0)
                    ip_str = p.get("allowed_ips") or p.get("client_ip") or "--"

                    lines.append(t("vpn_client_row", lang, name=html.escape(p.get('name')), ip=html.escape(ip_str), status=status, rx=rx, tx=tx))

            lines.append("\n" + t("vpn_ovpn_clients", lang))
            if not ov_clients:
                lines.append(t("vpn_no_ovpn", lang))
            else:
                for c in ov_clients:
                    status = t("vpn_connected", lang) if c.get("connected") else t("vpn_offline", lang)
                    rx = format_bytes(c.get("bytes_received") or 0)
                    tx = format_bytes(c.get("bytes_sent") or 0)
                    ip_str = c.get("virtual_ip") or "--"

                    lines.append(t("vpn_client_row", lang, name=html.escape(c.get('name')), ip=html.escape(ip_str), status=status, rx=rx, tx=tx))

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self._say_error(chat_id, "VPN", e)

    def _vpn_add_client(self, chat_id: int, name: str, proto: str = "wg") -> None:
        self._say(chat_id, "vpn_generating", proto=html.escape(proto.upper()), name=html.escape(name))
        try:
            if proto in ("ovpn", "openvpn"):
                c = ovpn.add_client(name)
                ovpn_profile = ovpn.get_unified_ovpn_profile(
                    name,
                    endpoint_host=self.cfg.openvpn.public_endpoint,
                    port=self.cfg.openvpn.port
                )
                if not ovpn_profile:
                    self._say(chat_id, "vpn_profile_failed", proto="OpenVPN", name=html.escape(name))
                    return

                caption = self._tr(chat_id, "vpn_ovpn_created", name=html.escape(name), ip=c.get("ip") or self._tr(chat_id, "vpn_dhcp_pool"))
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
                    self._say(chat_id, "vpn_profile_failed", proto="WireGuard", name=html.escape(name))
                    return

                ip_str = peer.get("allowed_ips") or peer.get("client_ip") or "10.66.66.x"
                caption = self._tr(
                    chat_id, "vpn_wg_created", name=html.escape(name), ip=html.escape(ip_str),
                    endpoint=f"{html.escape(str(self.cfg.wireguard.public_endpoint or 'Auto'))}:{self.cfg.wireguard.port}",
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
                    caption=self._tr(chat_id, "vpn_profile_caption", proto="WireGuard", file=f"{html.escape(name)}.conf")
                )
        except Exception as e:
            self._say_error(chat_id, "VPN", e)

    def _vpn_send_qr(self, chat_id: int, name: str) -> None:
        try:
            peers = wg.load_peers()
            target = next((p for p in peers if p.get("name", "").lower() == name.lower() or p.get("id") == name), None)
            if not target:
                self._say(chat_id, "vpn_wg_not_found", name=html.escape(name))
                return

            qr_png = wg.get_client_qr_png_bytes(
                target.get("id", name),
                endpoint_host=self.cfg.wireguard.public_endpoint,
                port=self.cfg.wireguard.port
            )
            if not qr_png:
                self._say(chat_id, "vpn_qr_failed", name=html.escape(name))
                return

            caption = self._tr(chat_id, "vpn_qr_caption", name=html.escape(target.get("name")), ip=html.escape(target.get("allowed_ips") or ""))
            self.client.send_photo(chat_id, qr_png, caption=caption, filename=f"wireguard_{name}_qr.png")
        except Exception as e:
            self._say_error(chat_id, "QR", e)

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
                    caption = self._tr(chat_id, "vpn_profile_caption", proto="WireGuard", file=f"{html.escape(wg_target.get('name'))}.conf")
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
                    caption = self._tr(chat_id, "vpn_profile_caption", proto="OpenVPN", file=f"{html.escape(ov_target.get('name'))}.ovpn")
                    self.client.send_document(chat_id, f"{name}.ovpn", ovpn_profile.encode("utf-8"), caption=caption)
                    return

            self._say(chat_id, "vpn_client_not_found", name=html.escape(name))
        except Exception as e:
            self._say_error(chat_id, "VPN", e)

    def _vpn_toggle(self, chat_id: int, proto: str, enable: bool) -> None:
        self._say(chat_id, "vpn_starting" if enable else "vpn_stopping", proto=html.escape(proto.upper()))
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
                self._say(chat_id, "vpn_started" if enable else "vpn_stopped", proto="OpenVPN")
            else:
                if enable:
                    wg.apply_configuration(
                        port=self.cfg.wireguard.port,
                        subnet=self.cfg.wireguard.subnet,
                        subnet_ipv6=self.cfg.wireguard.subnet_ipv6,
                    )
                else:
                    wg.run_helper("wireguard-stop")
                self._say(chat_id, "vpn_started" if enable else "vpn_stopped", proto="WireGuard")
        except Exception as e:
            self._say_error(chat_id, "VPN", e)

    def _vpn_delete_client(self, chat_id: int, name: str) -> None:
        try:
            # Check WireGuard
            peers = wg.load_peers()
            wg_target = next((p for p in peers if p.get("name", "").lower() == name.lower() or p.get("id") == name), None)
            if wg_target:
                wg.delete_peer(wg_target.get("id"))
                self._say(chat_id, "vpn_deleted", proto="WireGuard", name=html.escape(name))
                return

            # Check OpenVPN
            clients = ovpn.load_clients()
            ov_target = next((c for c in clients if c.get("name", "").lower() == name.lower()), None)
            if ov_target:
                ovpn.delete_client(ov_target.get("name"))
                self._say(chat_id, "vpn_deleted", proto="OpenVPN", name=html.escape(name))
                return

            self._say(chat_id, "vpn_client_not_found", name=html.escape(name))
        except Exception as e:
            self._say_error(chat_id, "VPN", e)

    # =========================================================================
    # 3b. DuckDNS Dynamic DNS (DynDNS)
    # =========================================================================

    def _cmd_dyndns(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        import nmb.netd.duckdns as dd
        from nmb.config import save_config

        subcmd = args[0].lower() if args else ""
        d_cfg = self.cfg.duckdns

        if subcmd in ("update", "sync", "now", "force"):
            if not d_cfg.domain or not d_cfg.token:
                self._say(chat_id, "dd_not_configured")
                return

            self._say(chat_id, "dd_syncing")
            detected_v6 = None
            try:
                from nmb.netd.wireguard import get_device_addresses
                _, v6_addrs = get_device_addresses()
                if v6_addrs:
                    detected_v6 = v6_addrs[0][1]
            except Exception:
                log.debug("suppressed exception", exc_info=True)

            res = dd.update_duckdns(
                domain=d_cfg.domain,
                token=d_cfg.token,
                ip=d_cfg.custom_ip if d_cfg.custom_ip else None,
                ipv6=detected_v6,
                provider=getattr(d_cfg, "provider", "duckdns") or "duckdns",
                ipv6_mode=getattr(d_cfg, "ipv6_mode", "auto") or "auto",
            )
            dd.wake_duckdns_daemon()

            if res.get("status") == "ok" or res.get("success"):
                ip = res.get("ip") or self._tr(chat_id, "dd_detected_ip")
                fqdn = res.get("fqdn") or f"{dd.clean_domain(d_cfg.domain)}.duckdns.org"
                updated_tag = self._tr(chat_id, "dd_ip_updated" if res.get("updated") else "dd_ip_unchanged")
                self._say(chat_id, "dd_synced", fqdn=html.escape(fqdn), ip=html.escape(ip), tag=updated_tag, status=html.escape(res.get("message", "OK")))
            else:
                self._say(chat_id, "dd_failed", error=html.escape(res.get("message") or self._tr(chat_id, "unknown_error")))
            return

        if subcmd in ("interval", "every", "time"):
            if len(args) < 2:
                curr_int = d_cfg.update_interval_min
                self._say(chat_id, "dd_interval_current", min=curr_int)
                return
            try:
                new_int = max(1, min(1440, int(args[1])))
            except ValueError:
                self._say(chat_id, "dd_interval_invalid")
                return

            d_cfg.update_interval_min = new_int
            save_config(self.cfg)
            dd.wake_duckdns_daemon()

            self._say(chat_id, "dd_interval_set", min=new_int)
            return

        if subcmd in ("on", "enable", "start"):
            d_cfg.enabled = True
            save_config(self.cfg)       # the updater in the web server follows the saved settings

            self._say(chat_id, "dd_enabled", host=html.escape(dd.clean_domain(d_cfg.domain)), min=d_cfg.update_interval_min)
            return

        if subcmd in ("off", "disable", "stop"):
            d_cfg.enabled = False
            save_config(self.cfg)       # the updater in the web server stops within 30 s
            self._say(chat_id, "dd_disabled")
            return

        if subcmd in ("domain", "host", "subdomain"):
            if len(args) < 2:
                curr_dom = d_cfg.domain
                self._say(chat_id, "dd_domain_current", domain=html.escape(curr_dom or self._tr(chat_id, "lbl_none")))
                return
            new_dom = dd.clean_domain(args[1])
            d_cfg.domain = new_dom
            save_config(self.cfg)
            dd.wake_duckdns_daemon()
            self._say(chat_id, "dd_domain_set", domain=html.escape(new_dom))
            return

        if subcmd == "token":
            if len(args) < 2:
                is_set = self._tr(chat_id, "lbl_configured" if d_cfg.token else "lbl_not_configured")
                self._say(chat_id, "dd_token_current", state=is_set)
                return
            new_tok = args[1].strip()
            d_cfg.token = new_tok
            save_config(self.cfg)
            dd.wake_duckdns_daemon()
            self._say(chat_id, "dd_token_set")
            return

        # Default: Status overview
        st = dd.get_duckdns_status(self.cfg)
        status_badge = t("dd_enabled_badge", lang) if st.get("enabled") else t("dd_disabled_badge", lang)
        last_st = st.get("last_status") or t("lbl_never", lang)
        last_st_badge = "🟢 OK" if last_st == "OK" else ("🔴 KO" if last_st == "KO" else html.escape(str(last_st)))
        fqdn = st.get("fqdn") or (f"{st.get('domain')}.duckdns.org" if st.get("domain") else f"<i>{t('lbl_not_configured', lang)}</i>")
        wan_ip = st.get("last_ip") or st.get("detected_ip") or f"<i>{t('dd_pending', lang)}</i>"
        interval_m = st.get("update_interval_min", 10)
        last_up = st.get("last_update") or t("lbl_never", lang)
        next_secs = st.get("next_update_seconds", 0)
        if next_secs > 0:
            nm = next_secs // 60
            ns = next_secs % 60
            next_str = t("dd_in_time", lang, m=nm, s=ns, at=st.get("next_update", ""))
        else:
            next_str = st.get("next_update") or "--"

        msg = t(
            "dd_status_msg", lang, status=status_badge, fqdn=fqdn, ip=wan_ip, min=interval_m,
            last=html.escape(last_up), last_status=last_st_badge, next=html.escape(next_str),
            token=t("lbl_yes" if st.get("token_set") else "lbl_no", lang),
            message=html.escape(st.get("last_message") or t("lbl_ready", lang)),
        )
        self.client.send_message(chat_id, msg)

    # =========================================================================
    # 4. DNS Ad-Blocker (Pi-hole Sinkhole)
    # =========================================================================

    def _cmd_adblock(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._adblock_status(chat_id, lang)
        elif subcmd in ("on", "enable", "start"):
            ab.set_adblock_enabled(True, self.cfg)
            self.client.send_message(chat_id, t("adblock_enabled", lang))
        elif subcmd in ("off", "disable", "stop"):
            ab.set_adblock_enabled(False, self.cfg)
            self.client.send_message(chat_id, t("adblock_disabled", lang))
        elif subcmd == "block":
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/adblock block &lt;domain&gt;")
                return
            domain = args[1].strip()
            ab.add_blacklist_entry(domain)
            self.client.send_message(chat_id, t("adblock_blocked_msg", lang, domain=html.escape(domain)))
        elif subcmd == "unblock":
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/adblock unblock &lt;domain&gt;")
                return
            domain = args[1].strip()
            ab.remove_blacklist_entry(domain)
            ab.add_whitelist_entry(domain)
            self.client.send_message(chat_id, t("adblock_unblocked_msg", lang, domain=html.escape(domain)))
        elif subcmd == "update":
            self._say(chat_id, "ab_updating")
            ab.trigger_gravity_update()
            self.client.send_message(chat_id, t("adblock_update_msg", lang))
        elif subcmd == "guide":
            guide = ab.get_router_dhcp_guide()
            msg = t("ab_guide", lang, ip=html.escape(guide.get("primary_dns_ip") or guide.get("box_ip") or "192.168.1.100"))
            self.client.send_message(chat_id, msg)
        else:
            self._say(chat_id, "unknown_sub", cmd=html.escape(subcmd), supported="<code>/adblock</code>, <code>/adblock on</code>, <code>/adblock off</code>, <code>/adblock block &lt;domain&gt;</code>, <code>/adblock unblock &lt;domain&gt;</code>, <code>/adblock update</code>, <code>/adblock guide</code>")

    def _adblock_status(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            stat = ab.get_full_adblock_status()
            is_enabled = stat.get("enabled", False)
            status_badge = t("ab_active_badge" if is_enabled else "ab_disabled_badge", lang)

            total_q = stat.get("total_queries_today", 0)
            blocked_q = stat.get("blocked_queries_today", 0)
            pct = stat.get("block_percentage_today", 0.0)
            gravity = stat.get("domains_on_blocklist", 0)
            upstreams = ", ".join(stat.get("upstream_dns_servers", [])) or "1.1.1.1, 8.8.8.8"

            msg = t("adblock_title", lang) + "\n\n" + t(
                "ab_status_body", lang, status=status_badge, gravity=f"{gravity:,}", total=f"{total_q:,}",
                blocked=f"{blocked_q:,}", pct=f"{pct:.1f}", upstreams=html.escape(upstreams),
            )
            inline_ab = {
                "inline_keyboard": [
                    [{"text": t("btn_disable" if is_enabled else "btn_enable", lang), "callback_data": "/adblock off" if is_enabled else "/adblock on"},
                     {"text": t("btn_update_gravity", lang), "callback_data": "/adblock update"}],
                    [{"text": t("btn_status", lang), "callback_data": "/status"}, {"text": t("btn_main_menu", lang), "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_ab)
        except Exception as e:
            self._say_error(chat_id, "Adblock", e)

    # =========================================================================
    # 5. Self-Healing & System Audit
    # =========================================================================

    def _cmd_heal(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        subcmd = args[0].lower() if args else "audit"

        if subcmd in ("audit", "status"):
            self._heal_audit(chat_id, lang)
        elif subcmd in ("fix", "repair"):
            tier = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
            self._heal_fix(chat_id, tier, lang)
        elif subcmd in ("updates", "check"):
            self._heal_check_updates(chat_id, lang)
        elif subcmd == "apply":
            self._heal_apply_update(chat_id, lang)
        else:
            self._say(chat_id, "unknown_sub", cmd=html.escape(subcmd), supported="<code>/heal</code>, <code>/heal fix [tier]</code>, <code>/heal updates</code>, <code>/heal apply</code>")

    def _heal_audit(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        audit_wait = t("heal_auditing", lang)
        self.client.send_message(chat_id, audit_wait)
        try:
            res = heal.audit_system_health()
            comps = res.get("components", {})
            issues = res.get("issues_count", 0)
            verdict = (t("heal_verdict_ok", lang) if issues == 0 else t("heal_verdict_issues", lang, n=issues))

            svc_lines = []
            for item in comps.get("services", {}).get("items", []):
                icon = "🟢" if item.get("status") == "ok" else ("🔴" if item.get("severity") == "critical" else "🟡")
                svc_lines.append(f"  {icon} <code>{html.escape(str(item.get('id', '')).split(':', 1)[-1])}</code>")
            def _bad(cat: str) -> int:
                return sum(1 for i in comps.get(cat, {}).get("items", []) if i.get("status") != "ok")
            db_status = t("heal_db_ok" if comps.get("database", {}).get("status") == "ok" else "heal_db_bad", lang)

            title = t("heal_title", lang)

            daemons_hdr = t("heal_daemons", lang)

            msg = t(
                "heal_body", lang, title=title, verdict=verdict, daemons=daemons_hdr, services=chr(10).join(svc_lines),
                db=db_status, tables=len(comps.get("database", {}).get("items", [])),
                binaries=_bad("binaries"), symlinks=_bad("symlinks"),
            )
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self._say_error(chat_id, "Audit", e)

    def _heal_fix(self, chat_id: int, tier: Optional[int], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        tier_msg = t("heal_tier", lang, tier=tier) if tier else t("heal_adaptive", lang)
        self._say(chat_id, "heal_running", tier=tier_msg)
        try:
            res = heal.auto_heal_all(force_tier=tier)
            repairs = res.get("repairs_executed", [])
            remaining = res.get("post_issues_count", 0)

            if repairs:
                repair_list = "\n".join(f"• {html.escape(r)}" for r in repairs)
                msg = t("heal_done", lang, repairs=repair_list, remaining=remaining)
            else:
                msg = t("heal_healthy", lang)

            self.client.send_message(chat_id, msg)
        except Exception as e:
            self._say_error(chat_id, "Heal", e)

    def _heal_check_updates(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        self._say(chat_id, "upd_checking")
        try:
            res = heal.check_stable_updates()
            cur_ver = res.get("current_version", "unknown")
            if res.get("current_commit"):
                cur_ver = f"{cur_ver} ({res['current_commit']})"
            avail = res.get("update_available", False)
            latest = res.get("upstream_commit") or res.get("available_version") or cur_ver

            if avail:
                msg = t("upd_available", lang, cur=html.escape(cur_ver), latest=html.escape(latest))
            else:
                msg = t("upd_latest", lang, cur=html.escape(cur_ver))

            self.client.send_message(chat_id, msg)
        except Exception as e:
            self._say_error(chat_id, "Update", e)

    def _heal_apply_update(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        self._say(chat_id, "upd_applying")
        try:
            res = heal.apply_stable_update()
            if res.get("up_to_date"):
                self.client.send_message(chat_id, t("upd_latest", lang, cur=html.escape(str(res.get("version", "")))))
                return
            if res.get("started"):
                # Only started in the background (a box without Git): it said "update installed, the checks
                # passed" before anything was tested (2026-11-10).
                self._say(chat_id, "upd_started", ver=html.escape(str(res.get("target", "") or res.get("new_version", "") or "GitHub")))
                return
            if res.get("success"):
                msg = t("upd_done", lang, ver=html.escape(res.get("new_version", "")), cp=html.escape(res.get("checkpoint", "")))
            else:
                if res.get("rolled_back"):
                    msg = t("upd_rolled_back", lang, error=html.escape(res.get("error") or t("unknown_error", lang)), cp=html.escape(res.get("checkpoint", "")))
                else:
                    msg = t("upd_failed", lang, error=html.escape(res.get("error") or t("unknown_error", lang)))

            self.client.send_message(chat_id, msg)
        except Exception as e:
            self._say_error(chat_id, "Update", e)

    # =========================================================================
    # 6. Tasks, Process Manager & Load
    # =========================================================================

    def _cmd_tasks(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            summary = tasks.get_system_summary()
            procs_data = tasks.get_processes_list(limit=8)
            procs = procs_data[0] if isinstance(procs_data, tuple) else procs_data

            load_avg = [summary.get("loadavg_1m", 0.0), summary.get("loadavg_5m", 0.0), summary.get("loadavg_15m", 0.0)]
            cpu_pct, mem, disk, temp = _host_usage()
            temp_str = t("tasks_temp", lang, temp=f"{temp:.1f}") if temp is not None else ""

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

            msg = t("tasks_title", lang) + "\n\n" + t(
                "tasks_body", lang, cpu=f"{cpu_pct:.1f}",
                load=f"{load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}", temp=temp_str,
                mem=f"{mem_used_h} / {mem_tot_h}", mem_pct=f"{mem.get('percent', 0.0):.1f}",
                disk=f"{disk_used_h} / {disk_tot_h}", disk_pct=f"{disk.get('percent', 0.0):.1f}",
                uptime=html.escape(summary.get("uptime_human", "--")), count=summary.get("total_entities", 0),
                procs=chr(10).join(proc_lines),
            )
            inline_tasks = {
                "inline_keyboard": [
                    [{"text": t("btn_refresh", lang), "callback_data": "/tasks"}, {"text": t("btn_status", lang), "callback_data": "/status"}],
                    [{"text": t("btn_main_menu", lang), "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_tasks)
        except Exception as e:
            self._say_error(chat_id, "Tasks", e)

    def _cmd_kill(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if not args or not args[0].isdigit():
            self._say(chat_id, "usage", cmd="/kill &lt;pid&gt; [signal_num]")
            return

        pid = int(args[0])
        sig = int(args[1]) if len(args) > 1 and args[1].isdigit() else 15

        try:
            res = tasks.kill_process(pid, sig_num=sig)
            if res.get("status") == "ok":
                self._say(chat_id, "kill_ok", pid=pid, sig=sig)
            else:
                self._say(chat_id, "kill_failed", pid=pid, error=html.escape(res.get("message") or self._tr(chat_id, "unknown_error")))
        except Exception as e:
            self._say_error(chat_id, "Kill", e)

    # =========================================================================
    # 7. Wi-Fi & Guest Wi-Fi Station
    # =========================================================================

    def _cmd_wifi(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        subcmd = args[0].lower() if args else "status"

        if subcmd == "status":
            self._wifi_status(chat_id, lang)
        elif subcmd == "scan":
            self._wifi_scan(chat_id)
        elif subcmd == "connect":
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/wifi connect &lt;ssid&gt; [password]")
                return
            ssid = args[1].strip()
            pw = args[2].strip() if len(args) > 2 else ""
            self._wifi_connect(chat_id, ssid, pw)
        elif subcmd == "saved":
            self._wifi_saved(chat_id)
        else:
            self._say(chat_id, "unknown_sub", cmd=html.escape(subcmd), supported="<code>/wifi</code>, <code>/wifi scan</code>, <code>/wifi connect &lt;ssid&gt; [password]</code>, <code>/wifi saved</code>")

    def _wifi_status(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            stat = gw.get_guest_wifi_status("wlan0", self.cfg.network.wan_interface, getattr(self.cfg, "guest_wifi", None))
            is_conn = stat.get("connected", False)

            if is_conn:
                badge = t("wifi_connected", lang)
                iso_badge = t("wifi_isolated", lang) if stat.get("is_isolated_subnet") else ""
                details = t(
                    "wifi_details", lang, ssid=html.escape(stat.get("ssid", "")), ip=html.escape(stat.get("ip_address", "")),
                    gw=html.escape(stat.get("gateway", "")), subnet=html.escape(stat.get("subnet", "")), iso=iso_badge,
                    signal=stat.get("signal_percent", 0), sec=html.escape(stat.get("security", "")),
                    iface=html.escape(stat.get("interface", "wlan0")),
                )
            else:
                badge = t("wifi_disconnected", lang)
                details = t("wifi_idle", lang)

            msg = f"""{t('wifi_title', lang)}
{t('lbl_status', lang)}: <b>{badge}</b>

{details}

{t('wifi_commands', lang)}"""
            inline_wifi = {
                "inline_keyboard": [
                    [{"text": t("btn_wifi_scan", lang), "callback_data": "/wifi scan"}, {"text": t("btn_probe_refresh", lang), "callback_data": "/wifi"}],
                    [{"text": t("btn_status", lang), "callback_data": "/status"}, {"text": t("btn_main_menu", lang), "callback_data": "/menu"}]
                ]
            }
            self.client.send_message(chat_id, msg, reply_markup=inline_wifi)
        except Exception as e:
            self._say_error(chat_id, "Wi-Fi", e)

    def _wifi_scan(self, chat_id: int) -> None:
        self._say(chat_id, "wifi_scanning")
        try:
            nets = gw.scan_wifi_networks("wlan0")
            if not nets:
                self._say(chat_id, "wifi_no_networks")
                return

            lines = [self._tr(chat_id, "wifi_scan_title", count=len(nets))]
            for n in nets[:12]:
                in_use = "🟢 " if n.get("in_use") else ""
                ssid_raw = n.get("ssid")
                ssid = html.escape(ssid_raw) if ssid_raw else self._tr(chat_id, "wifi_hidden")
                sig = n.get("signal", 0)
                sec = n.get("security", "")
                ch = n.get("channel", "")

                lines.append(f"• {in_use}<b>{ssid}</b> — <b>{sig}%</b> ({self._tr(chat_id, 'wifi_channel')} {ch}, {html.escape(sec)})")

            lines.append(self._tr(chat_id, "wifi_connect_hint"))
            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self._say_error(chat_id, "Wi-Fi", e)

    def _wifi_connect(self, chat_id: int, ssid: str, pw: str) -> None:
        if self._radio_is_access_point():
            self._say(chat_id, "wifi_ap_busy")
            return
        self._say(chat_id, "wifi_connecting", ssid=html.escape(ssid))
        try:
            ok, message = gw.connect_guest_wifi(ssid=ssid, password=pw or None, iface="wlan0", metric=600)
            if ok:
                self._say(chat_id, "wifi_conn_ok", ssid=html.escape(ssid))
            else:
                self._say(chat_id, "wifi_conn_failed", ssid=html.escape(ssid), error=html.escape(message or self._tr(chat_id, "unknown_error")))
        except Exception as e:
            self._say_error(chat_id, "Wi-Fi", e)

    def _radio_is_access_point(self) -> bool:
        """Router mode runs the access point on wlan0 (nmb/netd/modes.py), and NetworkManager does not manage
        the radio then: a client connection could only fail, with an nmcli error (2026-11-10)."""
        try:
            st = json.loads((self.cfg.system.run_dir / "netd_state.json").read_text())
        except (OSError, ValueError):
            return False
        return st.get("active_mode") == "mode_a" and bool((st.get("details") or {}).get("hostapd_running"))

    def _wifi_saved(self, chat_id: int) -> None:
        try:
            profiles = gw.list_saved_wifi_connections()
            if not profiles:
                self._say(chat_id, "wifi_no_saved")
                return

            lines = [self._tr(chat_id, "wifi_saved_title")]
            for p in profiles:
                active = self._tr(chat_id, "wifi_profile_active" if p.get("in_use") else "wifi_profile_saved")
                lines.append(f"• <b>{html.escape(p.get('name'))}</b> ({active}) — UUID: <code>{html.escape(p.get('uuid', '--'))}</code>")

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self._say_error(chat_id, "Wi-Fi", e)

    # =========================================================================
    # 8. Backups & Disaster Recovery
    # =========================================================================

    def _cmd_backup(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        subcmd = args[0].lower() if args else "list"

        if subcmd == "list":
            self._backup_list(chat_id, lang)
        elif subcmd == "create":
            label = args[1].strip() if len(args) > 1 else "telegram_snapshot"
            self._backup_create(chat_id, label, lang)
        elif subcmd == "send":
            if len(args) < 2:
                self._say(chat_id, "usage", cmd="/backup send &lt;filename&gt;")
                return
            plain = len(args) > 2 and args[2].strip().lower() == "plain"
            self._backup_send(chat_id, args[1].strip(), lang, plain=plain)
        else:
            self._say(chat_id, "unknown_sub", cmd=html.escape(subcmd), supported="<code>/backup list</code>, <code>/backup create [label]</code>, <code>/backup send &lt;filename&gt; [plain]</code>")

    def _backup_list(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            backups = backup.list_backups()
            if not backups:
                self.client.send_message(chat_id, t("backup_none", lang))
                return

            lines = [t("backup_title", lang)]
            for b in backups[:10]:
                sz = format_bytes(b.get("size_bytes", 0))
                dt = b.get("created_at_iso", "")
                fname = b.get("filename", "")
                type_label = b.get("backup_type", "full")
                lines.append(f"• <code>{html.escape(fname)}</code>\n  {dt} | {sz} | {t('backup_type', lang)}: {type_label}")

            tip_label = t("backup_dl_tip", lang)
            lines.append(f"\n{tip_label}: <code>/backup send &lt;filename&gt;</code>")
            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self._say_error(chat_id, "Backup", e)

    def _backup_create(self, chat_id: int, label: str, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        wait_label = t("backup_creating", lang, label=html.escape(label))
        self.client.send_message(chat_id, wait_label)
        try:
            ok, path, meta = backup.create_backup(backup_type="full", comment=label)
            if not ok:
                raise RuntimeError(meta.get("error") or meta.get("message") or "backup failed")
            fname = path.name
            sz = format_bytes(path.stat().st_size if path.exists() else 0)

            msg = t("backup_created", lang, fname=html.escape(fname), size=sz)
            self.client.send_message(chat_id, msg)
        except Exception as e:
            self._say_error(chat_id, "Backup", e)

    def _backup_send(self, chat_id: int, filename: str, lang: Optional[str] = None, plain: bool = False) -> None:
        """Sends a backup encrypted with the owner's passphrase. The archive holds nmb.conf with every
        password and token and the VPN keys, and Telegram keeps what it is sent: unencrypted only when
        asked for with "plain" (audit bot H1)."""
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        clean_name = os.path.basename(filename)
        path = backup.BACKUP_DIR / clean_name
        if not clean_name or not path.is_file():
            not_found = t("backup_not_found", lang, file=html.escape(clean_name))
            self.client.send_message(chat_id, not_found)
            return

        passphrase = getattr(self.cfg.telegram, "backup_passphrase", "") or ""
        if not plain and backup.passphrase_problem(passphrase):
            self.client.send_message(chat_id, t("backup_need_passphrase", lang, file=html.escape(clean_name)))
            return

        up_label = t("backup_uploading", lang, file=html.escape(clean_name))
        self.client.send_message(chat_id, up_label)
        try:
            if plain:
                self.client.send_message(chat_id, t("backup_plain_warning", lang))
                data = path.read_bytes()
                out_name = clean_name
                caption = t("backup_caption", lang, file=html.escape(out_name), size=format_bytes(len(data)))
            else:
                try:
                    data = backup.encrypt_for_transfer(path, passphrase)
                except Exception as e:
                    self.client.send_message(chat_id, t("backup_encrypt_failed", lang, error=html.escape(str(e))))
                    return
                out_name = clean_name + ".gpg"
                caption = t("backup_caption_encrypted", lang, file=html.escape(out_name),
                            orig=html.escape(clean_name), size=format_bytes(len(data)))
            ok = self.client.send_document(chat_id, out_name, data, caption=caption)
            if not ok:
                self._say(chat_id, "backup_send_failed")
        except Exception as e:
            self._say_error(chat_id, "Backup", e)

    # =========================================================================
    # 9. Hardware Drivers
    # =========================================================================

    def _cmd_drivers(self, chat_id: int, lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        try:
            stat = drivers.get_full_driver_status()
            controllers = stat.get("controllers") or [
                {"chipset_name": i.get("chipset_name"), "interface": i.get("name"), "driver": i.get("driver"), "bus_type": i.get("bus_type") or "-"}
                for i in stat.get("interfaces", [])
            ]
            missing_fw = stat.get("missing_firmware", [])
            recommended = stat.get("recommended_packages", [])

            lines = [t("drivers_title", lang)]
            if not controllers:
                no_ctrl = t("drivers_none", lang)
                lines.append(no_ctrl)
            else:
                for c in controllers:
                    chip = c.get("chipset_name") or c.get("device_name") or t("drivers_controller", lang)
                    iface = c.get("interface") or "N/A"
                    driver_name = c.get("driver") or "generic"
                    bus = c.get("bus_type", "pci").upper()
                    lines.append(t("drivers_row", lang, chip=html.escape(chip), iface=html.escape(iface), driver=html.escape(driver_name), bus=bus))

            if missing_fw:
                fw_label = t("drivers_fw_missing", lang)
                lines.append(f"\n⚠️ <b>{fw_label}:</b> {len(missing_fw)} blobs")

            if recommended and not stat.get("all_drivers_ready"):
                pkg_names = [p.get("package", str(p)) if isinstance(p, dict) else str(p) for p in recommended]
                pkgs = ", ".join(f"<code>{html.escape(p)}</code>" for p in pkg_names)
                rec_label = t("drivers_recommended", lang)
                lines.append(f"\n💡 <b>{rec_label}:</b> {pkgs}")

            self.client.send_message(chat_id, "\n".join(lines))
        except Exception as e:
            self._say_error(chat_id, "Drivers", e)

    # =========================================================================
    # 10. System Reboot
    # =========================================================================

    def _cmd_reboot(self, chat_id: int, args: list[str], lang: Optional[str] = None) -> None:
        if lang is None:
            lang = get_chat_lang(chat_id, self.cfg)
        if not args or args[0].lower() != "now":
            self.client.send_message(chat_id, t("reboot_confirm", lang))
            return

        self.client.send_message(chat_id, t("reboot_starting", lang))
        try:
            subprocess.Popen(["sudo", "systemctl", "reboot"])
        except Exception as e:
            self._say_error(chat_id, "Reboot", e)
