"""List the box's logs as text lines, for the menu and for the logs command."""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

from nmb.tui.client import ApiClient

# Source name: (API path, field holding the rows, sent query field for the row limit)
SOURCES: Dict[str, Tuple[str, str]] = {
    "dev": ("/api/dev/logs", "records"),
    "system": ("/api/system/syslog", "entries"),
    "events": ("/api/status", "system_events"),
    "speed": ("/api/status", "speed_tests"),
    "crashes": ("/api/dev/crashes", "crashes"),
}
TIME_FIELDS = ("timestamp", "time", "ts", "datetime", "date", "created")
LEVEL_FIELDS = ("level", "severity", "status")
SOURCE_FIELDS = ("logger", "component", "source", "unit", "process", "engine", "kind")
TEXT_FIELDS = ("message", "msg", "detail", "text", "raw", "error", "file", "filename")


def _first(row: dict, names: Tuple[str, ...]) -> Any:
    return next((row[n] for n in names if row.get(n) not in (None, "")), "")


def _time_text(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000.0 if value > 1e11 else value
        return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def format_row(source: str, row: Any) -> str:
    if not isinstance(row, dict):
        return " ".join(str(row).split())
    text = _first(row, TEXT_FIELDS)
    if source == "speed" and row.get("status") == "ok":
        text = f"{(row.get('down_bps') or 0) / 1e6:.1f} / {(row.get('up_bps') or 0) / 1e6:.1f} Mbps"
    parts = [_time_text(_first(row, TIME_FIELDS)), str(_first(row, LEVEL_FIELDS)).upper(),
             str(_first(row, SOURCE_FIELDS)), " ".join(str(text).split())]
    return "  ".join(p for p in parts if p)


def _is_level(row: Any, level: str) -> bool:
    return isinstance(row, dict) and str(_first(row, LEVEL_FIELDS)).upper().startswith(level.upper())


def read_rows(client: ApiClient, source: str, lines: int = 200, level: str = "", grep: str = "") -> List[Any]:
    """Return the newest rows last, so the end of the output is the latest entry."""
    path, field = SOURCES[source]
    query: Optional[dict] = {"limit": max(lines, 1)} if source in ("dev", "system") else None
    rows = client.call("GET", path, query, timeout=30).get(field) or []
    if level:
        rows = [r for r in rows if _is_level(r, level)]
    if grep:
        rows = [r for r in rows if grep.lower() in format_row(source, r).lower()]
    if rows and isinstance(rows[0], dict):
        stamps = [_first(r, TIME_FIELDS) for r in (rows[0], rows[-1])]
        if all(isinstance(s, (int, float)) for s in stamps) and stamps[0] > stamps[1]:
            rows = rows[::-1]
        elif all(isinstance(s, str) and s for s in stamps) and stamps[0] > stamps[1]:
            rows = rows[::-1]
    return rows[-lines:] if lines > 0 else rows


def read_lines(client: ApiClient, source: str, lines: int = 200, level: str = "", grep: str = "") -> List[str]:
    return [format_row(source, row) for row in read_rows(client, source, lines, level, grep)]
