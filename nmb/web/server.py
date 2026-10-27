"""Embedded, low-footprint web server and REST API for NetworkMeasureBox.

Built with Python's standard library http.server (zero third-party dependencies).
Serves dashboard UI, live status JSON, speedtest triggers, and dossier downloads.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import re
import secrets
import signal
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from nmb.config import Config, load_config, save_config, CONNECTION_TYPES
from nmb.db import database as db
from nmb.netd import interfaces, dns
from nmb.netd.drivers import get_full_driver_status, trigger_driver_install, get_driver_install_status, get_interfaces_matrix
from nmb.netd.os_detector import detect_os_info, get_dynamic_interfaces, check_updates_available, trigger_system_upgrade, get_upgrade_status
from nmb.netd.explorer import scan_network_devices, get_cached_devices, get_explorer_summary
from nmb.netd.guest_wifi import scan_wifi_networks, get_guest_wifi_status, connect_guest_wifi, disconnect_guest_wifi, sync_guest_wifi_connection
from nmb.netd.wifi import detect_wifi_capabilities, get_wifi_status
from nmb.report.csv_export import export_ping_summary_csv, export_speedtests_csv
from nmb.report.dossier import generate_html_dossier
from nmb.report.llm_bundle import generate_llm_diagnostic_bundle
from nmb.report.metrics import aggregate_report_data
from nmb.report.svg_charts import render_latency_chart
from nmb.sniffer.engine import get_sniffer
from nmb.speed.iperf import run_iperf_client_test, get_latest_iperf_result, is_iperf_running, start_iperf_server, stop_iperf_server, get_iperf_server_status
from nmb.speed.iperf_directory import fetch_public_iperf_servers, probe_iperf_server
from nmb.speed.ookla import get_available_servers
from nmb.speed.runner import run_measurement_cycle
from nmb.speed.scheduler import AutonomousScheduler, get_cron_description
from nmb.speed.traceroute import run_traceroute, get_latest_traceroute, is_traceroute_running
from nmb.web.i18n import get_translations_for_lang, TRANSLATIONS
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


class WebRequestHandler(BaseHTTPRequestHandler):
    server: NMBServer  # type hint

    def log_message(self, format: str, *args) -> None:
        msg = format % args
        log.debug("[HTTP] %s %s - %s", self.address_string(), getattr(self, "command", ""), msg)

    def _check_auth(self) -> bool:
        """Enforce HTTP Basic Authentication if auth_enabled is true with rate limiting."""
        if not self.server.cfg.web.auth_enabled:
            return True

        req_path = urlparse(self.path).path
        if req_path in ("/logout", "/api/auth/logout", "/api/i18n"):
            return True

        client_ip = self.client_address[0] if hasattr(self, "client_address") else self.address_string()
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
                if secrets.compare_digest(user, configured_user) and secrets.compare_digest(password, configured_pass):
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_text: str, status: int = 200) -> None:
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        # 0. Logout UI and Auth Purge Endpoints
        if path == "/logout":
            self._send_html(get_logout_html())
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

        # 1. Main Dashboard UI
        if path in ("/", "/index.html"):
            self._send_html(get_dashboard_html())
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
            if parsed.query:
                try:
                    qs = parse_qs(parsed.query)
                    q = qs.get("q", [""])[0] or qs.get("search", [""])[0]
                except Exception:
                    pass
            servers = get_available_servers(search_query=q, limit=100)
            self._send_json({"servers": servers, "count": len(servers)})
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

        # 7. Standalone Dossier Download
        if path in ("/dossier", "/dossier.html"):
            conn = db.connect(readonly=True)
            report = aggregate_report_data(conn, self.server.cfg, window_hours=24.0)
            conn.close()
            html = generate_html_dossier(report)
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

        # 9. DNS Status
        if path in ("/api/network/dns", "/api/dns"):
            self._send_json(dns.get_dns_status())
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
                    pass
            self._send_json({
                "lang": req_lang,
                "current_configured": self.server.cfg.web.language,
                "translations": get_translations_for_lang(req_lang),
                "available": list(TRANSLATIONS.keys()),
            })
            return

        # 11. Multi-OS & Hardware Info
        if path == "/api/system/info":
            self._send_json(detect_os_info())
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
            self._send_json(get_ooni_status())
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

        # 17b. DuckDNS DynDNS Status
        if path == "/api/duckdns/status":
            from nmb.netd.duckdns import get_duckdns_status
            self._send_json(get_duckdns_status())
            return

        # 17c. WireGuard VPN Status, Config & QR
        if path == "/api/wireguard/status":
            from nmb.netd.wireguard import get_wireguard_status
            cfg = self.server.cfg
            self._send_json(get_wireguard_status(
                port=cfg.wireguard.port,
                subnet=cfg.wireguard.subnet,
                subnet_ipv6=cfg.wireguard.subnet_ipv6,
                dns=cfg.wireguard.dns,
            ))
            return

        if path == "/api/wireguard/peer/config":
            from nmb.netd.wireguard import get_client_config
            qs = parse_qs(parsed.query) if parsed.query else {}
            peer_name = qs.get("name", [""])[0] or qs.get("id", [""])[0]
            endpoint = self.server.cfg.wireguard.public_endpoint or (self.server.cfg.duckdns.domain + ".duckdns.org" if self.server.cfg.duckdns.domain else "")
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
            from nmb.netd.wireguard import get_client_qr_data_uri, get_client_qr_png_bytes
            qs = parse_qs(parsed.query) if parsed.query else {}
            peer_name = qs.get("name", [""])[0] or qs.get("id", [""])[0]
            endpoint = self.server.cfg.wireguard.public_endpoint or (self.server.cfg.duckdns.domain + ".duckdns.org" if self.server.cfg.duckdns.domain else "")
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
            self._send_json({"status": "ok", "qr_data_uri": data_uri})
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
            wan_iface = self.server.cfg.network.wan_interface
            self._send_json(get_guest_wifi_status(guest_iface, wan_iface=wan_iface, cfg_guest=self.server.cfg.guest_wifi))
            return

        if path in ("/api/network/wifi/guest/scan", "/api/wifi/guest/scan"):
            guest_iface = getattr(self.server.cfg.guest_wifi, "interface", "wlan0")
            nets = scan_wifi_networks(guest_iface, force_rescan=True)
            self._send_json({"status": "ok", "interface": guest_iface, "networks": nets})
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

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

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
            if origin_parsed.netloc and origin_parsed.netloc != host:
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

        if length > MAX_BODY_SIZE:
            log.warning("[SECURITY] Rejected oversized POST body: %d bytes (limit: %d)", length, MAX_BODY_SIZE)
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Payload exceeds 1MB limit")
            return

        parsed = urlparse(self.path)
        path = parsed.path

        raw_body = self.rfile.read(length) if length > 0 else b"{}"

        try:
            body_json = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            body_json = {}

        # 1. Trigger Speedtest (Asynchronous with state tracking)
        if path == "/api/speedtest":
            raw_sid = body_json.get("server_id")
            engine = str(body_json.get("engine", "ookla")).strip().lower()
            if engine not in ("ookla", "cloudflare", "rtr", "iperf3", "all"):
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
            if engine in ("ookla", "cloudflare", "rtr", "iperf3", "all"):
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
                self.server.cfg.speedtest.schedule_cron = str(sched_cron).strip()
            if auto_eng and str(auto_eng).strip():
                self.server.cfg.speedtest.automated_engine = str(auto_eng).strip().lower()
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
                msg_parts.append(f"Interval: {get_cron_description(str(sched_cron), user_lang)}.")
            if thresh_pct is not None:
                msg_parts.append(f"Idle gate: < {self.server.cfg.speedtest.idle_threshold_percent:.1f}% network load.")

            msg = " ".join(msg_parts) if msg_parts else "Measurement settings saved successfully."
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
                "schedule_mode": self.server.cfg.speedtest.schedule_mode,
                "schedule_cron": self.server.cfg.speedtest.schedule_cron,
                "automated_engine": self.server.cfg.speedtest.automated_engine,
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

            ok, msg = connect_guest_wifi(ssid=ssid, password=password, iface=guest_iface, metric=metric)
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
            import subprocess
            def _reboot_delayed():
                import time
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
            is_bidir = bidir_req or (direction_req in ("bidir", "both", "duplex", "full-duplex"))

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

            def _async_iperf():
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
                    "direction": "bidir" if is_bidir else ("down" if reverse else "up"),
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
            res = apply_kernel_network_tuning()
            status_data = get_kernel_network_status()
            self._send_json({
                "status": "ok",
                "message": "Kernel network performance optimizations applied successfully.",
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

            if is_traceroute_running():
                self._send_json({"status": "busy", "message": "Traceroute already in progress."}, status=409)
                return

            def _async_traceroute():
                try:
                    run_traceroute(host=target_host, max_hops=max_hops)
                except Exception as e:
                    log.error("Traceroute execution error: %s", e)

            threading.Thread(target=_async_traceroute, daemon=True, name="nmb-traceroute-worker").start()
            self._send_json({
                "status": "started",
                "message": f"Traceroute started to {target_host} (max {max_hops} hops)",
                "target": target_host,
            })
            return

        # 11b. OONI Probe Censorship Test Run
        if path == "/api/ooni/run":
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
            pkg = body_json.get("package", "all")
            res = trigger_driver_install(pkg)
            self._send_json(res)
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
            if "guest" in body_json:
                cfg.guest_wifi.interface = str(body_json["guest"]).strip()
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
            from nmb.devlog import purge_all_logs
            inc_db = bool(body_json.get("include_db", True))
            inc_journal = bool(body_json.get("include_journal", True))
            result = purge_all_logs(include_database_events=inc_db, include_system_journal=inc_journal)
            self._send_json(result)
            return

        # 16. DuckDNS DynDNS Settings & Update
        if path == "/api/duckdns/save":
            from nmb.netd.duckdns import start_duckdns_service, stop_duckdns_service
            enabled = bool(body_json.get("enabled", False))
            domain = str(body_json.get("domain", "")).strip()
            token = str(body_json.get("token", "")).strip()
            interval = int(body_json.get("update_interval_min", 10))
            custom_ip = str(body_json.get("custom_ip", "")).strip()

            self.server.cfg.duckdns.enabled = enabled
            self.server.cfg.duckdns.domain = domain
            if token:
                self.server.cfg.duckdns.token = token
            self.server.cfg.duckdns.update_interval_min = interval
            self.server.cfg.duckdns.custom_ip = custom_ip
            save_config(self.server.cfg)

            if enabled:
                start_duckdns_service(lambda: self.server.cfg)
                from nmb.netd.duckdns import update_duckdns
                res = update_duckdns(domain=domain, token=self.server.cfg.duckdns.token, ip=custom_ip or None)
                self._send_json({"status": "ok", "message": "DuckDNS settings saved & update triggered", "detail": res})
            else:
                stop_duckdns_service()
                self._send_json({"status": "ok", "message": "DuckDNS updater disabled"})
            return

        if path == "/api/duckdns/update":
            from nmb.netd.duckdns import update_duckdns
            d_cfg = self.server.cfg.duckdns
            if not d_cfg.domain or not d_cfg.token:
                self._send_json({"status": "error", "message": "DuckDNS domain and token are not configured."}, status=400)
                return
            res = update_duckdns(domain=d_cfg.domain, token=d_cfg.token, ip=d_cfg.custom_ip or None)
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
            dns = str(body_json.get("dns", "")).strip()

            self.server.cfg.proxy.enabled = enabled
            self.server.cfg.proxy.port = port
            self.server.cfg.proxy.auth_enabled = auth_enabled
            self.server.cfg.proxy.username = username
            if password:
                self.server.cfg.proxy.password = password
            self.server.cfg.proxy.tls_enabled = tls_enabled
            self.server.cfg.proxy.listen_ipv6 = listen_ipv6
            if dns or "dns" in body_json:
                self.server.cfg.proxy.dns = dns
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
        for eng in ("ookla", "cloudflare", "rtr", "iperf3"):
            row = conn.execute(
                """SELECT ts, trigger, status, server_name, server_host, server_location, client_ip, client_ipv6,
                          down_bps, up_bps, ping_us, jitter_us, loss_pct, result_url, error,
                          down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms, connection_type,
                          engine, colo
                   FROM speedtest
                   WHERE LOWER(engine) = ?
                   ORDER BY ts DESC LIMIT 1""",
                (eng,)
            ).fetchone()
            if row:
                d = dict(row)
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
            pass

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
                "mac_address": interfaces.get_mac_address(wan_iface) or "24:F5:A2:C5:A9:90",
                "public_ipv4": dual_v4,
                "public_ipv6": dual_v6,
                "public_ip": dual_v4 or dual_v6,
                "wps_pin": "76658594",
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
                "country": getattr(self.server.cfg.network, "wifi_country_code", "HU"),
                "security": getattr(self.server.cfg.network, "wifi_security", "wpa2"),
                "capabilities": detect_wifi_capabilities(self.server.cfg.network.wlan_interface),
                "live_status": get_wifi_status(self.server.cfg.network.wlan_interface),
            },
            "uptime_pct": report.uptime_pct,
            "outages_count": len(report.outages),
            "total_outage_sec": report.total_outage_sec,
            "bufferbloat": latest_bb,
            "latest_speedtest": report.speed_tests[0] if report.speed_tests else None,
            "schedule_mode": getattr(self.server.cfg.speedtest, "schedule_mode", "scheduled"),
            "schedule_cron": getattr(self.server.cfg.speedtest, "schedule_cron", "0 */6 * * *"),
            "schedule_cron_desc": get_cron_description(getattr(self.server.cfg.speedtest, "schedule_cron", "0 */6 * * *"), getattr(self.server.cfg.web, "language", "en")),
            "automated_engine": getattr(self.server.cfg.speedtest, "automated_engine", "ookla"),
            "idle_threshold_mode": getattr(self.server.cfg.speedtest, "idle_threshold_mode", "percent"),
            "idle_threshold_percent": getattr(self.server.cfg.speedtest, "idle_threshold_percent", 2.0),
            "idle_threshold_kbps": getattr(self.server.cfg.speedtest, "idle_threshold_kbps", 500),
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
            "speed_tests": report.speed_tests[:25],
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
            "wifi_band": getattr(cfg.network, "wifi_band", "auto"),
            "wifi_standard": getattr(cfg.network, "wifi_standard", "auto"),
            "wifi_channel": cfg.network.wifi_channel,
            "wifi_channel_width": getattr(cfg.network, "wifi_channel_width", "auto"),
            "wifi_country_code": getattr(cfg.network, "wifi_country_code", "HU"),
            "wifi_security": getattr(cfg.network, "wifi_security", "wpa2"),
            "wifi_capabilities": detect_wifi_capabilities(cfg.network.wlan_interface),
            "guest_wifi_enabled": getattr(cfg.guest_wifi, "enabled", False),
            "guest_wifi_interface": getattr(cfg.guest_wifi, "interface", "wlan0"),
            "guest_wifi_ssid": getattr(cfg.guest_wifi, "ssid", ""),
            "guest_wifi_password": getattr(cfg.guest_wifi, "password", ""),
            "guest_wifi_security": getattr(cfg.guest_wifi, "security", "auto"),
            "guest_wifi_metric": getattr(cfg.guest_wifi, "metric", 600),
            "guest_wifi_auto_reconnect": getattr(cfg.guest_wifi, "auto_reconnect", True),
            "schedule_mode": getattr(cfg.speedtest, "schedule_mode", "scheduled"),
            "schedule_cron": getattr(cfg.speedtest, "schedule_cron", "0 */6 * * *"),
            "automated_engine": getattr(cfg.speedtest, "automated_engine", "ookla"),
            "idle_threshold_mode": getattr(cfg.speedtest, "idle_threshold_mode", "percent"),
            "idle_threshold_percent": getattr(cfg.speedtest, "idle_threshold_percent", 2.0),
            "idle_threshold_kbps": getattr(cfg.speedtest, "idle_threshold_kbps", 500),
            "idle_check_kbps": getattr(cfg.speedtest, "idle_threshold_kbps", 500),
            "speedtest_server_id": getattr(cfg.speedtest, "server_id", None),
            "speedtest_server_name": getattr(cfg.speedtest, "server_name", ""),
            "speedtest_server_host": getattr(cfg.speedtest, "server_host", ""),
            "sqm_algorithm": getattr(cfg.system, "sqm_algorithm", "cake"),
            "auth_enabled": bool(getattr(cfg.web, "auth_enabled", True)),
            "admin_username": getattr(cfg.web, "admin_username", "admin"),
            "language": getattr(cfg.web, "language", "en"),
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
        if "guest_wifi_password" in body:
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
                cfg.speedtest.schedule_cron = sc
        if "automated_engine" in body:
            ae = str(body["automated_engine"]).strip().lower()
            if ae in ("ookla", "cloudflare", "rtr", "iperf3", "all"):
                cfg.speedtest.automated_engine = ae
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
        if "memory_profile" in body:
            cfg.system.memory_profile = str(body["memory_profile"]).strip().lower()
        if "admin_username" in body and str(body["admin_username"]).strip():
            cfg.web.admin_username = str(body["admin_username"]).strip()
        if "admin_password" in body and body["admin_password"]:
            cfg.web.admin_password = str(body["admin_password"])
        if "language" in body and str(body["language"]).strip() in TRANSLATIONS:
            cfg.web.language = str(body["language"]).strip()

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

    def _notify_daemon_reload(self) -> None:
        """Send SIGHUP to nmb-netd and nmb-telegram if running."""
        # 1. netd SIGHUP via pidfile
        netd_pid_file = self.server.cfg.system.run_dir / "netd.pid"
        if netd_pid_file.exists():
            try:
                pid = int(netd_pid_file.read_text().strip())
                os.kill(pid, signal.SIGHUP)
                log.info("sent SIGHUP to nmb-netd (pid %d)", pid)
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
            pass
    dmi = Path("/sys/devices/virtual/dmi/id/product_name")
    if dmi.exists():
        try:
            val = dmi.read_text(errors="ignore").strip()
            if val and val != "None":
                return val
        except Exception:
            pass
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
        addr = (cfg.web.host, cfg.web.port)
        super().__init__(addr, WebRequestHandler)

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

        # Synchronize background Guest Wi-Fi client station connection if enabled
        sync_guest_wifi_connection(self.cfg)

        # Synchronize background DuckDNS DynDNS updater if enabled
        if getattr(self.cfg, "duckdns", None) and self.cfg.duckdns.enabled:
            try:
                from nmb.netd.duckdns import start_duckdns_service
                start_duckdns_service(lambda: self.cfg)
            except Exception as e:
                log.debug("duckdns start error: %s", e)

        # Synchronize background HTTPS / CONNECT Proxy server if enabled
        if getattr(self.cfg, "proxy", None) and self.cfg.proxy.enabled:
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

        # Enforce kernel network performance tuning and multi-core RPS softirq steering
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
                pass
            try:
                from nmb.netd.proxy import stop_proxy_server
                stop_proxy_server()
            except Exception:
                pass
            self.server.server_close()
            log.info("nmb-web server shutdown complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-web", description="NetworkMeasureBox Embedded Web Server")
    parser.add_argument("--config", "-c", help="Path to nmb.conf")
    parser.add_argument("--port", "-p", type=int, help="Port to bind (default: 8080)")
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
