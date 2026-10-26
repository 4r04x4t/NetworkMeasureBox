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


def _iso(ts_ms: int) -> str:
    return datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc).isoformat()


def export_ping_summary_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "timestamp_iso", "timestamp_ms", "target_id", "target_addr", "target_label",
        "sent", "lost", "loss_pct", "rtt_min_ms", "rtt_avg_ms", "rtt_p95_ms", "rtt_max_ms", "jitter_ms"
    ])

    targets = {r["id"]: (r["addr"], r["label"]) for r in conn.execute("SELECT id, addr, label FROM target").fetchall()}
    rows = conn.execute(
        """SELECT ts, target_id, sent, lost, rtt_min, rtt_avg, rtt_p95, rtt_max, jitter_us
           FROM ping_minute WHERE ts >= ? AND ts <= ? ORDER BY ts ASC""",
        (start_ms, end_ms)
    ).fetchall()

    for r in rows:
        addr, label = targets.get(r["target_id"], ("", ""))
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
        ])
    return out.getvalue()


def export_speedtests_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int, contract_down_mbps: float = 0.0, contract_up_mbps: float = 0.0) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "timestamp_iso", "timestamp_ms", "trigger", "status", "engine", "colo", "connection_type",
        "client_ip", "client_ipv6", "down_mbps", "up_mbps", "down_pct_of_offered", "up_pct_of_offered", "ping_ms", "jitter_ms", "loss_pct",
        "bufferbloat_grade", "bufferbloat_delta_ms", "down_loaded_lat_ms", "up_loaded_lat_ms",
        "server_id", "server_name", "server_host", "server_location", "result_url", "error"
    ])

    rows = conn.execute(
        """SELECT ts, trigger, status, down_bps, up_bps, ping_us, jitter_us, loss_pct,
                  server_id, server_name, server_host, server_location, client_ip, client_ipv6, result_url, error,
                  down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms,
                  connection_type, engine, colo
           FROM speedtest WHERE ts >= ? AND ts <= ? ORDER BY ts DESC""",
        (start_ms, end_ms)
    ).fetchall()

    for r in rows:
        d_mbps = round(r["down_bps"] / 1_000_000.0, 2) if r["down_bps"] else None
        u_mbps = round(r["up_bps"] / 1_000_000.0, 2) if r["up_bps"] else None
        d_pct = round((d_mbps / contract_down_mbps) * 100.0, 1) if (contract_down_mbps > 0 and d_mbps is not None) else ""
        u_pct = round((u_mbps / contract_up_mbps) * 100.0, 1) if (contract_up_mbps > 0 and u_mbps is not None) else ""

        client_ipv6_val = r["client_ipv6"] if "client_ipv6" in r.keys() and r["client_ipv6"] else ""

        writer.writerow([
            _iso(r["ts"]),
            r["ts"],
            r["trigger"],
            r["status"],
            r["engine"] or "ookla",
            r["colo"] or "",
            r["connection_type"] or "",
            r["client_ip"] or "",
            client_ipv6_val,
            d_mbps if d_mbps is not None else "",
            u_mbps if u_mbps is not None else "",
            d_pct,
            u_pct,
            round(r["ping_us"] / 1000.0, 2) if r["ping_us"] else "",
            round(r["jitter_us"] / 1000.0, 2) if r["jitter_us"] else "",
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
        ])
    return out.getvalue()


def export_outages_csv(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["outage_id", "start_time_iso", "end_time_iso", "start_ms", "end_ms", "duration_sec", "cause"])

    rows = conn.execute(
        """SELECT id, start_ts, end_ts, cause FROM outage
           WHERE (end_ts IS NULL OR end_ts >= ?) AND start_ts <= ?
           ORDER BY start_ts DESC""",
        (start_ms, end_ms)
    ).fetchall()

    for r in rows:
        e_ts = r["end_ts"]
        dur = int((e_ts - r["start_ts"]) / 1000) if e_ts else ""
        writer.writerow([
            r["id"],
            _iso(r["start_ts"]),
            _iso(e_ts) if e_ts else "ONGOING",
            r["start_ts"],
            e_ts or "",
            dur,
            r["cause"] or "",
        ])
    return out.getvalue()


def export_all_csvs(conn: sqlite3.Connection, out_dir: Path, window_hours: float = 24.0) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = db.now_ms()
    start = now - int(window_hours * 3600 * 1000)

    pings_file = out_dir / "ping_summary.csv"
    pings_file.write_text(export_ping_summary_csv(conn, start, now))

    speed_file = out_dir / "speedtests.csv"
    speed_file.write_text(export_speedtests_csv(conn, start, now))

    outages_file = out_dir / "outages.csv"
    outages_file.write_text(export_outages_csv(conn, start, now))

    return [pings_file, speed_file, outages_file]
