"""Raw CSV exporter for technical escalation and regulatory filing.

Exports ping summaries, speedtests, outages, and port-throttling records
in standard RFC 4180 format.
"""
from __future__ import annotations

import csv
import datetime
import io
import sqlite3
from pathlib import Path
from typing import Optional

from nmb.db import database as db


def parse_export_range(qs: dict, now_ms: int, default_hours: Optional[float]) -> tuple:
    """(start_ms, end_ms) from the query: from= / to= (YYYY-MM-DD, an ISO time, or epoch ms) or
    hours= / days=. Without any, the last default_hours (None = everything). ValueError on bad input."""
    def one(name: str) -> Optional[str]:
        v = qs.get(name)
        if isinstance(v, list):
            v = v[0] if v else None
        return str(v).strip() if v not in (None, "") else None

    def stamp(text: str, end_of_day: bool) -> int:
        if text.isdigit():
            return int(text)
        if len(text) == 10:
            d = datetime.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            if end_of_day:
                d += datetime.timedelta(days=1)
            return int(d.timestamp() * 1000) - (1 if end_of_day else 0)
        d = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return int(d.timestamp() * 1000)

    f, t, hours, days = one("from"), one("to"), one("hours"), one("days")
    end = stamp(t, True) if t else now_ms
    if f:
        start = stamp(f, False)
    elif hours or days:
        span_h = float(hours) if hours else float(days) * 24.0
        if not 0 < span_h <= 24 * 3650:
            raise ValueError("range out of bounds")
        start = end - int(span_h * 3_600_000)
    else:
        start = 0 if default_hours is None else end - int(default_hours * 3_600_000)
    if start > end:
        raise ValueError("from is after to")
    return start, end


def _safe(value):
    """A text cell that a spreadsheet would run as a formula (=, +, -, @ first) gets a leading quote:
    server names, error texts and event details come from outside the box."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r") and value != "--":
        return "'" + value
    return value


class _SafeWriter:
    def __init__(self, out, **kw):
        self._w = csv.writer(out, **kw)

    def writerow(self, row):
        self._w.writerow([_safe(v) for v in row])


def _iso(ts_ms: int) -> str:
    return datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc).isoformat()


def export_ping_summary_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> str:
    out = io.StringIO()
    writer = _SafeWriter(out)
    writer.writerow([
        "timestamp_iso", "timestamp_ms", "target_id", "target_addr", "target_label",
        "sent", "lost", "loss_pct", "rtt_min_ms", "rtt_avg_ms", "rtt_p95_ms", "rtt_max_ms", "jitter_ms",
        "target_role", "time_zone",
    ])

    targets = {r["id"]: (r["addr"], r["label"], r["role"]) for r in conn.execute("SELECT id, addr, label, role FROM target").fetchall()}
    rows = conn.execute(
        """SELECT ts, target_id, sent, lost, rtt_min, rtt_avg, rtt_p95, rtt_max, jitter_us
           FROM ping_minute WHERE ts >= ? AND ts <= ? ORDER BY ts ASC""",
        (start_ms, end_ms)
    ).fetchall()

    for r in rows:
        addr, label, role = targets.get(r["target_id"], ("", "", ""))
        loss_pct = round((r["lost"] / r["sent"] * 100.0) if r["sent"] > 0 else 0.0, 2)
        writer.writerow([
            _iso(r["ts"]),
            r["ts"],
            r["target_id"],
            addr,
            label,
            r["sent"],
            r["lost"],
            loss_pct,
            round(r["rtt_min"] / 1000.0, 2) if r["rtt_min"] is not None else "",
            round(r["rtt_avg"] / 1000.0, 2) if r["rtt_avg"] is not None else "",
            round(r["rtt_p95"] / 1000.0, 2) if r["rtt_p95"] is not None else "",
            round(r["rtt_max"] / 1000.0, 2) if r["rtt_max"] is not None else "",
            round(r["jitter_us"] / 1000.0, 2) if r["jitter_us"] is not None else "",
            role or "",
            "UTC",
        ])
    return out.getvalue()


def export_speedtests_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int, contract_down_mbps: float = 0.0,
                          contract_up_mbps: float = 0.0, default_isp: str = "", box_id: str = "") -> str:
    """All speed test fields. The first 27 columns keep their order (anyone reading them by position is
    not broken); the columns after them were added on 2026-11-10. Times are UTC."""
    out = io.StringIO()
    writer = _SafeWriter(out)
    writer.writerow([
        "timestamp_iso", "timestamp_ms", "trigger", "status", "engine", "colo", "connection_type",
        "client_ip", "client_ipv6", "isp_name", "down_mbps", "up_mbps", "down_pct_of_offered", "up_pct_of_offered", "ping_ms", "jitter_ms", "loss_pct",
        "bufferbloat_grade", "bufferbloat_delta_ms", "down_loaded_lat_ms", "up_loaded_lat_ms",
        "server_id", "server_name", "server_host", "server_location", "result_url", "error",
        "row_id", "time_zone", "cycle_time_iso", "duration_s", "bound_iface", "bound_ip", "retransmits",
        "tcp_window", "box_id", "nmb_version", "box_mode", "client_ip_source",
    ])

    rows = conn.execute(
        """SELECT ts, trigger, status, down_bps, up_bps, ping_us, jitter_us, loss_pct,
                  server_id, server_name, server_host, server_location, client_ip, client_ipv6, result_url, error,
                  down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms,
                  connection_type, engine, colo, id, cycle_ts, duration_ms, bound_iface, bound_ip,
                  retransmits, tcp_window, nmb_version, box_mode, client_ip_source
           FROM speedtest WHERE ts >= ? AND ts <= ? ORDER BY ts DESC""",
        (start_ms, end_ms)
    ).fetchall()

    for r in rows:
        r = dict(r)
        try:
            from nmb.speed.iperf_directory import label_iperf_row
            label_iperf_row(r)
        except Exception:
            pass
        r_keys = r.keys()
        d_mbps = round(r["down_bps"] / 1_000_000.0, 2) if r["down_bps"] is not None else None
        u_mbps = round(r["up_bps"] / 1_000_000.0, 2) if r["up_bps"] is not None else None
        d_pct = round((d_mbps / contract_down_mbps) * 100.0, 1) if (contract_down_mbps > 0 and d_mbps is not None) else ""
        u_pct = round((u_mbps / contract_up_mbps) * 100.0, 1) if (contract_up_mbps > 0 and u_mbps is not None) else ""

        client_ipv6_val = r["client_ipv6"] if "client_ipv6" in r_keys and r["client_ipv6"] else ""
        isp = default_isp or ""          # the configured name; nothing is made up when none is set

        writer.writerow([
            _iso(r["ts"]),
            r["ts"],
            r["trigger"],
            r["status"],
            r["engine"] or "",
            r["colo"] or "",
            r["connection_type"] or "",
            r["client_ip"] or "",
            client_ipv6_val,
            isp,
            d_mbps if d_mbps is not None else "",
            u_mbps if u_mbps is not None else "",
            d_pct,
            u_pct,
            round(r["ping_us"] / 1000.0, 2) if r["ping_us"] is not None else "",
            round(r["jitter_us"] / 1000.0, 2) if r["jitter_us"] is not None else "",
            r["loss_pct"] if r["loss_pct"] is not None else "",
            r["bufferbloat_grade"] or "",
            r["bufferbloat_delta_ms"] if r["bufferbloat_delta_ms"] is not None else "",
            r["down_loaded_lat_ms"] if r["down_loaded_lat_ms"] is not None else "",
            r["up_loaded_lat_ms"] if r["up_loaded_lat_ms"] is not None else "",
            r["server_id"] or "",
            r["server_name"] or "",
            r["server_host"] or "",
            r["server_location"] or "",
            r["result_url"] or "",
            r["error"] or "",
            r["id"],
            "UTC",
            _iso(r["cycle_ts"]) if r["cycle_ts"] else "",
            round(r["duration_ms"] / 1000.0, 1) if r["duration_ms"] is not None else "",
            r["bound_iface"] or "",
            r["bound_ip"] or "",
            r["retransmits"] if r["retransmits"] is not None else "",
            r["tcp_window"] or "",
            box_id or "",
            r["nmb_version"] or "",
            r["box_mode"] or "",
            r["client_ip_source"] or "",
        ])
    return out.getvalue()


def export_detailed_speedtests_csv(
    conn: sqlite3.Connection,
    start_ms: int,
    end_ms: int,
    contract_down_mbps: float = 0.0,
    contract_up_mbps: float = 0.0,
    guaranteed_down_mbps: float = 0.0,
    guaranteed_up_mbps: float = 0.0,
    default_isp: str = "",
) -> str:
    """The detailed semicolon-separated speed test CSV (UTF-8 with BOM, for spreadsheets).

    Speeds that are not set are 0 and judge nothing: the export used to fill in 1000/200 and 300/50
    Mbit/s. A value that was not measured is "--", never "0 %" or "0 ms". Times are UTC (column
    "Time zone" says so). The status code is the dossier's (nmb/report/status_codes.py).
    """
    from nmb.report.status_codes import classify
    out = io.StringIO()
    # Semicolon delimited with UTF-8 BOM
    out.write("\ufeff")
    writer = _SafeWriter(out, delimiter=";")
    writer.writerow([
        "Time", "IP address", "ISP", "Download", "Download %", "Upload", "Upload %", "Latency", "Status",
        "Time zone", "Status text", "Engine", "Interface",
    ])

    rows = conn.execute(
        """SELECT ts, trigger, status, down_bps, up_bps, ping_us, jitter_us, client_ip, client_ipv6,
                  connection_type, error, engine, bound_iface
           FROM speedtest WHERE ts >= ? AND ts <= ? ORDER BY ts DESC""",
        (start_ms, end_ms)
    ).fetchall()

    def pct(value: Optional[float], of: float) -> str:
        return f"{round(value / of * 100.0)} %" if (of and of > 0 and value is not None) else "--"

    for r in rows:
        d_mbps = r["down_bps"] / 1_000_000.0 if r["down_bps"] is not None else None
        u_mbps = r["up_bps"] / 1_000_000.0 if r["up_bps"] is not None else None
        dt = datetime.datetime.fromtimestamp(r["ts"] / 1000.0, tz=datetime.timezone.utc)
        code, text = classify(r["status"], r["error"], d_mbps, u_mbps, bound_iface=r["bound_iface"],
                              connection_type=r["connection_type"],
                              contract_down=contract_down_mbps, contract_up=contract_up_mbps,
                              guaranteed_down=guaranteed_down_mbps, guaranteed_up=guaranteed_up_mbps)
        writer.writerow([
            dt.strftime("%Y-%m-%d %H:%M:%S"),
            r["client_ip"] or r["client_ipv6"] or "--",
            default_isp or "",
            f"{d_mbps:.2f} Mb/s" if d_mbps is not None else "--",
            pct(d_mbps, contract_down_mbps),
            f"{u_mbps:.2f} Mb/s" if u_mbps is not None else "--",
            pct(u_mbps, contract_up_mbps),
            f"{round(r['ping_us'] / 1000.0)} ms" if r["ping_us"] is not None else "--",
            code,
            "UTC",
            text,
            r["engine"] or "",
            r["bound_iface"] or "",
        ])

    return out.getvalue()


def export_outages_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> str:
    """Outages with the part the box caused itself taken out (counted_sec) and their kind:
    "isp" (counted against the line) or "own" (the box's own mode change, update or restart)."""
    from nmb.report.metrics import effective_outage_ends, own_action_windows, subtract_spans, MIN_ISP_OUTAGE_SEC
    out = io.StringIO()
    writer = _SafeWriter(out)
    writer.writerow(["outage_id", "start_time_iso", "end_time_iso", "start_ms", "end_ms", "duration_sec", "cause",
                     "cause_kind", "counted_sec", "own_action_sec"])

    rows = conn.execute(
        """SELECT id, start_ts, end_ts, cause FROM outage
           WHERE (end_ts IS NULL OR end_ts >= ?) AND start_ts <= ?
           ORDER BY start_ts DESC""",
        (start_ms, end_ms)
    ).fetchall()
    now = db.now_ms()
    ends = effective_outage_ends(conn, rows, now)
    windows = own_action_windows(conn, start_ms, end_ms)

    for r in rows:
        e_ts = r["end_ts"] or ends.get(r["id"])
        dur = int((e_ts - r["start_ts"]) / 1000) if e_ts else ""
        span_end = e_ts or now
        counted_ms = sum(b - a for a, b in subtract_spans((r["start_ts"], span_end), windows))
        own_ms = (span_end - r["start_ts"]) - counted_ms
        kind = "own" if (own_ms > 0 and counted_ms < MIN_ISP_OUTAGE_SEC * 1000) else "isp"
        writer.writerow([
            r["id"],
            _iso(r["start_ts"]),
            _iso(e_ts) if e_ts else "ONGOING",
            r["start_ts"],
            e_ts or "",
            dur,
            r["cause"] or "",
            kind,
            0 if kind == "own" else int(counted_ms / 1000),
            int(own_ms / 1000),
        ])
    return out.getvalue()


def export_events_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> str:
    """The box's event log (mode changes, its own actions, outages, PPPoE, DHCP, USB, tests).

    Only for the logged-in owner: event details can name settings. Times are UTC."""
    out = io.StringIO()
    writer = _SafeWriter(out)
    writer.writerow(["event_id", "time_iso", "time_ms", "time_zone", "severity", "source", "kind", "detail"])
    for r in conn.execute(
            "SELECT id, ts, severity, source, kind, detail FROM event WHERE ts >= ? AND ts <= ? ORDER BY ts DESC",
            (start_ms, end_ms)).fetchall():
        detail = r["detail"] or ""
        writer.writerow([r["id"], _iso(r["ts"]), r["ts"], "UTC", r["severity"], r["source"], r["kind"], detail])
    return out.getvalue()


def export_all_csvs(conn: sqlite3.Connection, out_dir: Path, window_hours: float = 24.0) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = db.now_ms()
    start = now - int(window_hours * 3600 * 1000)

    pings_file = out_dir / "ping_summary.csv"
    pings_file.write_text(export_ping_summary_csv(conn, start, now), encoding="utf-8")

    speed_file = out_dir / "speedtests.csv"
    speed_file.write_text(export_speedtests_csv(conn, start, now), encoding="utf-8")

    outages_file = out_dir / "outages.csv"
    outages_file.write_text(export_outages_csv(conn, start, now), encoding="utf-8")

    events_file = out_dir / "events.csv"
    events_file.write_text(export_events_csv(conn, start, now), encoding="utf-8")

    return [pings_file, speed_file, outages_file, events_file]
