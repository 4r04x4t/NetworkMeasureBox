"""
DuckDNS Dynamic DNS (DynDNS) Client for NetworkMeasureBox.

Periodically synchronizes the device's public WAN IP address with DuckDNS.org
independent of operational network mode (standalone, active gateway, or passive bridge).
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("nmb.netd.duckdns")

_duckdns_lock = threading.Lock()
_duckdns_thread: Optional[threading.Thread] = None
_duckdns_stop_event = threading.Event()

_duckdns_state: Dict[str, Any] = {
    "enabled": False,
    "domain": "",
    "token_set": False,
    "last_update_ts": 0.0,
    "last_status": "never_run",
    "last_ip": "",
    "last_ipv6": "",
    "last_message": "",
    "next_update_ts": 0.0,
    "consecutive_failures": 0,
}

IP_DETECTORS_V4 = [
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
]


def clean_domain(domain: str) -> str:
    """Normalize DuckDNS domain (e.g. 'mybox.duckdns.org' -> 'mybox')."""
    d = domain.strip().lower()
    if d.endswith(".duckdns.org"):
        d = d[:-12]
    return d


def detect_public_ip(timeout: float = 4.0) -> Optional[str]:
    """Detect current public WAN IPv4 address."""
    for url in IP_DETECTORS_V4:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "NetworkMeasureBox-DuckDNS/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    ip = resp.read().decode("utf-8", errors="ignore").strip()
                    if ip and (ip.count(".") == 3 or ":" in ip):
                        return ip
        except Exception as e:
            log.debug("failed to detect public IP from %s: %s", url, e)
            continue
    return None


def update_duckdns(
    domain: str,
    token: str,
    ip: Optional[str] = None,
    ipv6: Optional[str] = None,
    clear: bool = False,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Execute DuckDNS HTTP update query and update internal status."""
    clean_dom = clean_domain(domain)
    clean_tok = token.strip()

    if not clean_dom or not clean_tok:
        return {"status": "error", "message": "Domain and token are required."}

    params: Dict[str, str] = {
        "domains": clean_dom,
        "token": clean_tok,
        "verbose": "true",
    }
    if clear:
        params["clear"] = "true"
    else:
        if ip:
            params["ip"] = ip.strip()
        if ipv6:
            params["ipv6"] = ipv6.strip()

    query_str = urllib.parse.urlencode(params)
    url = f"https://www.duckdns.org/update?{query_str}"

    ts = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NetworkMeasureBox/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore").strip()
            lines = [l.strip() for l in body.splitlines() if l.strip()]

            is_ok = len(lines) > 0 and lines[0].upper() == "OK"
            detected_ip = lines[1] if len(lines) > 1 and lines[1] else (ip or "")
            detected_ipv6 = lines[2] if len(lines) > 2 and lines[2] else (ipv6 or "")
            updated = len(lines) > 3 and lines[3].upper() == "UPDATED"

            status_str = "OK" if is_ok else "KO"
            msg = f"DuckDNS response: {status_str}" + (" (IP Updated)" if updated else " (IP Unchanged)") if is_ok else "DuckDNS update rejected (check token/domain)"

            with _duckdns_lock:
                _duckdns_state["last_update_ts"] = ts
                _duckdns_state["last_status"] = "success" if is_ok else "failed"
                _duckdns_state["last_ip"] = detected_ip
                _duckdns_state["last_ipv6"] = detected_ipv6
                _duckdns_state["last_message"] = msg
                if is_ok:
                    _duckdns_state["consecutive_failures"] = 0
                else:
                    _duckdns_state["consecutive_failures"] += 1

            log.info("DuckDNS update for [%s]: %s (IP: %s)", clean_dom, status_str, detected_ip or "auto")
            return {
                "status": "ok" if is_ok else "error",
                "domain": clean_dom,
                "ip": detected_ip,
                "ipv6": detected_ipv6,
                "updated": updated,
                "message": msg,
                "timestamp": ts,
            }

    except Exception as e:
        log.error("DuckDNS request failed: %s", e)
        with _duckdns_lock:
            _duckdns_state["last_update_ts"] = ts
            _duckdns_state["last_status"] = "error"
            _duckdns_state["last_message"] = f"Network error: {e}"
            _duckdns_state["consecutive_failures"] += 1

        return {
            "status": "error",
            "domain": clean_dom,
            "message": f"Connection error contacting DuckDNS: {e}",
            "timestamp": ts,
        }


def get_duckdns_status() -> Dict[str, Any]:
    """Retrieve current DuckDNS DynDNS status snapshot."""
    with _duckdns_lock:
        state = dict(_duckdns_state)
    return state


def run_duckdns_daemon(cfg_getter, stop_event: threading.Event) -> None:
    """Background polling loop to keep DuckDNS in sync."""
    log.info("DuckDNS updater background loop started")
    while not stop_event.is_set():
        try:
            cfg = cfg_getter()
            duck_cfg = getattr(cfg, "duckdns", None)
            if not duck_cfg or not duck_cfg.enabled or not duck_cfg.token or not duck_cfg.domain:
                with _duckdns_lock:
                    _duckdns_state["enabled"] = False
                    _duckdns_state["next_update_ts"] = 0.0
                stop_event.wait(15)
                continue

            interval_sec = max(duck_cfg.update_interval_min * 60, 120)
            with _duckdns_lock:
                _duckdns_state["enabled"] = True
                _duckdns_state["domain"] = clean_domain(duck_cfg.domain)
                _duckdns_state["token_set"] = bool(duck_cfg.token)
                _duckdns_state["next_update_ts"] = time.time() + interval_sec

            # Perform update
            update_duckdns(
                domain=duck_cfg.domain,
                token=duck_cfg.token,
                ip=duck_cfg.custom_ip if duck_cfg.custom_ip else None,
            )

            # Sleep until next check or stop requested
            stop_event.wait(interval_sec)

        except Exception as e:
            log.error("error in duckdns loop: %s", e)
            stop_event.wait(30)


def start_duckdns_service(cfg_getter) -> None:
    """Start background DuckDNS service thread."""
    global _duckdns_thread
    if _duckdns_thread and _duckdns_thread.is_alive():
        return
    _duckdns_stop_event.clear()
    _duckdns_thread = threading.Thread(
        target=run_duckdns_daemon,
        args=(cfg_getter, _duckdns_stop_event),
        name="nmb-duckdns-updater",
        daemon=True,
    )
    _duckdns_thread.start()


def stop_duckdns_service() -> None:
    """Stop background DuckDNS service thread."""
    global _duckdns_thread
    _duckdns_stop_event.set()
    if _duckdns_thread and _duckdns_thread.is_alive():
        _duckdns_thread.join(timeout=2.0)
    _duckdns_thread = None
