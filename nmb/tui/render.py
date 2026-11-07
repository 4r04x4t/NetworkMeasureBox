"""Turn API answers into plain text lines."""
from __future__ import annotations

from typing import Any, List

SECRET_WORDS = ("password", "psk", "token", "secret", "auth_key", "private_key")
MAX_ROWS = 200


def _hide(key: str, value: Any) -> Any:
    if value and any(word in key.lower() for word in SECRET_WORDS):
        return "******"
    return value


def _scalar(value: Any) -> str:
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}"
    return " ".join(str(value).split()) if "\n" not in str(value) else str(value)


def _table(rows: List[dict], indent: str) -> List[str]:
    columns: List[str] = []
    for row in rows[:20]:
        for key, value in row.items():
            if key not in columns and not isinstance(value, (dict, list)) and len(columns) < 8:
                columns.append(key)
    cells = [[_scalar(_hide(c, row.get(c)))[:36] for c in columns] for row in rows[:MAX_ROWS]]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    line = indent + "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [line, indent + "|" + "|".join(f" {c:<{w}} " for c, w in zip(columns, widths)) + "|", line]
    out += [indent + "|" + "|".join(f" {v:<{w}} " for v, w in zip(row, widths)) + "|" for row in cells]
    out.append(line)
    if len(rows) > MAX_ROWS:
        out.append(f"{indent}... {len(rows) - MAX_ROWS} more rows")
    return out


def to_lines(data: Any, indent: str = "", key: str = "") -> List[str]:
    if isinstance(data, dict):
        out: List[str] = []
        for name, value in data.items():
            if name == "http_status" or (isinstance(value, str) and value.startswith("<svg")):
                continue
            if isinstance(value, (dict, list)):
                if value:
                    out.append(f"{indent}[{name}]")
                    out += to_lines(value, indent + "  ", name)
            else:
                text = _scalar(_hide(name, value))
                if "\n" in text:
                    out.append(f"{indent}{name}:")
                    out += [indent + "  " + part for part in text.splitlines()]
                else:
                    out.append(f"{indent}{name}: {text}")
        return out
    if isinstance(data, list):
        if data and all(isinstance(item, dict) for item in data):
            return _table(data, indent)
        return [f"{indent}- {_scalar(_hide(key, item))}" for item in data[:MAX_ROWS]]
    return [indent + _scalar(data)]
