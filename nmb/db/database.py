"""NetworkMeasureBox SQLite layer.

Live DB on tmpfs, periodic consistent snapshots to microSD via the online
backup API. Stdlib only.

CLI:
    python -m nmb.db.database init
    python -m nmb.db.database restore     # boot: SD -> tmpfs
    python -m nmb.db.database snapshot    # timer/shutdown: tmpfs -> SD
    python -m nmb.db.database maintain    # rollup + prune + optimize
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterator

log = logging.getLogger("nmb.db")

def get_live_db() -> Path:
    return Path(os.environ.get("NMB_LIVE_DB", "/var/lib/nmb/live/nmb.db"))


def get_persist_db() -> Path:
    return Path(os.environ.get("NMB_PERSIST_DB", "/var/lib/nmb/persist/nmb.db"))


LIVE_DB = get_live_db()
PERSIST_DB = get_persist_db()
SCHEMA = Path(__file__).with_name("schema.sql")

# Retention (days). Raw samples are the volume driver: 4 targets @ 2 Hz ≈ 690k rows/day.
RETENTION = {
    "ping_sample": 3,
    "iface_stat": 7,
    "ping_minute": 120,
    "event": 180,
    "alert": 180,
    "speedtest": 730,
    "port_check": 730,
    "outage": 730,
}

from nmb.common.memory import (
    get_db_live_size_cap,
    get_sqlite_pragmas,
    trim_process_memory,
)

# Dynamic cap on live DB size to protect tmpfs (e.g. 48MB on 512MB RAM, 192MB on standard/perf)
LIVE_SIZE_CAP = get_db_live_size_cap()


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def connect(path: Path | None = None, readonly: bool = False) -> sqlite3.Connection:
    target_path = path or get_live_db()
    if readonly:
        conn = sqlite3.connect(f"file:{target_path}?mode=ro", uri=True, timeout=5,
                               isolation_level=None, check_same_thread=False)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target_path, timeout=5, isolation_level=None,
                               check_same_thread=False)
        # Ensure file permissions allow group write (nmb service group)
        try:
            if target_path.exists():
                os.chmod(target_path, 0o664)
        except OSError:
            pass
    conn.row_factory = sqlite3.Row
    pragmas = get_sqlite_pragmas()
    for p in pragmas:
        if readonly and p.startswith(("PRAGMA journal_mode", "PRAGMA wal_", "PRAGMA journal_size")):
            continue
        conn.execute(p)

    if readonly:
        try:
            conn.execute("PRAGMA query_only=ON")
        except Exception:
            pass
    else:
        ensure_schema_upgrades(conn)

    log.debug("sqlite connected: path=%s (readonly=%s)", target_path, readonly)
    return conn


def ensure_schema_upgrades(conn: sqlite3.Connection) -> None:
    """Migrate schema dynamically to support bufferbloat, gateway ping roles, and telemetry extensions."""
    try:
        cur = conn.cursor()

        # Migrate target table with role column
        cur.execute("PRAGMA table_info(target)")
        target_cols = {row[1] for row in cur.fetchall()}
        if "role" not in target_cols:
            log.info("migrating schema: adding column role to target")
            cur.execute("ALTER TABLE target ADD COLUMN role TEXT DEFAULT 'Public DNS'")
            cur.execute("UPDATE target SET role = 'Public DNS' WHERE role IS NULL")

        cur.execute("PRAGMA table_info(speedtest)")
        existing_cols = {row[1] for row in cur.fetchall()}
        new_cols = [
            ("down_loaded_lat_ms", "REAL"),
            ("up_loaded_lat_ms", "REAL"),
            ("bufferbloat_grade", "TEXT"),
            ("bufferbloat_delta_ms", "REAL"),
            ("connection_type", "TEXT"),
            ("client_ip", "TEXT"),
            ("client_ipv6", "TEXT"),
            ("server_host", "TEXT"),
            ("server_location", "TEXT"),
            ("engine", "TEXT DEFAULT 'ookla'"),
            ("colo", "TEXT"),
            ("bound_iface", "TEXT"),
            ("bound_ip", "TEXT"),
            ("retransmits", "INTEGER"),
            ("tcp_window", "TEXT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                log.info("migrating schema: adding column %s to speedtest", col_name)
                cur.execute(f"ALTER TABLE speedtest ADD COLUMN {col_name} {col_type}")

        # Separate IPv4 and IPv6 for legacy records that stored IPv6 in client_ip
        try:
            cur.execute("UPDATE speedtest SET client_ipv6 = client_ip WHERE client_ip LIKE '%:%' AND (client_ipv6 IS NULL OR client_ipv6 = '')")
            from nmb.netd.interfaces import get_dual_stack_ips
            dual = get_dual_stack_ips()
            v4 = dual.get("public_ipv4") or dual.get("ipv4")
            if v4:
                cur.execute("UPDATE speedtest SET client_ip = ? WHERE client_ip LIKE '%:%'", (v4,))
        except Exception:
            pass
    except Exception as e:
        log.debug("schema upgrade check exception: %s", e)


@contextlib.contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit IMMEDIATE transaction (avoids SQLITE_BUSY lock upgrades)."""
    log.debug("sqlite BEGIN TRANSACTION")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException as ex:
        log.debug("sqlite ROLLBACK transaction: %s", ex)
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
        log.debug("sqlite COMMIT transaction")


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())
    ensure_schema_upgrades(conn)
    log.info("schema ready (user_version=%s)", conn.execute("PRAGMA user_version").fetchone()[0])


# --------------------------------------------------------------------------- rollup
def rollup_minutes(conn: sqlite3.Connection, upto_ms: int | None = None) -> int:
    """Aggregate complete minutes from ping_sample into ping_minute (idempotent)."""
    upto = (upto_ms or now_ms()) // 60_000 * 60_000
    row = conn.execute("SELECT COALESCE(MAX(ts), 0) FROM ping_minute").fetchone()
    start = row[0] + 60_000 if row[0] else 0
    if start >= upto:
        return 0
    rows = conn.execute(
        """SELECT target_id, ts/60000*60000 AS m, rtt_us
           FROM ping_sample WHERE ts >= ? AND ts < ?
           ORDER BY target_id, ts""", (start, upto)).fetchall()

    out, key, buf = [], None, []

    def flush() -> None:
        if not buf:
            return
        ok = [r for r in buf if r is not None]
        jit = (sum(abs(a - b) for a, b in zip(ok[1:], ok)) // (len(ok) - 1)) if len(ok) > 1 else None
        s = sorted(ok)
        p95 = s[min(len(s) - 1, int(len(s) * 0.95))] if s else None
        out.append((key[1], key[0], len(buf), len(buf) - len(ok),
                    s[0] if s else None, (sum(s) // len(s)) if s else None,
                    s[-1] if s else None, p95, jit))

    for r in rows:
        k = (r["target_id"], r["m"])
        if k != key:
            flush()
            key, buf = k, []
        buf.append(r["rtt_us"])
    flush()

    with tx(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO ping_minute VALUES (?,?,?,?,?,?,?,?,?)", out)
    return len(out)


# --------------------------------------------------------------------------- pruning
_TS_COL = {"outage": "start_ts"}


def prune(conn: sqlite3.Connection) -> dict[str, int]:
    """Circular retention: delete rows older than per-table horizon, in small batches."""
    deleted: dict[str, int] = {}
    now = now_ms()
    for table, days in RETENTION.items():
        col = _TS_COL.get(table, "ts")
        cutoff = now - days * 86_400_000
        total = 0
        while True:  # batch to keep write locks short for probe writers
            with tx(conn):
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE rowid IN "
                    f"(SELECT rowid FROM {table} WHERE {col} < ? LIMIT 20000)"
                    if table not in ("ping_sample", "ping_minute", "iface_stat") else
                    f"DELETE FROM {table} WHERE {col} < ? AND "
                    f"{col} < (SELECT COALESCE(MIN({col}),0) + 3600000 FROM {table})",
                    (cutoff,))
            total += cur.rowcount
            if cur.rowcount == 0:
                break
        deleted[table] = total

    # Size guard: drop oldest raw samples hour by hour until under cap.
    while _db_bytes(conn) > LIVE_SIZE_CAP:
        with tx(conn):
            n = conn.execute(
                "DELETE FROM ping_sample WHERE ts < "
                "(SELECT MIN(ts) + 3600000 FROM ping_sample)").rowcount
        if n == 0:
            break
        deleted["ping_sample"] = deleted.get("ping_sample", 0) + n
        conn.execute("PRAGMA incremental_vacuum")
        log.warning("size cap hit, pruned %d raw samples", n)
    return deleted


def _db_bytes(conn: sqlite3.Connection) -> int:
    pc = conn.execute("PRAGMA page_count").fetchone()[0]
    fl = conn.execute("PRAGMA freelist_count").fetchone()[0]
    ps = conn.execute("PRAGMA page_size").fetchone()[0]
    return (pc - fl) * ps


def maintain(conn: sqlite3.Connection) -> None:
    n = rollup_minutes(conn)
    d = prune(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA optimize")
    trim_process_memory()
    log.info("maintain: rolled %d minutes, pruned %s", n, {k: v for k, v in d.items() if v})


# --------------------------------------------------------------------------- snapshot
def snapshot(src: Path | None = None, dst: Path | None = None) -> None:
    """Consistent online copy tmpfs -> SD, written atomically (tmp + fsync + rename)."""
    source = src or get_live_db()
    dest = dst or get_persist_db()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    s = connect(source)
    d = sqlite3.connect(tmp)
    try:
        s.backup(d, pages=4096, sleep=0.01)  # yields to writers between chunks
        d.execute("PRAGMA journal_mode=DELETE")  # single self-contained file on SD
        d.commit()
    finally:
        d.close()
        s.close()
    with open(tmp, "rb+") as f:
        os.fsync(f.fileno())
    os.replace(tmp, dest)
    dfd = os.open(dest.parent, os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    log.info("snapshot -> %s (%d KiB)", dest, dest.stat().st_size // 1024)


def restore(src: Path | None = None, dst: Path | None = None) -> None:
    """Boot-time: hydrate tmpfs DB from last SD snapshot; validate integrity."""
    source = src or get_persist_db()
    dest = dst or get_live_db()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        log.info("live DB already present, skip restore")
        return
    if source.exists():
        s = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            ok = s.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            if ok:
                d = sqlite3.connect(dest)
                s.backup(d)
                d.close()
                log.info("restored %s -> %s", source, dest)
            else:
                bad = source.with_suffix(f".corrupt.{int(time.time())}")
                os.replace(source, bad)
                log.error("snapshot corrupt, quarantined to %s; starting fresh", bad)
        finally:
            s.close()
    conn = connect(dst)
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")  # effective only on new DBs
    init(conn)
    conn.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="nmb-db")
    ap.add_argument("cmd", choices=["init", "restore", "snapshot", "maintain"])
    a = ap.parse_args(argv)
    if a.cmd == "restore":
        restore()
    elif a.cmd == "snapshot":
        snapshot()
    else:
        conn = connect()
        init(conn) if a.cmd == "init" else maintain(conn)
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
