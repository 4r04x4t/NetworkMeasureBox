"""Optional daily data limit for scheduled tests, for metered connections such as mobile data."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Tuple

from nmb.db import database as db

KV_KEY = "speedtest_data_used"


def interface_bytes(iface: str) -> int:
    """Return bytes received plus sent so far on an interface."""
    base = Path("/sys/class/net") / iface / "statistics"
    try:
        return int((base / "rx_bytes").read_text()) + int((base / "tx_bytes").read_text())
    except (OSError, ValueError):
        return 0


def _today() -> str:
    return datetime.date.today().isoformat()


def used_today_mb(conn, key: str = KV_KEY) -> float:
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    if not row:
        return 0.0
    day, _, used = str(row[0]).partition("|")
    try:
        return float(used) if day == _today() else 0.0
    except ValueError:
        return 0.0


def add_usage_mb(conn, megabytes: float, key: str = KV_KEY) -> None:
    total = used_today_mb(conn, key) + max(0.0, megabytes)
    with db.tx(conn):
        conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)",
                     (key, f"{_today()}|{total:.1f}", db.now_ms()))


def limit_reached(conn, limit_mb: float, key: str = KV_KEY) -> Tuple[bool, float]:
    """Return whether scheduled tests must stop today, and the amount used. A limit of 0 means none."""
    used = used_today_mb(conn, key)
    return limit_mb > 0 and used >= limit_mb, used
