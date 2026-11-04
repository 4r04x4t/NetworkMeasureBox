"""
DuckDNS Dynamic DNS (DynDNS) Client for NetworkMeasureBox.

Periodically synchronizes the device's public WAN IP address with DuckDNS.org
independent of operational network mode (standalone, active gateway, or passive bridge).
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("nmb.netd.duckdns")

_duckdns_lock = threading.Lock()
_duckdns_thread: Optional[threading.Thread] = None
_duckdns_stop_event = threading.Event()
_duckdns_wake_event = threading.Event()
_cfg_getter: Optional[Callable[[], Any]] = None

_duckdns_state: Dict[str, Any] = {
    "enabled": False,
    "running": False,
    "domain": "",
    "fqdn": "",
    "token_set": False,
    "update_interval_min": 10,
    "interval_min": 10,
    "custom_ip": "",
    "last_update_ts": 0.0,
    "last_status": "never_run",
    "last_ip": "",
    "detected_ip": "",
    "last_ipv6": "",
    "last_message": "",
    "next_update_ts": 0.0,
    "consecutive_failures": 0,
    "last_saved_ts": 0.0,
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
                _duckdns_state["last_status"] = "OK" if is_ok else "KO"
                _duckdns_state["last_ip"] = detected_ip
                _duckdns_state["detected_ip"] = detected_ip
                _duckdns_state["last_ipv6"] = detected_ipv6
                _duckdns_state["last_message"] = msg
                _duckdns_state["domain"] = clean_dom
                _duckdns_state["fqdn"] = f"{clean_dom}.duckdns.org"
                if is_ok:
                    _duckdns_state["consecutive_failures"] = 0
                else:
                    _duckdns_state["consecutive_failures"] += 1

            log.info("DuckDNS update for [%s]: %s (IP: %s)", clean_dom, status_str, detected_ip or "auto")
            return {
                "status": "ok" if is_ok else "error",
                "success": is_ok,
                "domain": clean_dom,
                "fqdn": f"{clean_dom}.duckdns.org",
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
            "success": False,
            "domain": clean_dom,
            "fqdn": f"{clean_dom}.duckdns.org",
            "message": f"Connection error contacting DuckDNS: {e}",
            "timestamp": ts,
        }


def wake_duckdns_daemon() -> None:
    """Signal background DuckDNS daemon to wake up immediately and apply new interval/config."""
    _duckdns_wake_event.set()


def reload_duckdns_service(cfg_getter: Optional[Callable[[], Any]] = None) -> None:
    """Update config reference and wake daemon instantly."""
    global _cfg_getter
    if cfg_getter is not None:
        _cfg_getter = cfg_getter
    wake_duckdns_daemon()


def get_duckdns_status(cfg: Optional[Any] = None) -> Dict[str, Any]:
    """Retrieve current DuckDNS DynDNS status snapshot, augmented with authoritative config."""
    global _cfg_getter
    if cfg is None and _cfg_getter is not None:
        try:
            cfg = _cfg_getter()
        except Exception:
            cfg = None

    with _duckdns_lock:
        state = dict(_duckdns_state)

    if cfg is not None and getattr(cfg, "duckdns", None):
        d_cfg = cfg.duckdns
        state["enabled"] = bool(d_cfg.enabled)
        dom = clean_domain(d_cfg.domain) if d_cfg.domain else state.get("domain", "")
        state["domain"] = dom
        state["fqdn"] = f"{dom}.duckdns.org" if dom else ""
        state["token_set"] = bool(d_cfg.token)
        try:
            interval = max(1, int(d_cfg.update_interval_min))
        except (ValueError, TypeError):
            interval = 10
        state["update_interval_min"] = interval
        state["interval_min"] = interval
        state["custom_ip"] = d_cfg.custom_ip or ""

    now = time.time()
    last_ts = state.get("last_update_ts", 0.0)
    next_ts = state.get("next_update_ts", 0.0)
    interval_m = state.get("update_interval_min", 10)

    if state.get("enabled") and last_ts > 0 and interval_m > 0:
        expected_next = last_ts + (interval_m * 60)
        if next_ts <= 0 or abs(next_ts - expected_next) > 3.0:
            next_ts = expected_next
            state["next_update_ts"] = next_ts

    state["detected_ip"] = state.get("last_ip", "")
    state["running"] = bool(_duckdns_thread and _duckdns_thread.is_alive())

    if last_ts > 0:
        state["last_update"] = datetime.datetime.fromtimestamp(last_ts).isoformat(timespec="seconds")
    else:
        state["last_update"] = ""

    if next_ts > 0:
        state["next_update"] = datetime.datetime.fromtimestamp(next_ts).isoformat(timespec="seconds")
        state["next_update_seconds"] = max(0, int(next_ts - now))
    else:
        state["next_update"] = ""
        state["next_update_seconds"] = 0

    return state


def run_duckdns_daemon(cfg_getter: Callable[[], Any], stop_event: threading.Event) -> None:
    """Background loop to keep DuckDNS synchronized on strict schedule."""
    log.info("DuckDNS updater background loop started")
    while not stop_event.is_set():
        try:
            _duckdns_wake_event.clear()
            cfg = cfg_getter()
            duck_cfg = getattr(cfg, "duckdns", None)
            if not duck_cfg or not duck_cfg.enabled or not duck_cfg.token or not duck_cfg.domain:
                with _duckdns_lock:
                    _duckdns_state["enabled"] = False
                    _duckdns_state["running"] = True
                    _duckdns_state["next_update_ts"] = 0.0
                # Wait 15 seconds or until woken by config change
                _duckdns_wake_event.wait(timeout=15.0)
                continue

            raw_min = getattr(duck_cfg, "update_interval_min", 10)
            try:
                interval_min = max(1, int(raw_min))
            except (ValueError, TypeError):
                interval_min = 10
            interval_sec = interval_min * 60

            clean_dom = clean_domain(duck_cfg.domain)
            now = time.time()
            last_ts = _duckdns_state.get("last_update_ts", 0.0)
            time_since_last = now - last_ts if last_ts > 0 else float("inf")

            with _duckdns_lock:
                _duckdns_state["enabled"] = True
                _duckdns_state["running"] = True
                _duckdns_state["domain"] = clean_dom
                _duckdns_state["fqdn"] = f"{clean_dom}.duckdns.org" if clean_dom else ""
                _duckdns_state["token_set"] = bool(duck_cfg.token)
                _duckdns_state["update_interval_min"] = interval_min
                _duckdns_state["interval_min"] = interval_min
                _duckdns_state["custom_ip"] = duck_cfg.custom_ip or ""

            # Check if an update is due
            if time_since_last >= interval_sec:
                detected_v6 = None
                try:
                    from nmb.netd.wireguard import get_device_addresses
                    _, v6_addrs = get_device_addresses()
                    if v6_addrs:
                        detected_v6 = v6_addrs[0][1]
                except Exception:
                    pass

                update_duckdns(
                    domain=duck_cfg.domain,
                    token=duck_cfg.token,
                    ip=duck_cfg.custom_ip if duck_cfg.custom_ip else None,
                    ipv6=detected_v6,
                )
                now = time.time()
                with _duckdns_lock:
                    if _duckdns_state.get("last_update_ts", 0.0) < now - 5.0:
                        _duckdns_state["last_update_ts"] = now

            # Recalculate remaining sleep time until next scheduled cycle
            last_ts = _duckdns_state.get("last_update_ts", 0.0)
            time_since_last = time.time() - last_ts if last_ts > 0 else float("inf")
            remaining = max(1.0, interval_sec - time_since_last)

            with _duckdns_lock:
                _duckdns_state["next_update_ts"] = time.time() + remaining

            # Sleep for remaining seconds, or wake instantly on config change or shutdown
            _duckdns_wake_event.wait(timeout=remaining)

        except Exception as e:
            log.error("error in duckdns loop: %s", e)
            _duckdns_wake_event.wait(timeout=30.0)

    with _duckdns_lock:
        _duckdns_state["running"] = False
    log.info("DuckDNS updater background loop stopped")


def start_duckdns_service(cfg_getter: Callable[[], Any]) -> None:
    """Start or reload background DuckDNS service thread."""
    global _duckdns_thread, _cfg_getter
    _cfg_getter = cfg_getter
    _duckdns_stop_event.clear()
    if _duckdns_thread and _duckdns_thread.is_alive():
        wake_duckdns_daemon()
        return
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
    _duckdns_wake_event.set()
    if _duckdns_thread and _duckdns_thread.is_alive():
        _duckdns_thread.join(timeout=2.0)
    _duckdns_thread = None
    with _duckdns_lock:
        _duckdns_state["enabled"] = False
        _duckdns_state["running"] = False
        _duckdns_state["next_update_ts"] = 0.0
