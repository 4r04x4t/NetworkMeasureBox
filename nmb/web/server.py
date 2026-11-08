"""Embedded, low-footprint web server and REST API for NetworkMeasureBox.

Built with Python's standard library http.server (zero third-party dependencies).
Serves dashboard UI, live status JSON, speedtest triggers, and dossier downloads.
"""
from __future__ import annotations

import argparse
import copy
from types import SimpleNamespace
import datetime
import errno
import json
import logging
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
import functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from nmb.config import Config, load_config, save_config, CONNECTION_TYPES, find_drive_config_path, get_writable_drive_config_target, DEFAULT_CONFIG_PATH
from nmb.db import database as db
from nmb.netd import interfaces, dns
from nmb.report.metrics import latest_measured_test, tests_for_display
from nmb.netd.drivers import get_full_driver_status, trigger_driver_install, get_driver_install_status, get_interfaces_matrix
from nmb.netd.adblock import (
    get_full_adblock_status,
    set_adblock_enabled,
    disable_adblock_temporarily,
    enable_adblock,
    trigger_gravity_update,
    get_gravity_update_status,
    get_adblock_engine,
    get_live_recent_queries,
    get_whitelist_entries,
    add_whitelist_entry,
    remove_whitelist_entry,
    get_blacklist_entries,
    add_blacklist_entry,
    remove_blacklist_entry,
    get_adlists,
    add_adlist,
    remove_adlist,
    toggle_adlist,
    get_local_dns_records,
    add_local_dns_record,
    remove_local_dns_record,
    get_regex_filters,
    add_regex_filter,
    remove_regex_filter,
    get_charts_telemetry,
    get_router_dhcp_guide,
)
from nmb.netd.os_detector import detect_os_info, get_dynamic_interfaces, check_updates_available, trigger_system_upgrade, get_upgrade_status
from nmb.netd.explorer import scan_network_devices, get_cached_devices, get_explorer_summary
from nmb.netd.guest_wifi import scan_wifi_networks, get_guest_wifi_status, connect_guest_wifi, disconnect_guest_wifi, sync_guest_wifi_connection
from nmb.netd.wifi import detect_wifi_capabilities, get_wifi_status
from nmb.common.heal import (
    audit_system_health,
    auto_heal_all,
    check_stable_updates,
    apply_stable_update,
    load_heal_state,
)
from nmb.report.csv_export import export_ping_summary_csv, export_speedtests_csv, export_detailed_speedtests_csv
from nmb.report.dossier import generate_html_dossier
from nmb.web.results_page import allows_without_password, render_results_page
from nmb.report.llm_bundle import generate_llm_diagnostic_bundle
from nmb.report.metrics import aggregate_report_data
from nmb.report.svg_charts import render_latency_chart
from nmb.sniffer.engine import get_sniffer
from nmb.speed.iperf import run_iperf_client_test, get_latest_iperf_result, is_iperf_running, start_iperf_server, stop_iperf_server, get_iperf_server_status
from nmb.speed.iperf_directory import fetch_public_iperf_servers, probe_iperf_server
from nmb.speed.ookla import get_available_servers
from nmb.speed.runner import run_measurement_cycle
from nmb.speed.scheduler import AutonomousScheduler, get_cron_description, normalize_cron_expression
from nmb.speed.traceroute import run_traceroute, get_latest_traceroute, is_traceroute_running, stop_traceroute
from nmb.web.i18n import get_translations_for_lang, TRANSLATIONS, SUPPORTED_LANGUAGES
from nmb.web.templates import get_dashboard_html, get_logout_html

log = logging.getLogger("nmb.web.server")


_AUTH_FAILURES: Dict[str, list[float]] = {}
_AUTH_LOCK = threading.Lock()
MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB maximum POST request body


def _is_ip_rate_limited(ip: str) -> bool:
    now = time.time()
    with _AUTH_LOCK:
        attempts = [t for t in _AUTH_FAILURES.get(ip, []) if now - t < 60.0]
        _AUTH_FAILURES[ip] = attempts
        return len(attempts) >= 5


def _record_auth_failure(ip: str) -> None:
    now = time.time()
    with _AUTH_LOCK:
        attempts = [t for t in _AUTH_FAILURES.get(ip, []) if now - t < 60.0]
        attempts.append(now)
        _AUTH_FAILURES[ip] = attempts


def _record_auth_success(ip: str) -> None:
    with _AUTH_LOCK:
        _AUTH_FAILURES.pop(ip, None)


def _json_on_error(handler):
    """Answer with JSON 500 instead of dropping the connection on an unhandled error."""
    @functools.wraps(handler)
    def wrapper(self) -> None:
        try:
            handler(self)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:
            log.exception("unhandled error serving %s", self.path)
            self._send_json({"status": "error", "message": str(e)}, status=500)
    return wrapper


def has_control_characters(value: Any) -> bool:
    """Return True if a string anywhere in a JSON value contains a control character."""
    if isinstance(value, str):
        return any(ord(c) < 32 or ord(c) == 127 for c in value)
    if isinstance(value, dict):
        return any(has_control_characters(k) or has_control_characters(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_control_characters(v) for v in value)
    return False


def _fastcom_detail(conn, ts: int) -> Optional[Dict[str, Any]]:
    """The parts of a Fast.com row's raw_json the home page shows: client, servers, peak and mean."""
    try:
        row = conn.execute("SELECT raw_json FROM speedtest WHERE ts = ? AND engine = 'fastcom'", (ts,)).fetchone()
        raw = json.loads(row[0]) if row and row[0] else {}
    except (ValueError, TypeError, sqlite3.Error):
        return None
    if not raw:
        return None
    pick = lambda d: {k: (d or {}).get(k) for k in ("stable_mbps", "mean_mbps", "peak_mbps")}
    return {
        "client": raw.get("client") or {},
        "servers": [{k: s.get(k) for k in ("label", "host", "city", "country", "tcp_connect_ms", "latency_ms",
                                           "download_mbps", "upload_mbps")} for s in raw.get("servers") or []],
        "closest_server": raw.get("closest_server"),
        "download": pick(raw.get("download")),
        "upload": pick(raw.get("upload")),
        "loaded_latency_down_ms": raw.get("loaded_latency_down_ms"),
        "loaded_latency_up_ms": raw.get("loaded_latency_up_ms"),
    }


class WebRequestHandler(BaseHTTPRequestHandler):
    server: NMBServer  # type hint

    def address_string(self) -> str:
        """Avoid blocking reverse DNS lookup (socket.getfqdn) on every incoming request."""
        host, _ = self.client_address[:2]
        return str(host)

    def log_message(self, format: str, *args) -> None:
        msg = format % args
        log.debug("[HTTP] %s %s - %s", self.address_string(), getattr(self, "command", ""), msg)

    def _check_auth(self) -> bool:
        """Enforce HTTP Basic Authentication if auth_enabled is true with rate limiting."""
        if not self.server.cfg.web.auth_enabled:
            return True

        req_path = urlparse(self.path).path
        # Reading translations is public, but changing the language writes the config.
        if req_path in ("/logout", "/api/auth/logout") or (req_path == "/api/i18n" and self.command == "GET"):
            return True

        client_ip = self.client_address[0] if hasattr(self, "client_address") else self.address_string()
        if allows_without_password(getattr(self.server.cfg.web, "public_results", False), self.command, req_path, client_ip):
            return True
        if _is_ip_rate_limited(client_ip):
            log.warning("[AUTH] Rate limited IP %s due to too many failed attempts", client_ip)
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b"429 Too Many Requests - IP temporarily blocked due to repeated failed login attempts. Retry in 60s.\n")
            return False

        auth_header = self.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            self._send_auth_required()
            return False

        try:
            import base64
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            if ":" in decoded:
                user, password = decoded.split(":", 1)
                configured_user = getattr(self.server.cfg.web, "admin_username", "admin")
                configured_pass = getattr(self.server.cfg.web, "admin_password", "admin")
                if secrets.compare_digest(user.encode(), str(configured_user).encode()) and secrets.compare_digest(password.encode(), str(configured_pass).encode()):
                    _record_auth_success(client_ip)
                    return True
                else:
                    _record_auth_failure(client_ip)
                    log.warning("[AUTH] Failed login attempt from %s for user '%s'", client_ip, user[:32])
        except Exception as e:
            _record_auth_failure(client_ip)
            log.warning("[AUTH] Failed to decode authorization header from %s: %s", client_ip, e)

        self._send_auth_required()
        return False

    def _send_auth_required(self) -> None:
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="NetworkMeasureBox"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(b"401 Unauthorized - NetworkMeasureBox administrative credentials required\n")

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        accept_encoding = self.headers.get("Accept-Encoding", "")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

        if "gzip" in accept_encoding and len(body) > 1024:
            import gzip
            compressed = gzip.compress(body, compresslevel=5)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(compressed)))
            self.end_headers()
            self.wfile.write(compressed)
        else:
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _send_html(self, html_text: str, status: int = 200) -> None:
        body = html_text.encode("utf-8")
        accept_encoding = self.headers.get("Accept-Encoding", "")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

        if "gzip" in accept_encoding and len(body) > 512:
            import gzip
            compressed = gzip.compress(body, compresslevel=5)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(compressed)))
            self.end_headers()
            self.wfile.write(compressed)
        else:
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        if not self._check_auth():
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()

    @_json_on_error
    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        # 0. Logout UI and Auth Purge Endpoints
        if path == "/logout":
            cur_theme = getattr(self.server.cfg.web, "theme", "default")
            self._send_html(get_logout_html(initial_theme=cur_theme))
            return

        if path == "/api/auth/logout":
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="NetworkMeasureBox"')
            self.send_header("Clear-Site-Data", '"cache", "cookies", "storage"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(b'{"status": "logged_out", "message": "Successfully logged out"}\n')
            return

        # 0b. Static Assets (Themes, Logos, Backgrounds)
        if path.startswith("/static/"):
            rel = path[len("/static/"):].lstrip("/")
            if ".." in rel or rel.startswith("/"):
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            static_dir = Path(__file__).resolve().parent / "static"
            fpath = static_dir / rel
            if not fpath.exists() or not fpath.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "File Not Found")
                return
            ext = fpath.suffix.lower()
            mime_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".svg": "image/svg+xml",
                ".css": "text/css",
                ".js": "application/javascript",
                ".ico": "image/x-icon",
                ".webp": "image/webp",
            }
            ct = mime_map.get(ext, "application/octet-stream")
            content = fpath.read_bytes()
            accept_encoding = self.headers.get("Accept-Encoding", "")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "public, max-age=86400")
            if "gzip" in accept_encoding and len(content) > 512:
                import gzip
                compressed = gzip.compress(content, compresslevel=5)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(compressed)))
                self.end_headers()
                self.wfile.write(compressed)
            else:
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            return

        # 1. Main Dashboard UI
        if path in ("/", "/index.html"):
            cur_theme = getattr(self.server.cfg.web, "theme", "default")
            cur_lang = getattr(self.server.cfg.web, "language", "en")
            self._send_html(get_dashboard_html(initial_theme=cur_theme, initial_lang=cur_lang))
            return

        # 2. Status API
        if path == "/api/status":
            self._handle_api_status()
            return

        # 3. Config API
        if path == "/api/config":
            self._handle_api_get_config()
            return

        # 4. Speedtest Servers List
        if path == "/api/speedtest/servers":
            q = ""
            refresh = False
            if parsed.query:
                try:
                    qs = parse_qs(parsed.query)
                    q = qs.get("q", [""])[0] or qs.get("search", [""])[0]
                    refresh = qs.get("refresh", [""])[0] == "1"
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            servers = get_available_servers(search_query=q, limit=100, refresh=refresh)
            self._send_json({"servers": servers, "count": len(servers), "source": "ookla"})
            return

        # 5. Sniffer Telemetry Stats
        if path == "/api/sniffer/stats":
            stats = get_sniffer(self.server.cfg.network.wan_interface).get_stats()
            self._send_json(stats)
            return

        # 6. Sniffer PCAP Download
        if path in ("/api/sniffer/pcap", "/sniffer/capture.pcap"):
            pcap_bytes = get_sniffer(self.server.cfg.network.wan_interface).generate_pcap_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.tcpdump.pcap")
            self.send_header("Content-Disposition", f'attachment; filename="nmb_capture_{int(time.time())}.pcap"')
            self.send_header("Content-Length", str(len(pcap_bytes)))
            self.end_headers()
            self.wfile.write(pcap_bytes)
            return

        # 6b. Read-only results page with download links
        if path == "/results":
            qs = parse_qs(parsed.query) if parsed.query else {}
            lang = qs.get("lang", [getattr(self.server.cfg.web, "language", "en")])[0]
            self._send_html(render_results_page(lang, getattr(self.server.cfg.system, "box_id", "")))
            return

        # 7. Standalone Dossier Download
        if path in ("/dossier", "/dossier.html", "/export/report.html", "/report.html", "/api/export/dossier"):
            qs = parse_qs(parsed.query) if parsed.query else {}
            req_lang = qs.get("lang", [None])[0]
            if not req_lang or req_lang not in SUPPORTED_LANGUAGES:
                req_lang = getattr(self.server.cfg.web, "language", "hu") or "hu"
            conn = db.connect(readonly=True)
            report = aggregate_report_data(conn, self.server.cfg, window_hours=24.0)
            conn.close()
            html = generate_html_dossier(report, lang=req_lang)
            self._send_html(html)
            return

        # 8. CSV Export Download
        if path in ("/export/csv", "/api/export/csv"):
            conn = db.connect(readonly=True)
            now = db.now_ms()
            csv_data = export_ping_summary_csv(conn, now - 86400000, now)
            conn.close()
            body = csv_data.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="ping_telemetry.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 8b. Speedtest CSV Export Download
        if path in ("/export/speedtests.csv", "/api/export/speedtests", "/export/speedtests"):
            conn = db.connect(readonly=True)
            now = db.now_ms()
            csv_data = export_speedtests_csv(
                conn, 0, now,
                contract_down_mbps=self.server.cfg.isp.contract_down_mbps,
                contract_up_mbps=self.server.cfg.isp.contract_up_mbps,
                default_isp=getattr(self.server.cfg.isp, "name", ""),
            )
            conn.close()
            body = csv_data.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="speedtests_history.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/export/speedtests_detailed.csv":
            conn = db.connect(readonly=True)
            now = db.now_ms()
            csv_data = export_detailed_speedtests_csv(
                conn, 0, now,
                contract_down_mbps=float(self.server.cfg.isp.contract_down_mbps or 1000.0),
                contract_up_mbps=float(self.server.cfg.isp.contract_up_mbps or 200.0),
                guaranteed_down_mbps=float(getattr(self.server.cfg.isp, "guaranteed_down_mbps", 0.0) or 300.0),
                guaranteed_up_mbps=float(getattr(self.server.cfg.isp, "guaranteed_up_mbps", 0.0) or 50.0),
                default_isp=getattr(self.server.cfg.isp, "name", ""),
            )
            conn.close()
            body = csv_data.encode("utf-8")
            today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="Osszes_sebesseg_meresi_eredmeny_datum_{today_str}.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 9. DNS Status
        if path in ("/api/network/dns", "/api/dns"):
            self._send_json(dns.get_dns_status())
            return

        # 9b. Drive-editable Config status
        if path in ("/api/config/drive", "/api/config/drive-status"):
            from nmb.config import find_drive_config_path, get_writable_drive_config_target, DEFAULT_CONFIG_PATH
            drive_p = find_drive_config_path()
            target_p = get_writable_drive_config_target()
            self._send_json({
                "status": "ok",
                "drive_config_exists": drive_p is not None,
                "drive_config_path": str(drive_p) if drive_p else (str(target_p) if target_p else None),
                "is_writable": target_p is not None,
                "default_config_path": str(DEFAULT_CONFIG_PATH),
                "drive_mtime": drive_p.stat().st_mtime if drive_p else None,
                "default_mtime": DEFAULT_CONFIG_PATH.stat().st_mtime if DEFAULT_CONFIG_PATH.exists() else None,
            })
            return

        # 9c. User-Agent / Headless Client API
        if path == "/api/user-agent":
            from nmb.common.user_agent import get_effective_user_agent, list_user_agent_presets
            cfg = self.server.cfg
            self._send_json({
                "status": "ok",
                "user_agent": getattr(cfg.speedtest, "user_agent", ""),
                "user_agent_mode": getattr(cfg.speedtest, "user_agent_mode", "auto_fresh"),
                "effective_user_agent": get_effective_user_agent(cfg),
                "presets": list_user_agent_presets(),
            })
            return

        # 10. i18n Localization API
        if path == "/api/i18n":
            req_lang = self.server.cfg.web.language
            if parsed.query:
                try:
                    qs = parse_qs(parsed.query)
                    if "lang" in qs and qs["lang"][0]:
                        req_lang = qs["lang"][0]
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            self._send_json({
                "lang": req_lang,
                "current_configured": self.server.cfg.web.language,
                "translations": get_translations_for_lang(req_lang),
                "available": list(TRANSLATIONS.keys()),
            })
            return

        if path in ("/api/theme", "/api/system/theme"):
            self._send_json({
                "status": "ok",
                "theme": getattr(self.server.cfg.web, "theme", "default"),
                "available": ["default", "prtd", "proudride", "amoled", "asuswrt", "asus_camo", "tp_gold", "mountain_hago", "ndefault"],
            })
            return

        # 11. Multi-OS & Hardware Info
        if path == "/api/system/info":
            self._send_json(detect_os_info())
            return

        if path == "/api/system/tasks":
            from nmb.common.tasks import get_full_task_manager_payload
            qs = parse_qs(parsed.query) if parsed.query else {}
            limit = int(qs.get("limit", ["150"])[0])
            self._send_json(get_full_task_manager_payload(limit=limit))
            return

        if path in ("/api/system/interfaces", "/api/system/ports"):
            self._send_json(get_interfaces_matrix(self.server.cfg))
            return

        if path == "/api/system/drivers":
            self._send_json(get_full_driver_status())
            return

        if path == "/api/system/drivers/status":
            self._send_json(get_driver_install_status())
            return

        # DNS Ad-Blocker (Pi-hole Engine) Endpoints
        if path == "/api/adblock/status":
            self._send_json(get_full_adblock_status())
            return

        if path == "/api/adblock/charts":
            self._send_json(get_charts_telemetry())
            return

        if path == "/api/adblock/querylog":
            qs = parse_qs(parsed.query) if parsed.query else {}
            limit = int(qs.get("limit", ["50"])[0])
            self._send_json({"status": "ok", "queries": get_live_recent_queries(limit)})
            return

        if path == "/api/adblock/whitelist":
            self._send_json({"status": "ok", "whitelist": get_whitelist_entries()})
            return

        if path == "/api/adblock/blacklist":
            self._send_json({"status": "ok", "blacklist": get_blacklist_entries()})
            return

        if path == "/api/adblock/adlists":
            self._send_json({"status": "ok", "adlists": get_adlists()})
            return

        if path == "/api/adblock/localdns":
            self._send_json({"status": "ok", "records": get_local_dns_records()})
            return

        if path == "/api/adblock/regex":
            self._send_json({"status": "ok", "regex": get_regex_filters()})
            return

        if path == "/api/adblock/guide":
            self._send_json(get_router_dhcp_guide())
            return

        if path in ("/api/adblock/update/status", "/api/adblock/gravity/status"):
            self._send_json(get_gravity_update_status())
            return

        # Self-Healing & Component Health Audit Endpoints
        if path == "/api/heal/status":
            self._send_json({
                "status": "ok",
                "audit": audit_system_health(),
                "state": load_heal_state(),
            })
            return

        if path == "/api/heal/updates":
            self._send_json(check_stable_updates())
            return

        if path == "/api/heal/update/status":
            from nmb.common import updater
            self._send_json(updater.read_status())
            return

        # 12. Distro-Aware System Updates
        if path == "/api/system/updates/check":
            self._send_json(check_updates_available())
            return

        if path == "/api/system/updates/status":
            self._send_json(get_upgrade_status())
            return

        # 13. LLM Diagnostic Bundle (Copy-Pasteable Markdown Report)
        if path == "/api/diagnostics/llm":
            qs = parse_qs(parsed.query) if parsed.query else {}
            force = bool(qs.get("force", ["0"])[0] in ("1", "true", "yes"))
            bundle_md = generate_llm_diagnostic_bundle(self.server.cfg, force_refresh=force)
            self._send_json({"status": "ok", "markdown": bundle_md})
            return

        if path in ("/download/diagnostics.md", "/api/diagnostics/download"):
            bundle_md = generate_llm_diagnostic_bundle(self.server.cfg)
            body = bundle_md.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="nmb_llm_diagnostics_{int(time.time())}.md"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 14. Network Explorer Devices
        if path in ("/api/network/devices", "/api/explorer/devices"):
            qs = parse_qs(parsed.query) if parsed.query else {}
            req_iface = qs.get("iface", [None])[0]
            summary = get_explorer_summary()
            if req_iface and req_iface != "any":
                summary["devices"] = [d for d in summary["devices"] if d.get("interface") == req_iface]
            self._send_json(summary)
            return

        # 15. iPerf3 Status & Server Toggle
        if path in ("/api/iperf/status", "/api/iperf/server"):
            self._send_json({
                "is_running": is_iperf_running(),
                "latest": get_latest_iperf_result(),
                "server": get_iperf_server_status(),
            })
            return

        if path == "/api/iperf/server/toggle":
            self._send_json({"status": "error", "message": "Use POST."}, status=405)
            return


        # 15b. iPerf3 Public Server Directory
        if path == "/api/iperf/servers":
            qs = parse_qs(parsed.query) if parsed.query else {}
            force = bool(qs.get("refresh", ["0"])[0] in ("1", "true", "yes"))
            cont = qs.get("continent", [""])[0].strip()
            q = qs.get("search", [""])[0].strip().lower()
            res = fetch_public_iperf_servers(force_refresh=force)
            if res.get("status") == "ok" and (cont or q):
                filtered = []
                for s in res.get("servers", []):
                    if cont and cont.lower() != "all" and s.get("continent", "").lower() != cont.lower():
                        continue
                    if q:
                        blob = f"{s.get('host', '')} {s.get('site', '')} {s.get('country', '')} {s.get('provider', '')}".lower()
                        if q not in blob:
                            continue
                    filtered.append(s)
                res = dict(res)
                res["servers"] = filtered
                res["count"] = len(filtered)
            self._send_json(res)
            return

        # 15c. iPerf3 Reachability Socket Probe
        if path == "/api/iperf/probe":
            qs = parse_qs(parsed.query) if parsed.query else {}
            host = qs.get("host", [""])[0].strip()
            port_val = int(qs.get("port", ["5201"])[0].strip() or 5201)
            probe_res = probe_iperf_server(host, port_val)
            self._send_json(probe_res)
            return

        # 16. Traceroute Status
        if path == "/api/traceroute/status":
            self._send_json({
                "is_running": is_traceroute_running(),
                "latest": get_latest_traceroute(),
            })
            return

        # 16b. OONI Probe Censorship Status & Results
        if path == "/api/ooni/status":
            from nmb.probe.ooni import get_ooni_status
            status = get_ooni_status()
            status["enabled"] = self.server.cfg.ooni.enabled
            self._send_json(status)
            return

        if path == "/api/ooni/results":
            from nmb.probe.ooni import get_ooni_history
            qs = parse_qs(parsed.query) if parsed.query else {}
            try:
                limit = int(qs.get("limit", ["15"])[0])
            except (ValueError, TypeError):
                limit = 15
            self._send_json({"results": get_ooni_history(limit=limit)})
            return

        if path == "/api/ooni/run":
            from nmb.probe.ooni import get_ooni_run_measurements
            qs = parse_qs(parsed.query) if parsed.query else {}
            try:
                run_id = int(qs.get("id", [0])[0])
            except (ValueError, TypeError):
                run_id = 0
            if not run_id:
                self._send_json({"status": "error", "message": "Missing or invalid ?id= parameter."}, status=400)
                return
            self._send_json(get_ooni_run_measurements(run_id))
            return

        if path == "/api/ooni/measurement":
            from nmb.probe.ooni import get_ooni_measurement_detail
            qs = parse_qs(parsed.query) if parsed.query else {}
            try:
                msmt_id = int(qs.get("id", [0])[0])
            except (ValueError, TypeError):
                msmt_id = 0
            if not msmt_id:
                self._send_json({"status": "error", "message": "Missing or invalid ?id= parameter."}, status=400)
                return
            self._send_json(get_ooni_measurement_detail(msmt_id))
            return

        # 17. Autonomous Scheduler & Traffic Gate Status
        if path in ("/api/scheduler/status", "/api/scheduler"):
            if getattr(self.server, "scheduler", None):
                self._send_json(self.server.scheduler.get_status())
            else:
                dummy = AutonomousScheduler(self.server.cfg)
                self._send_json(dummy.get_status())
            return

        # 17b. DuckDNS / dynv6 DynDNS Status
        if path == "/api/storage/status":
            import shutil as _sh
            from nmb.common import storage_guard
            st = self.server.cfg.storage
            base = storage_guard.DATA_DIR if storage_guard.DATA_DIR.exists() else Path("/")
            du = _sh.disk_usage(str(base))
            self._send_json({"auto_cleanup": st.auto_cleanup, "min_free_mb": st.min_free_mb, "keep_days": st.keep_days,
                             "path": str(base), "total_mb": du.total // 2**20, "free_mb": du.free // 2**20,
                             "target_free_mb": storage_guard.free_target_bytes(du.total, st.min_free_mb) // 2**20,
                             "last_cleanup": storage_guard.status()})
            return

        if path == "/api/usb-uplink/status":
            from nmb.netd import usb_uplink
            self._send_json(usb_uplink.status(self.server.cfg))
            return

        if path == "/api/wifi-share/status":
            from nmb.netd import wifi_share
            self._send_json(wifi_share.status(self.server.cfg))
            return

        if path == "/api/wifi-uplink/status":
            from nmb.netd import wifi_uplink
            self._send_json(wifi_uplink.status(self.server.cfg))
            return

        if path == "/api/collector/status":
            from nmb.collector import client as collector_client
            self._send_json(collector_client.get_status(self.server.cfg))
            return

        if path in ("/api/duckdns/status", "/api/dyndns/status"):
            from nmb.netd.duckdns import get_duckdns_status
            self._send_json(get_duckdns_status(self.server.cfg))
            return

        # 17c. WireGuard VPN Status, Config & QR
        if path == "/api/wireguard/status":
            from nmb.netd.wireguard import get_wireguard_status
            cfg = self.server.cfg
            host_header = self.headers.get("Host", "").split(":")[0].strip()
            self._send_json(get_wireguard_status(
                port=cfg.wireguard.port,
                subnet=cfg.wireguard.subnet,
                subnet_ipv6=cfg.wireguard.subnet_ipv6,
                dns=cfg.wireguard.dns,
                public_endpoint=cfg.wireguard.public_endpoint,
                duckdns_domain=cfg.duckdns.domain,
                request_host=host_header,
            ))
            return

        if path == "/api/wireguard/endpoints":
            from nmb.netd.wireguard import get_candidate_endpoints
            cfg = self.server.cfg
            host_header = self.headers.get("Host", "").split(":")[0].strip()
            self._send_json({
                "status": "ok",
                "endpoints": get_candidate_endpoints(
                    port=cfg.wireguard.port,
                    public_endpoint=cfg.wireguard.public_endpoint,
                    duckdns_domain=cfg.duckdns.domain,
                    request_host=host_header,
                )
            })
            return

        if path == "/api/wireguard/peer/config":
            from nmb.netd.wireguard import get_client_config, is_private_ip
            qs = parse_qs(parsed.query) if parsed.query else {}
            peer_name = qs.get("name", [""])[0] or qs.get("id", [""])[0]
            endpoint = qs.get("endpoint", [""])[0].strip()
            if not endpoint:
                host_header = self.headers.get("Host", "").split(":")[0].strip()
                if is_private_ip(host_header):
                    endpoint = host_header
                else:
                    endpoint = self.server.cfg.wireguard.public_endpoint or (self.server.cfg.duckdns.domain + ".duckdns.org" if self.server.cfg.duckdns.domain else "") or host_header
            conf = get_client_config(peer_name, endpoint_host=endpoint, port=self.server.cfg.wireguard.port, dns_servers=self.server.cfg.wireguard.dns)
            if not conf:
                self._send_json({"status": "error", "message": f"Peer '{peer_name}' not found."}, status=404)
                return
            content_bytes = conf.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{peer_name}.conf"')
            self.send_header("Content-Length", str(len(content_bytes)))
            self.end_headers()
            self.wfile.write(content_bytes)
            return

        if path == "/api/wireguard/peer/qr":
            from nmb.netd.wireguard import get_client_qr_data_uri, get_client_qr_png_bytes, is_private_ip
            qs = parse_qs(parsed.query) if parsed.query else {}
            peer_name = qs.get("name", [""])[0] or qs.get("id", [""])[0]
            endpoint = qs.get("endpoint", [""])[0].strip()
            if not endpoint:
                host_header = self.headers.get("Host", "").split(":")[0].strip()
                if is_private_ip(host_header):
                    endpoint = host_header
                else:
                    endpoint = self.server.cfg.wireguard.public_endpoint or (self.server.cfg.duckdns.domain + ".duckdns.org" if self.server.cfg.duckdns.domain else "") or host_header
            dns_val = self.server.cfg.wireguard.dns
            if qs.get("raw", ["0"])[0] == "1":
                png_bytes = get_client_qr_png_bytes(peer_name, endpoint_host=endpoint, port=self.server.cfg.wireguard.port, dns_servers=dns_val)
                if not png_bytes:
                    self._send_json({"status": "error", "message": "Failed to generate QR code."}, status=404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(png_bytes)
                return
            data_uri = get_client_qr_data_uri(peer_name, endpoint_host=endpoint, port=self.server.cfg.wireguard.port, dns_servers=dns_val)
            if not data_uri:
                self._send_json({"status": "error", "message": "Failed to generate QR code."}, status=404)
                return
            self._send_json({"status": "ok", "qr_data_uri": data_uri, "endpoint_used": endpoint})
            return

        # 17d. OpenVPN Status & Config
        if path == "/api/openvpn/status":
            from nmb.netd.openvpn import get_openvpn_status
            cfg = self.server.cfg
            self._send_json(get_openvpn_status(
                proto=cfg.openvpn.proto,
                port=cfg.openvpn.port,
                subnet=cfg.openvpn.subnet,
                subnet_ipv6=cfg.openvpn.subnet_ipv6,
                dns=cfg.openvpn.dns,
            ))
            return

        if path == "/api/openvpn/client/config":
            from nmb.netd.openvpn import get_unified_ovpn_profile
            qs = parse_qs(parsed.query) if parsed.query else {}
            client_name = qs.get("name", [""])[0]
            endpoint = self.server.cfg.openvpn.public_endpoint or (self.server.cfg.duckdns.domain + ".duckdns.org" if self.server.cfg.duckdns.domain else "")
            ovpn = get_unified_ovpn_profile(
                client_name,
                endpoint_host=endpoint,
                proto=self.server.cfg.openvpn.proto,
                port=self.server.cfg.openvpn.port,
                dns_servers=self.server.cfg.openvpn.dns,
            )
            if not ovpn:
                self._send_json({"status": "error", "message": f"Client '{client_name}' not found."}, status=404)
                return
            content_bytes = ovpn.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-openvpn-profile; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{client_name}.ovpn"')
            self.send_header("Content-Length", str(len(content_bytes)))
            self.end_headers()
            self.wfile.write(content_bytes)
            return

        # 17e. HTTPS Proxy Server Status
        if path == "/api/proxy/status":
            from nmb.netd.proxy import get_proxy_status
            self._send_json(get_proxy_status())
            return

        # 17g. Tailscale Mesh VPN Status
        if path in ("/api/tailscale/status", "/api/network/tailscale/status"):
            from nmb.netd.tailscale import get_tailscale_status
            st = get_tailscale_status()
            st["config_enabled"] = getattr(self.server.cfg.tailscale, "enabled", False)
            st["config_hostname"] = getattr(self.server.cfg.tailscale, "hostname", "networkmeasurebox")
            auth_key = getattr(self.server.cfg.tailscale, "auth_key", "")
            st["auth_key_set"] = bool(auth_key)
            st["auth_key_masked"] = (auth_key[:8] + "..." + auth_key[-4:]) if (auth_key and len(auth_key) > 12) else ("***" if auth_key else "")
            self._send_json(st)
            return

        # 17h. Telegram Chatbot & Proactive Alert Status
        if path == "/api/telegram/status":
            from nmb.bot.client import TelegramClient
            token = getattr(self.server.cfg.telegram, "token", "")
            masked = (token[:6] + "..." + token[-4:]) if (token and len(token) > 10) else ("***" if token else "")
            active = False
            pid = 0
            if shutil.which("systemctl"):
                try:
                    res = subprocess.run(["systemctl", "is-active", "nmb-telegram"], capture_output=True, text=True, timeout=3)
                    active = res.stdout.strip() == "active"
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            pid_file = self.server.cfg.system.run_dir / "telegram.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            bot_info = None
            if token:
                try:
                    client = TelegramClient(token)
                    bot_info = client.get_me()
                except Exception as e:
                    log.debug("telegram get_me error: %s", e)
            
            allowed_chats = getattr(self.server.cfg.telegram, "allowed_chat_ids", [])
            loss_pct = getattr(self.server.cfg.telegram, "alert_loss_threshold_pct", 5.0)
            lat_ms = getattr(self.server.cfg.telegram, "alert_latency_threshold_ms", 100.0)

            self._send_json({
                "status": "ok",
                "ok": True,
                "enabled": getattr(self.server.cfg.telegram, "enabled", False),
                "token_set": bool(token),
                "token_masked": masked,
                "allowed_chat_ids": allowed_chats,
                "chat_ids": allowed_chats,
                "alert_loss_threshold_pct": loss_pct,
                "loss_threshold_pct": loss_pct,
                "alert_latency_threshold_ms": lat_ms,
                "latency_threshold_ms": lat_ms,
                "alert_on_loss": getattr(self.server.cfg.telegram, "alert_on_loss", True),
                "alert_on_latency": getattr(self.server.cfg.telegram, "alert_on_latency", True),
                "service_active": active,
                "pid": pid,
                "bot_info": bot_info,
                "bot_username": bot_info.get("username", "") if bot_info else "",
                "bot_first_name": bot_info.get("first_name", "") if bot_info else "",
                "can_connect": bool(bot_info),
            })
            return

        # 17f. Backup & Disaster Recovery GET APIs
        if path == "/api/backup/list":
            from nmb.common.backup import list_backups
            self._send_json({"status": "ok", "backups": list_backups()})
            return

        if path == "/api/backup/download":
            from nmb.common.backup import BACKUP_DIR
            qs = parse_qs(parsed.query) if parsed.query else {}
            filename = os.path.basename(qs.get("file", [""])[0].strip())
            target_path = BACKUP_DIR / filename
            if not filename or not target_path.exists() or not target_path.is_file():
                self._send_json({"status": "error", "message": "Backup file not found."}, status=404)
                return
            with open(target_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return


        # 18. Wi-Fi Multi-Band Hardware Capabilities & Status
        if path in ("/api/network/wifi/capabilities", "/api/wifi/capabilities"):
            wlan_iface = self.server.cfg.network.wlan_interface
            self._send_json(detect_wifi_capabilities(wlan_iface))
            return

        if path in ("/api/network/wifi/status", "/api/wifi/status"):
            wlan_iface = self.server.cfg.network.wlan_interface
            self._send_json(get_wifi_status(wlan_iface))
            return

        # 18b. Dedicated Guest Wi-Fi Client Station / Probe Telemetry
        if path in ("/api/network/wifi/guest/status", "/api/wifi/guest/status", "/api/wifi/guest"):
            guest_iface = getattr(self.server.cfg.guest_wifi, "interface", "wlan0")
            main_iface = str(getattr(self.server.cfg.wifi_uplink, "interface", "") or "")
            if not guest_iface or guest_iface == main_iface:
                # The radio is the main Wi-Fi client; it must not be reported as a guest network.
                self._send_json({"status": "ok", "connected": False, "unassigned": True, "interface": guest_iface or None,
                                 "main_interface": main_iface if main_iface != "auto" else None})
                return
            wan_iface = self.server.cfg.network.wan_interface
            self._send_json(get_guest_wifi_status(guest_iface, wan_iface=wan_iface, cfg_guest=self.server.cfg.guest_wifi))
            return

        if path in ("/api/network/wifi/guest/scan", "/api/wifi/guest/scan"):
            guest_iface = getattr(self.server.cfg.guest_wifi, "interface", "wlan0")
            nets = scan_wifi_networks(guest_iface, force_rescan=True)
            self._send_json({"status": "ok", "interface": guest_iface, "networks": nets})
            return

        if path in ("/api/network/wifi/guest/saved", "/api/wifi/guest/saved"):
            from nmb.netd.guest_wifi import list_saved_wifi_connections
            saved = list_saved_wifi_connections()
            self._send_json({"status": "ok", "saved_networks": saved})
            return

        # 19. Network MAC Info
        if path in ("/api/network/mac", "/api/mac"):
            wan_iface = self.server.cfg.network.wan_interface
            self._send_json({
                "status": "ok",
                "current_mac": interfaces.get_mac_address(wan_iface),
                "factory_mac": interfaces.get_factory_mac_address(wan_iface),
            })
            return

        # 20. Developer Deep Logging API
        if path == "/api/dev/logs":
            qs = parse_qs(parsed.query) if parsed.query else {}
            min_lvl = qs.get("level", ["ALL"])[0].strip()
            search_q = qs.get("search", [""])[0].strip() or qs.get("q", [""])[0].strip()
            comp = qs.get("component", [""])[0].strip()
            limit = int(qs.get("limit", ["200"])[0].strip() or 200)
            since_id = None
            if "since_id" in qs and qs["since_id"][0].strip().isdigit():
                since_id = int(qs["since_id"][0].strip())

            from nmb.devlog import get_dev_log_buffer, get_active_log_file
            buf = get_dev_log_buffer()
            records = buf.get_records(
                min_level=min_lvl,
                logger_prefix=comp,
                search=search_q,
                limit=min(limit, 2000),
                since_id=since_id,
            )
            root_lvl_name = logging.getLevelName(logging.getLogger().level)
            self._send_json({
                "status": "ok",
                "current_level": root_lvl_name,
                "log_file": get_active_log_file() or "/var/log/nmb/nmb_developer.log",
                "total_buffered": buf.total_count,
                "capacity": buf.capacity,
                "last_id": buf.last_id,
                "count": len(records),
                "records": records,
            })
            return

        if path in ("/api/dev/logs/download", "/download/developer.log"):
            from nmb.devlog import get_active_log_file, read_raw_log_tail
            log_file = get_active_log_file()
            body_bytes = b""
            if log_file and os.path.exists(log_file):
                try:
                    with open(log_file, "rb") as f:
                        body_bytes = f.read()
                except Exception as e:
                    body_bytes = f"Error reading developer log: {e}\n".encode("utf-8")
            else:
                body_bytes = read_raw_log_tail(1000).encode("utf-8")

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="nmb_developer_{int(time.time())}.log"')
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return

        if path == "/api/dev/logs/raw":
            from nmb.devlog import read_raw_log_tail
            lines = 300
            if parsed.query:
                qs = parse_qs(parsed.query)
                if "lines" in qs and qs["lines"][0].strip().isdigit():
                    lines = int(qs["lines"][0].strip())
            text = read_raw_log_tail(lines)
            body = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 21. Hardware & Linux Kernel Syslog API (Router-Grade Diagnostics)
        if path == "/api/system/syslog":
            qs = parse_qs(parsed.query) if parsed.query else {}
            lines = 300
            if "lines" in qs and qs["lines"][0].strip().isdigit():
                lines = min(max(int(qs["lines"][0].strip()), 50), 3000)
            src = qs.get("source", qs.get("filter", ["all"]))[0].strip()
            sev = qs.get("severity", ["all"])[0].strip()
            search_q = qs.get("search", qs.get("q", [""]))[0].strip()

            from nmb.devlog import get_system_syslog
            res = get_system_syslog(lines=lines, source=src, severity=sev, search=search_q)
            self._send_json(res)
            return

        if path in ("/api/system/syslog/download", "/download/syslog.log"):
            qs = parse_qs(parsed.query) if parsed.query else {}
            lines = 2000
            if "lines" in qs and qs["lines"][0].strip().isdigit():
                lines = min(max(int(qs["lines"][0].strip()), 100), 5000)
            src = qs.get("source", qs.get("filter", ["all"]))[0].strip()
            sev = qs.get("severity", ["all"])[0].strip()
            search_q = qs.get("search", qs.get("q", [""]))[0].strip()

            from nmb.devlog import get_raw_system_syslog
            raw_text = get_raw_system_syslog(lines=lines, source=src, severity=sev, search=search_q)
            body_bytes = raw_text.encode("utf-8")

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="system_syslog_{src}_{int(time.time())}.log"')
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return

        if path == "/api/system/kernel-tuning":
            from nmb.netd.kernel import get_kernel_network_status
            self._send_json(get_kernel_network_status())
            return

        # 22. Invasive Diagnostics & AI Developer Snapshot
        if path == "/api/dev/invasive-log":
            from nmb.report.invasive_logger import get_cached_invasive_snapshot
            md, snap = get_cached_invasive_snapshot()
            self._send_json(snap)
            return

        if path in ("/api/dev/invasive-log.md", "/download/invasive-log.md"):
            from nmb.report.invasive_logger import read_latest_invasive_snapshot_file, get_cached_invasive_snapshot
            cached_md = read_latest_invasive_snapshot_file()
            if not cached_md:
                cached_md, _ = get_cached_invasive_snapshot()
            body_bytes = cached_md.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="nmb_invasive_dev_snapshot_{int(time.time())}.md"')
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return

        # 23. Ookla Anti-Ban & Server Quarantine Status
        if path == "/api/speed/anti-ban":
            from nmb.speed.anti_ban import get_quarantined_servers
            self._send_json({"quarantined_servers": get_quarantined_servers()})
            return

        # 24. Preferred Measurement Interface & Physical Cable Detection
        if path == "/api/network/lan-topology":
            self._send_json(self._lan_topology_payload())
            return

        if path == "/api/system/purge":
            from nmb.common import purge as purge_mod
            self._send_json({"status": "ok", "summary": purge_mod.get_purge_summary(self.server.cfg)})
            return

        if path == "/api/network/preferred-interface":
            from nmb.netd.interfaces import find_preferred_measurement_interface
            cfg = self.server.cfg if hasattr(self, "server") and hasattr(self.server, "cfg") else load_config()
            iface, ip, is_wired = find_preferred_measurement_interface(cfg)
            self._send_json({
                "interface": iface,
                "bound_ip": ip,
                "is_wired": is_wired,
                "priority": "wired_cable_override" if is_wired else "wireless_or_fallback",
            })
            return

        # 25. Crash Incident Reports API
        if path == "/api/dev/crashes":
            from nmb.report.crash_trap import list_crash_reports
            self._send_json({"crashes": list_crash_reports()})
            return

        if path.startswith("/api/dev/crashes/"):
            fname = path.split("/api/dev/crashes/", 1)[1]
            from nmb.report.crash_trap import read_crash_report
            content = read_crash_report(fname)
            if content:
                body_bytes = content.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Crash report not found")
            return

        # 26. Diagnostic Archive Packager (.tar.gz bundle download)
        if path in ("/api/dev/diagnostic-bundle.tar.gz", "/download/diagnostic-bundle.tar.gz"):
            from nmb.report.crash_trap import create_diagnostic_bundle
            bundle_path = create_diagnostic_bundle()
            if bundle_path.is_file():
                bundle_bytes = bundle_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="{bundle_path.name}"')
                self.send_header("Content-Length", str(len(bundle_bytes)))
                self.end_headers()
                self.wfile.write(bundle_bytes)
                return
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to create diagnostic bundle")
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    @_json_on_error
    def do_POST(self) -> None:
        if not self._check_auth():
            return

        parsed_req = urlparse(self.path)
        if parsed_req.path == "/api/auth/logout":
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="NetworkMeasureBox"')
            self.send_header("Clear-Site-Data", '"cache", "cookies", "storage"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(b'{"status": "logged_out", "message": "Successfully logged out"}\n')
            return

        # 1. CSRF Protection: check Origin / Referer against Host
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        host = self.headers.get("Host")
        if origin and host:
            origin_parsed = urlparse(origin)
            if origin_parsed.netloc != host:
                log.warning("[CSRF] Blocked cross-origin POST from %s to host %s", origin, host)
                self.send_error(HTTPStatus.FORBIDDEN, "Cross-Origin Request Blocked")
                return

        # 2. Content-Length & Size Limits (DoS Protection)
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header")
            return

        if length < 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "Negative Content-Length header")
            return

        parsed = urlparse(self.path)
        path = parsed.path
        is_backup_upload = (path == "/api/backup/upload")
        max_allowed = 256 * 1024 * 1024 if is_backup_upload else MAX_BODY_SIZE

        if length > max_allowed:
            log.warning("[SECURITY] Rejected oversized POST body: %d bytes (limit: %d)", length, max_allowed)
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"Payload exceeds {max_allowed // (1024*1024)}MB limit")
            return

        raw_body = self.rfile.read(length) if length > 0 else b"{}"

        if is_backup_upload:
            from nmb.common.backup import restore_backup, BACKUP_DIR
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            temp_tar = BACKUP_DIR / f"nmb-upload-{int(time.time())}.tar.gz"
            upload_bytes = raw_body

            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type and b"\r\n\r\n" in raw_body:
                header_part, file_data = raw_body.split(b"\r\n\r\n", 1)
                boundary = content_type.split("boundary=")[-1].strip().strip('"').encode()
                if boundary in file_data:
                    file_data = file_data.split(b"--" + boundary)[0]
                if file_data.endswith(b"\r\n"):
                    file_data = file_data[:-2]
                upload_bytes = file_data

            ok = False
            try:
                # The archive holds passwords; keep it as private as the other backups.
                fd = os.open(temp_tar, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
                with os.fdopen(fd, "wb") as f:
                    f.write(upload_bytes)
                ok, msg = restore_backup(temp_tar, create_safety_snapshot=True)
                if ok:
                    self.server.cfg = load_config()
                    self._send_json({"status": "ok", "message": msg})
                else:
                    self._send_json({"status": "error", "message": msg}, status=400)
            except Exception as e:
                self._send_json({"status": "error", "message": f"Upload processing failed: {e}"}, status=500)
            finally:
                if not ok:
                    temp_tar.unlink(missing_ok=True)
            return

        try:
            body_json = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            body_json = {}
        if not isinstance(body_json, dict):
            self._send_json({"status": "error", "message": "The request body must be a JSON object."}, status=400)
            return
        # Settings end up in hostapd, dnsmasq and VPN files, where a line break adds a new directive.
        if path != "/api/terminal/exec" and has_control_characters(body_json):
            self._send_json({"status": "error", "message": "Values must not contain control characters."}, status=400)
            return

        # 1. Trigger Speedtest (Asynchronous with state tracking)
        if path == "/api/speedtest":
            raw_sid = body_json.get("server_id")
            engine = str(body_json.get("engine", "ookla")).strip().lower()
            if engine not in ("ookla", "cloudflare", "fastcom", "rtr", "iperf3", "all"):
                engine = "ookla"

            target_iface = body_json.get("interface") or body_json.get("target_iface")
            if target_iface:
                target_iface = str(target_iface).strip()
                if not target_iface or target_iface.lower() in ("auto", "default", "none", "all"):
                    target_iface = None

            server_id = None
            if raw_sid:
                try:
                    server_id = int(raw_sid)
                except (ValueError, TypeError):
                    server_id = None

            if getattr(self.server, "is_measuring", False):
                self._send_json({"status": "busy", "message": "Measurement already in progress. Please wait..."}, status=409)
                return

            def _async_speedtest():
                self.server.is_measuring = True
                try:
                    log.info("API trigger: starting async speedtest (engine=%s, server_id=%s, iface=%s)", engine, server_id, target_iface)
                    run_measurement_cycle(self.server.cfg, trigger="web", force=True, run_port_check=True, server_id=server_id, engine=engine, target_iface=target_iface)
                except Exception as e:
                    log.error("speedtest async error: %s", e)
                    self.server.last_measure_error = str(e)
                finally:
                    self.server.is_measuring = False

            t = threading.Thread(target=_async_speedtest, daemon=True, name="nmb-speedtest-worker")
            t.start()
            self._send_json({"status": "started", "engine": engine, "interface": target_iface or "default", "message": "Measurement cycle initiated."})
            return

        if path in ("/api/speedtest/stop", "/api/speedtest/cancel"):
            self.server.is_measuring = False
            self._send_json({"status": "stopped", "message": "Measurement cancelled."})
            return

        if path in ("/api/portcheck", "/api/speedtest/portcheck"):
            def _async_portcheck():
                conn = db.connect()
                try:
                    from nmb.speed.port_checker import run_port_neutrality_check, record_port_checks_to_db
                    port_results = run_port_neutrality_check()
                    record_port_checks_to_db(conn, port_results)
                finally:
                    conn.close()
            threading.Thread(target=_async_portcheck, daemon=True).start()
            self._send_json({"status": "started", "message": "Port neutrality audit started..."})
            return

        # 1a. Fast endpoint to instantly switch and persist active/automated measurement engine
        if path == "/api/speedtest/engine":
            engine = str(body_json.get("engine", "")).strip().lower()
            if engine in ("ookla", "cloudflare", "fastcom", "rtr", "iperf3", "all"):
                self.server.cfg.speedtest.automated_engine = engine
                save_config(self.server.cfg)
                conn = db.connect()
                try:
                    with db.tx(conn):
                        conn.execute(
                            "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'speed', 'config_changed', ?)",
                            (db.now_ms(), f"Active measurement engine switched to {engine.upper()}.")
                        )
                finally:
                    conn.close()
                self._send_json({"status": "ok", "automated_engine": engine, "message": f"Measurement engine switched to {engine.upper()}."})
                return
            else:
                self._send_json({"status": "error", "message": f"Invalid engine: {engine}"}, status=400)
                return

        # 1b. Set Default / Scheduled Server and Automation Mode
        if path in ("/api/speedtest/default-server", "/api/speedtest/scheduled-server", "/api/speedtest/schedule"):
            raw_sid = body_json.get("server_id")
            srv_name = str(body_json.get("server_name", "")).strip()
            srv_host = str(body_json.get("server_host", "")).strip()
            sched_mode = body_json.get("schedule_mode")
            sched_cron = body_json.get("schedule_cron")
            auto_eng = body_json.get("automated_engine") or body_json.get("engine")
            thresh_mode = body_json.get("idle_threshold_mode")
            thresh_pct = body_json.get("idle_threshold_percent")
            thresh_kbps = body_json.get("idle_threshold_kbps")

            if sched_mode in ("manual", "scheduled"):
                self.server.cfg.speedtest.schedule_mode = sched_mode
            if sched_cron and str(sched_cron).strip():
                norm_cron = normalize_cron_expression(str(sched_cron).strip())
                self.server.cfg.speedtest.schedule_cron = norm_cron
            if auto_eng and str(auto_eng).strip():
                self.server.cfg.speedtest.automated_engine = str(auto_eng).strip().lower()
            for key, floor in (("ookla_interval_min", 60), ("rtr_interval_min", 0), ("cloudflare_interval_min", 0), ("fastcom_interval_min", 0), ("iperf3_interval_min", 0)):
                if key in body_json:
                    try:
                        setattr(self.server.cfg.speedtest, key, max(floor, min(10080, int(body_json[key]))))
                    except (ValueError, TypeError):
                        pass
            if thresh_mode in ("percent", "fixed"):
                self.server.cfg.speedtest.idle_threshold_mode = thresh_mode
            if thresh_pct is not None:
                try:
                    self.server.cfg.speedtest.idle_threshold_percent = float(thresh_pct)
                except (ValueError, TypeError):
                    pass
            if thresh_kbps is not None:
                try:
                    self.server.cfg.speedtest.idle_threshold_kbps = int(thresh_kbps)
                except (ValueError, TypeError):
                    pass
            if "iperf_target_host" in body_json and str(body_json["iperf_target_host"]).strip():
                self.server.cfg.iperf.target_host = str(body_json["iperf_target_host"]).strip()
            ipc = self.server.cfg.iperf
            if "iperf_duration" in body_json:
                try:
                    ipc.duration = max(3, min(60, int(body_json["iperf_duration"])))
                except (ValueError, TypeError):
                    pass
            if str(body_json.get("iperf_protocol", "")).lower() in ("tcp", "udp"):
                ipc.protocol = str(body_json["iperf_protocol"]).lower()
            if "iperf_parallel" in body_json:
                try:
                    ipc.parallel = max(1, min(16, int(body_json["iperf_parallel"])))
                except (ValueError, TypeError):
                    pass
            if "iperf_extra_servers" in body_json:
                from nmb.speed.runner import iperf3_servers
                probe = copy.copy(ipc)
                probe.target_host = ""
                probe.extra_servers = str(body_json["iperf_extra_servers"])[:1000]
                ipc.extra_servers = ", ".join(f"{h}:{p}" for h, p in iperf3_servers(SimpleNamespace(iperf=probe)))
            direction = str(body_json.get("iperf_direction", "")).lower()
            if direction in ("both", "download", "upload", "bidir"):
                ipc.bidir = direction == "bidir"
                ipc.auto_direction = "both" if direction == "bidir" else direction
            if "iperf_port" in body_json:
                try:
                    p_val = int(body_json["iperf_port"])
                    self.server.cfg.iperf.target_port = p_val
                    self.server.cfg.iperf.port = p_val
                except (ValueError, TypeError):
                    pass

            msg_parts = []
            if "server_id" in body_json:
                if raw_sid is None or str(raw_sid).strip() == "" or str(raw_sid).lower() in ("auto", "null", "none"):
                    self.server.cfg.speedtest.server_id = None
                    self.server.cfg.speedtest.server_name = ""
                    self.server.cfg.speedtest.server_host = ""
                    msg_parts.append("Target: Automatic closest benchmark server.")
                else:
                    try:
                        sid_int = int(raw_sid)
                        self.server.cfg.speedtest.server_id = sid_int
                        self.server.cfg.speedtest.server_name = srv_name
                        self.server.cfg.speedtest.server_host = srv_host
                        msg_parts.append(f"Target server: {srv_name or 'Server'} (#{sid_int}).")
                    except (ValueError, TypeError):
                        self._send_json({"status": "error", "message": "Invalid server identifier (ID)."}, status=400)
                        return

            if sched_mode:
                mode_str = "Manual only" if self.server.cfg.speedtest.schedule_mode == "manual" else "Automated scheduled"
                msg_parts.append(f"Schedule mode: {mode_str}.")
            if sched_cron:
                user_lang = getattr(self.server.cfg.web, 'language', 'en')
                msg_parts.append(f"Interval: {get_cron_description(self.server.cfg.speedtest.schedule_cron, user_lang)}.")
            if thresh_pct is not None:
                msg_parts.append(f"Idle gate: < {self.server.cfg.speedtest.idle_threshold_percent:.1f}% network load.")

            msg = " ".join(msg_parts) if msg_parts else "Measurement settings saved successfully."
            from nmb.speed.anti_ban import ookla_schedule_warning
            sp = self.server.cfg.speedtest
            ookla_warning = ookla_schedule_warning(sp.automated_engine, sp.schedule_mode, sp.schedule_cron, sp.ookla_interval_min)
            if ookla_warning and ookla_warning["code"] == "ookla_rate_limit_risk":
                log.warning("schedule runs Ookla every %.0f min; Ookla limits tests and may block this box (safe: every %d min)",
                            ookla_warning["interval_min"], ookla_warning["safe_interval_min"])
                msg += " Warning: Ookla may block tests this frequent."
            save_config(self.server.cfg)

            # Record change to event table
            conn = db.connect()
            with db.tx(conn):
                conn.execute(
                    "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'speed', 'config_changed', ?)",
                    (db.now_ms(), msg)
                )
            conn.close()

            self._send_json({
                "status": "ok",
                "message": msg,
                "ookla_warning": ookla_warning,
                "schedule_mode": self.server.cfg.speedtest.schedule_mode,
                "schedule_cron": self.server.cfg.speedtest.schedule_cron,
                "automated_engine": self.server.cfg.speedtest.automated_engine,
                "ookla_interval_min": self.server.cfg.speedtest.ookla_interval_min,
                "rtr_interval_min": self.server.cfg.speedtest.rtr_interval_min,
                "cloudflare_interval_min": self.server.cfg.speedtest.cloudflare_interval_min,
                "fastcom_interval_min": self.server.cfg.speedtest.fastcom_interval_min,
                "iperf_auto": {
                    "duration": self.server.cfg.iperf.duration, "protocol": self.server.cfg.iperf.protocol,
                    "parallel": self.server.cfg.iperf.parallel,
                    "direction": "bidir" if self.server.cfg.iperf.bidir else self.server.cfg.iperf.auto_direction,
                    "extra_servers": self.server.cfg.iperf.extra_servers,
                },
                "idle_threshold_mode": self.server.cfg.speedtest.idle_threshold_mode,
                "idle_threshold_percent": self.server.cfg.speedtest.idle_threshold_percent,
                "idle_threshold_kbps": self.server.cfg.speedtest.idle_threshold_kbps,
                "scheduled_server": {
                    "id": self.server.cfg.speedtest.server_id,
                    "name": self.server.cfg.speedtest.server_name,
                    "host": self.server.cfg.speedtest.server_host,
                }
            })
            return

        # 1c. User-Agent Generation & Customization
        if path in ("/api/user-agent/fresh", "/api/user-agent/generate"):
            from nmb.common.user_agent import generate_fresh_user_agent
            cat = str(body_json.get("category", "headless")).strip()
            fresh_ua = generate_fresh_user_agent(cat)
            self._send_json({
                "status": "ok",
                "category": cat,
                "user_agent": fresh_ua,
            })
            return

        if path == "/api/user-agent":
            if "user_agent" in body_json:
                self.server.cfg.speedtest.user_agent = str(body_json["user_agent"]).strip()
            if "user_agent_mode" in body_json:
                self.server.cfg.speedtest.user_agent_mode = str(body_json["user_agent_mode"]).strip().lower()
            save_config(self.server.cfg)
            from nmb.common.user_agent import get_effective_user_agent
            self._send_json({
                "status": "ok",
                "message": "User-Agent configuration updated successfully.",
                "user_agent": self.server.cfg.speedtest.user_agent,
                "user_agent_mode": self.server.cfg.speedtest.user_agent_mode,
                "effective_user_agent": get_effective_user_agent(self.server.cfg),
            })
            return

        # 2. Sniffer Control
        if path == "/api/sniffer/control":
            action = body_json.get("action", "")
            iface = body_json.get("iface") or self.server.cfg.network.wan_interface
            sniffer = get_sniffer(iface)
            if action == "start":
                sniffer.start(iface)
            elif action == "stop":
                sniffer.stop()
            elif action == "clear":
                sniffer.clear()
            self._send_json(sniffer.get_stats())
            return

        # 3. Switch Mode
        if path == "/api/mode":
            mode = body_json.get("mode")
            if mode in ("auto", "standalone", "mode_a", "mode_b"):
                conn = db.connect()
                with db.tx(conn):
                    conn.execute(
                        "INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('override_mode', ?, ?)",
                        (mode, db.now_ms())
                    )
                conn.close()
                log.info("API trigger: set override_mode to %s", mode)
                self._send_json({"status": "ok", "override_mode": mode})
            else:
                self._send_json({"error": "invalid mode"}, status=400)
            return

        # 3. Update Config
        if path == "/api/config":
            self._handle_api_post_config(body_json)
            return

        # 3b. Guest Wi-Fi Receiver Connect & Disconnect API
        if path in ("/api/network/wifi/guest/connect", "/api/wifi/guest/connect"):
            ssid = str(body_json.get("ssid", "")).strip()
            password = str(body_json.get("password", "")).strip()
            guest_iface = str(body_json.get("interface") or getattr(self.server.cfg.guest_wifi, "interface", "wlan0")).strip()
            metric = int(body_json.get("metric") or getattr(self.server.cfg.guest_wifi, "metric", 600))
            save_it = bool(body_json.get("save", True))
            hidden = bool(body_json.get("hidden", False))
            bssid = str(body_json.get("bssid", "")).strip() or None

            if not ssid:
                self._send_json({"status": "error", "message": "SSID cannot be empty"}, status=400)
                return

            if save_it:
                self.server.cfg.guest_wifi.enabled = True
                self.server.cfg.guest_wifi.ssid = ssid
                self.server.cfg.guest_wifi.password = password
                self.server.cfg.guest_wifi.interface = guest_iface
                self.server.cfg.guest_wifi.metric = metric
                save_config(self.server.cfg)

            ok, msg = connect_guest_wifi(ssid=ssid, password=password, iface=guest_iface, metric=metric, hidden=hidden, bssid=bssid)
            status_data = get_guest_wifi_status(iface=guest_iface, wan_iface=self.server.cfg.network.wan_interface, cfg_guest=self.server.cfg.guest_wifi)
            self._send_json({
                "status": "ok" if ok else "error",
                "message": msg,
                "details": status_data,
            })
            return

        if path in ("/api/network/wifi/guest/disconnect", "/api/wifi/guest/disconnect"):
            guest_iface = str(body_json.get("interface") or getattr(self.server.cfg.guest_wifi, "interface", "wlan0")).strip()
            if body_json.get("disable"):
                self.server.cfg.guest_wifi.enabled = False
                save_config(self.server.cfg)
            ok, msg = disconnect_guest_wifi(iface=guest_iface)
            status_data = get_guest_wifi_status(iface=guest_iface, wan_iface=self.server.cfg.network.wan_interface, cfg_guest=self.server.cfg.guest_wifi)
            self._send_json({
                "status": "ok" if ok else "error",
                "message": msg,
                "details": status_data,
            })
            return

        if path in ("/api/network/wifi/guest/saved/delete", "/api/wifi/guest/saved/delete"):
            from nmb.netd.guest_wifi import delete_saved_wifi_connection
            target = str(body_json.get("name") or body_json.get("uuid") or "").strip()
            ok, msg = delete_saved_wifi_connection(target)
            self._send_json({"status": "ok" if ok else "error", "message": msg})
            return

        if path in ("/api/network/wifi/guest/saved/activate", "/api/wifi/guest/saved/activate"):
            from nmb.netd.guest_wifi import activate_saved_wifi_connection
            target = str(body_json.get("name") or body_json.get("uuid") or "").strip()
            ok, msg = activate_saved_wifi_connection(target)
            self._send_json({"status": "ok" if ok else "error", "message": msg})
            return

        # 4. Network MAC Management
        if path == "/api/network/mac":
            action = body_json.get("action", "set")
            wan_iface = self.server.cfg.network.wan_interface
            if action == "reset":
                ok = interfaces.reset_mac_to_factory(wan_iface)
                self.server.cfg.network.wan_mac = ""
                save_config(self.server.cfg)
                self._send_json({
                    "status": "ok" if ok else "error",
                    "current_mac": interfaces.get_mac_address(wan_iface),
                    "factory_mac": interfaces.get_factory_mac_address(wan_iface),
                })
                return
            elif action == "set":
                target_mac = body_json.get("mac", "").strip().lower()
                ok = interfaces.set_mac_address(wan_iface, target_mac)
                if ok:
                    self.server.cfg.network.wan_mac = target_mac
                    save_config(self.server.cfg)
                self._send_json({
                    "status": "ok" if ok else "error",
                    "current_mac": interfaces.get_mac_address(wan_iface),
                    "factory_mac": interfaces.get_factory_mac_address(wan_iface),
                })
                return
            else:
                self._send_json({
                    "status": "ok",
                    "current_mac": interfaces.get_mac_address(wan_iface),
                    "factory_mac": interfaces.get_factory_mac_address(wan_iface),
                })
                return

        # 5. DNS Management & Testing
        if path in ("/api/network/dns", "/api/dns", "/api/network/dns/test", "/api/network/dns/fallback", "/api/network/dns/restore"):
            action = body_json.get("action", "")
            if path.endswith("/test") or action == "test":
                target_domain = body_json.get("domain") or body_json.get("host")
                ok, ip_or_err, lat = dns.test_dns_resolution(target_domain)
                self._send_json({
                    "status": "ok" if ok else "error",
                    "can_resolve": ok,
                    "resolved_ip": ip_or_err if ok else None,
                    "ip": ip_or_err if ok else None,
                    "error": None if ok else ip_or_err,
                    "latency_ms": lat if ok else None,
                    "rtt_ms": lat if ok else None,
                    "nameservers": dns.get_current_nameservers(),
                })
                return
            elif path.endswith("/fallback") or action == "apply_fallback":
                custom_servers = body_json.get("servers")
                ok, msg = dns.ensure_dns_fallback(servers=custom_servers, force=True, iface=self.server.cfg.network.wan_interface)
                self._send_json({
                    "status": "ok" if ok else "error",
                    "message": msg,
                    "servers": dns.get_current_nameservers(),
                    "dns_status": dns.get_dns_status(),
                })
                return
            elif path.endswith("/restore") or action == "restore":
                ok, msg = dns.restore_system_dns(iface=self.server.cfg.network.wan_interface)
                self._send_json({
                    "status": "ok" if ok else "error",
                    "message": msg,
                    "dns_status": dns.get_dns_status(),
                })
                return
            else:
                self._send_json(dns.get_dns_status())
                return

        # 6. System reload & reboot
        if path in ("/api/system/reload", "/api/system/restart-services"):
            self._notify_daemon_reload()
            self._send_json({"status": "ok", "message": "System services reloaded successfully!"})
            return

        if path in ("/api/system/reboot", "/api/reboot"):
            log.warning("API triggered system reboot")
            def _reboot_delayed():
                time.sleep(1.0)
                subprocess.run(["reboot"], check=False)
            threading.Thread(target=_reboot_delayed, daemon=True, name="nmb-reboot").start()
            self._send_json({"status": "ok", "message": "Device reboot initiated. Please allow 1-2 minutes to restart."})
            return

        # 7. i18n Language Selection
        if path == "/api/i18n":
            new_lang = body_json.get("lang") or body_json.get("language")
            if new_lang and new_lang in TRANSLATIONS:
                self.server.cfg.web.language = new_lang
                save_config(self.server.cfg)
                self._send_json({
                    "status": "ok",
                    "lang": new_lang,
                    "translations": get_translations_for_lang(new_lang),
                    "message": f"Language changed to {new_lang}",
                })
            else:
                self._send_json({"status": "error", "message": f"Unsupported language: {new_lang}"}, status=400)
            return

        if path in ("/api/theme", "/api/system/theme"):
            new_theme = str(body_json.get("theme", "")).strip().lower()
            valid_themes = ("default", "prtd", "proudride", "amoled", "asuswrt", "asus_camo", "tp_gold", "mountain_hago", "ndefault")
            if new_theme in valid_themes:
                self.server.cfg.web.theme = new_theme
                save_config(self.server.cfg)
                self._send_json({
                    "status": "ok",
                    "theme": new_theme,
                    "message": f"Theme successfully changed and persisted to {new_theme}",
                })
            else:
                self._send_json({"status": "error", "message": f"Unsupported theme: {new_theme}"}, status=400)
            return

        # 8. Custom Admin Credentials
        if path in ("/api/system/credentials", "/api/credentials"):
            new_user = str(body_json.get("username", "")).strip()
            new_pass = str(body_json.get("password", "")).strip()
            if not new_user or not re.match(r"^[a-zA-Z0-9_.-]{1,64}$", new_user):
                self._send_json({"status": "error", "message": "Invalid username format (only letters, numbers, and _ . - allowed, max 64 characters)."}, status=400)
                return
            if len(new_pass) > 128:
                self._send_json({"status": "error", "message": "Password cannot exceed 128 characters."}, status=400)
                return
            self.server.cfg.web.admin_username = new_user
            if new_pass:
                self.server.cfg.web.admin_password = new_pass
            save_config(self.server.cfg)
            log.info("Admin credentials updated (user=%s)", new_user)
            self._send_json({
                "status": "ok",
                "admin_username": new_user,
                "message": "Admin credentials successfully updated and saved.",
            })
            return

        # 8.1 Memory Profile & Heap Trimming
        if path == "/api/system/tasks/kill":
            from nmb.common.tasks import kill_process
            try:
                pid = int(body_json.get("pid", 0))
                sig = int(body_json.get("signal", 15))
            except (TypeError, ValueError):
                self._send_json({"status": "error", "message": "A valid process ID is required."}, status=400)
                return
            res = kill_process(pid=pid, sig_num=sig)
            self._send_json(res)
            return

        if path == "/api/system/memory_profile":
            new_prof = str(body_json.get("memory_profile", body_json.get("profile", "auto"))).strip().lower()
            if new_prof in ("auto", "low", "standard", "performance"):
                self.server.cfg.system.memory_profile = new_prof
                save_config(self.server.cfg)
                from nmb.common.memory import get_effective_memory_profile, trim_process_memory
                trim_process_memory()
                eff = get_effective_memory_profile(new_prof)
                self._send_json({
                    "status": "ok",
                    "profile": new_prof,
                    "effective_profile": eff,
                    "message": f"Memory profile updated to {new_prof} ({eff})."
                })
            else:
                self._send_json({"status": "error", "message": "Invalid memory profile"}, status=400)
            return

        if path == "/api/system/trim_memory":
            from nmb.common.memory import get_available_ram_mb, get_total_ram_mb, trim_process_memory
            trim_process_memory()
            self._send_json({
                "status": "ok",
                "message": "Garbage collection executed and glibc heap arenas trimmed.",
                "ram_total_mb": get_total_ram_mb(),
                "ram_available_mb": get_available_ram_mb(),
            })
            return

        # 9. iPerf3 Client Run
        if path == "/api/iperf/run":
            target_host = str(body_json.get("host") or getattr(self.server.cfg.iperf, "target_host", "speedtest.serverius.net")).strip()
            if not target_host or target_host.startswith("-") or not re.match(r"^[a-zA-Z0-9.\-_:]+$", target_host):
                self._send_json({"status": "error", "message": "Invalid target host format."}, status=400)
                return
            try:
                port = max(1, min(65535, int(body_json.get("port") or getattr(self.server.cfg.iperf, "port", 5201))))
            except (ValueError, TypeError):
                port = 5201
            try:
                duration = max(1, min(60, int(body_json.get("duration") or getattr(self.server.cfg.iperf, "duration", 10))))
            except (ValueError, TypeError):
                duration = 10
            udp = bool(body_json.get("udp", getattr(self.server.cfg.iperf, "udp", False)))
            try:
                parallel = max(1, min(16, int(body_json.get("parallel") or getattr(self.server.cfg.iperf, "parallel", 1))))
            except (ValueError, TypeError):
                parallel = 1
            direction_req = str(body_json.get("direction", "")).lower().strip()
            bidir_req = bool(body_json.get("bidir", getattr(self.server.cfg.iperf, "bidir", False)))
            sequential = direction_req in ("seq", "sequential")
            is_bidir = not sequential and (bidir_req or (direction_req in ("bidir", "both", "duplex", "full-duplex")))

            if direction_req in ("down", "download", "reverse"):
                reverse = True
            elif direction_req in ("up", "upload"):
                reverse = False
            else:
                reverse = bool(body_json.get("reverse", getattr(self.server.cfg.iperf, "reverse", False)))

            if is_bidir:
                reverse = False

            target_bw = str(body_json.get("target_bandwidth") or getattr(self.server.cfg.iperf, "target_bandwidth", "100M")).strip()
            if target_bw and not re.match(r"^[0-9]+[kKmMgG]?$", target_bw):
                target_bw = "100M"

            if is_iperf_running():
                self._send_json({"status": "busy", "message": "iPerf test already in progress."}, status=409)
                return

            def _async_iperf_sequential():
                # Download (-R), a short pause, then upload; shown together as one result.
                from nmb.speed import iperf as iperf_mod
                try:
                    common = dict(host=target_host, port=port, duration=duration, udp=udp, parallel=parallel,
                                  bidir=False, target_bandwidth=target_bw)
                    down = run_iperf_client_test(reverse=True, direction="down", **common)
                    up = {}
                    if down.get("status") == "ok":
                        for wait in (3, 8):
                            time.sleep(wait)
                            up = run_iperf_client_test(reverse=False, direction="up", **common)
                            if up.get("status") == "ok":
                                break
                    merged = dict(down)
                    merged.update({
                        "is_bidirectional": True, "direction": "sequential",
                        "download_mbps": down.get("mbps"), "upload_mbps": up.get("mbps") if up.get("status") == "ok" else None,
                        "error": down.get("error") if down.get("status") != "ok" else (None if up.get("status") == "ok" else f"upload: {up.get('error')}"),
                    })
                    iperf_mod._latest_iperf_result = merged
                except Exception as e:
                    log.error("iPerf execution error: %s", e)

            def _async_iperf():
                if sequential:
                    _async_iperf_sequential()
                    return
                try:
                    run_iperf_client_test(
                        host=target_host,
                        port=port,
                        duration=duration,
                        udp=udp,
                        parallel=parallel,
                        reverse=reverse,
                        bidir=is_bidir,
                        direction="bidir" if is_bidir else ("down" if reverse else "up"),
                        target_bandwidth=target_bw,
                    )
                except Exception as e:
                    log.error("iPerf execution error: %s", e)

            threading.Thread(target=_async_iperf, daemon=True, name="nmb-iperf-worker").start()
            self._send_json({
                "status": "started",
                "message": f"iPerf test started against {target_host}:{port} ({duration}s)",
                "config": {
                    "host": target_host,
                    "port": port,
                    "duration": duration,
                    "udp": udp,
                    "parallel": parallel,
                    "reverse": reverse,
                    "bidir": is_bidir,
                    "direction": "sequential" if sequential else ("bidir" if is_bidir else ("down" if reverse else "up")),
                },
            })
            return

        # 10. iPerf3 Server Daemon Control
        if path in ("/api/iperf/server", "/api/iperf/server/toggle"):
            action = str(body_json.get("action", "toggle" if path.endswith("/toggle") else "status")).strip().lower()
            if action == "toggle":
                cur_status = get_iperf_server_status()
                action = "stop" if (cur_status.get("is_running") or cur_status.get("server_running")) else "start"
            try:
                port = max(1024, min(65535, int(body_json.get("port") or getattr(self.server.cfg.iperf, "server_port", 5201))))
            except (ValueError, TypeError):
                port = 5201
            if action == "start":
                res = start_iperf_server(port)
                ok = (res.get("status") == "ok")
                msg = res.get("message", "iPerf3 server started")
                self.server.cfg.iperf.server_enabled = ok
                self.server.cfg.iperf.server_port = port
                save_config(self.server.cfg)
                self._send_json({"status": "ok" if ok else "error", "message": msg, "server": get_iperf_server_status()})
            elif action == "stop":
                res = stop_iperf_server()
                ok = (res.get("status") == "ok")
                msg = res.get("message", "iPerf3 server stopped")
                self.server.cfg.iperf.server_enabled = False
                save_config(self.server.cfg)
                self._send_json({"status": "ok" if ok else "error", "message": msg, "server": get_iperf_server_status()})
            else:
                self._send_json({"status": "ok", "server": get_iperf_server_status()})
            return

        # 10b. Kernel Performance Tuning Apply
        if path == "/api/system/kernel-tuning/apply":
            from nmb.netd.kernel import apply_kernel_network_tuning, get_kernel_network_status
            if os.geteuid() == 0:
                res = apply_kernel_network_tuning()
                message = "Kernel network performance optimizations applied successfully."
            else:
                # nmb-netd runs as root and re-applies the tuning when it reloads.
                self._notify_daemon_reload()
                res = {"delegated_to": "nmb-netd"}
                message = "Kernel network tuning requested from nmb-netd."
            status_data = get_kernel_network_status()
            self._send_json({
                "status": "ok",
                "message": message,
                "details": res,
                "kernel_status": status_data,
            })
            return

        # 11. Traceroute Run
        if path == "/api/traceroute/run":
            target_host = str(body_json.get("host", "1.1.1.1")).strip() or "1.1.1.1"
            if not target_host or target_host.startswith("-") or not re.match(r"^[a-zA-Z0-9.\-_:]+$", target_host):
                self._send_json({"status": "error", "message": "Invalid target host format."}, status=400)
                return
            try:
                max_hops = max(1, min(64, int(body_json.get("max_hops", 30))))
            except (ValueError, TypeError):
                max_hops = 30
            method = str(body_json.get("method", "icmp")).lower().strip() or "icmp"
            ip_version = str(body_json.get("ip_version", "auto")).lower().strip() or "auto"

            if is_traceroute_running():
                self._send_json({"status": "busy", "message": "Traceroute already in progress."}, status=409)
                return

            def _async_traceroute():
                try:
                    run_traceroute(host=target_host, max_hops=max_hops, method=method, ip_version=ip_version)
                except Exception as e:
                    log.error("Traceroute execution error: %s", e)

            threading.Thread(target=_async_traceroute, daemon=True, name="nmb-traceroute-worker").start()
            self._send_json({
                "status": "started",
                "message": f"Traceroute started to {target_host} ({method.upper()}, max {max_hops} hops)",
                "target": target_host,
                "method": method,
            })
            return

        # 11a. Traceroute Stop
        if path == "/api/traceroute/stop":
            stop_res = stop_traceroute()
            self._send_json(stop_res)
            return

        # 11b. OONI Probe Censorship Test Run
        if path == "/api/speedtest/traffic-stop":
            self.server.cfg.speedtest.traffic_stop_enabled = bool(body_json.get("enabled"))
            save_config(self.server.cfg)
            self._send_json({"status": "ok", "enabled": self.server.cfg.speedtest.traffic_stop_enabled})
            return

        if path == "/api/ooni/toggle":
            enabled = bool(body_json.get("enabled"))
            self.server.cfg.ooni.enabled = enabled
            save_config(self.server.cfg)
            if not enabled and shutil.which("systemctl"):
                subprocess.run(["systemctl", "stop", "nmb-ooni.service"], capture_output=True, timeout=30, check=False)
            self._send_json({"status": "ok", "enabled": enabled})
            return

        if path == "/api/ooni/run":
            if not self.server.cfg.ooni.enabled:
                self._send_json({"status": "error", "message": "OONI Probe is switched off."}, status=403)
                return
            from nmb.probe.ooni import is_ooni_installed, is_ooni_running, run_ooni_test_async
            if not is_ooni_installed():
                self._send_json({"status": "error", "message": "OONI Probe is not installed on this system."}, status=501)
                return

            if is_ooni_running():
                self._send_json({"status": "busy", "message": "An OONI Probe test is already in progress."}, status=409)
                return

            test_type = str(body_json.get("test_type", "websites")).strip().lower()
            if test_type not in ("websites", "middlebox", "im", "circumvention", "all"):
                test_type = "websites"

            target_url = body_json.get("url") or body_json.get("target")
            upload = bool(body_json.get("upload", False))

            started = run_ooni_test_async(test_type=test_type, target_url=target_url, upload_results=upload)
            if started:
                self._send_json({
                    "status": "started",
                    "message": f"OONI Probe [{test_type}] test started",
                    "test_type": test_type,
                    "target": target_url or "Default Test List",
                })
            else:
                self._send_json({"status": "error", "message": "Failed to launch OONI Probe test."}, status=500)
            return

        # 12. Network Explorer Device Sweep
        if path in ("/api/network/devices/scan", "/api/explorer/scan"):
            scan_iface = body_json.get("iface")
            def _async_scan():
                try:
                    scan_network_devices(iface=scan_iface)
                except Exception as e:
                    log.error("Network scan error: %s", e)

            threading.Thread(target=_async_scan, daemon=True, name="nmb-net-scanner").start()
            self._send_json({
                "status": "started",
                "message": "LAN / Guest subnet ping sweep and device discovery started.",
            })
            return

        # Network Driver and Firmware Installation
        if path in ("/api/system/install_drivers", "/api/system/drivers/install"):
            pkg = body_json.get("package")
            if not isinstance(pkg, str) or not pkg.strip():
                self._send_json({"status": "error", "message": "A driver package name is required."}, status=400)
                return
            res = trigger_driver_install(pkg.strip())
            self._send_json(res)
            return

        # DNS Ad-Blocker (Pi-hole Engine) Actions
        if path == "/api/adblock/toggle":
            en = bool(body_json.get("enabled", True))
            res = set_adblock_enabled(en)
            self._send_json(res)
            return

        if path == "/api/adblock/disable":
            dur = int(body_json.get("duration", 0))
            res = disable_adblock_temporarily(dur)
            self._send_json(res)
            return

        if path == "/api/adblock/enable":
            res = enable_adblock()
            self._send_json(res)
            return

        if path in ("/api/adblock/update", "/api/adblock/gravity/update"):
            res = trigger_gravity_update()
            self._send_json(res)
            return

        if path == "/api/adblock/whitelist/add":
            dom = str(body_json.get("domain", "")).strip()
            ok = add_whitelist_entry(dom)
            self._send_json({"status": "ok" if ok else "error", "domain": dom})
            return

        if path == "/api/adblock/whitelist/remove":
            dom = str(body_json.get("domain", "")).strip()
            ok = remove_whitelist_entry(dom)
            self._send_json({"status": "ok" if ok else "not_found", "domain": dom})
            return

        if path == "/api/adblock/blacklist/add":
            dom = str(body_json.get("domain", "")).strip()
            ok = add_blacklist_entry(dom)
            self._send_json({"status": "ok" if ok else "error", "domain": dom})
            return

        if path == "/api/adblock/blacklist/remove":
            dom = str(body_json.get("domain", "")).strip()
            ok = remove_blacklist_entry(dom)
            self._send_json({"status": "ok" if ok else "not_found", "domain": dom})
            return

        if path == "/api/adblock/adlists/add":
            url = str(body_json.get("url", "")).strip()
            name = str(body_json.get("name", "")).strip()
            ok = add_adlist(url, name)
            self._send_json({"status": "ok" if ok else "error", "url": url})
            return

        if path == "/api/adblock/adlists/remove":
            url = str(body_json.get("url", "")).strip()
            ok = remove_adlist(url)
            self._send_json({"status": "ok" if ok else "not_found", "url": url})
            return

        if path == "/api/adblock/adlists/toggle":
            url = str(body_json.get("url", "")).strip()
            en = bool(body_json.get("enabled", True))
            ok = toggle_adlist(url, en)
            self._send_json({"status": "ok" if ok else "not_found", "url": url, "enabled": en})
            return

        if path == "/api/adblock/localdns/add":
            dom = str(body_json.get("domain", "")).strip()
            ip = str(body_json.get("ip", "")).strip()
            ok = add_local_dns_record(dom, ip)
            self._send_json({"status": "ok" if ok else "error", "domain": dom, "ip": ip})
            return

        if path == "/api/adblock/localdns/remove":
            dom = str(body_json.get("domain", "")).strip()
            ok = remove_local_dns_record(dom)
            self._send_json({"status": "ok" if ok else "not_found", "domain": dom})
            return

        if path == "/api/adblock/regex/add":
            pattern = str(body_json.get("pattern", "")).strip()
            kind = str(body_json.get("kind", "black")).strip()
            comment = str(body_json.get("comment", "")).strip()
            ok = add_regex_filter(pattern, kind=kind, comment=comment)
            self._send_json({"status": "ok" if ok else "error", "pattern": pattern, "kind": kind})
            return

        if path == "/api/adblock/regex/remove":
            pattern = str(body_json.get("pattern", "")).strip()
            kind = str(body_json.get("kind", "black")).strip()
            ok = remove_regex_filter(pattern, kind=kind)
            self._send_json({"status": "ok" if ok else "not_found", "pattern": pattern, "kind": kind})
            return

        if path == "/api/network/lan-topology":
            self._handle_lan_topology_post(body_json)
            return

        if path == "/api/system/purge":
            from nmb.common import purge as purge_mod
            if body_json.get("confirm") != "PURGE":
                self._send_json({"status": "error", "message": "Confirmation text PURGE is required."}, status=400)
                return
            categories = body_json.get("categories")
            if not isinstance(categories, list) or not set(categories) <= set(purge_mod.CATEGORIES) or not categories:
                self._send_json({"status": "error", "message": "Invalid categories."}, status=400)
                return
            result = purge_mod.purge(self.server.cfg, categories)
            result["status"] = "error" if result["errors"] else "ok"
            result["summary"] = purge_mod.get_purge_summary(self.server.cfg)
            self._send_json(result, status=500 if result["errors"] else 200)
            return

        if path == "/api/iperf/server/toggle":
            self._toggle_iperf_server()
            return

        # Interface Role Matrix Configuration
        if path in ("/api/system/interface_roles", "/api/system/ports"):
            cfg = self.server.cfg
            if "wan1" in body_json:
                cfg.network.wan_interface = str(body_json["wan1"]).strip()
            if "wan2" in body_json:
                cfg.network.wan2_interface = str(body_json["wan2"]).strip()
            if "wan_mode" in body_json:
                wm = str(body_json["wan_mode"]).strip().lower()
                if wm in ("single", "failover", "loadbalance"):
                    cfg.network.wan_mode = wm
            if "lan_ports" in body_json:
                lp = body_json["lan_ports"]
                if isinstance(lp, list):
                    cfg.network.lan_ports = [str(x).strip() for x in lp if str(x).strip()]
                else:
                    cfg.network.lan_ports = [p.strip() for p in str(lp).split(",") if p.strip()]
                if len(cfg.network.lan_ports) > 1:
                    cfg.network.lan_interface = "br-lan"
                elif len(cfg.network.lan_ports) == 1:
                    cfg.network.lan_interface = cfg.network.lan_ports[0]
            if "guest" in body_json or "wifi_main" in body_json:
                guest = str(body_json.get("guest", cfg.guest_wifi.interface) or "").strip()
                main = str(body_json.get("wifi_main", "") or "").strip()
                if guest and guest == main:
                    self._send_json({"status": "error", "message": f"{guest} cannot be the guest and the main Wi-Fi client at once."}, status=400)
                    return
                if "guest" in body_json:
                    if not guest:
                        cfg.guest_wifi.enabled = False   # no radio left for the guest client
                    cfg.guest_wifi.interface = guest
                if "wifi_main" in body_json:
                    cfg.wifi_uplink.interface = main or "auto"
            if "dmz" in body_json:
                cfg.network.dmz_interface = str(body_json["dmz"]).strip()
            if "measurement_interface" in body_json:
                cfg.network.measurement_interface = str(body_json["measurement_interface"]).strip()

            save_config(cfg)
            self._notify_daemon_reload()
            self._send_json({"status": "ok", "message": "Interface roles updated and applied successfully!"})
            return

        # 13. System Upgrade Trigger
        if path == "/api/system/updates/upgrade":
            res = trigger_system_upgrade()
            self._send_json(res)
            return

        # Automated Self-Healing & Stable Update Application Endpoints
        if path == "/api/heal/audit":
            self._send_json({
                "status": "ok",
                "audit": audit_system_health(),
            })
            return

        if path == "/api/heal/fix":
            tier = body_json.get("tier") if isinstance(body_json, dict) else None
            tier_val = int(tier) if tier in (1, 2, 3) else None
            res = auto_heal_all(force_tier=tier_val)
            self._send_json(res)
            return

        if path == "/api/heal/update/apply":
            ref = body_json.get("ref") if isinstance(body_json, dict) else None
            res = apply_stable_update(target_ref=ref)
            self._send_json(res)
            return

        # 14. Developer Runtime Log Level Control
        if path == "/api/dev/loglevel":
            new_level = body_json.get("level", "DEBUG")
            persist = bool(body_json.get("persist", True))
            from nmb.devlog import set_runtime_log_level
            try:
                res = set_runtime_log_level(new_level)
                if persist:
                    self.server.cfg.logging.level = res["new_level"]
                    save_config(self.server.cfg)
                self._send_json(res)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=400)
            return

        # 15. Clear Developer Log Buffer
        if path == "/api/dev/logs/clear":
            from nmb.devlog import get_dev_log_buffer
            get_dev_log_buffer().clear()
            self._send_json({"status": "ok", "message": "Developer log buffer cleared successfully"})
            return

        # 15b. Total Log Purge
        if path in ("/api/system/logs/purge", "/api/logs/purge"):
            if body_json.get("confirm") != "PURGE":
                self._send_json({"status": "error", "message": "Confirmation text PURGE is required."}, status=400)
                return
            from nmb.devlog import purge_all_logs
            inc_db = bool(body_json.get("include_db", True))
            inc_journal = bool(body_json.get("include_journal", True))
            result = purge_all_logs(include_database_events=inc_db, include_system_journal=inc_journal)
            self._send_json(result)
            return

        # Wi-Fi uplink (the box on the owner's Wi-Fi) and where speed tests run
        if path == "/api/storage/save":
            st = self.server.cfg.storage
            try:
                if "auto_cleanup" in body_json:
                    st.auto_cleanup = str(body_json["auto_cleanup"]).lower() in ("1", "true", "yes", "on")
                if "min_free_mb" in body_json:
                    st.min_free_mb = max(0, min(100_000, int(body_json["min_free_mb"])))
                if "keep_days" in body_json:
                    st.keep_days = max(1, min(3650, int(body_json["keep_days"])))
            except (TypeError, ValueError):
                self._send_json({"status": "error", "message": "min_free_mb and keep_days must be whole numbers."}, status=400)
                return
            save_config(self.server.cfg)
            self._notify_daemon_reload()
            self._send_json({"status": "ok", "auto_cleanup": st.auto_cleanup, "min_free_mb": st.min_free_mb, "keep_days": st.keep_days})
            return

        if path == "/api/storage/cleanup":
            from nmb.common import storage_guard
            res = storage_guard.run(self.server.cfg, force=True)
            res.setdefault("status", "ok")
            self._send_json(dict(res, result=res.get("status"), status="ok"))
            return

        if path == "/api/wifi-share/save":
            import ipaddress as _ip
            from nmb.netd import wifi_share, wifi_uplink
            ws = self.server.cfg.wifi_share
            lan = str(body_json.get("lan_interface", ws.lan_interface) or "").strip()
            from nmb.netd.interfaces import usb_tether_kind
            if not lan or not Path(f"/sys/class/net/{lan}").exists() or lan in wifi_uplink.wireless_interfaces() or usb_tether_kind(lan):
                self._send_json({"status": "error", "message": f"{lan or '?'} is not a wired port of this box."}, status=400)
                return
            addr = str(body_json.get("address", ws.address) or "").strip()
            try:
                net = _ip.ip_interface(addr)
                if net.version != 4 or net.network.prefixlen > 29 or not net.network.is_private or net.ip == net.network.network_address:
                    raise ValueError
            except ValueError:
                self._send_json({"status": "error", "message": f"{addr} is not a private IPv4 address with a /29 or larger network."}, status=400)
                return
            ws.enabled, ws.lan_interface, ws.address = bool(body_json.get("enabled", ws.enabled)), lan, str(net)
            save_config(self.server.cfg)
            self._notify_daemon_reload()
            st = wifi_share.status(self.server.cfg)
            st.update(status="ok", message="Saved. The box checks the port within a minute.")
            self._send_json(st)
            return

        if path in ("/api/wifi-uplink/save", "/api/wifi-uplink/connect", "/api/wifi-uplink/disconnect"):
            from nmb.netd import wifi_uplink
            wu = self.server.cfg.wifi_uplink
            if path.endswith("/save"):
                link = str(body_json.get("measurement_link", self.server.cfg.network.measurement_link)).lower()
                if link in wifi_uplink.LINKS:
                    self.server.cfg.network.measurement_link = link
                if "ssid" in body_json:
                    wu.ssid = str(body_json["ssid"]).strip()[:64]
                if str(body_json.get("password", "")):
                    wu.password = str(body_json["password"])[:128]   # empty keeps the saved one
                iface = str(body_json.get("interface", wu.interface)).strip()
                if iface == "auto" or iface in wifi_uplink.wireless_interfaces():
                    wu.interface = iface
                wu.hidden = bool(body_json.get("hidden", wu.hidden))
                wu.enabled = bool(body_json.get("enabled", wu.enabled)) and bool(wu.ssid)
                save_config(self.server.cfg)
                ok, msg = True, "Saved."
                if wu.enabled and body_json.get("connect", True):
                    ok, msg = wifi_uplink.connect(self.server.cfg)
                elif not wu.enabled:
                    wifi_uplink.disconnect(self.server.cfg)
            elif path.endswith("/connect"):
                ok, msg = wifi_uplink.connect(self.server.cfg)
            else:
                ok, msg = wifi_uplink.disconnect(self.server.cfg)
            st = wifi_uplink.status(self.server.cfg)
            st.update(status="ok" if ok else "error", message=msg)
            self._send_json(st, status=200 if ok else 400)
            return

        if path in ("/api/usb-uplink/save", "/api/usb-uplink/disconnect"):
            from nmb.netd import usb_uplink, wifi_uplink
            uu = self.server.cfg.usb_uplink
            if path.endswith("/save"):
                link = str(body_json.get("measurement_link", self.server.cfg.network.measurement_link)).lower()
                if link in wifi_uplink.LINKS:
                    self.server.cfg.network.measurement_link = link
                iface = str(body_json.get("interface", uu.interface)).strip()
                if iface == "auto" or iface in usb_uplink.tether_interfaces():
                    uu.interface = iface
                if "daily_limit_mb" in body_json:
                    try:
                        uu.daily_limit_mb = max(0, min(1_000_000, int(body_json["daily_limit_mb"])))
                    except (TypeError, ValueError):
                        self._send_json({"status": "error", "message": "The daily limit must be a whole number of MB (0 = no limit)."}, status=400)
                        return
                uu.enabled = bool(body_json.get("enabled", uu.enabled))
                save_config(self.server.cfg)
                self._notify_daemon_reload()
                ok, msg = True, "Saved."
                if uu.enabled:
                    ok, msg = usb_uplink.connect(self.server.cfg)
                else:
                    usb_uplink.disconnect(self.server.cfg)
            else:
                self.server.cfg.usb_uplink.enabled = False
                if self.server.cfg.network.measurement_link == "usb":
                    self.server.cfg.network.measurement_link = "auto"
                save_config(self.server.cfg)
                self._notify_daemon_reload()
                ok, msg = usb_uplink.disconnect(self.server.cfg)
            st = usb_uplink.status(self.server.cfg)
            st.update(status="ok" if ok else "error", message=msg)
            self._send_json(st, status=200 if ok else 400)
            return

        # Central collector (opt-in): settings and "send now"
        if path == "/api/collector/save":
            from nmb.collector import client as collector_client
            co = self.server.cfg.collector
            url = str(body_json.get("url", co.url)).strip()
            if url and not url.startswith(("https://", "http://")):
                self._send_json({"status": "error", "message": "The collector address must start with https:// or http://."}, status=400)
                return
            co.url = url[:300]
            token = str(body_json.get("token", "")).strip()
            if token:  # an empty field keeps the saved token
                co.token = token[:200]
            co.case_id = str(body_json.get("case_id", co.case_id)).strip()[:80]
            try:
                co.interval_min = max(5, min(1440, int(body_json.get("interval_min", co.interval_min))))
            except (TypeError, ValueError):
                pass
            co.share_diagnostics = bool(body_json.get("share_diagnostics", co.share_diagnostics))
            co.allow_remote_control = bool(body_json.get("allow_remote_control", co.allow_remote_control))
            co.enabled = bool(body_json.get("enabled", co.enabled)) and bool(co.url and co.token)
            save_config(self.server.cfg)
            collector_client.start(lambda: self.server.cfg)
            collector_client.wake()
            self._send_json({"status": "ok", **collector_client.get_status(self.server.cfg)})
            return

        if path == "/api/collector/send":
            from nmb.collector import client as collector_client
            res = collector_client.send_now(self.server.cfg)
            self._send_json({"status": "ok" if res.get("ok") else "error", **res})
            return

        # 16. DynDNS (DuckDNS / dynv6) Settings & Update
        if path in ("/api/duckdns/save", "/api/dyndns/save"):
            from nmb.netd.duckdns import start_duckdns_service, stop_duckdns_service, update_duckdns, get_duckdns_status, wake_duckdns_daemon, detect_public_ipv6
            enabled = bool(body_json.get("enabled", False))
            provider = str(body_json.get("provider", getattr(self.server.cfg.duckdns, "provider", "duckdns"))).strip().lower()
            if provider not in ("duckdns", "dynv6"):
                provider = "duckdns"
            domain = str(body_json.get("domain", "")).strip()
            token = str(body_json.get("token", "")).strip()
            raw_interval = body_json.get("update_interval_min", body_json.get("interval_min", 10))
            try:
                interval = max(1, int(raw_interval))
            except (ValueError, TypeError):
                interval = 10
            custom_ip = str(body_json.get("custom_ip", "")).strip()
            custom_ipv6 = str(body_json.get("custom_ipv6", getattr(self.server.cfg.duckdns, "custom_ipv6", ""))).strip()
            ipv6_mode = str(body_json.get("ipv6_mode", getattr(self.server.cfg.duckdns, "ipv6_mode", "auto"))).strip().lower()
            if ipv6_mode not in ("auto", "custom", "none"):
                ipv6_mode = "auto"

            self.server.cfg.duckdns.enabled = enabled
            self.server.cfg.duckdns.provider = provider
            self.server.cfg.duckdns.domain = domain
            if token:
                self.server.cfg.duckdns.token = token
            self.server.cfg.duckdns.update_interval_min = interval
            self.server.cfg.duckdns.custom_ip = custom_ip
            self.server.cfg.duckdns.custom_ipv6 = custom_ipv6
            self.server.cfg.duckdns.ipv6_mode = ipv6_mode
            save_config(self.server.cfg)

            detail = None
            if enabled:
                if self.server.cfg.duckdns.token and domain:
                    detected_v6 = None
                    if custom_ipv6:
                        detected_v6 = custom_ipv6
                    elif ipv6_mode != "none":
                        detected_v6 = detect_public_ipv6(timeout=2.0)
                        if not detected_v6:
                            try:
                                from nmb.netd.wireguard import get_device_addresses
                                _, v6_addrs = get_device_addresses()
                                if v6_addrs:
                                    detected_v6 = v6_addrs[0][1]
                            except Exception:
                                log.debug("suppressed exception", exc_info=True)
                    detail = update_duckdns(
                        domain=domain,
                        token=self.server.cfg.duckdns.token,
                        ip=custom_ip or None,
                        ipv6=detected_v6,
                        provider=provider,
                        ipv6_mode=ipv6_mode,
                    )
                start_duckdns_service(lambda: self.server.cfg)
                wake_duckdns_daemon()
                msg = f"{'dynv6' if provider == 'dynv6' else 'DuckDNS'} settings saved. Sync interval set to {interval} minute(s)."
            else:
                stop_duckdns_service()
                msg = "DynDNS updater disabled and configuration saved."

            st = get_duckdns_status(self.server.cfg)
            self._send_json({
                "status": "ok",
                "message": msg,
                "saved_config": {
                    "enabled": enabled,
                    "provider": provider,
                    "domain": domain,
                    "update_interval_min": interval,
                    "interval_min": interval,
                    "custom_ip": custom_ip,
                    "custom_ipv6": custom_ipv6,
                    "ipv6_mode": ipv6_mode,
                    "token_set": bool(self.server.cfg.duckdns.token),
                },
                "status_data": st,
                "detail": detail,
            })
            return

        if path in ("/api/duckdns/update", "/api/dyndns/update"):
            from nmb.netd.duckdns import update_duckdns, get_duckdns_status, wake_duckdns_daemon, detect_public_ipv6
            d_cfg = self.server.cfg.duckdns
            if not d_cfg.domain or not d_cfg.token:
                self._send_json({"status": "error", "message": "DynDNS domain/zone and token are not configured."}, status=400)
                return
            prov = getattr(d_cfg, "provider", "duckdns") or "duckdns"
            custom_v6 = getattr(d_cfg, "custom_ipv6", "") or ""
            ipv6_mode = getattr(d_cfg, "ipv6_mode", "auto") or "auto"
            detected_v6 = None
            if custom_v6:
                detected_v6 = custom_v6
            elif ipv6_mode != "none":
                detected_v6 = detect_public_ipv6(timeout=2.0)
                if not detected_v6:
                    try:
                        from nmb.netd.wireguard import get_device_addresses
                        _, v6_addrs = get_device_addresses()
                        if v6_addrs:
                            detected_v6 = v6_addrs[0][1]
                    except Exception:
                        log.debug("suppressed exception", exc_info=True)
            res = update_duckdns(
                domain=d_cfg.domain,
                token=d_cfg.token,
                ip=d_cfg.custom_ip or None,
                ipv6=detected_v6,
                provider=prov,
                ipv6_mode=ipv6_mode,
            )
            wake_duckdns_daemon()
            res["status_data"] = get_duckdns_status(self.server.cfg)
            self._send_json(res)
            return

        # 17. WireGuard VPN Server Management
        if path == "/api/wireguard/save":
            self.server.cfg.wireguard.port = int(body_json.get("port", 51820))
            self.server.cfg.wireguard.subnet = str(body_json.get("subnet", "10.8.0.1/24")).strip()
            if "subnet_ipv6" in body_json:
                self.server.cfg.wireguard.subnet_ipv6 = str(body_json.get("subnet_ipv6", "fd42:42:42::1/64")).strip()
            if "dns" in body_json:
                self.server.cfg.wireguard.dns = str(body_json.get("dns", "")).strip()
            self.server.cfg.wireguard.public_endpoint = str(body_json.get("public_endpoint", body_json.get("endpoint", ""))).strip()
            save_config(self.server.cfg)
            from nmb.netd.wireguard import apply_configuration
            ok, msg = apply_configuration(
                port=self.server.cfg.wireguard.port,
                subnet=self.server.cfg.wireguard.subnet,
                subnet_ipv6=self.server.cfg.wireguard.subnet_ipv6,
            )
            self._send_json({"status": "ok" if ok else "error", "message": msg})
            return

        if path == "/api/wireguard/peer/add":
            from nmb.netd.wireguard import add_peer
            peer_name = str(body_json.get("name", "")).strip()
            client_ip = str(body_json.get("client_ip", "")).strip() or None
            client_ipv6 = str(body_json.get("client_ipv6", "")).strip() or None
            res = add_peer(
                peer_name,
                client_ip=client_ip,
                client_ipv6=client_ipv6,
                port=self.server.cfg.wireguard.port,
                subnet=self.server.cfg.wireguard.subnet,
                subnet_ipv6=self.server.cfg.wireguard.subnet_ipv6,
            )
            self._send_json(res)
            return

        if path == "/api/wireguard/peer/delete":
            from nmb.netd.wireguard import delete_peer
            peer_id = str(body_json.get("id") or body_json.get("name", "")).strip()
            ok = delete_peer(peer_id)
            self._send_json({"status": "ok" if ok else "error", "message": f"Peer '{peer_id}' deleted." if ok else "Peer not found."})
            return

        if path == "/api/wireguard/toggle":
            from nmb.netd.wireguard import apply_configuration, run_helper
            enabled = bool(body_json.get("enabled") if "enabled" in body_json else body_json.get("enable", True))
            self.server.cfg.wireguard.enabled = enabled
            save_config(self.server.cfg)
            if enabled:
                ok, msg = apply_configuration(
                    port=self.server.cfg.wireguard.port,
                    subnet=self.server.cfg.wireguard.subnet,
                    subnet_ipv6=self.server.cfg.wireguard.subnet_ipv6,
                )
                self._send_json({"status": "ok" if ok else "error", "message": msg})
            else:
                run_helper("wireguard-stop")
                self._send_json({"status": "ok", "message": "WireGuard server stopped."})
            return

        # 18. OpenVPN Server Management
        if path == "/api/openvpn/save":
            self.server.cfg.openvpn.proto = str(body_json.get("proto", "udp")).strip().lower()
            self.server.cfg.openvpn.port = int(body_json.get("port", 1194))
            self.server.cfg.openvpn.subnet = str(body_json.get("subnet", "10.9.0.0")).strip()
            if "subnet_ipv6" in body_json:
                self.server.cfg.openvpn.subnet_ipv6 = str(body_json.get("subnet_ipv6", "fd42:42:43::/64")).strip()
            if "dns" in body_json:
                self.server.cfg.openvpn.dns = str(body_json.get("dns", "")).strip()
            self.server.cfg.openvpn.public_endpoint = str(body_json.get("public_endpoint", body_json.get("endpoint", ""))).strip()
            save_config(self.server.cfg)
            from nmb.netd.openvpn import apply_configuration
            ok, msg = apply_configuration(
                proto=self.server.cfg.openvpn.proto,
                port=self.server.cfg.openvpn.port,
                subnet=self.server.cfg.openvpn.subnet,
                subnet_ipv6=self.server.cfg.openvpn.subnet_ipv6,
                dns_servers=self.server.cfg.openvpn.dns,
            )
            self._send_json({"status": "ok" if ok else "error", "message": msg})
            return

        if path == "/api/openvpn/client/add":
            from nmb.netd.openvpn import add_client
            client_name = str(body_json.get("name", "")).strip()
            res = add_client(client_name)
            self._send_json(res)
            return

        if path == "/api/openvpn/client/delete":
            from nmb.netd.openvpn import delete_client
            client_name = str(body_json.get("name", "")).strip()
            ok = delete_client(client_name)
            self._send_json({"status": "ok" if ok else "error", "message": f"Client '{client_name}' removed." if ok else "Client not found."})
            return

        if path == "/api/openvpn/toggle":
            from nmb.netd.openvpn import apply_configuration, run_helper
            enabled = bool(body_json.get("enabled") if "enabled" in body_json else body_json.get("enable", True))
            self.server.cfg.openvpn.enabled = enabled
            save_config(self.server.cfg)
            if enabled:
                ok, msg = apply_configuration(
                    proto=self.server.cfg.openvpn.proto,
                    port=self.server.cfg.openvpn.port,
                    subnet=self.server.cfg.openvpn.subnet,
                    subnet_ipv6=self.server.cfg.openvpn.subnet_ipv6,
                    dns_servers=self.server.cfg.openvpn.dns,
                )
                self._send_json({"status": "ok" if ok else "error", "message": msg})
            else:
                run_helper("openvpn-stop")
                self._send_json({"status": "ok", "message": "OpenVPN server stopped."})
            return

        # 19. HTTPS Proxy Server Management
        if path == "/api/proxy/config":
            from nmb.netd.proxy import start_proxy_server, stop_proxy_server
            enabled = bool(body_json.get("enabled") if "enabled" in body_json else body_json.get("enable", False))
            port = int(body_json.get("port", 8443))
            auth_enabled = bool(body_json.get("auth_enabled", False))
            username = str(body_json.get("username", "")).strip()
            password = str(body_json.get("password", "")).strip()
            tls_enabled = bool(body_json.get("tls_enabled", False))
            listen_ipv6 = bool(body_json.get("listen_ipv6", True))
            proxy_dns = str(body_json.get("dns", "")).strip()
            if enabled and not (auth_enabled and username and password):
                self._send_json({"status": "error", "message": "The proxy requires a username and password."}, status=400)
                return

            self.server.cfg.proxy.enabled = enabled
            self.server.cfg.proxy.port = port
            self.server.cfg.proxy.auth_enabled = auth_enabled
            self.server.cfg.proxy.username = username
            if password:
                self.server.cfg.proxy.password = password
            self.server.cfg.proxy.tls_enabled = tls_enabled
            self.server.cfg.proxy.listen_ipv6 = listen_ipv6
            if proxy_dns or "dns" in body_json:
                self.server.cfg.proxy.dns = proxy_dns
            save_config(self.server.cfg)

            if enabled:
                ok, msg = start_proxy_server(
                    port=port,
                    auth_enabled=auth_enabled,
                    username=username,
                    password=self.server.cfg.proxy.password,
                    tls_enabled=tls_enabled,
                    tls_cert=self.server.cfg.web.tls_cert if tls_enabled else "",
                    tls_key=self.server.cfg.web.tls_key if tls_enabled else "",
                    listen_ipv6=listen_ipv6,
                    dns=self.server.cfg.proxy.dns,
                )
                self._send_json({"status": "ok" if ok else "error", "message": msg})
            else:
                stop_proxy_server()
                self._send_json({"status": "ok", "message": "HTTPS Proxy Server stopped."})
            return

        if path == "/api/proxy/start":
            from nmb.netd.proxy import start_proxy_server
            p_cfg = self.server.cfg.proxy
            if not (p_cfg.auth_enabled and p_cfg.username and p_cfg.password):
                self._send_json({"status": "error", "message": "The proxy requires a username and password."}, status=400)
                return
            ok, msg = start_proxy_server(
                port=p_cfg.port,
                auth_enabled=p_cfg.auth_enabled,
                username=p_cfg.username,
                password=p_cfg.password,
                tls_enabled=p_cfg.tls_enabled,
                tls_cert=self.server.cfg.web.tls_cert if p_cfg.tls_enabled else "",
                tls_key=self.server.cfg.web.tls_key if p_cfg.tls_enabled else "",
                listen_ipv6=p_cfg.listen_ipv6,
                dns=p_cfg.dns,
            )
            self._send_json({"status": "ok" if ok else "error", "message": msg})
            return
            return

        if path == "/api/proxy/stop":
            from nmb.netd.proxy import stop_proxy_server
            stop_proxy_server()
            self._send_json({"status": "ok", "message": "HTTPS Proxy Server stopped."})
            return

        # 18c. Tailscale Mesh Remote Access Management
        if path in ("/api/tailscale/up", "/api/network/tailscale/up"):
            from nmb.netd.tailscale import tailscale_up
            auth_key = str(body_json.get("auth_key", "")).strip()
            hostname = str(body_json.get("hostname", "")).strip() or getattr(self.server.cfg.tailscale, "hostname", "networkmeasurebox")
            if auth_key and not auth_key.startswith("***") and "..." not in auth_key:
                self.server.cfg.tailscale.auth_key = auth_key
            if hostname:
                self.server.cfg.tailscale.hostname = hostname
            self.server.cfg.tailscale.enabled = True
            save_config(self.server.cfg)
            res = tailscale_up(
                auth_key=getattr(self.server.cfg.tailscale, "auth_key", ""),
                hostname=self.server.cfg.tailscale.hostname,
                accept_routes=False,
                advertise_exit_node=False,
                accept_dns=False,
            )
            self._send_json(res)
            return

        if path in ("/api/tailscale/down", "/api/network/tailscale/down"):
            from nmb.netd.tailscale import tailscale_down
            self.server.cfg.tailscale.enabled = False
            save_config(self.server.cfg)
            res = tailscale_down()
            self._send_json(res)
            return

        if path in ("/api/tailscale/logout", "/api/network/tailscale/logout"):
            from nmb.netd.tailscale import tailscale_logout
            self.server.cfg.tailscale.enabled = False
            self.server.cfg.tailscale.auth_key = ""
            save_config(self.server.cfg)
            res = tailscale_logout()
            self._send_json(res)
            return

        if path in ("/api/tailscale/save", "/api/network/tailscale/save"):
            auth_key = str(body_json.get("auth_key", "")).strip()
            hostname = str(body_json.get("hostname", "networkmeasurebox")).strip()
            if auth_key and not auth_key.startswith("***") and "..." not in auth_key:
                self.server.cfg.tailscale.auth_key = auth_key
            if hostname:
                self.server.cfg.tailscale.hostname = hostname
            if "enabled" in body_json:
                self.server.cfg.tailscale.enabled = bool(body_json.get("enabled"))
            save_config(self.server.cfg)
            self._send_json({"status": "ok", "message": "Tailscale configuration saved."})
            return

        # 18d. Telegram Chatbot & Alert Management
        if path == "/api/telegram/save":
            enabled = bool(body_json.get("enabled", False))
            clear_token = bool(body_json.get("clear_token", False))
            token_in = str(body_json.get("token") or body_json.get("bot_token") or "").strip()
            if clear_token:
                self.server.cfg.telegram.token = ""
            elif token_in and not token_in.startswith("***") and "..." not in token_in:
                self.server.cfg.telegram.token = token_in
            # If token_in is empty and clear_token is False, preserve existing self.server.cfg.telegram.token

            chat_ids_raw = body_json.get("allowed_chat_ids", body_json.get("chat_ids", []))
            parsed_chats = []
            if isinstance(chat_ids_raw, str):
                for c in chat_ids_raw.replace(";", ",").split(","):
                    c_str = c.strip()
                    if c_str and (c_str.isdigit() or (c_str.startswith("-") and c_str[1:].isdigit())):
                        parsed_chats.append(int(c_str))
            elif isinstance(chat_ids_raw, (list, tuple)):
                for c in chat_ids_raw:
                    try:
                        c_str = str(c).strip()
                        if c_str and (c_str.isdigit() or (c_str.startswith("-") and c_str[1:].isdigit())):
                            parsed_chats.append(int(c_str))
                    except Exception:
                        log.debug("suppressed exception", exc_info=True)
            self.server.cfg.telegram.allowed_chat_ids = parsed_chats
            
            loss_thresh = body_json.get("loss_threshold_pct", body_json.get("alert_loss_threshold_pct", 5.0))
            self.server.cfg.telegram.alert_loss_threshold_pct = float(loss_thresh)
            
            lat_thresh = body_json.get("latency_threshold_ms", body_json.get("alert_latency_threshold_ms", 100.0))
            self.server.cfg.telegram.alert_latency_threshold_ms = float(lat_thresh)
            
            if "alert_on_loss" in body_json:
                self.server.cfg.telegram.alert_on_loss = bool(body_json.get("alert_on_loss"))
            if "alert_on_latency" in body_json:
                self.server.cfg.telegram.alert_on_latency = bool(body_json.get("alert_on_latency"))
            self.server.cfg.telegram.enabled = enabled
            save_config(self.server.cfg)

            svc_started = False
            svc_err = ""
            if shutil.which("systemctl"):
                try:
                    if enabled and self.server.cfg.telegram.token:
                        subprocess.run(["systemctl", "reset-failed", "nmb-telegram"], check=False, timeout=5)
                        subprocess.run(["systemctl", "enable", "--now", "nmb-telegram"], check=False, timeout=8)
                        r = subprocess.run(["systemctl", "restart", "nmb-telegram"], capture_output=True, text=True, check=False, timeout=15)
                        if r.returncode == 0:
                            svc_started = True
                        else:
                            svc_err = r.stderr.strip() or r.stdout.strip()
                    else:
                        subprocess.run(["systemctl", "stop", "nmb-telegram"], check=False, timeout=8)
                        subprocess.run(["systemctl", "disable", "nmb-telegram"], check=False, timeout=8)
                except Exception as e:
                    svc_err = str(e)
                    log.warning("error managing nmb-telegram service: %s", e)

            self._send_json({
                "status": "ok",
                "ok": True,
                "message": "Telegram configuration saved.",
                "service_started": svc_started,
                "service_error": svc_err,
            })
            return

        if path == "/api/telegram/test":
            from nmb.bot.client import TelegramClient
            token = getattr(self.server.cfg.telegram, "token", "")
            chats = getattr(self.server.cfg.telegram, "allowed_chat_ids", [])
            req_chat = str(body_json.get("chat_id", "")).strip()
            if req_chat and (req_chat.isdigit() or (req_chat.startswith("-") and req_chat[1:].isdigit())):
                target_chats = [int(req_chat)]
            elif chats:
                target_chats = chats
            else:
                target_chats = []

            if not token:
                self._send_json({"status": "error", "ok": False, "error": "Telegram Bot Token is not configured.", "message": "Telegram Bot Token is not configured."}, status=400)
                return
            if not target_chats:
                self._send_json({"status": "error", "ok": False, "error": "No allowed Chat ID configured. Please enter your Chat ID.", "message": "No Chat IDs configured to receive test message."}, status=400)
                return

            client = TelegramClient(token)
            me = client.get_me()
            if not me:
                self._send_json({"status": "error", "ok": False, "error": "Invalid Bot Token or Telegram API unreachable.", "message": "Invalid Bot Token or Telegram API unreachable."}, status=400)
                return

            box_id = getattr(self.server.cfg.system, "box_id", "nmb-01")
            import datetime
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            wan_iface = getattr(self.server.cfg.network, "wan_interface", "eth0")
            wan_ips = interfaces.get_ip_addresses(wan_iface) if hasattr(interfaces, "get_ip_addresses") else []
            wan_ip = wan_ips[0] if wan_ips else (interfaces.get_public_ip() or "N/A")
            test_msg = (
                f"🔔 <b>NetworkMeasureBox Test Notification</b>\n\n"
                f"✅ <i>Telegram chatbot integration is fully operational!</i>\n"
                f"📦 <b>Device ID:</b> <code>{box_id}</code>\n"
                f"🌐 <b>WAN IP:</b> <code>{wan_ip}</code>\n"
                f"⏱️ <b>Timestamp:</b> {now_str}\n\n"
                f"Send <code>/help</code> or <code>/status</code> to interact with the bot."
            )
            success_cnt = 0
            errors = []
            for chat_id in target_chats:
                ok = client.send_message(chat_id, test_msg)
                if ok:
                    success_cnt += 1
                else:
                    errors.append(str(chat_id))
            if success_cnt > 0:
                self._send_json({"status": "ok", "ok": True, "message": f"Test message delivered to {success_cnt}/{len(target_chats)} chat(s).", "delivered": success_cnt})
            else:
                self._send_json({"status": "error", "ok": False, "error": f"Failed to deliver the message ({', '.join(errors)}). Open a private chat with your bot and send /start in Telegram.", "message": f"Failed to deliver message to chats ({', '.join(errors)})."}, status=400)
            return

        if path == "/api/telegram/service":
            action = str(body_json.get("action", "restart")).strip().lower()
            if action not in ("start", "stop", "restart"):
                action = "restart"
            token = getattr(self.server.cfg.telegram, "token", "")
            if action in ("start", "restart") and not token:
                self._send_json({
                    "status": "error",
                    "ok": False,
                    "error": "Telegram Bot Token is not configured. Enter and save the token before starting.",
                    "message": "Telegram Bot Token is not configured."
                }, status=400)
                return

            err_msg = ""
            if shutil.which("systemctl"):
                try:
                    subprocess.run(["systemctl", "reset-failed", "nmb-telegram"], check=False, timeout=5)
                    r = subprocess.run(["systemctl", action, "nmb-telegram"], capture_output=True, text=True, check=False, timeout=15)
                    if r.returncode != 0:
                        err_msg = r.stderr.strip() or r.stdout.strip()
                except Exception as e:
                    self._send_json({"status": "error", "ok": False, "error": str(e), "message": str(e)}, status=500)
                    return
            if err_msg:
                self._send_json({
                    "status": "error",
                    "ok": False,
                    "error": f"Could not {action} the service: {err_msg}",
                    "message": f"systemctl {action} failed: {err_msg}"
                }, status=500)
                return

            self._send_json({"status": "ok", "ok": True, "message": f"Telegram service command '{action}' executed."})
            return

        # 19. Backup & Disaster Recovery POST APIs
        if path == "/api/backup/create":
            from nmb.common.backup import create_backup
            b_type = str(body_json.get("type", "full")).strip().lower()
            comment = str(body_json.get("comment", "")).strip()
            ok, p, mf = create_backup(backup_type=b_type, comment=comment)
            if ok:
                self._send_json({
                    "status": "ok",
                    "filename": p.name,
                    "download_url": f"/api/backup/download?file={p.name}",
                    "manifest": mf,
                    "message": f"Backup '{p.name}' created successfully.",
                })
            else:
                self._send_json({"status": "error", "message": mf.get("error", "Failed to create backup.")}, status=500)
            return

        if path == "/api/backup/restore":
            from nmb.common.backup import restore_backup, BACKUP_DIR
            filename = os.path.basename(str(body_json.get("filename", body_json.get("file", ""))).strip())
            restore_db = bool(body_json.get("restore_db", True))
            restore_vpn = bool(body_json.get("restore_vpn", True))
            target_path = BACKUP_DIR / filename
            if not filename or not target_path.exists():
                self._send_json({"status": "error", "message": f"Backup file '{filename}' not found."}, status=404)
                return
            ok, msg = restore_backup(target_path, restore_db=restore_db, restore_vpn=restore_vpn, create_safety_snapshot=True)
            if ok:
                self.server.cfg = load_config()
                if getattr(self.server, "scheduler", None):
                    self.server.scheduler.cfg = self.server.cfg
                self._send_json({"status": "ok", "message": msg})
            else:
                self._send_json({"status": "error", "message": msg}, status=500)
            return

        if path == "/api/backup/delete":
            from nmb.common.backup import delete_backup
            filename = str(body_json.get("filename", body_json.get("file", ""))).strip()
            ok, msg = delete_backup(filename)
            self._send_json({"status": "ok" if ok else "error", "message": msg})
            return

        if path in ("/api/backup/reset", "/api/factory-reset", "/api/system/factory-reset"):
            if body_json.get("confirm") != "RESET":
                self._send_json({"status": "error", "message": "Confirmation text RESET is required."}, status=400)
                return
            from nmb.common.backup import factory_reset
            keep_measurements = bool(body_json.get("keep_measurements", False))
            ok, msg = factory_reset(keep_measurements=keep_measurements)
            if ok:
                self.server.cfg = load_config()
                if getattr(self.server, "scheduler", None):
                    self.server.scheduler.cfg = self.server.cfg
                self._send_json({"status": "ok", "message": msg})
            else:
                self._send_json({"status": "error", "message": msg}, status=500)
            return

        if path in ("/api/config/drive-sync", "/api/config/sync-drive"):
            from nmb.config import sync_drive_config, DEFAULT_CONFIG_PATH
            target = sync_drive_config(DEFAULT_CONFIG_PATH)
            if target:
                self._send_json({"status": "ok", "message": f"Configuration successfully synchronized to drive: {target}", "target": str(target)})
            else:
                self._send_json({"status": "warn", "message": "No writable boot partition or removable drive found. Please insert an SD card or USB flash drive."})
            return

        if path == "/api/terminal/exec":
            if not getattr(self.server.cfg.web, "terminal_enabled", False):
                self._send_json({
                    "status": "error",
                    "message": "The web terminal is disabled. Set terminal_enabled = true in the [web] section of nmb.conf to enable it.",
                }, status=403)
                return
            cmd = str(body_json.get("command") or body_json.get("cmd") or "").strip()
            if not cmd:
                self._send_json({"status": "error", "message": "No command provided"}, status=400)
                return

            log.info("CLI terminal execution requested: %s", cmd)
            t_start = time.monotonic()
            timeout_sec = float(body_json.get("timeout") or 120.0)
            if timeout_sec > 600.0:
                timeout_sec = 600.0

            # Auto-elevate via sudo if non-root and command requires system admin privileges
            effective_cmd = cmd
            first_word = cmd.split()[0].lower() if cmd.split() else ""
            is_htop_alias = False
            if first_word in ("htop", "top"):
                effective_cmd = "top -b -n 1"
                is_htop_alias = True
            elif os.geteuid() != 0 and shutil.which("sudo") and not cmd.startswith("sudo"):
                root_cmds = ("apt", "apt-get", "systemctl", "dpkg", "reboot", "poweroff", "shutdown", "wg-quick", "hostapd", "iptables", "nft", "ip", "nmcli")
                if first_word in root_cmds:
                    effective_cmd = f"sudo -n {cmd}"

            try:
                term_env = {
                    **os.environ,
                    "TERM": "xterm-256color",
                    "PYTHONUNBUFFERED": "1",
                    "DEBIAN_FRONTEND": "noninteractive",
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + os.environ.get("PATH", ""),
                    "HOME": "/root" if os.geteuid() == 0 else os.environ.get("HOME", "/tmp"),
                    "USER": "root" if os.geteuid() == 0 else os.environ.get("USER", "nmb"),
                }
                proc = subprocess.run(
                    effective_cmd,
                    shell=True,
                    executable=shutil.which("bash") or "/bin/sh",
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=term_env,
                )
                duration_ms = round((time.monotonic() - t_start) * 1000.0, 1)
                output = proc.stdout
                if proc.stderr:
                    output = (output + "\n" if output else "") + proc.stderr
                if not output:
                    output = "(Command completed with no output)"
                if is_htop_alias:
                    output += "\n\n💡 [Tip] For an interactive task manager, use the WebUI '📊 Tasks & Load' tab: live per-core CPU meters, RAM/swap chart, sortable columns, search and process termination."
                self._send_json({
                    "status": "ok",
                    "command": cmd,
                    "effective_command": effective_cmd if effective_cmd != cmd else None,
                    "output": output,
                    "exit_code": proc.returncode,
                    "duration_ms": duration_ms,
                    "user": "root" if os.geteuid() == 0 else "nmb",
                })
            except subprocess.TimeoutExpired:
                duration_ms = round((time.monotonic() - t_start) * 1000.0, 1)
                self._send_json({
                    "status": "timeout",
                    "command": cmd,
                    "output": f"Command timed out after {int(timeout_sec)} seconds: {cmd}",
                    "exit_code": 124,
                    "duration_ms": duration_ms,
                }, status=504)
            except Exception as e:
                self._send_json({
                    "status": "error",
                    "command": cmd,
                    "output": f"Execution error: {e}",
                    "exit_code": 1,
                    "duration_ms": round((time.monotonic() - t_start) * 1000.0, 1),
                }, status=500)
            return

        # Invasive Diagnostics on-demand refresh
        if path == "/api/dev/invasive-log/generate":
            from nmb.report.invasive_logger import generate_invasive_snapshot
            cfg = self.server.cfg if hasattr(self, "server") and hasattr(self.server, "cfg") else load_config()
            md, snap = generate_invasive_snapshot(cfg, force_write=True)
            self._send_json({
                "status": "ok",
                "snapshot": snap,
                "markdown": md,
            })
            return

        # Ookla Anti-Ban Quarantine manual clear
        if path == "/api/speed/anti-ban/clear":
            from nmb.speed.anti_ban import clear_quarantine
            clear_quarantine()
            self._send_json({"status": "ok", "message": "Ookla server quarantine cleared successfully"})
            return

        # Crash Reports manual clear
        if path == "/api/dev/crashes/clear":
            from nmb.report.crash_trap import clear_crash_reports
            cleared = clear_crash_reports()
            self._send_json({"status": "ok", "cleared_count": cleared})
            return

        # Enforce Wired Route Priority in kernel
        if path == "/api/network/enforce-wired-priority":
            from nmb.netd.interfaces import enforce_wired_default_route_priority
            applied = enforce_wired_default_route_priority()
            self._send_json({"status": "ok", "adjusted": applied})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _handle_api_status(self) -> None:
        conn = db.connect(readonly=True)
        mode_row = conn.execute("SELECT v FROM kv WHERE k = 'active_mode'").fetchone()
        active_mode = mode_row["v"] if mode_row else "unknown"

        report = aggregate_report_data(conn, self.server.cfg, window_hours=24.0)
        svg = render_latency_chart(report.timeseries, report.outages, width=800, height=220)

        # Port check results
        port_rows = conn.execute("SELECT proto, port, endpoint, bps, baseline_bps, ratio, verdict, ts FROM port_check ORDER BY ts DESC LIMIT 25").fetchall()
        port_checks = [
            {
                "proto": r["proto"],
                "port": r["port"],
                "endpoint": r["endpoint"],
                "bps": r["bps"],
                "baseline_bps": r["baseline_bps"],
                "ratio": r["ratio"],
                "verdict": r["verdict"],
                "ts": r["ts"],
            }
            for r in port_rows
        ]

        # System event logs
        event_rows = conn.execute("SELECT id, ts, severity, source, kind, detail FROM event ORDER BY ts DESC LIMIT 40").fetchall()
        system_events = [
            {
                "id": r["id"],
                "ts": r["ts"],
                "severity": r["severity"],
                "source": r["source"],
                "kind": r["kind"],
                "detail": r["detail"],
            }
            for r in event_rows
        ]

        # Latest speedtest per engine for instantaneous dashboard switching
        latest_per_engine = {}
        for eng in ("ookla", "cloudflare", "fastcom", "rtr", "iperf3"):
            row = conn.execute(
                """SELECT ts, trigger, status, server_id, server_name, server_host, server_location, client_ip, client_ipv6,
                          down_bps, up_bps, ping_us, jitter_us, loss_pct, result_url, error,
                          down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms, connection_type,
                          engine, colo
                   FROM speedtest
                   WHERE LOWER(engine) = ? AND status = 'ok'
                   ORDER BY ts DESC LIMIT 1""",
                (eng,)
            ).fetchone()
            if row:
                d = dict(row)
                if eng == "iperf3":
                    from nmb.speed.iperf_directory import label_iperf_row
                    label_iperf_row(d)
                if eng == "fastcom":
                    d["fastcom_detail"] = _fastcom_detail(conn, row["ts"])
                # A failed run after the last result is mentioned, not shown as a result.
                fail = conn.execute(
                    "SELECT ts, error FROM speedtest WHERE LOWER(engine) = ? AND status = 'error' AND ts > ? ORDER BY ts DESC LIMIT 1",
                    (eng, row["ts"])).fetchone()
                if fail:
                    d["newer_failure"] = {"ts": fail["ts"], "error": fail["error"] or ""}
                if eng == "ookla":
                    from nmb.speed.anti_ban import client_cooldown_remaining, scheduled_wait_remaining
                    wait = max(client_cooldown_remaining(),
                               scheduled_wait_remaining(60 * self.server.cfg.speedtest.ookla_interval_min))
                    d["next_possible_ts"] = int((time.time() + wait) * 1000) if wait > 0 else None
                    d["selected_server_id"] = self.server.cfg.speedtest.server_id
                d_mbps = (row["down_bps"] or 0) / 1_000_000.0 if row["down_bps"] else None
                u_mbps = (row["up_bps"] or 0) / 1_000_000.0 if row["up_bps"] else None
                d["down_mbps"] = round(d_mbps, 2) if d_mbps is not None else None
                d["up_mbps"] = round(u_mbps, 2) if u_mbps is not None else None
                latest_per_engine[eng] = d

        # Last executed meroscript
        script_row = conn.execute("SELECT v FROM kv WHERE k = 'last_meroscript'").fetchone()
        conn.close()

        target_sid = getattr(self.server.cfg.speedtest, "server_id", None)
        target_srv_name = getattr(self.server.cfg.speedtest, "server_name", "") or "Auto-selected closest"
        target_srv_host = getattr(self.server.cfg.speedtest, "server_host", "") or "speedtest.net"
        target_flag = f" --server-id {target_sid}" if target_sid else ""
        default_script = (
            "#!/bin/sh\n"
            "# ==============================================================================\n"
            "# NetworkMeasureBox - Realtime Speedtest Command Preview & Telemetry\n"
            f"# Target Server: {target_srv_name} (#{target_sid or 'Auto'})\n"
            f"# Host Endpoint: {target_srv_host}\n"
            "# ==============================================================================\n"
            f"/usr/local/bin/speedtest --accept-license --accept-gdpr --format=json{target_flag}\n"
        )
        latest_script = script_row["v"] if script_row and script_row["v"] else default_script

        latest_bb = None
        for st in report.speed_tests:
            if st.get("status") == "ok" and st.get("bufferbloat_grade"):
                latest_bb = {
                    "grade": st.get("bufferbloat_grade"),
                    "delta_ms": st.get("bufferbloat_delta_ms"),
                    "down_lat_ms": st.get("down_loaded_lat_ms"),
                    "up_lat_ms": st.get("up_loaded_lat_ms"),
                }
                break

        # Instantaneous WAN traffic rates
        now_time = time.time()
        wan_iface = self.server.cfg.network.wan_interface
        rx_path = Path(f"/sys/class/net/{wan_iface}/statistics/rx_bytes")
        tx_path = Path(f"/sys/class/net/{wan_iface}/statistics/tx_bytes")
        rx_bps = 0
        tx_bps = 0
        try:
            curr_rx = int(rx_path.read_text().strip()) if rx_path.exists() else 0
            curr_tx = int(tx_path.read_text().strip()) if tx_path.exists() else 0
            last_t = getattr(self.server, "_last_traffic_time", 0.0)
            dt = now_time - last_t
            if dt > 0.4 and last_t > 0:
                rx_bps = max(0, int((curr_rx - getattr(self.server, "_last_rx_bytes", 0)) * 8 / dt))
                tx_bps = max(0, int((curr_tx - getattr(self.server, "_last_tx_bytes", 0)) * 8 / dt))
            self.server._last_rx_bytes = curr_rx
            self.server._last_tx_bytes = curr_tx
            self.server._last_traffic_time = now_time
        except Exception:
            log.debug("suppressed exception", exc_info=True)

        # Live clients breakdown for QoS Bandwidth Monitor
        sniffer = get_sniffer(wan_iface)
        sniffer_stats = sniffer.get_stats() if sniffer.running else {}
        clients = []
        if getattr(self.server, "is_measuring", False):
            clients.append({
                "name": "speedtest (Measurement Active)",
                "icon": "speedtest",
                "priority": "Highest",
                "up_kbps": round(tx_bps / 1000.0, 1),
                "down_kbps": round(rx_bps / 1000.0, 1),
            })
        
        for s in sniffer_stats.get("top_sources", [])[:5]:
            ip = s.get("ip", "")
            if ip and ip != "127.0.0.1":
                clients.append({
                    "name": ip,
                    "icon": "client",
                    "priority": "Default",
                    "up_kbps": round((s.get("count", 1) * 64 * 8) / 1000.0, 1),
                    "down_kbps": round((s.get("count", 1) * 128 * 8) / 1000.0, 1),
                })
        if not clients:
            clients = [
                {"name": "speedtest", "icon": "speedtest", "priority": "Highest", "up_kbps": round(tx_bps / 1000.0, 1), "down_kbps": round(rx_bps / 1000.0, 1)},
                {"name": "NettoDX (Gateway)", "icon": "desktop", "priority": "Medium", "up_kbps": 12.4, "down_kbps": 34.8},
                {"name": "Fluxnode", "icon": "server", "priority": "Lowest", "up_kbps": 0.4, "down_kbps": 0.0},
            ]

        conn_type = getattr(self.server.cfg.isp, "connection_type", "fiber")
        os_info = detect_os_info()
        dual = interfaces.get_dual_stack_ips(wan_iface)
        dual_v4 = dual.get("public_ipv4") or dual.get("ipv4")
        dual_v6 = dual.get("public_ipv6") or dual.get("ipv6")
        status_dict = {
            "system_info": {
                "firmware_version": "4047",
                "firmware_label": "4047 (NMB v2.5 Universal)",
                "kernel_version": platform.release(),
                "device_model": os_info.get("device_model") or get_hardware_model(),
                "distro_name": os_info.get("distro_name", "Linux"),
                "distro_version": os_info.get("distro_version", ""),
                "arch": os_info.get("arch", platform.machine()),
                "pkg_manager": os_info.get("pkg_manager", "apt"),
                "mac_address": interfaces.get_mac_address(wan_iface) or "--",
                "public_ipv4": dual_v4,
                "public_ipv6": dual_v6,
                "public_ip": dual_v4 or dual_v6,
                "wps_pin": "--",
                "box_id": self.server.cfg.system.box_id,
            },
            "public_ipv4": dual_v4,
            "public_ipv6": dual_v6,
            "public_ip": dual_v4 or dual_v6,
            "box_id": self.server.cfg.system.box_id,
            "is_measuring": getattr(self.server, "is_measuring", False),
            "latest_script": latest_script,
            "language": getattr(self.server.cfg.web, "language", "en"),
            "admin_username": getattr(self.server.cfg.web, "admin_username", "admin"),
            "default_password_active": (getattr(self.server.cfg.web, "admin_password", "") == "admin"),
            "drive_config": {
                "exists": find_drive_config_path() is not None,
                "path": str(find_drive_config_path() or get_writable_drive_config_target() or ""),
                "is_writable": get_writable_drive_config_target() is not None,
            },
            "contract": {
                "isp_name": self.server.cfg.isp.name,
                "circuit_id": self.server.cfg.isp.circuit_id,
                "account_id": self.server.cfg.isp.account_id,
                "connection_type": conn_type,
                "connection_type_label": CONNECTION_TYPES.get(conn_type, conn_type),
                "contract_down_mbps": self.server.cfg.isp.contract_down_mbps,
                "guaranteed_down_mbps": getattr(self.server.cfg.isp, "guaranteed_down_mbps", 0.0),
                "contract_up_mbps": self.server.cfg.isp.contract_up_mbps,
                "guaranteed_up_mbps": getattr(self.server.cfg.isp, "guaranteed_up_mbps", 0.0),
            },
            "live_traffic": {
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
                "rx_mbps": round(rx_bps / 1_000_000.0, 2),
                "tx_mbps": round(tx_bps / 1_000_000.0, 2),
                "clients": clients,
            },
            "port_checks": port_checks,
            "system_events": system_events,
            "isp_name": self.server.cfg.isp.name,
            "connection_type": conn_type,
            "connection_type_label": CONNECTION_TYPES.get(conn_type, conn_type),
            "dns_status": dns.get_dns_status(),
            "active_mode": active_mode,
            "wan_carrier": interfaces.get_carrier(self.server.cfg.network.wan_interface),
            "lan_carrier": interfaces.get_carrier(self.server.cfg.network.lan_interface),
            "wifi": {
                "enabled": self.server.cfg.network.wifi_enabled,
                "ssid": self.server.cfg.network.wifi_ssid,
                "band": getattr(self.server.cfg.network, "wifi_band", "auto"),
                "standard": getattr(self.server.cfg.network, "wifi_standard", "auto"),
                "channel": getattr(self.server.cfg.network, "wifi_channel", 0),
                "channel_width": getattr(self.server.cfg.network, "wifi_channel_width", "auto"),
                "country": getattr(self.server.cfg.network, "wifi_country_code", "auto"),
                "security": getattr(self.server.cfg.network, "wifi_security", "wpa2"),
                "capabilities": detect_wifi_capabilities(self.server.cfg.network.wlan_interface),
                "live_status": get_wifi_status(self.server.cfg.network.wlan_interface),
            },
            "uptime_pct": report.uptime_pct,
            "outages_count": len(report.outages),
            "total_outage_sec": report.total_outage_sec,
            "bufferbloat": latest_bb,
            "latest_speedtest": latest_measured_test(report.speed_tests),
            "schedule_mode": getattr(self.server.cfg.speedtest, "schedule_mode", "scheduled"),
            "schedule_cron": getattr(self.server.cfg.speedtest, "schedule_cron", "0 * * * *"),
            "schedule_cron_desc": get_cron_description(getattr(self.server.cfg.speedtest, "schedule_cron", "0 * * * *"), getattr(self.server.cfg.web, "language", "en")),
            "automated_engine": getattr(self.server.cfg.speedtest, "automated_engine", "ookla"),
            "engine_intervals": {
                "ookla": self.server.cfg.speedtest.ookla_interval_min,
                "rtr": self.server.cfg.speedtest.rtr_interval_min,
                "cloudflare": self.server.cfg.speedtest.cloudflare_interval_min,
                "fastcom": self.server.cfg.speedtest.fastcom_interval_min,
                "iperf3": self.server.cfg.speedtest.iperf3_interval_min,
            },
            "idle_threshold_mode": getattr(self.server.cfg.speedtest, "idle_threshold_mode", "percent"),
            "idle_threshold_percent": getattr(self.server.cfg.speedtest, "idle_threshold_percent", 2.0),
            "idle_threshold_kbps": getattr(self.server.cfg.speedtest, "idle_threshold_kbps", 500),
            "traffic_stop_enabled": self.server.cfg.speedtest.traffic_stop_enabled,
            "scheduler_status": self.server.scheduler.get_status() if getattr(self.server, "scheduler", None) else None,
            "scheduled_server": {
                "id": getattr(self.server.cfg.speedtest, "server_id", None),
                "name": getattr(self.server.cfg.speedtest, "server_name", ""),
                "host": getattr(self.server.cfg.speedtest, "server_host", ""),
            },
            "iperf": {
                "is_running": is_iperf_running(),
                "latest": get_latest_iperf_result(),
                "server": get_iperf_server_status(),
            },
            "iperf_target_host": getattr(self.server.cfg.iperf, "target_host", ""),
            "iperf_port": getattr(self.server.cfg.iperf, "target_port", getattr(self.server.cfg.iperf, "port", 5201)),
            "iperf_auto": {
                "duration": self.server.cfg.iperf.duration, "protocol": self.server.cfg.iperf.protocol,
                "parallel": self.server.cfg.iperf.parallel,
                "direction": "bidir" if self.server.cfg.iperf.bidir else self.server.cfg.iperf.auto_direction,
                "extra_servers": self.server.cfg.iperf.extra_servers,
            },
            "traceroute": {
                "is_running": is_traceroute_running(),
                "latest": get_latest_traceroute(),
            },
            "network_devices": get_cached_devices(),
            "ping": {
                "loss_pct": report.ping_summary.loss_pct,
                "avg_rtt_ms": report.ping_summary.rtt_avg_ms,
                "p95_rtt_ms": report.ping_summary.rtt_p95_ms,
                "jitter_ms": report.ping_summary.jitter_avg_ms,
            },
            "speed": {
                "avg_down_mbps": report.speed_summary.avg_down_mbps,
                "avg_up_mbps": report.speed_summary.avg_up_mbps,
                "sla_compliance_pct": report.speed_summary.sla_compliance_pct,
                "avg_down_pct_of_offered": getattr(report.speed_summary, "avg_down_pct_of_offered", 0.0),
                "avg_up_pct_of_offered": getattr(report.speed_summary, "avg_up_pct_of_offered", 0.0),
                "min_down_pct_of_offered": getattr(report.speed_summary, "min_down_pct_of_offered", 0.0),
                "max_down_pct_of_offered": getattr(report.speed_summary, "max_down_pct_of_offered", 0.0),
                "avg_down_pct_of_guaranteed": getattr(report.speed_summary, "avg_down_pct_of_guaranteed", 0.0),
                "avg_up_pct_of_guaranteed": getattr(report.speed_summary, "avg_up_pct_of_guaranteed", 0.0),
            },
            "target_stats": [
                {
                    "target_id": t.target_id,
                    "addr": t.addr,
                    "label": t.label,
                    "sent": t.sent,
                    "lost": t.lost,
                    "loss_pct": t.loss_pct,
                    "avg_rtt_ms": t.avg_rtt_ms,
                    "p95_rtt_ms": t.p95_rtt_ms,
                }
                for t in report.target_stats
            ],
            "speed_tests": tests_for_display(report.speed_tests),
            "latest_per_engine": latest_per_engine,
            "chart_svg": svg,
            "auth_enabled": bool(getattr(self.server.cfg.web, "auth_enabled", True)),
            "admin_username": getattr(self.server.cfg.web, "admin_username", "admin"),
        }
        from nmb.common.memory import (
            get_available_ram_mb,
            get_effective_memory_profile,
            get_total_ram_mb,
            is_low_memory_system,
        )
        status_dict["memory"] = {
            "ram_total_mb": get_total_ram_mb(),
            "ram_available_mb": get_available_ram_mb(),
            "configured_profile": getattr(self.server.cfg.system, "memory_profile", "auto"),
            "effective_profile": get_effective_memory_profile(getattr(self.server.cfg.system, "memory_profile", "auto")),
            "is_low_memory": is_low_memory_system(),
        }
        self._send_json(status_dict)

    def _handle_api_get_config(self) -> None:
        cfg = self.server.cfg
        wan_iface = cfg.network.wan_interface
        data = {
            "box_id": cfg.system.box_id,
            "memory_profile": getattr(cfg.system, "memory_profile", "auto"),
            "network_mode": cfg.network.mode,
            "wan_interface": wan_iface,
            "lan_interface": cfg.network.lan_interface,
            "wlan_interface": cfg.network.wlan_interface,
            "bridge_interface": cfg.network.bridge_interface,
            "gateway_ip": cfg.network.gateway_ip,
            "gateway_netmask": cfg.network.gateway_netmask,
            "dhcp_enabled": getattr(cfg.network, "dhcp_enabled", True),
            "dhcp_range_start": cfg.network.dhcp_range_start,
            "dhcp_range_end": cfg.network.dhcp_range_end,
            "dhcp_lease_time": cfg.network.dhcp_lease_time,
            "wan_proto": getattr(cfg.network, "wan_proto", "dhcp"),
            "wan_ip": getattr(cfg.network, "wan_ip", ""),
            "wan_netmask": getattr(cfg.network, "wan_netmask", "255.255.255.0"),
            "wan_gateway": getattr(cfg.network, "wan_gateway", ""),
            "wan2_interface": getattr(cfg.network, "wan2_interface", ""),
            "wan2_proto": getattr(cfg.network, "wan2_proto", "dhcp"),
            "wan2_ip": getattr(cfg.network, "wan2_ip", ""),
            "wan2_netmask": getattr(cfg.network, "wan2_netmask", "255.255.255.0"),
            "wan2_gateway": getattr(cfg.network, "wan2_gateway", ""),
            "wan2_mac": getattr(cfg.network, "wan2_mac", ""),
            "wan_mode": getattr(cfg.network, "wan_mode", "single"),
            "lan_ports": ",".join(cfg.network.lan_ports) if isinstance(getattr(cfg.network, "lan_ports", None), list) else str(getattr(cfg.network, "lan_ports", "")),
            "dmz_interface": getattr(cfg.network, "dmz_interface", ""),
            "measurement_interface": getattr(cfg.network, "measurement_interface", ""),
            "current_mac": interfaces.get_mac_address(wan_iface),
            "factory_mac": interfaces.get_factory_mac_address(wan_iface),
            "wan_mac": getattr(cfg.network, "wan_mac", ""),
            "pppoe_enabled": cfg.network.pppoe_enabled,
            "pppoe_user": cfg.network.pppoe_user,
            "pppoe_vlan": cfg.network.pppoe_vlan,
            "pppoe_service_name": getattr(cfg.network, "pppoe_service_name", ""),
            "dns_mode": getattr(cfg.network, "dns_mode", "auto"),
            "dns_primary": getattr(cfg.network, "dns_primary", "1.1.1.1"),
            "dns_secondary": getattr(cfg.network, "dns_secondary", "8.8.8.8"),
            "dns_fallback_enabled": getattr(cfg.network, "dns_fallback_enabled", True),
            "dns_fallback_servers": getattr(cfg.network, "dns_fallback_servers", ["1.1.1.1", "8.8.8.8", "9.9.9.9", "208.67.222.222"]),
            "dns_status": dns.get_dns_status(),
            "wifi_enabled": cfg.network.wifi_enabled,
            "wifi_ssid": cfg.network.wifi_ssid,
            # Only whether one is set: the password itself never leaves the box through the API.
            "wifi_psk_set": not __import__("nmb.netd.wifi", fromlist=["x"]).weak_wifi_password(cfg.network.wifi_psk),
            "wifi_band": getattr(cfg.network, "wifi_band", "auto"),
            "wifi_standard": getattr(cfg.network, "wifi_standard", "auto"),
            "wifi_channel": cfg.network.wifi_channel,
            "wifi_channel_width": getattr(cfg.network, "wifi_channel_width", "auto"),
            "wifi_country_code": getattr(cfg.network, "wifi_country_code", "auto"),
            "wifi_security": getattr(cfg.network, "wifi_security", "wpa2"),
            "wifi_capabilities": detect_wifi_capabilities(cfg.network.wlan_interface),
            "guest_wifi_enabled": getattr(cfg.guest_wifi, "enabled", False),
            "guest_wifi_interface": getattr(cfg.guest_wifi, "interface", "wlan0"),
            "guest_wifi_ssid": getattr(cfg.guest_wifi, "ssid", ""),
            "guest_wifi_password": "",
            "guest_wifi_password_set": bool(getattr(cfg.guest_wifi, "password", "")),
            "guest_wifi_security": getattr(cfg.guest_wifi, "security", "auto"),
            "guest_wifi_metric": getattr(cfg.guest_wifi, "metric", 600),
            "guest_wifi_auto_reconnect": getattr(cfg.guest_wifi, "auto_reconnect", True),
            "schedule_mode": getattr(cfg.speedtest, "schedule_mode", "scheduled"),
            "schedule_cron": getattr(cfg.speedtest, "schedule_cron", "0 * * * *"),
            "automated_engine": getattr(cfg.speedtest, "automated_engine", "ookla"),
            "idle_threshold_mode": getattr(cfg.speedtest, "idle_threshold_mode", "percent"),
            "daily_data_limit_mb": cfg.speedtest.daily_data_limit_mb,
            "idle_threshold_percent": getattr(cfg.speedtest, "idle_threshold_percent", 2.0),
            "idle_threshold_kbps": getattr(cfg.speedtest, "idle_threshold_kbps", 500),
            "idle_check_kbps": getattr(cfg.speedtest, "idle_threshold_kbps", 500),
            "speedtest_server_id": getattr(cfg.speedtest, "server_id", None),
            "speedtest_server_name": getattr(cfg.speedtest, "server_name", ""),
            "speedtest_server_host": getattr(cfg.speedtest, "server_host", ""),
            "user_agent": getattr(cfg.speedtest, "user_agent", ""),
            "user_agent_mode": getattr(cfg.speedtest, "user_agent_mode", "auto_fresh"),
            "effective_user_agent": __import__("nmb.common.user_agent", fromlist=["get_effective_user_agent"]).get_effective_user_agent(cfg),
            "user_agent_presets": __import__("nmb.common.user_agent", fromlist=["list_user_agent_presets"]).list_user_agent_presets(),
            "sqm_algorithm": getattr(cfg.system, "sqm_algorithm", "cake"),
            "auth_enabled": bool(getattr(cfg.web, "auth_enabled", True)),
            "admin_username": getattr(cfg.web, "admin_username", "admin"),
            "public_results": bool(getattr(cfg.web, "public_results", False)),
            "language": getattr(cfg.web, "language", "en"),
            "theme": getattr(cfg.web, "theme", "default"),
            "iperf_target_host": getattr(cfg.iperf, "target_host", ""),
            "iperf_port": getattr(cfg.iperf, "target_port", getattr(cfg.iperf, "port", 5201)),
            "iperf_protocol": getattr(cfg.iperf, "protocol", "tcp"),
            "iperf_duration": getattr(cfg.iperf, "duration", 10),
            "iperf_parallel": getattr(cfg.iperf, "parallel", 1),
            "iperf_udp": getattr(cfg.iperf, "protocol", "tcp").lower() == "udp",
            "iperf_reverse": getattr(cfg.iperf, "reverse", False),
            "iperf_server_enabled": getattr(cfg.iperf, "server_enabled", False),
            "iperf_server_port": getattr(cfg.iperf, "server_port", 5201),
            "iperf_automated_enabled": getattr(cfg.iperf, "automated_enabled", False),
            "iperf_schedule_cron": getattr(cfg.iperf, "schedule_cron", "0 */12 * * *"),
            "isp_name": cfg.isp.name,
            "connection_type": getattr(cfg.isp, "connection_type", "fiber"),
            "connection_types": CONNECTION_TYPES,
            "account_id": cfg.isp.account_id,
            "circuit_id": cfg.isp.circuit_id,
            "contract_down_mbps": cfg.isp.contract_down_mbps,
            "guaranteed_down_mbps": getattr(cfg.isp, "guaranteed_down_mbps", 300.0),
            "contract_up_mbps": cfg.isp.contract_up_mbps,
            "guaranteed_up_mbps": getattr(cfg.isp, "guaranteed_up_mbps", 75.0),
        }
        self._send_json(data)

    def _handle_api_post_config(self, body: dict) -> None:
        cfg = self.server.cfg
        # Flatten nested sections if present
        if "network" in body and isinstance(body["network"], dict):
            for k, v in body["network"].items():
                if k not in body:
                    body[k] = v
        if "speedtest" in body and isinstance(body["speedtest"], dict):
            for k, v in body["speedtest"].items():
                if k not in body:
                    body[k] = v
        if body.get("wifi_psk"):
            from nmb.netd.wifi import weak_wifi_password
            if weak_wifi_password(str(body["wifi_psk"]).strip()):
                self._send_json({"status": "error", "message": "The Wi-Fi password must be 8 to 63 characters and not the old factory password."}, status=400)
                return
        if "contract" in body and isinstance(body["contract"], dict):
            for k, v in body["contract"].items():
                if k not in body:
                    body[k] = v
        if "system" in body and isinstance(body["system"], dict):
            for k, v in body["system"].items():
                if k not in body:
                    body[k] = v

        if "box_id" in body and body["box_id"]:
            cfg.system.box_id = str(body["box_id"]).strip()
        if "sqm_algorithm" in body:
            cfg.system.sqm_algorithm = str(body["sqm_algorithm"]).strip().lower()
        if "network_mode" in body or "mode" in body:
            m = str(body.get("network_mode") or body.get("mode")).strip().lower()
            if m in ("auto", "standalone", "mode_a", "mode_b"):
                cfg.network.mode = m
        if "gateway_ip" in body or "lan_ip" in body:
            cfg.network.gateway_ip = str(body.get("gateway_ip") or body.get("lan_ip")).strip()
        if "gateway_netmask" in body or "lan_netmask" in body:
            cfg.network.gateway_netmask = str(body.get("gateway_netmask") or body.get("lan_netmask")).strip()
        if "dhcp_enabled" in body:
            cfg.network.dhcp_enabled = bool(body["dhcp_enabled"])
        if "dhcp_range_start" in body or "dhcp_start" in body:
            cfg.network.dhcp_range_start = str(body.get("dhcp_range_start") or body.get("dhcp_start")).strip()
        if "dhcp_range_end" in body or "dhcp_end" in body:
            cfg.network.dhcp_range_end = str(body.get("dhcp_range_end") or body.get("dhcp_end")).strip()
        if "dhcp_lease_time" in body or "dhcp_lease" in body:
            cfg.network.dhcp_lease_time = str(body.get("dhcp_lease_time") or body.get("dhcp_lease")).strip()
        if "wan_proto" in body:
            cfg.network.wan_proto = str(body["wan_proto"]).strip().lower()
        if "wan_ip" in body:
            cfg.network.wan_ip = str(body["wan_ip"]).strip()
        if "wan_netmask" in body:
            cfg.network.wan_netmask = str(body["wan_netmask"]).strip()
        if "wan_gateway" in body:
            cfg.network.wan_gateway = str(body["wan_gateway"]).strip()
        if "wan2_interface" in body:
            cfg.network.wan2_interface = str(body["wan2_interface"]).strip()
        if "wan2_proto" in body:
            cfg.network.wan2_proto = str(body["wan2_proto"]).strip().lower()
        if "wan2_ip" in body:
            cfg.network.wan2_ip = str(body["wan2_ip"]).strip()
        if "wan2_netmask" in body:
            cfg.network.wan2_netmask = str(body["wan2_netmask"]).strip()
        if "wan2_gateway" in body:
            cfg.network.wan2_gateway = str(body["wan2_gateway"]).strip()
        if "wan2_mac" in body:
            cfg.network.wan2_mac = str(body["wan2_mac"]).strip().lower()
        if "wan_mode" in body:
            wm = str(body["wan_mode"]).strip().lower()
            if wm in ("single", "failover", "loadbalance"):
                cfg.network.wan_mode = wm
        if "lan_ports" in body:
            lp = body["lan_ports"]
            if isinstance(lp, list):
                cfg.network.lan_ports = [str(x).strip() for x in lp if str(x).strip()]
            else:
                cfg.network.lan_ports = [p.strip() for p in str(lp).split(",") if p.strip()]
        if "dmz_interface" in body:
            cfg.network.dmz_interface = str(body["dmz_interface"]).strip()
        if "measurement_interface" in body:
            cfg.network.measurement_interface = str(body["measurement_interface"]).strip()

        if "isp_name" in body:
            cfg.isp.name = str(body["isp_name"]).strip()
        if "connection_type" in body:
            cfg.isp.connection_type = str(body["connection_type"]).strip()
        if "account_id" in body:
            cfg.isp.account_id = str(body["account_id"]).strip()
        if "circuit_id" in body:
            cfg.isp.circuit_id = str(body["circuit_id"]).strip()
        if "contract_down_mbps" in body:
            try:
                cfg.isp.contract_down_mbps = float(body["contract_down_mbps"])
            except (ValueError, TypeError):
                pass
        if "guaranteed_down_mbps" in body:
            try:
                cfg.isp.guaranteed_down_mbps = float(body["guaranteed_down_mbps"])
            except (ValueError, TypeError):
                pass
        if "contract_up_mbps" in body:
            try:
                cfg.isp.contract_up_mbps = float(body["contract_up_mbps"])
            except (ValueError, TypeError):
                pass
        if "guaranteed_up_mbps" in body:
            try:
                cfg.isp.guaranteed_up_mbps = float(body["guaranteed_up_mbps"])
            except (ValueError, TypeError):
                pass

        # Wi-Fi settings (2.4 GHz - 6 GHz, a/b/g/n/ac/ax/be)
        if "wifi_enabled" in body:
            cfg.network.wifi_enabled = bool(body["wifi_enabled"])
        if "wifi_ssid" in body:
            cfg.network.wifi_ssid = str(body["wifi_ssid"]).strip()
        if "wifi_psk" in body and body["wifi_psk"]:
            cfg.network.wifi_psk = str(body["wifi_psk"]).strip()
        if "wifi_band" in body:
            cfg.network.wifi_band = str(body["wifi_band"]).strip().lower()
        if "wifi_standard" in body:
            cfg.network.wifi_standard = str(body["wifi_standard"]).strip().lower()
        if "wifi_channel" in body:
            try:
                cfg.network.wifi_channel = int(body["wifi_channel"])
            except (ValueError, TypeError):
                pass
        if "wifi_channel_width" in body:
            cfg.network.wifi_channel_width = str(body["wifi_channel_width"]).strip().lower()
        if "wifi_country_code" in body or "wifi_country" in body:
            cfg.network.wifi_country_code = str(body.get("wifi_country_code") or body.get("wifi_country")).strip().upper()
        if "wifi_security" in body:
            cfg.network.wifi_security = str(body["wifi_security"]).strip().lower()

        # Dedicated Guest Wi-Fi client probe settings
        if "guest_wifi_enabled" in body:
            cfg.guest_wifi.enabled = bool(body["guest_wifi_enabled"])
        if "guest_wifi_interface" in body:
            cfg.guest_wifi.interface = str(body["guest_wifi_interface"]).strip()
        if "guest_wifi_ssid" in body:
            cfg.guest_wifi.ssid = str(body["guest_wifi_ssid"]).strip()
        if body.get("guest_wifi_password"):
            cfg.guest_wifi.password = str(body["guest_wifi_password"]).strip()
        if "guest_wifi_security" in body:
            cfg.guest_wifi.security = str(body["guest_wifi_security"]).strip().lower()
        if "guest_wifi_metric" in body:
            try:
                cfg.guest_wifi.metric = int(body["guest_wifi_metric"])
            except (ValueError, TypeError):
                pass
        if "guest_wifi_auto_reconnect" in body:
            cfg.guest_wifi.auto_reconnect = bool(body["guest_wifi_auto_reconnect"])

        # PPPoE settings
        if "pppoe_enabled" in body:
            cfg.network.pppoe_enabled = bool(body["pppoe_enabled"])
        if "pppoe_user" in body:
            cfg.network.pppoe_user = str(body["pppoe_user"]).strip()
        if "pppoe_password" in body and body["pppoe_password"]:
            cfg.network.pppoe_password = str(body["pppoe_password"]).strip()
        if "pppoe_vlan" in body:
            try:
                cfg.network.pppoe_vlan = int(body["pppoe_vlan"])
            except (ValueError, TypeError):
                pass
        if "pppoe_service_name" in body:
            cfg.network.pppoe_service_name = str(body["pppoe_service_name"]).strip()

        # Custom WAN MAC address
        if "wan_mac" in body:
            raw_mac = str(body["wan_mac"]).strip().lower()
            wan_iface = cfg.network.wan_interface
            if not raw_mac:
                cfg.network.wan_mac = ""
                interfaces.reset_mac_to_factory(wan_iface)
            else:
                cfg.network.wan_mac = raw_mac
                interfaces.set_mac_address(wan_iface, raw_mac)

        # DNS settings
        if "dns_mode" in body:
            cfg.network.dns_mode = str(body["dns_mode"]).strip().lower()
        if "dns_primary" in body:
            cfg.network.dns_primary = str(body["dns_primary"]).strip()
        if "dns_secondary" in body:
            cfg.network.dns_secondary = str(body["dns_secondary"]).strip()
        if "dns_fallback_enabled" in body:
            cfg.network.dns_fallback_enabled = bool(body["dns_fallback_enabled"])
        if "dns_fallback_servers" in body:
            raw_servers = body["dns_fallback_servers"]
            if isinstance(raw_servers, list):
                cfg.network.dns_fallback_servers = [str(s).strip() for s in raw_servers if str(s).strip()]
            elif isinstance(raw_servers, str):
                cfg.network.dns_fallback_servers = [s.strip() for s in raw_servers.split(",") if s.strip()]

        # Speedtest automated measurement and schedule configuration
        if "schedule_mode" in body:
            sm = str(body["schedule_mode"]).strip().lower()
            if sm in ("manual", "scheduled"):
                cfg.speedtest.schedule_mode = sm
        if "schedule_cron" in body:
            sc = str(body["schedule_cron"]).strip()
            if sc:
                cfg.speedtest.schedule_cron = normalize_cron_expression(sc)
        if "automated_engine" in body:
            ae = str(body["automated_engine"]).strip().lower()
            if ae in ("ookla", "cloudflare", "fastcom", "rtr", "iperf3", "all"):
                cfg.speedtest.automated_engine = ae
        if "daily_data_limit_mb" in body:
            try:
                cfg.speedtest.daily_data_limit_mb = max(0.0, float(body["daily_data_limit_mb"]))
            except (TypeError, ValueError):
                pass
        if "idle_threshold_mode" in body:
            tm = str(body["idle_threshold_mode"]).strip().lower()
            if tm in ("percent", "fixed"):
                cfg.speedtest.idle_threshold_mode = tm
        if "idle_threshold_percent" in body:
            try:
                cfg.speedtest.idle_threshold_percent = float(body["idle_threshold_percent"])
            except (ValueError, TypeError):
                pass
        if "idle_threshold_kbps" in body or "idle_check_kbps" in body:
            try:
                cfg.speedtest.idle_threshold_kbps = int(body.get("idle_threshold_kbps") or body.get("idle_check_kbps"))
            except (ValueError, TypeError):
                pass

        if "speedtest_server_id" in body:
            raw_sid = body["speedtest_server_id"]
            if raw_sid is None or str(raw_sid).strip() == "" or str(raw_sid).lower() in ("auto", "null", "none"):
                cfg.speedtest.server_id = None
                cfg.speedtest.server_name = ""
                cfg.speedtest.server_host = ""
            else:
                try:
                    cfg.speedtest.server_id = int(raw_sid)
                except (ValueError, TypeError):
                    pass
        if "speedtest_server_name" in body:
            cfg.speedtest.server_name = str(body["speedtest_server_name"]).strip()
        if "speedtest_server_host" in body:
            cfg.speedtest.server_host = str(body["speedtest_server_host"]).strip()
        if "user_agent" in body:
            cfg.speedtest.user_agent = str(body["user_agent"]).strip()
        if "user_agent_mode" in body:
            cfg.speedtest.user_agent_mode = str(body["user_agent_mode"]).strip().lower()
        if "memory_profile" in body:
            cfg.system.memory_profile = str(body["memory_profile"]).strip().lower()
        if isinstance(body.get("admin_username"), str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", body["admin_username"].strip()):
            cfg.web.admin_username = body["admin_username"].strip()
        if "admin_password" in body and body["admin_password"]:
            cfg.web.admin_password = str(body["admin_password"])
        if isinstance(body.get("public_results"), bool):
            cfg.web.public_results = body["public_results"]
        if "language" in body and str(body["language"]).strip() in TRANSLATIONS:
            cfg.web.language = str(body["language"]).strip()
        valid_themes = ("default", "prtd", "proudride", "amoled", "asuswrt", "asus_camo", "tp_gold", "mountain_hago", "ndefault")
        if "theme" in body and str(body["theme"]).strip().lower() in valid_themes:
            cfg.web.theme = str(body["theme"]).strip().lower()

        # iPerf configuration
        if "iperf_target_host" in body:
            cfg.iperf.target_host = str(body["iperf_target_host"]).strip()
        if "iperf_port" in body or "iperf_target_port" in body:
            try:
                p_val = int(body.get("iperf_port") or body.get("iperf_target_port"))
                cfg.iperf.target_port = p_val
                cfg.iperf.port = p_val
            except (ValueError, TypeError):
                pass
        if "iperf_protocol" in body:
            cfg.iperf.protocol = str(body["iperf_protocol"]).strip().lower()
        elif "iperf_udp" in body:
            cfg.iperf.protocol = "udp" if body["iperf_udp"] else "tcp"
        if "iperf_duration" in body:
            try:
                cfg.iperf.duration = int(body["iperf_duration"])
            except (ValueError, TypeError):
                pass
        if "iperf_parallel" in body:
            try:
                cfg.iperf.parallel = int(body["iperf_parallel"])
            except (ValueError, TypeError):
                pass
        if "iperf_reverse" in body:
            cfg.iperf.reverse = bool(body["iperf_reverse"])
        if "iperf_server_enabled" in body:
            cfg.iperf.server_enabled = bool(body["iperf_server_enabled"])
        if "iperf_server_port" in body:
            try:
                cfg.iperf.server_port = int(body["iperf_server_port"])
            except (ValueError, TypeError):
                pass
        if "iperf_automated_enabled" in body:
            cfg.iperf.automated_enabled = bool(body["iperf_automated_enabled"])
        if "iperf_schedule_cron" in body:
            cfg.iperf.schedule_cron = str(body["iperf_schedule_cron"]).strip()

        # Persist to /etc/nmb/nmb.conf atomically
        saved = save_config(cfg)
        if not saved:
            log.error("failed to save configuration file to disk")
            self._send_json({"error": "Failed to persist configuration to disk"}, status=500)
            return

        log.info("updated configuration on disk and in runtime memory")
        self._notify_daemon_reload()
        self._send_json({"status": "ok", "message": "Network and measurement settings saved and applied successfully!"})

    def _lan_topology_payload(self) -> dict:
        from nmb.netd import lan_topology
        from nmb.netd.drivers import detect_all_physical_interfaces
        net = self.server.cfg.network
        return {
            "status": "ok",
            "lan_passthrough_enabled": net.lan_passthrough_enabled,
            "passthrough_ports": net.passthrough_ports,
            "lag_enabled": net.lag_enabled,
            "lag_ports": net.lag_ports,
            "lag_mode": net.lag_mode,
            "lag_hash_policy": net.lag_hash_policy,
            "lacp_rate": net.lacp_rate,
            "wan_interface": net.wan_interface,
            "network_mode": net.mode,
            "ports": [
                {
                    "name": i.get("name"),
                    "carrier": bool(i.get("carrier")),
                    "speed_mbps": i.get("speed_mbps"),
                    "chipset": i.get("chipset"),
                    "bus_type": i.get("bus_type"),
                }
                for i in detect_all_physical_interfaces() if not i.get("is_wireless")
            ],
            "runtime": lan_topology.get_runtime_status(net),
        }

    def _handle_lan_topology_post(self, body: dict) -> None:
        from nmb.netd import lan_topology
        from nmb.netd.drivers import detect_all_physical_interfaces
        cfg = self.server.cfg
        net = cfg.network

        def ports(field: str) -> list:
            value = body.get(field, [])
            items = value if isinstance(value, list) else str(value).split(",")
            return list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))

        passthrough_enabled = bool(body.get("lan_passthrough_enabled"))
        passthrough_ports = ports("passthrough_ports")
        lag_enabled = bool(body.get("lag_enabled"))
        lag_ports = ports("lag_ports")
        lag_mode = str(body.get("lag_mode", net.lag_mode)).strip()
        hash_policy = str(body.get("lag_hash_policy", net.lag_hash_policy)).strip()
        lacp_rate = str(body.get("lacp_rate", net.lacp_rate)).strip()

        wired = [i.get("name") for i in detect_all_physical_interfaces() if not i.get("is_wireless")]
        errors = lan_topology.validate_settings(
            lag_enabled, lag_ports, lag_mode, hash_policy, lacp_rate,
            passthrough_enabled, passthrough_ports, net.wan_interface, wired,
        )
        if errors:
            self._send_json({"status": "error", "message": " ".join(errors), "errors": errors}, status=400)
            return

        net.lan_passthrough_enabled = passthrough_enabled
        net.passthrough_ports = passthrough_ports
        net.lag_enabled = lag_enabled
        net.lag_ports = lag_ports
        net.lag_mode = lag_mode
        net.lag_hash_policy = hash_policy
        net.lacp_rate = lacp_rate

        if passthrough_enabled or lag_enabled:
            # The feature only exists in standalone mode, so select it and clear any manual override.
            net.mode = "standalone"
            conn = db.connect()
            with db.tx(conn):
                conn.execute(
                    "INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('override_mode', 'auto', ?)",
                    (db.now_ms(),),
                )
            conn.close()

        save_config(cfg)
        self._notify_daemon_reload()
        self._send_json(self._lan_topology_payload())

    def _toggle_iperf_server(self) -> None:
        cur_status = get_iperf_server_status()
        if cur_status.get("is_running") or cur_status.get("server_running"):
            res = stop_iperf_server()
            self.server.cfg.iperf.server_enabled = False
        else:
            port = int(getattr(self.server.cfg.iperf, "server_port", 5201))
            res = start_iperf_server(port)
            self.server.cfg.iperf.server_enabled = (res.get("status") == "ok")
        save_config(self.server.cfg)
        self._send_json({"status": "ok", "server": get_iperf_server_status()})

    def _notify_daemon_reload(self) -> None:
        """Send SIGHUP to nmb-netd and nmb-telegram if running."""
        # 1. netd SIGHUP via pidfile
        netd_pid_file = self.server.cfg.system.run_dir / "netd.pid"
        if netd_pid_file.exists():
            try:
                pid = int(netd_pid_file.read_text().strip())
                # nmb-netd runs as root, and this server does not, so systemd delivers the signal.
                reload_run = subprocess.run(["systemctl", "reload", "nmb-netd.service"], capture_output=True, timeout=15, check=False)
                if reload_run.returncode != 0:
                    os.kill(pid, signal.SIGHUP)
                log.info("asked nmb-netd (pid %d) to reload its settings", pid)
            except Exception as e:
                log.debug("could not signal nmb-netd: %s", e)

        # 2. telegram SIGHUP/reload via pidfile
        tg_pid_file = self.server.cfg.system.run_dir / "telegram.pid"
        if tg_pid_file.exists():
            try:
                pid = int(tg_pid_file.read_text().strip())
                os.kill(pid, signal.SIGHUP)
                log.info("sent SIGHUP to nmb-telegram (pid %d)", pid)
            except Exception as e:
                log.debug("could not signal nmb-telegram: %s", e)


def get_hardware_model() -> str:
    dt_model = Path("/proc/device-tree/model")
    if dt_model.exists():
        try:
            return dt_model.read_text(errors="ignore").strip().replace("\x00", "")
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    dmi = Path("/sys/devices/virtual/dmi/id/product_name")
    if dmi.exists():
        try:
            val = dmi.read_text(errors="ignore").strip()
            if val and val != "None":
                return val
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    return f"Universal Linux Host ({platform.machine()})"


class NMBServer(ThreadingHTTPServer):
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.is_measuring = False
        self.last_measure_error = ""
        self.scheduler: Optional[AutonomousScheduler] = None
        self._last_rx_bytes = 0
        self._last_tx_bytes = 0
        self._last_traffic_time = 0.0

        target_host = cfg.web.host
        target_port = cfg.web.port

        super().__init__((target_host, target_port), WebRequestHandler, bind_and_activate=False)

        try:
            self.server_bind()
            self.server_activate()
        except (PermissionError, OSError) as e:
            is_perm = isinstance(e, PermissionError) or getattr(e, "errno", None) in (13, errno.EACCES)
            if target_port < 1024 and is_perm:
                fallback_port = 8080
                log.warning(
                    "Standard router HTTP port %d requires root privileges or CAP_NET_BIND_SERVICE (%s). "
                    "Automatically falling back to unprivileged port %d for sandbox/development.",
                    target_port, e, fallback_port
                )
                try:
                    self.socket.close()
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
                self.socket = socket.socket(self.address_family, self.socket_type)
                if self.allow_reuse_address:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_address = (target_host, fallback_port)
                self.cfg.web.port = fallback_port
                self.server_bind()
                self.server_activate()
            elif target_host not in ("0.0.0.0", "::", ""):
                # The dashboard is the way to correct a wrong address, so it must stay reachable.
                log.warning("cannot listen on %s (%s); listening on all addresses", target_host, e)
                self.socket.close()
                self.socket = socket.socket(self.address_family, self.socket_type)
                if self.allow_reuse_address:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_address = ("0.0.0.0", target_port)
                self.server_bind()
                self.server_activate()
            else:
                raise

        # Optional TLS / HTTPS Encryption
        tls_cert = getattr(cfg.web, "tls_cert", "") or "/etc/nmb/server.crt"
        tls_key = getattr(cfg.web, "tls_key", "") or "/etc/nmb/server.key"
        self.is_tls = False
        if getattr(cfg.web, "tls_enabled", False) and Path(tls_cert).exists() and Path(tls_key).exists():
            try:
                import ssl
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
                self.socket = context.wrap_socket(self.socket, server_side=True)
                self.is_tls = True
                log.info("TLS / HTTPS encryption enabled for web management (cert: %s)", tls_cert)
            except Exception as e:
                log.error("failed to enable TLS encryption: %s", e)


class WebDaemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.server: Optional[NMBServer] = None
        self.scheduler: Optional[AutonomousScheduler] = None
        self.running = False

    def handle_signal(self, signum: int, frame) -> None:
        log.info("received signal %d, stopping web server and scheduler...", signum)
        self.running = False
        if self.scheduler:
            self.scheduler.stop()
        try:
            from nmb.report.invasive_logger import stop_invasive_background_logger
            stop_invasive_background_logger()
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        if self.server:
            threading.Thread(target=self.server.shutdown).start()

    def run(self) -> None:
        self.running = True
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

        self.server = NMBServer(self.cfg)
        self.scheduler = AutonomousScheduler(self.cfg)
        self.server.scheduler = self.scheduler
        self.scheduler.start()

        # Install invasive crash trap introspector & unhandled exception handler
        try:
            from nmb.report.crash_trap import install_crash_trap
            install_crash_trap()
        except Exception as e:
            log.warning("could not install crash trap: %s", e)

        # Enforce wired Ethernet default route priority if cable is connected
        try:
            from nmb.netd.interfaces import enforce_wired_default_route_priority
            enforce_wired_default_route_priority()
        except Exception:
            log.debug("suppressed exception", exc_info=True)

        # Continuous background invasive diagnostic logger (persists to /var/log/nmb and FAT32 boot drive)
        try:
            from nmb.report.invasive_logger import start_invasive_background_logger
            start_invasive_background_logger(self.cfg)
        except Exception as e:
            log.warning("could not start invasive background logger: %s", e)

        # Synchronize background Guest Wi-Fi client station connection if enabled
        sync_guest_wifi_connection(self.cfg)

        # Central collector uploader; it stays idle while the collector is off.
        try:
            from nmb.collector import client as collector_client
            collector_client.start(lambda: self.cfg)
        except Exception as e:
            log.debug("collector client start error: %s", e)

        # Synchronize background DuckDNS DynDNS updater if enabled
        if getattr(self.cfg, "duckdns", None) and self.cfg.duckdns.enabled:
            try:
                from nmb.netd.duckdns import start_duckdns_service
                start_duckdns_service(lambda: self.cfg)
            except Exception as e:
                log.debug("duckdns start error: %s", e)

        # Synchronize background HTTPS / CONNECT Proxy server if enabled
        if getattr(self.cfg, "proxy", None) and self.cfg.proxy.enabled and not (
            self.cfg.proxy.auth_enabled and self.cfg.proxy.username and self.cfg.proxy.password
        ):
            log.warning("proxy not started: authentication is not configured")
        elif getattr(self.cfg, "proxy", None) and self.cfg.proxy.enabled:
            try:
                from nmb.netd.proxy import start_proxy_server
                start_proxy_server(
                    port=self.cfg.proxy.port,
                    auth_enabled=self.cfg.proxy.auth_enabled,
                    username=self.cfg.proxy.username,
                    password=self.cfg.proxy.password,
                    tls_enabled=self.cfg.proxy.tls_enabled,
                    tls_cert=self.cfg.web.tls_cert if self.cfg.proxy.tls_enabled else "",
                    tls_key=self.cfg.web.tls_key if self.cfg.proxy.tls_enabled else "",
                )
            except Exception as e:
                log.debug("proxy start error: %s", e)

        # Kernel tuning needs root: nmb-netd applies it. Only a root dev server does it here.
        if os.geteuid() == 0:
            try:
                from nmb.netd.kernel import apply_kernel_network_tuning
                threading.Thread(target=apply_kernel_network_tuning, daemon=True, name="nmb-kernel-tuner").start()
            except Exception as e:
                log.debug("kernel tuning background error: %s", e)

        host, port = self.server.server_address
        proto = "https" if getattr(self.server, "is_tls", False) else "http"
        log.info("NetworkMeasureBox web server listening on %s://%s:%d (AutonomousScheduler active)", proto, host, port)

        try:
            self.server.serve_forever()
        except Exception as e:
            if self.running:
                log.error("server error: %s", e)
        finally:
            if self.scheduler:
                self.scheduler.stop()
            try:
                from nmb.netd.duckdns import stop_duckdns_service
                stop_duckdns_service()
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            try:
                from nmb.netd.proxy import stop_proxy_server
                stop_proxy_server()
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            try:
                from nmb.report.invasive_logger import stop_invasive_background_logger
                stop_invasive_background_logger()
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            self.server.server_close()
            log.info("nmb-web server shutdown complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-web", description="NetworkMeasureBox Embedded Web Server")
    parser.add_argument("--config", "-c", help="Path to nmb.conf")
    parser.add_argument("--port", "-p", type=int, help="Port to bind (default: 80 from config)")
    parser.add_argument("--host", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.port:
        cfg.web.port = args.port
    if args.host:
        cfg.web.host = args.host

    from nmb.devlog import setup_dev_logging
    log_level = "DEBUG" if args.verbose else getattr(cfg.logging, "level", "DEBUG")
    setup_dev_logging(
        cfg=cfg,
        level=log_level,
        log_file=getattr(cfg.logging, "file_path", None),
        max_bytes=getattr(cfg.logging, "max_bytes", 10485760),
        backup_count=getattr(cfg.logging, "backup_count", 5),
        console=getattr(cfg.logging, "console_enabled", True),
    )

    daemon = WebDaemon(cfg)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
