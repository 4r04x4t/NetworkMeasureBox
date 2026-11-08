"""A root-only copy of the secrets the owner typed in (tokens, passwords), to restore them if a bug wipes them.

2026-11-08: an update replaced the Telegram token with an empty value and the Wi-Fi password with the
factory one. The owner then has to find and type them again. nmb-netd (root) therefore keeps the last
set value of every secret in /var/lib/nmb/secrets.keep (mode 600, root), for up to 30 days after it was
last seen. `nmb-selftest` reports a secret that is set here but missing in nmb.conf, and
`nmb-selftest secrets-restore` puts it back. A secret the owner clears on purpose is restored only
when they run that command.

Values never leave the box and are never printed; only the names are.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

KEEP_FILE = Path("/var/lib/nmb/secrets.keep")
CONFIG = Path("/etc/nmb/nmb.conf")
MAX_AGE_DAYS = 30
_SECRET = re.compile(r"(password|psk|token|auth_key|secret)", re.I)
_INVALID = {"", "__KEEP_CURRENT__", "NetworkMeasureBox123"}


def _read_secrets(text: str) -> Dict[str, str]:
    p = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        p.read_string(text)
    except configparser.Error:
        return {}
    out = {}
    for sec in p.sections():
        for key, val in p.items(sec):
            if _SECRET.search(key):
                out[f"{sec}.{key}"] = (val or "").strip()
    return out


def _load() -> Dict[str, Dict[str, object]]:
    try:
        return json.loads(KEEP_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Dict[str, object]]) -> None:
    KEEP_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = KEEP_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, KEEP_FILE)


def update(config_text: str | None = None, now: float | None = None) -> None:
    """Remember every set secret (root, called by nmb-netd every loop; cheap when nothing changed)."""
    now = time.time() if now is None else now
    text = CONFIG.read_text(encoding="utf-8") if config_text is None else config_text
    data = _load()
    changed = False
    for name, val in _read_secrets(text).items():
        if val in _INVALID:
            continue
        cur = data.get(name)
        if not cur or cur.get("value") != val:
            data[name] = {"value": val, "seen": now}
            changed = True
        elif now - float(cur.get("seen", 0)) > 3600:
            cur["seen"] = now
            changed = True
    for name in [n for n, v in data.items() if now - float(v.get("seen", 0)) > MAX_AGE_DAYS * 86400]:
        del data[name]
        changed = True
    if changed:
        _save(data)


def lost(config_text: str | None = None) -> List[Tuple[str, float]]:
    """Secrets kept here but empty or factory in nmb.conf: (section.key, last seen)."""
    text = CONFIG.read_text(encoding="utf-8") if config_text is None else config_text
    now_vals = _read_secrets(text)
    return sorted((n, float(v.get("seen", 0))) for n, v in _load().items()
                  if now_vals.get(n, "") in _INVALID)


def restore(config_text: str | None = None) -> Tuple[str, List[str]]:
    """The config text with the lost secrets put back, and their names."""
    text = CONFIG.read_text(encoding="utf-8") if config_text is None else config_text
    data = _load()
    names = [n for n, _ in lost(text)]
    if not names:
        return text, []
    out, section = [], ""
    seen = set()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
        m = re.match(r"^(\s*)([A-Za-z0-9_.-]+)\s*=", line)
        if m and f"{section}.{m.group(2).lower()}" in names:
            name = f"{section}.{m.group(2).lower()}"
            line = f"{m.group(1)}{m.group(2)} = {data[name]['value']}"
            seen.add(name)
        out.append(line)
    return "\n".join(out) + "\n", sorted(seen)
