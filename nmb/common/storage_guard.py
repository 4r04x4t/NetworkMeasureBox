"""Storage guard: free space before the disk fills up, scaled to the size of the disk (``[storage]``).

``nmb-netd`` (root) checks every 10 minutes. The space to keep free depends on the disk:
15 % on disks up to 2 GB, 10 % up to 16 GB, 5 % above, never less than 200 MB and never more
than 2 GB (``min_free_mb`` overrides it). Below that, it deletes, oldest first, until 25 % more
than that is free again:

1. rotated logs, old diagnostic bundles and crash reports (``/var/log/nmb``);
2. update backups except the newest one, old reports and saved log copies (``/var/lib/nmb``);
3. the system journal, down to 32 MB;
4. active NMB logs larger than 1 MB (emptied, not deleted);
5. only then measurements: raw ping samples first, then minute and interface statistics,
   then events and speed tests, the oldest day at a time, keeping at least ``keep_days``
   (7) days; below half of the free-space target the last day is kept.

Every run that deleted something is logged, and deleted measurements are recorded as an event.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.storage")

DATA_DIR = Path("/var/lib/nmb")
LOG_DIR = Path("/var/log/nmb")
STATE_FILE = Path("/run/nmb/storage_guard.json")
CHECK_EVERY_SEC = 600.0
MB = 1024 * 1024

_last_check = 0.0


def free_target_bytes(total_bytes: int, min_free_mb: int = 0) -> int:
    """How much the disk keeps free: a share of its size, between 200 MB and 2 GB."""
    if min_free_mb > 0:
        return min_free_mb * MB
    gb = total_bytes / (1024 ** 3)
    share = 0.15 if gb <= 2 else 0.10 if gb <= 16 else 0.05
    return int(min(max(total_bytes * share, 200 * MB), 2048 * MB))


def _free(path: Path) -> int:
    return shutil.disk_usage(str(path)).free


def _files_oldest_first(patterns: List[tuple]) -> List[Path]:
    found: List[Path] = []
    for base, glob in patterns:
        if base.exists():
            found.extend(p for p in base.glob(glob) if p.is_file())
    return sorted(set(found), key=lambda p: p.stat().st_mtime)


def _delete_until(files: List[Path], path: Path, goal: int, done: List[str]) -> bool:
    for f in files:
        if _free(path) >= goal:
            return True
        try:
            size = f.stat().st_size
            f.unlink()
            done.append(f"{f} ({size // 1024} kB)")
        except OSError as e:
            log.debug("could not delete %s: %s", f, e)
    return _free(path) >= goal


def _backups_but_newest(base: Path) -> List[Path]:
    if not base.exists():
        return []
    items = sorted((p for p in base.iterdir()), key=lambda p: p.stat().st_mtime)
    return items[:-1]


def _rm(p: Path) -> int:
    try:
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p)
        else:
            size = p.stat().st_size
            p.unlink()
        return size
    except OSError:
        return 0


TABLES = ("ping_sample", "ping_minute", "iface_stat", "event", "speedtest")
_TS = {"outage": "start_ts"}


def prune_measurements(conn, path: Path, goal: int, keep_days: int, done: List[str]) -> int:
    """Delete the oldest day of each table in turn, never inside the last ``keep_days`` days.

    The live database is in RAM; the disk copy shrinks when it is written out again, so a snapshot
    follows every deleted day.
    """
    cutoff = int(time.time() * 1000) - keep_days * 86_400_000
    deleted = 0
    for table in TABLES:
        col = _TS.get(table, "ts")
        while _free(path) < goal:
            try:
                row = conn.execute(f"SELECT MIN({col}) FROM {table}").fetchone()
            except Exception:
                break
            oldest = row[0] if row else None
            if oldest is None or oldest >= cutoff:
                break
            n = conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (min(oldest + 86_400_000, cutoff),)).rowcount
            deleted += n
            if n == 0:
                break
            _shrink_persist(conn)
        if deleted:
            done.append(f"{table}: rows older than {keep_days} days")
        if _free(path) >= goal:
            break
    return deleted


def _shrink_persist(conn) -> None:
    """The disk copy of the database shrinks only when the live one is written out again."""
    try:
        conn.execute("PRAGMA incremental_vacuum")
        from nmb.db import database
        database.snapshot()
    except Exception as e:
        log.warning("snapshot after pruning failed (the old copy stays): %s", e)


def run(cfg: Any = None, force: bool = False) -> Dict[str, Any]:
    """Check the disk and clean up when it is too full; returns what it did."""
    global _last_check
    st = getattr(cfg, "storage", None)
    if st is not None and not getattr(st, "auto_cleanup", True):
        return {"status": "off"}
    now = time.monotonic()
    if not force and now - _last_check < CHECK_EVERY_SEC:
        return {"status": "skipped"}
    _last_check = now
    path = DATA_DIR if DATA_DIR.exists() else Path("/")
    usage = shutil.disk_usage(str(path))
    target = free_target_bytes(usage.total, int(getattr(st, "min_free_mb", 0) or 0))
    goal = int(target * 1.25)
    keep_days = max(1, int(getattr(st, "keep_days", 7) or 7))
    res: Dict[str, Any] = {"status": "ok", "total_mb": usage.total // MB, "free_mb": usage.free // MB,
                           "target_free_mb": target // MB, "deleted": [], "measurement_rows": 0}
    if usage.free >= target:
        _write(res)
        return res

    log.warning("disk almost full: %d MB free, keeping %d MB free; cleaning up", usage.free // MB, target // MB)
    done: List[str] = res["deleted"]
    ok = _delete_until(_files_oldest_first([
        (LOG_DIR, "*.log.[0-9]*"), (LOG_DIR, "*.gz"), (LOG_DIR, "*.old"),
        (LOG_DIR / "bundles", "*"), (LOG_DIR / "crashes", "*"),
        (DATA_DIR / "persist" / "logs", "*"),
    ]), path, goal, done)
    if not ok:
        for p in _backups_but_newest(DATA_DIR / "backups") + _files_oldest_first([(DATA_DIR / "persist" / "reports", "*")]):
            if _free(path) >= goal:
                break
            size = _rm(p)
            if size:
                done.append(f"{p} ({size // 1024} kB)")
        ok = _free(path) >= goal
    if not ok and shutil.which("journalctl"):
        subprocess.run(["journalctl", "--vacuum-size=32M"], capture_output=True, timeout=60)
        done.append("system journal down to 32 MB")
        ok = _free(path) >= goal
    if not ok and LOG_DIR.exists():
        for f in sorted(LOG_DIR.glob("*.log"), key=lambda p: -p.stat().st_size):
            if f.stat().st_size > MB:
                try:
                    with open(f, "r+") as fh:
                        fh.truncate(0)
                    done.append(f"{f} emptied")
                except OSError:
                    pass
        ok = _free(path) >= goal
    if not ok:
        try:
            from nmb.db import database
            conn = database.connect()
            try:
                critical = _free(path) < target // 2
                rows = prune_measurements(conn, path, goal, 1 if critical else keep_days, done)
                res["measurement_rows"] = rows
                if rows:
                    conn.execute(
                        "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warning', 'storage', 'storage_cleanup', ?)",
                        (int(time.time() * 1000), f"Disk almost full: deleted {rows} old measurement rows to keep {target // MB} MB free."))
            finally:
                conn.close()
        except Exception as e:
            log.warning("measurement cleanup failed: %s", e)
    res["free_mb"] = _free(path) // MB
    res["status"] = "cleaned" if _free(path) >= target else "still_full"
    log.warning("storage cleanup: now %d MB free (%s); %s", res["free_mb"], res["status"], "; ".join(done[:8]) or "nothing to delete")
    _write(res)
    return res


def _write(res: Dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(dict(res, ts=int(time.time()))))
    except OSError:
        pass


def status() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
