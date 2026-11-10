"""One-off correction of speed test values that NMB filled in instead of measuring (2026-11-10).

Before 2026-11-10 the engines and the runner stored placeholders as if they were measurements:
0 % packet loss from engines that do not measure loss, a fixed 0.5 ms RTR jitter, an estimated RTR
bufferbloat, an "A+" bufferbloat grade without any loaded sample, the block size as the iPerf3 TCP
window, the box's LAN address as the public client IP, home pages as result links, fixed server
places. This module clears exactly those values in the stored rows.

Nothing is lost: every cleared value is kept in the table speedtest_correction (row id, field, the
old value, the reason, when), so the change can be checked and undone. It runs once per database
(kv marker), inside one IMMEDIATE transaction, and never touches a value it cannot recognise as
made up.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from nmb.common.netaddr import global_ip

log = logging.getLogger("nmb.db.corrections")

MARKER = "data_correction_2026_11_10"

SCHEMA = """
CREATE TABLE IF NOT EXISTS speedtest_correction (
    id          INTEGER PRIMARY KEY,
    speedtest_id INTEGER NOT NULL,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    reason      TEXT NOT NULL,
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_speedtest_correction_row ON speedtest_correction(speedtest_id);
"""

GENERIC_RESULT_URLS = ("https://speed.cloudflare.com", "https://speed.cloudflare.com/",
                       "https://www.netztest.at", "https://www.netztest.at/")
PLACEHOLDER_LOCATIONS = ("Vienna, Austria (BEREC Cluster)", "Anycast Edge")
PLACEHOLDER_WINDOW_PREFIXES = ("Block:", "MSS:", "Auto (TCP Autotuning)")


def _raw(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        data = json.loads(row["raw_json"] or "")
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def corrections_for(row: sqlite3.Row) -> List[Tuple[str, Any, Any, str]]:
    """(field, old, new, reason) for one stored speedtest row; empty when nothing is made up."""
    out: List[Tuple[str, Any, Any, str]] = []
    keys = row.keys()

    def fix(field: str, new: Any, reason: str) -> None:
        if field in keys and row[field] is not None and row[field] != new:
            out.append((field, row[field], new, reason))

    engine = (row["engine"] or "").lower()
    raw = _raw(row)

    # Packet loss: Cloudflare and RTR never measure it; Ookla only when its JSON has packetLoss.
    if engine in ("cloudflare", "rtr"):
        fix("loss_pct", None, f"{engine} does not measure packet loss; 0 % was a placeholder")
    elif engine == "ookla" and row["loss_pct"] is not None and raw and "packetLoss" not in raw:
        fix("loss_pct", None, "Ookla did not report packet loss for this test; 0 % was a placeholder")

    # RTR: fixed 0.5 ms jitter of the old wrapper, |median-min| of the Python fallback, estimated
    # bufferbloat, fixed place and colo.
    if engine == "rtr":
        raw_engine = raw.get("engine")
        if row["jitter_us"] == 500 and raw_engine == "rtr-nettest-native-c" and "ping_count" not in raw:
            fix("jitter_us", None, "RTR jitter 0.5 ms was a fixed value of the old wrapper")
        elif raw_engine == "rtr-nettest" and "ping_count" not in raw:
            fix("jitter_us", None, "RTR fallback 'jitter' was median minus minimum, not jitter")
        for f in ("down_loaded_lat_ms", "up_loaded_lat_ms", "bufferbloat_grade", "bufferbloat_delta_ms"):
            fix(f, None, "RTR does not measure latency under load; the value was estimated")
        if row["colo"] == "VIE":
            fix("colo", None, "RTR colo 'VIE' was a fixed value")

    # Bufferbloat graded without any loaded-latency sample.
    if row["down_loaded_lat_ms"] is None and row["up_loaded_lat_ms"] is None and engine != "rtr":
        fix("bufferbloat_grade", None, "graded without any latency sample under load")
        fix("bufferbloat_delta_ms", None, "graded without any latency sample under load")

    # iPerf3: block size as 'window', 0 retransmits filled in, LAN address as client IP, loaded RTT in
    # the ping column, port as colo.
    if engine == "iperf3":
        if isinstance(row["tcp_window"], str) and row["tcp_window"].startswith(PLACEHOLDER_WINDOW_PREFIXES):
            fix("tcp_window", None, "the iPerf3 block size / MSS was stored as the TCP window")
        if row["ping_us"] is not None:
            fix("ping_us", None, "iPerf3 RTT is the TCP RTT under upload load, not an idle ping")
            if row["up_bps"] is not None and row["up_loaded_lat_ms"] is None:
                out.append(("up_loaded_lat_ms", None, round(row["ping_us"] / 1000.0, 2),
                            "iPerf3 TCP RTT under upload load moved to the loaded-latency column"))
        if isinstance(row["colo"], str) and row["colo"].startswith("Port "):
            fix("colo", None, "the iPerf3 port was stored as the colo")

    # Places that were fixed strings, and the client's own town stored as the Cloudflare server place.
    if row["server_location"] in PLACEHOLDER_LOCATIONS:
        fix("server_location", None, "fixed placeholder, not the server's place")
    elif engine == "cloudflare" and row["server_location"] and row["colo"] \
            and not str(row["server_location"]).startswith("Cloudflare "):
        fix("server_location", f"Cloudflare {row['colo']}",
            "Cloudflare's city/country headers describe the client, not the server")

    # Home pages stored as the result link.
    if row["result_url"] in GENERIC_RESULT_URLS:
        fix("result_url", None, "a home page, not a result page")

    # Client IP: only a public address is the line's address; a LAN/CGNAT address is not.
    if row["client_ip"] and global_ip(row["client_ip"]) is None:
        fix("client_ip", None, "not a public address (LAN, CGNAT or invalid)")
        if "bound_ip" in keys and not row["bound_ip"]:
            out.append(("bound_ip", None, row["client_ip"], "the local address kept as the bound address"))
    if row["client_ipv6"] and global_ip(row["client_ipv6"]) is None:
        fix("client_ipv6", None, "not a public address (link-local, ULA or invalid)")

    # A 0 ms round trip is not a measurement.
    if row["ping_us"] == 0:
        fix("ping_us", None, "0 ms was stored for a missing ping")
    seen, unique = set(), []
    for item in out:                      # one change per field, the first reason wins
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


# Second pass (found by the independent review of 2026-11-10): placeholders the first pass missed.
MARKER_B = "data_correction_2026_11_10b"
# c2d0ed6 went live at this time; older Cloudflare rows could store the idle latency as "loaded".
CLOUDFLARE_FIX_MS = 1794313356000


def corrections_b_for(row: sqlite3.Row) -> List[Tuple[str, Any, Any, str]]:
    from nmb.common.netaddr import is_local_ip
    out: List[Tuple[str, Any, Any, str]] = []
    keys = row.keys()

    def fix(field: str, new: Any, reason: str) -> None:
        if field in keys and row[field] != new and (row[field] is not None or new is not None):
            out.append((field, row[field], new, reason))

    engine = (row["engine"] or "").lower()
    raw = _raw(row)
    if engine == "cloudflare" and row["jitter_us"] == 0:
        fix("jitter_us", None, "Cloudflare stored 0 ms jitter when it had fewer than two latency samples")
    if engine == "rtr" and raw.get("engine") == "rtr-nettest" and "ping_count" not in raw \
            and raw.get("ping_min_ms") == 15.0 and raw.get("ping_median_ms") == 15.0:
        fix("ping_us", None, "RTR fallback invented 15 ms when no ping came back")
    if engine == "cloudflare" and (row["ts"] or 0) < CLOUDFLARE_FIX_MS and row["ping_us"] is not None:
        idle = round(row["ping_us"] / 1000.0, 2)
        same = [f for f in ("down_loaded_lat_ms", "up_loaded_lat_ms") if row[f] is not None and round(row[f], 2) == idle]
        for f in same:
            fix(f, None, "the idle latency was stored as the latency under load (no sample under load)")
        if same and row["bufferbloat_grade"] is not None:
            fix("bufferbloat_grade", None, "graded from the idle latency stored as the loaded one")
            fix("bufferbloat_delta_ms", None, "graded from the idle latency stored as the loaded one")
    host = str(row["server_host"] or "")
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    if engine == "iperf3" and is_local_ip(host) and "client_ip_source" in keys and row["client_ip_source"] != "local":
        fix("client_ip_source", "local", "a test against a server on the local network (it measured the LAN)")
        if not row["client_ip"] and row["bound_ip"] and is_local_ip(row["bound_ip"]):
            fix("client_ip", row["bound_ip"], "a LAN test keeps the box's local address")
    return out


# Third pass (second independent review): the old Cloudflare code truncated the idle latency for ping_us
# but rounded it for the "loaded" columns, so pass B's exact match missed about 5 % of those rows; and a
# direction stored as 0 bit/s in a successful test was a direction that was not measured.
MARKER_C = "data_correction_2026_11_10c"


def corrections_c_for(row: sqlite3.Row) -> List[Tuple[str, Any, Any, str]]:
    out: List[Tuple[str, Any, Any, str]] = []
    keys = row.keys()

    def fix(field: str, new: Any, reason: str) -> None:
        if field in keys and row[field] != new and (row[field] is not None or new is not None):
            out.append((field, row[field], new, reason))

    engine = (row["engine"] or "").lower()
    if engine == "cloudflare" and (row["ts"] or 0) < CLOUDFLARE_FIX_MS and row["ping_us"] is not None:
        idle_trunc = row["ping_us"] / 1000.0          # int(idle * 1000) / 1000: up to 1 us below the idle value
        same = [f for f in ("down_loaded_lat_ms", "up_loaded_lat_ms")
                if row[f] is not None and -0.006 <= row[f] - idle_trunc <= 0.0061]
        for f in same:
            fix(f, None, "the idle latency was stored as the latency under load (no sample under load)")
        if same and row["bufferbloat_grade"] is not None:
            fix("bufferbloat_grade", None, "graded from the idle latency stored as the loaded one")
            fix("bufferbloat_delta_ms", None, "graded from the idle latency stored as the loaded one")
    if row["status"] == "ok":
        for f in ("down_bps", "up_bps"):
            if row[f] == 0:
                fix(f, None, "0 bit/s was stored for a direction that was not measured")
    return out


BATCH_ROWS = 300
PASSES = None   # set below: (marker, rule) in order


def apply(conn: sqlite3.Connection, now_ms: Optional[int] = None) -> int:
    """Every pass that has not run on this database yet; returns the number of changed values."""
    return sum(_apply_pass(conn, marker, rule, now_ms) for marker, rule in PASSES)


def _apply_pass(conn: sqlite3.Connection, marker: str, rule, now_ms: Optional[int] = None) -> int:
    """Run the correction once; returns the number of changed values (0 when it already ran).

    Short IMMEDIATE transactions of BATCH_ROWS rows each, so the probe and the other writers never wait
    long (their busy timeout is 5 s). Each batch reads its rows again inside its transaction and only
    corrects what is still made up, so an interrupted run, or two processes at once, change every value
    at most once; the marker is written when every batch is done.
    """
    if conn.in_transaction:
        return 0
    conn.executescript(SCHEMA)
    if conn.execute("SELECT 1 FROM kv WHERE k = ?", (marker,)).fetchone():
        return 0
    now_ms = now_ms or int(time.time() * 1000)
    ids = [r[0] for r in conn.execute("SELECT id FROM speedtest ORDER BY id").fetchall()]
    changed = 0
    prev = conn.row_factory
    try:
        for start in range(0, len(ids), BATCH_ROWS):
            chunk = ids[start:start + BATCH_ROWS]
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    f"SELECT * FROM speedtest WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
                conn.row_factory = prev
                for row in rows:
                    for field, old, new, reason in rule(row):
                        conn.execute(f"UPDATE speedtest SET {field} = ? WHERE id = ?", (new, row["id"]))
                        conn.execute(
                            "INSERT INTO speedtest_correction (speedtest_id, field, old_value, new_value, reason, ts) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (row["id"], field, None if old is None else str(old),
                             None if new is None else str(new), reason, now_ms))
                        changed += 1
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (marker, str(changed), now_ms))
        conn.commit()
    finally:
        conn.row_factory = prev
    if changed:
        log.info("speed test data: %d made-up values cleared (originals kept in speedtest_correction)", changed)
    return changed


PASSES = ((MARKER, corrections_for), (MARKER_B, corrections_b_for), (MARKER_C, corrections_c_for))
