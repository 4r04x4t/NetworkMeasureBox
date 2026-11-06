"""Selective deletion of stored data. Configuration, credentials and VPN keys are never touched."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, Iterable, List

from nmb.common import backup
from nmb.db import database as db

log = logging.getLogger("nmb.common.purge")

CATEGORY_TABLES = {
    "measurements": ("ping_sample", "ping_minute", "speedtest", "port_check", "outage", "iface_stat"),
    "events": ("event", "alert"),
}
CATEGORIES = ("measurements", "events", "reports", "backups", "logs")


def _reports_dir(cfg) -> Path:
    return Path(cfg.system.data_dir) / "persist" / "reports"


def _dir_stats(path: Path) -> Dict[str, int]:
    files = [p for p in path.iterdir() if p.is_file()] if path.is_dir() else []
    return {"items": len(files), "bytes": sum(p.stat().st_size for p in files)}


def get_purge_summary(cfg) -> Dict[str, Dict[str, int]]:
    """Return item counts and sizes per category."""
    summary = {c: {"items": 0, "bytes": 0} for c in CATEGORIES}
    try:
        conn = db.connect(readonly=True)
        try:
            for category, tables in CATEGORY_TABLES.items():
                for table in tables:
                    summary[category]["items"] += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()
    except Exception as e:
        log.warning("could not count stored rows: %s", e)
    summary["reports"] = _dir_stats(_reports_dir(cfg))
    summary["backups"] = _dir_stats(backup.BACKUP_DIR)
    log_file = getattr(cfg.logging, "file_path", None)
    if log_file:
        summary["logs"] = _dir_stats(Path(log_file).parent)
    return summary


def _purge_tables(categories: List[str]) -> int:
    conn = db.connect()
    deleted = 0
    try:
        with db.tx(conn):
            for category in categories:
                for table in CATEGORY_TABLES[category]:
                    deleted += conn.execute(f"DELETE FROM {table}").rowcount
        conn.execute("VACUUM")
    finally:
        conn.close()
    # The persistent copy would otherwise bring the rows back after a reboot.
    db.snapshot()
    return deleted


def _purge_dir(path: Path) -> int:
    count = 0
    if path.is_dir():
        for item in path.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink()
                count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                count += 1
    return count


def purge(cfg, categories: Iterable[str]) -> Dict[str, object]:
    """Delete the selected categories. Returns deleted counts and per-category errors."""
    selected = list(dict.fromkeys(categories))
    unknown = [c for c in selected if c not in CATEGORIES]
    if unknown or not selected:
        raise ValueError(f"Unknown or empty purge categories: {unknown}")

    deleted: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    tables = [c for c in selected if c in CATEGORY_TABLES]
    if tables:
        try:
            count = _purge_tables(tables)
            for c in tables:
                deleted[c] = count
        except Exception as e:
            log.error("database purge failed: %s", e)
            for c in tables:
                errors[c] = str(e)
    for category, path in (("reports", _reports_dir(cfg)), ("backups", backup.BACKUP_DIR)):
        if category in selected:
            try:
                deleted[category] = _purge_dir(path)
            except OSError as e:
                errors[category] = str(e)
    if "logs" in selected:
        try:
            from nmb.devlog import purge_all_logs
            purge_all_logs(include_database_events=False, include_system_journal=True)
            deleted["logs"] = 1
        except Exception as e:
            errors["logs"] = str(e)
    log.warning("data purge executed: categories=%s deleted=%s errors=%s", selected, deleted, errors)
    return {"deleted": deleted, "errors": errors}
