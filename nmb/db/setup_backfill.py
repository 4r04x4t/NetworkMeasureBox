"""The setup of measurements stored before it was recorded, reconstructed once (owner, 2026-11-10).

Until 2026-11-10 a speed test row did not say how the box was connected: the mode was stored only
from that day's noon on, the link kind and whether the box was directly on the ISP never. They are
reconstructed here from what the database still holds, and marked ``derived``:

- the mode from the event log: every switch is an event ``mode_change`` ("Switched from X to Y:
  reason"); a failed switch (``mode_change_failed``) or a stopped netd (own action ``netd_stop``) makes
  the mode unknown until the next switch, and inside the box's own mode-change windows it is unknown;
- the link kind from the stored interface name (``ppp0`` is PPPoE, ``wlan0`` Wi-Fi; an interface the
  event log names as a USB tether is USB), never from today's system and never from the configured
  line type;
- directly on the ISP or behind a router from the stored IPv4 address (a PPPoE session or a public or
  CGNAT address is direct, a private one is behind a router); a row with only an IPv6 address keeps
  it unknown;
- a mode switch to another mode while a test ran makes it ``changed``.

Only empty fields are filled, nothing measured is replaced. Every value written into a speed test row
is kept in ``speedtest_correction`` (so the collector gets it too); outages get the mode at their
start; the history of setups goes into ``network_state`` as ``derived`` rows for the time before netd
recorded it. Runs once per database (kv marker), in short IMMEDIATE transactions like corrections.py.
"""
from __future__ import annotations

import bisect
import logging
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from nmb.common import net_setup

log = logging.getLogger("nmb.db.setup_backfill")

MARKER = "setup_backfill_2026_11_10"
BATCH_ROWS = 300
MAX_WINDOW_MS = 30 * 60 * 1000          # own_action.MAX_OPEN_MS: an open window counts for at most this long
DEFAULT_TEST_MS = 5 * 60 * 1000         # rows without a duration (before 2026-11-10): a whole run's span
REASON = "setup derived afterwards from the event log and the stored interface and address"

_SWITCH = re.compile(r"^Switched from (\S+) to (\S+?): (.*)$", re.S)
_ON_IFACE = re.compile(r"\bon (\S+?)(?:[;:,)]|$|\s)")
_USB_ON = re.compile(r"USB tethering on (\S+)")


class History:
    """The box's setup over time, as far as the event log tells it."""

    def __init__(self, states: List[Tuple[int, Optional[str], Optional[str], Optional[str], Optional[str], str]],
                 windows: List[Tuple[int, int]], usb_ifaces: Tuple[str, ...] = ()):
        self.usb_ifaces = tuple(usb_ifaces)      # interfaces the event log names as USB tethers
        self.states = sorted(states, key=lambda s: s[0])          # (ts, mode, iface, kind, path, detail)
        self.times = [s[0] for s in self.states]
        self.windows = sorted(windows)
        self.win_starts = [w[0] for w in self.windows]

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "History":
        states: List[Tuple[int, Optional[str], Optional[str], Optional[str], Optional[str], str]] = []
        last_mode: Optional[Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]] = None
        rows = conn.execute(
            "SELECT ts, kind, detail FROM event WHERE kind IN ('mode_change', 'mode_change_failed', "
            "'uplink_usb_fallback', 'uplink_usb_fallback_end') ORDER BY ts, id").fetchall()
        stops = conn.execute("SELECT start_ts FROM own_action WHERE kind = 'netd_stop'").fetchall() \
            if _has_table(conn, "own_action") else []
        events = [(int(r[0]), r[1], r[2] or "") for r in rows] + [(int(s[0]), "netd_stop", "") for s in stops]
        events.sort(key=lambda e: e[0])
        for ts, kind, detail in events:
            if kind == "mode_change":
                state = _state_from_switch(detail)
                if state is None:
                    continue
                last_mode = state
                states.append((ts, *state, detail[:300]))
            elif kind in ("mode_change_failed", "netd_stop"):
                last_mode = (None, None, None, None)
                states.append((ts, None, None, None, None, kind))
            elif kind == "uplink_usb_fallback":
                m = _USB_ON.search(detail)
                mode = last_mode[0] if last_mode else None
                states.append((ts, mode, m.group(1) if m else None, "usb", None, detail[:300]))
            elif kind == "uplink_usb_fallback_end" and last_mode is not None:
                states.append((ts, *last_mode, detail[:300]))
        usb_ifaces = tuple(sorted({m.group(1) for _, kind, detail in events if kind == "uplink_usb_fallback"
                                   for m in [_USB_ON.search(detail)] if m}))
        states = _enrich_from_tests(conn, states, usb_ifaces)
        windows: List[Tuple[int, int]] = []
        if _has_table(conn, "own_action"):
            for start, end in conn.execute(
                    "SELECT start_ts, end_ts FROM own_action WHERE kind = 'mode_change'").fetchall():
                windows.append((int(start), int(end) if end else int(start) + MAX_WINDOW_MS))
        return cls(states, windows, usb_ifaces)

    def in_window(self, ts: int) -> bool:
        i = bisect.bisect_right(self.win_starts, ts) - 1
        return i >= 0 and self.windows[i][0] <= ts <= self.windows[i][1]

    def at(self, ts: int) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """(mode, iface, kind, path) at ts; all None inside a mode-change window or before any record."""
        if self.in_window(ts):
            return None, None, None, None
        i = bisect.bisect_right(self.times, ts) - 1
        if i < 0:
            return None, None, None, None
        return self.states[i][1:5]

    def mode_changed(self, start: int, end: int, mode: Optional[str]) -> bool:
        """A switch to another mode between start and end (a netd restart into the same mode is none)."""
        if mode is None:
            return False
        i = bisect.bisect_right(self.times, start)
        while i < len(self.states) and self.states[i][0] <= end:
            if self.states[i][1] is not None and self.states[i][1] != mode:
                return True
            i += 1
        return False


def _enrich_from_tests(conn: sqlite3.Connection, states, usb_ifaces: Tuple[str, ...] = ()):
    """Fill a period's unknown link and position from the speed tests measured in it.

    Only when every successful test of the period that stored an interface and an IPv4 address tells
    the same (same interface, same kind, same address class); otherwise the period stays unknown.
    """
    tests = conn.execute("SELECT ts, bound_iface, bound_ip FROM speedtest "
                         "WHERE status = 'ok' AND bound_iface IS NOT NULL ORDER BY ts").fetchall()
    times = [int(t[0]) for t in tests]
    out = []
    for i, (ts, mode, iface, kind, path, detail) in enumerate(states):
        if mode is None or (kind is not None and path is not None):
            out.append((ts, mode, iface, kind, path, detail))
            continue
        end = states[i + 1][0] if i + 1 < len(states) else None
        lo = bisect.bisect_left(times, ts)
        hi = bisect.bisect_left(times, end) if end is not None else len(tests)
        seen = set()
        for _, b_iface, b_ip in tests[lo:hi]:
            if iface is not None and b_iface != iface:
                continue
            b_kind = net_setup.uplink_kind_by_name(b_iface, mode, usb_ifaces)
            b_path = net_setup.isp_path_for(b_kind, b_ip) if b_kind else None
            if b_kind and b_path:
                seen.add((b_iface, b_kind, b_path))
        if len(seen) == 1:
            b_iface, b_kind, b_path = seen.pop()
            if kind in (None, b_kind):
                iface, kind, path = b_iface, b_kind, path or b_path
                detail = (detail + "; link and position from this period's speed tests")[:300]
        out.append((ts, mode, iface, kind, path, detail))
    return out


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _state_from_switch(detail: str) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]]:
    """(mode, iface, kind, path) told by a mode_change detail; None when it cannot be read."""
    m = _SWITCH.match(detail.strip())
    if not m or m.group(2) not in net_setup.MODES:
        return None
    mode, reason = m.group(2), m.group(3)
    if mode == "mode_a" and "PPPoE server answers" in reason:
        # pppoe-discovery answered on the WAN port: the box sat on the ISP's access line itself
        return mode, "ppp0", "pppoe", "direct_pppoe"
    if mode == "standalone" and "bridged to it (LAN passthrough)" in reason:
        # only automatic mode's own reason proves it; "LAN passthrough or link aggregation enabled" does not
        return mode, net_setup.PASSTHROUGH_BRIDGE, "passthrough", None
    on = _ON_IFACE.search(reason)
    iface = on.group(1) if on else None
    kind = net_setup.uplink_kind_by_name(iface, mode) if iface and mode == "standalone" else None
    return mode, (iface if kind else None), kind, None


def _fill_speedtest(row: sqlite3.Row, hist: History) -> List[Tuple[str, Any]]:
    """(field, value) to write into one speedtest row (only empty fields)."""
    if row["setup_source"]:
        return []
    ts = int(row["ts"])
    h_mode, _, h_kind, h_path = hist.at(ts)
    mode = row["box_mode"] or h_mode
    out: List[Tuple[str, Any]] = []
    if not row["box_mode"] and mode:
        out.append(("box_mode", mode))
    # from the stored interface only; a row without one keeps the link unknown (no guess from the mode)
    kind = row["uplink_kind"] or net_setup.uplink_kind_by_name(row["bound_iface"], mode, hist.usb_ifaces)
    if not row["uplink_kind"] and kind:
        out.append(("uplink_kind", kind))
    path = row["isp_path"] or (net_setup.isp_path_for(kind, row["bound_ip"]) if kind else None)
    if path is None and kind == "pppoe" and h_path == "direct_pppoe":
        path = "direct_pppoe"
    if not row["isp_path"] and path:
        out.append(("isp_path", path))
    if not out:
        return []
    span = row["duration_ms"] if row["duration_ms"] else (DEFAULT_TEST_MS if row["status"] == "ok" else 0)
    changed = hist.mode_changed(ts, ts + int(span), mode)
    out.append(("setup_source", "changed" if changed else "derived"))
    return out


def apply(conn: sqlite3.Connection, now_ms: Optional[int] = None) -> int:
    """Run once; returns the number of values written (0 when it already ran)."""
    if conn.in_transaction:
        return 0
    from nmb.db import corrections
    conn.executescript(corrections.SCHEMA)
    net_setup.ensure_schema(conn)
    if conn.execute("SELECT 1 FROM kv WHERE k = ?", (MARKER,)).fetchone():
        return 0
    cols = {r[1] for r in conn.execute("PRAGMA table_info(speedtest)").fetchall()}
    if not {"uplink_kind", "isp_path", "setup_source", "box_mode"} <= cols:
        return 0                        # columns not migrated yet: run on the next connect
    now_ms = now_ms or int(time.time() * 1000)
    hist = History.load(conn)
    written = _write_history(conn, hist) + _fill_speedtests(conn, hist, now_ms) + _fill_outages(conn, hist)
    conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (MARKER, str(written), now_ms))
    conn.commit()
    if written:
        log.info("measurement setup: %d values derived from the event log (marked 'derived')", written)
    return written


def _write_history(conn: sqlite3.Connection, hist: History) -> int:
    """Derived network_state rows for the time before netd recorded the setup itself."""
    first = conn.execute("SELECT MIN(ts) FROM network_state WHERE source = 'recorded'").fetchone()[0]
    rows, prev = [], None
    for ts, mode, iface, kind, path, detail in hist.states:
        if first is not None and ts >= first:
            break
        key = (mode, iface, kind, path)
        if key == prev:
            continue
        prev = key
        rows.append((ts, mode, iface, kind, path, "derived", detail))
    conn.execute("BEGIN IMMEDIATE")
    try:
        # checked inside the transaction: two processes starting together after an update write it once
        if conn.execute("SELECT 1 FROM network_state WHERE source = 'derived' LIMIT 1").fetchone() or \
                conn.execute("SELECT 1 FROM kv WHERE k = ?", (MARKER,)).fetchone():
            conn.execute("COMMIT")
            return 0
        conn.executemany("INSERT INTO network_state (ts, box_mode, iface, uplink_kind, isp_path, source, detail) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def _fill_speedtests(conn: sqlite3.Connection, hist: History, now_ms: int) -> int:
    ids = [r[0] for r in conn.execute("SELECT id FROM speedtest WHERE setup_source IS NULL ORDER BY id").fetchall()]
    changed, prev = 0, conn.row_factory
    try:
        for start in range(0, len(ids), BATCH_ROWS):
            chunk = ids[start:start + BATCH_ROWS]
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(f"SELECT * FROM speedtest WHERE id IN ({','.join('?' * len(chunk))}) "
                                    "AND setup_source IS NULL", chunk).fetchall()
                conn.row_factory = prev
                for row in rows:
                    for field, value in _fill_speedtest(row, hist):
                        conn.execute(f"UPDATE speedtest SET {field} = ? WHERE id = ?", (value, row["id"]))
                        conn.execute(
                            "INSERT INTO speedtest_correction (speedtest_id, field, old_value, new_value, reason, ts) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (row["id"], field, None, str(value), REASON, now_ms))
                        changed += 1
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.row_factory = prev
    return changed


def _fill_outages(conn: sqlite3.Connection, hist: History) -> int:
    rows = conn.execute("SELECT id, start_ts FROM outage WHERE setup_source IS NULL").fetchall()
    updates = []
    for oid, start_ts in rows:
        mode, _, kind, path = hist.at(int(start_ts))
        if mode or kind or path:
            updates.append((mode, kind, path, "derived", oid))
    if not updates:
        return 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany("UPDATE outage SET box_mode = ?, uplink_kind = ?, isp_path = ?, setup_source = ? "
                         "WHERE id = ? AND setup_source IS NULL", updates)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(updates)
