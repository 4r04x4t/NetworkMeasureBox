"""Time windows in which the box itself disrupts its own connection (mode change, update, restart).

An outage during such a window is the box's doing, not the ISP's: the reports list it separately and
leave it out of the availability (2026-11-10: about 15 of 18 recorded outages were the box's own mode
changes and updates, all counted against the ISP).

begin() opens a window and returns its id; end() closes it. A window that is never closed (the
process died, the box rebooted) is closed by close_stale() at the next netd start. Every call writes
an event too (own_action_start / own_action_end), so the event log shows it. Root writers (netd, the
updater) use the database like netd always has.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Iterator, Optional

log = logging.getLogger("nmb.common.own_action")

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_action (
    id       INTEGER PRIMARY KEY,
    start_ts INTEGER NOT NULL,
    end_ts   INTEGER,
    kind     TEXT NOT NULL,
    source   TEXT NOT NULL,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS ix_own_action_start ON own_action(start_ts);
"""

# How long after an own action the line may still be coming back (PPPoE dial, DHCP, the probe's
# re-bind check every 30 s and its 15 s outage threshold plus a 10 s flush).
GRACE_AFTER_MS = 120_000
GRACE_BEFORE_MS = 5_000
# A window still open after this long is treated as ended (a crash left it open).
MAX_OPEN_MS = 30 * 60_000


def _connect():
    from nmb.db import database as db
    return db.connect()


def begin(kind: str, source: str, detail: str = "") -> Optional[int]:
    """Open a window; never raises (a failed record must not stop the action itself)."""
    try:
        from nmb.db import database as db
        conn = _connect()
        try:
            now = db.now_ms()
            with db.tx(conn):
                cur = conn.execute("INSERT INTO own_action (start_ts, kind, source, detail) VALUES (?, ?, ?, ?)",
                                   (now, kind, source, detail[:500]))
                conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', ?, 'own_action_start', ?)",
                             (now, source, f"{kind}: {detail}"[:500]))
                return int(cur.lastrowid)
        finally:
            conn.close()
    except Exception as e:
        log.warning("own action %s not recorded: %s", kind, e)
        return None


def end(action_id: Optional[int], detail: str = "") -> None:
    if not action_id:
        return
    try:
        from nmb.db import database as db
        conn = _connect()
        try:
            now = db.now_ms()
            with db.tx(conn):
                row = conn.execute("SELECT kind, source FROM own_action WHERE id = ?", (action_id,)).fetchone()
                conn.execute("UPDATE own_action SET end_ts = ? WHERE id = ? AND end_ts IS NULL", (now, action_id))
                if row:
                    conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', ?, 'own_action_end', ?)",
                                 (now, row[1], f"{row[0]}{': ' + detail if detail else ''}"[:500]))
        finally:
            conn.close()
    except Exception as e:
        log.warning("own action %s end not recorded: %s", action_id, e)


def close_stale(now_ms: Optional[int] = None) -> int:
    """At netd start: windows left open by a reboot or a crash end now (or after MAX_OPEN_MS)."""
    try:
        from nmb.db import database as db
        conn = _connect()
        try:
            now = now_ms or db.now_ms()
            with db.tx(conn):
                cur = conn.execute(
                    "UPDATE own_action SET end_ts = MIN(?, start_ts + ?) WHERE end_ts IS NULL", (now, MAX_OPEN_MS))
                return cur.rowcount
        finally:
            conn.close()
    except Exception as e:
        log.warning("open own actions not closed: %s", e)
        return 0


@contextlib.contextmanager
def window(kind: str, source: str, detail: str = "") -> Iterator[Optional[int]]:
    action_id = begin(kind, source, detail)
    try:
        yield action_id
    finally:
        end(action_id)
