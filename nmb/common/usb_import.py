"""Settings from a USB stick: plug in a stick with `nmb.conf` (or `nmb-import.conf`) at its top level.

Started by udev for every USB storage partition (nmb-usb-import@.service, root). The file may hold only
the keys to change, for example:

    [telegram]
    token = 123456:ABC...
    [network]
    wifi_psk = my-own-password
    pppoe_user = ...
    pppoe_password = ...

What happens:
* the stick is mounted read-write with nosuid,nodev,noexec, only for the import;
* every key in the file is set in /etc/nmb/nmb.conf, all other settings stay; a secret left empty or as
  `__KEEP_CURRENT__` never replaces a set one;
* the old settings are kept in /var/lib/nmb/config-backups/ first;
* the same file is applied once (its checksum is remembered), so the stick can stay plugged in;
* the result goes to `nmb-import-result.txt` on the stick (key names only, never values) and into the
  event log; the services reload.

`[usb_import] enabled = false` turns it off. Anyone who can plug in a stick can also take out the SD card,
so this gives no access beyond physical access.
"""
from __future__ import annotations

import configparser
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

log = logging.getLogger("nmb.usb_import")

CONFIG = Path("/etc/nmb/nmb.conf")
BACKUP_DIR = Path("/var/lib/nmb/config-backups")
STATE = Path("/var/lib/nmb/usb-import.json")
MOUNT = Path("/run/nmb/usb-import")
NAMES = ("nmb.conf", "nmb-import.conf", "NMB/nmb.conf")
RESULT = "nmb-import-result.txt"
_SECRET = re.compile(r"(password|psk|token|auth_key|secret)", re.I)
_KEEP = {"", "__KEEP_CURRENT__"}


def apply_partial(current_text: str, update_text: str) -> Tuple[str, List[str], List[str]]:
    """current_text with every key of update_text set. Returns (text, applied names, skipped names)."""
    upd = configparser.RawConfigParser(strict=False, interpolation=None)
    upd.optionxform = str
    upd.read_string(update_text)
    lines = current_text.splitlines()
    applied: List[str] = []
    skipped: List[str] = []
    for sec in upd.sections():
        if sec == "usb_import":
            continue
        for key, val in upd.items(sec):
            val = (val or "").strip()
            name = f"{sec}.{key}"
            if _SECRET.search(key) and val in _KEEP:
                skipped.append(name)
                continue
            # find the section in the current text
            start = next((i for i, ln in enumerate(lines) if ln.strip() == f"[{sec}]"), None)
            if start is None:
                lines += ["", f"[{sec}]", f"{key} = {val}"]
                applied.append(name)
                continue
            end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
            pat = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
            hit = next((i for i in range(start + 1, end) if pat.match(lines[i])), None)
            if hit is None:
                lines.insert(end, f"{key} = {val}")
            else:
                lines[hit] = f"{key} = {val}"
            applied.append(name)
    return "\n".join(lines) + "\n", applied, skipped


def _enabled(text: str) -> bool:
    p = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        p.read_string(text)
        return p.get("usb_import", "enabled", fallback="true").strip().lower() not in ("false", "0", "no", "off")
    except configparser.Error:
        return True


def _state() -> Dict[str, float]:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def import_text(update_text: str, now: float | None = None) -> Dict[str, object]:
    """Apply update_text to /etc/nmb/nmb.conf (root). Returns what happened, names only."""
    now = time.time() if now is None else now
    digest = hashlib.sha256(update_text.encode()).hexdigest()
    st = _state()
    if digest in st:
        return {"ok": True, "status": "already", "applied": [], "skipped": []}
    current = CONFIG.read_text(encoding="utf-8")
    if not _enabled(current):
        return {"ok": False, "status": "disabled", "applied": [], "skipped": []}
    try:
        text, applied, skipped = apply_partial(current, update_text)
        configparser.RawConfigParser(strict=False, interpolation=None).read_string(text)
    except configparser.Error as e:
        return {"ok": False, "status": f"not a valid settings file: {str(e).splitlines()[0][:120]}", "applied": [], "skipped": []}
    if not applied:
        return {"ok": False, "status": "no setting to change in the file", "applied": [], "skipped": skipped}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    backup = BACKUP_DIR / time.strftime("nmb.conf.usb-%Y%m%d-%H%M%S", time.localtime(now))
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(current)
    s = CONFIG.stat()
    tmp = CONFIG.with_suffix(".usbimport")
    tmp.write_text(text, encoding="utf-8")
    os.chown(tmp, s.st_uid, s.st_gid)
    os.chmod(tmp, s.st_mode & 0o777)
    os.replace(tmp, CONFIG)
    st[digest] = now
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st))
    os.chmod(STATE, 0o600)
    return {"ok": True, "status": "applied", "applied": applied, "skipped": skipped, "backup": str(backup)}


def _run(cmd: List[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _event(severity: str, detail: str) -> None:
    try:
        from nmb.db import database as db
        conn = db.connect()
        with db.tx(conn):
            conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, ?, 'usb', 'usb_config_import', ?)",
                         (db.now_ms(), severity, detail[:2000]))
        conn.close()
    except Exception as e:
        log.warning("could not log the USB import: %s", e)


def import_from_device(dev: str) -> int:
    """udev entry point: mount /dev/<dev>, apply a settings file if there is one, write the result back."""
    if not re.match(r"^[a-z0-9]+$", dev or ""):
        return 2
    MOUNT.mkdir(parents=True, exist_ok=True)
    target = MOUNT / dev
    target.mkdir(exist_ok=True)
    if _run(["mount", "-o", "rw,nosuid,nodev,noexec", f"/dev/{dev}", str(target)]).returncode != 0:
        target.rmdir()
        return 0   # not a file system we can read: nothing to do
    try:
        found = next((target / n for n in NAMES if (target / n).is_file()), None)
        if not found:
            return 0
        try:
            text = found.read_text(encoding="utf-8-sig")[:256 * 1024]
            res = import_text(text)
        except Exception as e:
            res = {"ok": False, "status": f"{type(e).__name__}: {e}", "applied": [], "skipped": []}
        lines = [f"NetworkMeasureBox settings import, {time.strftime('%Y-%m-%d %H:%M:%S')}",
                 f"File: {found.name}", f"Result: {res['status']}"]
        if res.get("applied"):
            lines.append("Applied: " + ", ".join(res["applied"]))
        if res.get("skipped"):
            lines.append("Kept (empty or __KEEP_CURRENT__ secrets): " + ", ".join(res["skipped"]))
        try:
            (target / RESULT).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
        if res["status"] == "applied":
            _event("info", f"Settings imported from a USB stick ({found.name}): " + ", ".join(res["applied"]))
            for unit in ("nmb-web", "nmb-telegram"):
                _run(["systemctl", "try-restart", unit], timeout=60)
            _run(["systemctl", "reload", "nmb-netd"])
        elif res["status"] != "already":
            _event("warn", f"USB settings import refused ({found.name}): {res['status']}")
        log.info("USB import from %s: %s", dev, res["status"])
        return 0 if res["ok"] else 1
    finally:
        _run(["sync"])
        _run(["umount", str(target)])
        try:
            target.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(import_from_device(sys.argv[1]) if len(sys.argv) > 1 else 2)
