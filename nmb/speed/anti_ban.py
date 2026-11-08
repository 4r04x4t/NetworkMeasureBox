"""Ookla Speedtest Anti-Ban, Rate-Limit Protection & Server Fleet Circuit Breaker.

Provides automated safeguards against temporary IP/server bans by Ookla:
1. Ban & 429 signature detection in CLI stderr and API responses.
2. Dynamic Server Quarantine (cooldown periods for rate-limited servers).
3. Anti-hotspotting server pool rotation across top regional low-latency targets.
4. Seamless Circuit Breaker: Automatically falls back to RTR-NetTest or Cloudflare Edge
   when Ookla rate limits are detected, ensuring uninterrupted measurement history.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.speed.anti_ban")

# Quarantined server registry: server_id -> unquarantine_timestamp (monotonic)
_quarantined_servers: Dict[int, float] = {}
_server_history: Dict[int, float] = {}  # server_id -> last_attempt_timestamp
_lock = threading.Lock()

BAN_SIGNATURES = [
    "429",
    "too many requests",
    "rate limit",
    "rate-limit",
    "banned",
    "throttled",
    "blocked",
    "selection failed",
    "could not retrieve speedtest configuration",
    "configuration - could not retrieve",
    "forbidden",
    "refused by server",
    "connection refused",
    "temporarily unavailable",
    "socket error",
]


def is_ookla_ban_error(error_text: Optional[str], return_code: Optional[int] = None) -> Tuple[bool, str]:
    """Detect if an error or stderr output matches known Ookla rate-limit or ban signatures."""
    if not error_text and return_code is None:
        return False, ""

    txt = (error_text or "").lower()
    for sig in BAN_SIGNATURES:
        if sig in txt:
            return True, f"Detected Ookla rate limit / ban signature: '{sig}'"

    # Returncode 1 or 2 with empty or generic failure when server was specified
    if return_code in (1, 2) and any(w in txt for w in ("server", "connect", "timeout", "network", "resolve")):
        return True, f"Ookla server connection failure (code {return_code}): {txt[:80]}"

    return False, ""


def quarantine_server(server_id: int, duration_sec: int = 7200, reason: str = "") -> None:
    """Quarantine a specific Ookla server so automated runs avoid it during cooldown."""
    until = time.monotonic() + duration_sec
    with _lock:
        _quarantined_servers[server_id] = until
    log.warning("quarantining Ookla server %d for %ds (reason: %s)", server_id, duration_sec, reason or "rate limit")

    # Log to SQLite event table if possible
    try:
        from nmb.db import database as db
        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warn', 'speed', 'ookla_quarantine', ?)",
                (db.now_ms(), f"Ookla server #{server_id} temporarily quarantined ({duration_sec // 60} min) to avoid a ban: {reason}")
            )
        conn.close()
    except Exception as e:
        log.debug("could not write quarantine event to db: %s", e)


def is_server_quarantined(server_id: int) -> bool:
    """Check if a server ID is currently in the quarantine cooldown window."""
    now = time.monotonic()
    with _lock:
        if server_id in _quarantined_servers:
            if now < _quarantined_servers[server_id]:
                return True
            else:
                del _quarantined_servers[server_id]
    return False


def get_quarantined_servers() -> Dict[int, float]:
    """Return dictionary of quarantined server IDs with remaining seconds."""
    now = time.monotonic()
    result: Dict[int, float] = {}
    with _lock:
        expired = []
        for sid, until in _quarantined_servers.items():
            if now < until:
                result[sid] = round(until - now, 1)
            else:
                expired.append(sid)
        for sid in expired:
            del _quarantined_servers[sid]
    return result


def clear_quarantine() -> None:
    """Clear all quarantined servers and the client rate-limit cooldown."""
    global _client_limited_until, _client_cooldown_sec, _client_last_attempt
    with _lock:
        _quarantined_servers.clear()
        _client_limited_until = 0.0
        _client_cooldown_sec = CLIENT_COOLDOWN_MIN_SEC
        _client_last_attempt = 0.0
        _save_cooldown()
    log.info("cleared all Ookla server quarantines and the client cooldown")


# Ookla's CLI limits the whole client ("Limit reached: Too many requests"), not one
# server. Trying another server only spends more requests, so the client waits instead.
CLIENT_LIMIT_SIGNATURES = ("limit reached", "too many requests", "429")
CLIENT_COOLDOWN_MIN_SEC = 1800
CLIENT_COOLDOWN_MAX_SEC = 4 * 3600
# Kept in a file with wall-clock times: a restart must not ask Ookla again early, since
# every early request makes Ookla's block longer. The web server and nmb-speed share it.
CLIENT_COOLDOWN_FILE = Path(os.environ.get("NMB_OOKLA_COOLDOWN_FILE", "/var/lib/nmb/ookla_cooldown.json"))
_client_limited_until = 0.0
_client_cooldown_sec = CLIENT_COOLDOWN_MIN_SEC
_client_last_attempt = 0.0


def _load_cooldown() -> None:
    global _client_limited_until, _client_cooldown_sec, _client_last_attempt
    try:
        data = json.loads(CLIENT_COOLDOWN_FILE.read_text())
        until = float(data.get("until", 0.0))
        length = int(data.get("length", CLIENT_COOLDOWN_MIN_SEC))
        last = float(data.get("last", 0.0))
    except (OSError, ValueError, TypeError, AttributeError):
        return
    _client_last_attempt = min(last, time.time())
    # A clock set far back must not pause Ookla for longer than the longest cooldown.
    _client_limited_until = min(until, time.time() + CLIENT_COOLDOWN_MAX_SEC)
    _client_cooldown_sec = max(CLIENT_COOLDOWN_MIN_SEC, min(length, CLIENT_COOLDOWN_MAX_SEC))


def _save_cooldown() -> None:
    try:
        CLIENT_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CLIENT_COOLDOWN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"until": _client_limited_until, "length": _client_cooldown_sec,
                                   "last": _client_last_attempt}))
        os.replace(tmp, CLIENT_COOLDOWN_FILE)
    except OSError as e:
        log.debug("could not save the Ookla cooldown: %s", e)


def is_client_rate_limit(error_text: Optional[str]) -> bool:
    """True when Ookla refused this client for sending too many tests."""
    txt = (error_text or "").lower()
    return any(sig in txt for sig in CLIENT_LIMIT_SIGNATURES)


def mark_client_rate_limited() -> int:
    """Start (or double) the client cooldown; returns its length in seconds."""
    global _client_limited_until, _client_cooldown_sec
    with _lock:
        _load_cooldown()
        if _client_limited_until > 0.0:
            _client_cooldown_sec = min(_client_cooldown_sec * 2, CLIENT_COOLDOWN_MAX_SEC)
        duration = _client_cooldown_sec
        _client_limited_until = time.time() + duration
        _save_cooldown()
    log.warning("Ookla rate-limited this box; pausing Ookla tests for %d min", duration // 60)
    return duration


def mark_client_ok() -> None:
    """A successful Ookla test ends the cooldown back-off."""
    global _client_limited_until, _client_cooldown_sec
    with _lock:
        _client_limited_until = 0.0
        _client_cooldown_sec = CLIENT_COOLDOWN_MIN_SEC
        _save_cooldown()


def client_cooldown_remaining() -> float:
    """Seconds left before Ookla may be asked again (0 when it may)."""
    with _lock:
        _load_cooldown()
        return max(0.0, _client_limited_until - time.time())


def record_server_attempt(server_id: int) -> None:
    """Record that an Ookla server was attempted."""
    with _lock:
        _server_history[server_id] = time.monotonic()


def get_smart_rotated_server(target_server_id: Optional[int] = None) -> Optional[int]:
    """Select the next optimal, non-quarantined Ookla server from the local regional pool.

    If target_server_id is given and not quarantined, verifies it. If it is quarantined
    or None, picks the least recently used healthy server from the nearby fleet.
    """
    if target_server_id is not None and not is_server_quarantined(target_server_id):
        return target_server_id

    if target_server_id is not None and is_server_quarantined(target_server_id):
        log.info("designated Ookla server %d is quarantined; selecting non-banned alternative from fleet", target_server_id)

    # Fetch available low-latency servers
    try:
        from nmb.speed.ookla import get_available_servers
        servers = get_available_servers(limit=30)
    except Exception as e:
        log.warning("failed to fetch available servers for rotation: %s", e)
        return None

    if not servers:
        return None

    now = time.monotonic()
    candidates = []
    with _lock:
        for s in servers:
            sid = s.get("id")
            if not sid:
                continue
            if sid in _quarantined_servers and now < _quarantined_servers[sid]:
                continue
            last_ts = _server_history.get(sid, 0.0)
            candidates.append((last_ts, sid))

    if not candidates:
        log.warning("all candidate Ookla servers are quarantined; clearing quarantine window")
        clear_quarantine()
        return servers[0].get("id")

    # Pick the least recently attempted server (lowest last_ts)
    candidates.sort(key=lambda x: x[0])
    chosen_id = candidates[0][1]
    log.info("smart server rotation selected Ookla server %d (least recently used)", chosen_id)
    return chosen_id



# Ookla refuses a client that tests too often. Hourly has worked on the developer's
# box; per-minute tests were refused within the hour.
OOKLA_SAFE_INTERVAL_SEC = 3600


def record_client_attempt() -> None:
    """Note that Ookla is being asked now (for the hourly limit of scheduled tests)."""
    global _client_last_attempt
    with _lock:
        _load_cooldown()
        _client_last_attempt = time.time()
        _save_cooldown()


def scheduled_wait_remaining(interval_sec: float = OOKLA_SAFE_INTERVAL_SEC) -> float:
    """Seconds before a scheduled Ookla test may run; never more often than OOKLA_SAFE_INTERVAL_SEC."""
    interval_sec = max(float(OOKLA_SAFE_INTERVAL_SEC), float(interval_sec))
    with _lock:
        _load_cooldown()
        if not _client_last_attempt:
            return 0.0
        return max(0.0, _client_last_attempt + interval_sec - time.time())


def ookla_schedule_warning(engine: str, schedule_mode: str, cron_expr: str,
                           ookla_interval_min: int = OOKLA_SAFE_INTERVAL_SEC // 60) -> Optional[Dict[str, Any]]:
    """Describe the Ookla rate-limit risk of this schedule, or None when there is none."""
    paused_min = int(client_cooldown_remaining() // 60) + 1 if client_cooldown_remaining() > 0 else 0
    uses_ookla = engine in ("ookla", "all")
    gap = None
    if uses_ookla and schedule_mode == "scheduled":
        from nmb.speed.scheduler import shortest_gap_seconds
        gap = shortest_gap_seconds(cron_expr)
    if gap is not None and gap < OOKLA_SAFE_INTERVAL_SEC:
        return {
            "code": "ookla_rate_limit_risk",
            "interval_min": round(gap / 60, 1),
            "safe_interval_min": max(OOKLA_SAFE_INTERVAL_SEC // 60, int(ookla_interval_min)),
            "paused_min": paused_min,
        }
    if paused_min:
        return {"code": "ookla_paused", "paused_min": paused_min, "safe_interval_min": OOKLA_SAFE_INTERVAL_SEC // 60}
    return None
