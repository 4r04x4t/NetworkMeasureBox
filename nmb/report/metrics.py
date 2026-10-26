"""Telemetry analytics and metric aggregation for ISP reports.

Queries ping_minute, speedtest, outage, and port_check tables across
a specified timeframe (e.g., 24h, 7d, 30d) to compute SLA compliance.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from nmb.config import Config
from nmb.db import database as db

log = logging.getLogger("nmb.report.metrics")


@dataclass
class OutageRecord:
    id: int
    start_ts: int
    end_ts: Optional[int]
    duration_sec: int
    cause: str


@dataclass
class PingSummary:
    total_sent: int = 0
    total_lost: int = 0
    loss_pct: float = 0.0
    rtt_min_ms: Optional[float] = None
    rtt_avg_ms: Optional[float] = None
    rtt_p95_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    jitter_avg_ms: Optional[float] = None


@dataclass
class TargetPingStats:
    target_id: int
    addr: str
    label: str
    sent: int = 0
    lost: int = 0
    loss_pct: float = 0.0
    avg_rtt_ms: Optional[float] = None
    p95_rtt_ms: Optional[float] = None


@dataclass
class SpeedtestSummary:
    total_tests: int = 0
    successful_tests: int = 0
    skipped_busy: int = 0
    avg_down_mbps: Optional[float] = None
    max_down_mbps: Optional[float] = None
    min_down_mbps: Optional[float] = None
    avg_up_mbps: Optional[float] = None
    max_up_mbps: Optional[float] = None
    min_up_mbps: Optional[float] = None
    avg_down_pct_of_offered: Optional[float] = None
    avg_up_pct_of_offered: Optional[float] = None
    min_down_pct_of_offered: Optional[float] = None
    max_down_pct_of_offered: Optional[float] = None
    avg_down_pct_of_guaranteed: Optional[float] = None
    avg_up_pct_of_guaranteed: Optional[float] = None
    sla_compliance_pct: float = 100.0


@dataclass
class TimeSeriesPoint:
    ts: int
    rtt_ms: Optional[float]
    loss_pct: float
    jitter_ms: Optional[float]


@dataclass
class ReportData:
    start_ms: int
    end_ms: int
    box_id: str
    isp_name: str
    account_id: str
    circuit_id: str
    contract_down_mbps: float
    contract_up_mbps: float
    guaranteed_down_mbps: float = 0.0
    guaranteed_up_mbps: float = 0.0
    isp_connection_type: str = "fiber"

    uptime_pct: float = 100.0
    total_outage_sec: int = 0
    outages: List[OutageRecord] = field(default_factory=list)

    ping_summary: PingSummary = field(default_factory=PingSummary)
    target_stats: List[TargetPingStats] = field(default_factory=list)
    timeseries: List[TimeSeriesPoint] = field(default_factory=list)

    speed_summary: SpeedtestSummary = field(default_factory=SpeedtestSummary)
    speed_tests: List[dict] = field(default_factory=list)

    port_checks: List[dict] = field(default_factory=list)
    throttled_ports_count: int = 0

    sla_verdict: str = "COMPLIANT"  # COMPLIANT, DEGRADED, BREACHED


def aggregate_report_data(
    conn: sqlite3.Connection,
    cfg: Config,
    window_hours: float = 24.0,
    end_ms: Optional[int] = None,
) -> ReportData:
    """Aggregate all telemetry into a structured ReportData dataclass."""
    # Ensure any recent raw ping samples are rolled into ping_minute (skip if readonly)
    try:
        is_ro = bool(conn.execute("PRAGMA query_only").fetchone()[0])
        if not is_ro:
            db.rollup_minutes(conn)
    except Exception as e:
        log.debug("rollup check skipped: %s", e)

    now = end_ms or db.now_ms()
    start = now - int(window_hours * 3600 * 1000)

    guar_down = float(getattr(cfg.isp, "guaranteed_down_mbps", 0.0) or 0.0)
    guar_up = float(getattr(cfg.isp, "guaranteed_up_mbps", 0.0) or 0.0)

    report = ReportData(
        start_ms=start,
        end_ms=now,
        box_id=cfg.system.box_id,
        isp_name=cfg.isp.name,
        account_id=cfg.isp.account_id,
        circuit_id=cfg.isp.circuit_id,
        contract_down_mbps=cfg.isp.contract_down_mbps,
        contract_up_mbps=cfg.isp.contract_up_mbps,
        guaranteed_down_mbps=guar_down,
        guaranteed_up_mbps=guar_up,
        isp_connection_type=getattr(cfg.isp, "connection_type", "fiber"),
    )

    # 1. Outages
    outage_rows = conn.execute(
        """SELECT id, start_ts, end_ts, cause FROM outage
           WHERE (end_ts IS NULL OR end_ts >= ?) AND start_ts <= ?
           ORDER BY start_ts DESC""",
        (start, now)
    ).fetchall()

    total_outage_ms = 0
    for r in outage_rows:
        o_start = max(start, r["start_ts"])
        o_end = min(now, r["end_ts"]) if r["end_ts"] else now
        dur_sec = max(0, int((o_end - o_start) / 1000))
        total_outage_ms += (o_end - o_start)
        report.outages.append(OutageRecord(
            id=r["id"],
            start_ts=r["start_ts"],
            end_ts=r["end_ts"],
            duration_sec=dur_sec,
            cause=r["cause"] or "Unreachable",
        ))

    window_duration_ms = max(1, now - start)
    report.total_outage_sec = int(total_outage_ms / 1000)
    report.uptime_pct = max(0.0, min(100.0, (1.0 - (total_outage_ms / window_duration_ms)) * 100.0))

    # 2. Ping Telemetry (from ping_minute)
    ping_rows = conn.execute(
        """SELECT target_id, ts, sent, lost, rtt_min, rtt_avg, rtt_p95, rtt_max, jitter_us
           FROM ping_minute
           WHERE ts >= ? AND ts <= ?
           ORDER BY ts ASC""",
        (start, now)
    ).fetchall()

    target_map = {
        r["id"]: (r["addr"], r["label"])
        for r in conn.execute("SELECT id, addr, label FROM target").fetchall()
    }

    per_target_accum: Dict[int, dict] = {}
    minute_buckets: Dict[int, List[dict]] = {}

    total_sent = 0
    total_lost = 0
    all_avg_rtts: List[float] = []
    all_jitters: List[float] = []

    for r in ping_rows:
        tid = r["target_id"]
        sent = r["sent"]
        lost = r["lost"]
        total_sent += sent
        total_lost += lost

        if r["rtt_avg"] is not None:
            rtt_ms = r["rtt_avg"] / 1000.0
            all_avg_rtts.append(rtt_ms)
        if r["jitter_us"] is not None:
            all_jitters.append(r["jitter_us"] / 1000.0)

        if tid not in per_target_accum:
            per_target_accum[tid] = {"sent": 0, "lost": 0, "rtts": []}
        per_target_accum[tid]["sent"] += sent
        per_target_accum[tid]["lost"] += lost
        if r["rtt_avg"] is not None:
            per_target_accum[tid]["rtts"].append(r["rtt_avg"] / 1000.0)

        # 15-minute bucketing for timeline chart
        bucket_ts = (r["ts"] // (15 * 60 * 1000)) * (15 * 60 * 1000)
        if bucket_ts not in minute_buckets:
            minute_buckets[bucket_ts] = []
        minute_buckets[bucket_ts].append(r)

    # Ping summary stats
    if total_sent > 0:
        report.ping_summary.total_sent = total_sent
        report.ping_summary.total_lost = total_lost
        report.ping_summary.loss_pct = round((total_lost / total_sent) * 100.0, 2)

    if all_avg_rtts:
        all_avg_rtts.sort()
        report.ping_summary.rtt_min_ms = round(all_avg_rtts[0], 2)
        report.ping_summary.rtt_avg_ms = round(sum(all_avg_rtts) / len(all_avg_rtts), 2)
        p95_idx = min(len(all_avg_rtts) - 1, int(len(all_avg_rtts) * 0.95))
        report.ping_summary.rtt_p95_ms = round(all_avg_rtts[p95_idx], 2)
        report.ping_summary.rtt_max_ms = round(all_avg_rtts[-1], 2)

    if all_jitters:
        report.ping_summary.jitter_avg_ms = round(sum(all_jitters) / len(all_jitters), 2)

    # Target stats breakdown
    for tid, accum in per_target_accum.items():
        addr, label = target_map.get(tid, (f"Target {tid}", f"ID {tid}"))
        t_sent = accum["sent"]
        t_lost = accum["lost"]
        t_loss_pct = round((t_lost / t_sent * 100.0) if t_sent > 0 else 0.0, 2)
        rtts = sorted(accum["rtts"])
        avg_rtt = round(sum(rtts) / len(rtts), 2) if rtts else None
        p95_rtt = round(rtts[min(len(rtts) - 1, int(len(rtts) * 0.95))], 2) if rtts else None

        report.target_stats.append(TargetPingStats(
            target_id=tid,
            addr=addr,
            label=label,
            sent=t_sent,
            lost=t_lost,
            loss_pct=t_loss_pct,
            avg_rtt_ms=avg_rtt,
            p95_rtt_ms=p95_rtt,
        ))

    # Time series points
    for b_ts in sorted(minute_buckets.keys()):
        b_rows = minute_buckets[b_ts]
        b_sent = sum(r["sent"] for r in b_rows)
        b_lost = sum(r["lost"] for r in b_rows)
        b_loss_pct = round((b_lost / b_sent * 100.0) if b_sent > 0 else 0.0, 2)
        b_rtts = [r["rtt_avg"] / 1000.0 for r in b_rows if r["rtt_avg"] is not None]
        b_jits = [r["jitter_us"] / 1000.0 for r in b_rows if r["jitter_us"] is not None]
        avg_rtt = round(sum(b_rtts) / len(b_rtts), 2) if b_rtts else None
        avg_jit = round(sum(b_jits) / len(b_jits), 2) if b_jits else None

        report.timeseries.append(TimeSeriesPoint(
            ts=b_ts,
            rtt_ms=avg_rtt,
            loss_pct=b_loss_pct,
            jitter_ms=avg_jit,
        ))

    # 3. Speedtest results
    speed_rows = conn.execute(
        """SELECT ts, trigger, status, server_name, server_host, server_location, client_ip, client_ipv6,
                  down_bps, up_bps, ping_us, jitter_us, loss_pct, result_url, error,
                  down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms, connection_type,
                  engine, colo
           FROM speedtest
           WHERE ts >= ? AND ts <= ?
           ORDER BY ts DESC""",
        (start, now)
    ).fetchall()

    down_mbps_list: List[float] = []
    up_mbps_list: List[float] = []
    compliant_tests = 0

    contract_down = float(cfg.isp.contract_down_mbps or 0.0)
    contract_up = float(cfg.isp.contract_up_mbps or 0.0)

    for s in speed_rows:
        d_dict = dict(s)
        d_mbps = (s["down_bps"] or 0) / 1_000_000.0 if s["down_bps"] else None
        u_mbps = (s["up_bps"] or 0) / 1_000_000.0 if s["up_bps"] else None
        d_dict["down_mbps"] = round(d_mbps, 2) if d_mbps is not None else None
        d_dict["up_mbps"] = round(u_mbps, 2) if u_mbps is not None else None

        # Speed percentage achieved compared to contracted (offered) and guaranteed speeds
        d_dict["down_pct_of_offered"] = round((d_mbps / contract_down) * 100.0, 1) if (contract_down > 0 and d_mbps is not None) else None
        d_dict["up_pct_of_offered"] = round((u_mbps / contract_up) * 100.0, 1) if (contract_up > 0 and u_mbps is not None) else None
        d_dict["down_pct_of_guaranteed"] = round((d_mbps / guar_down) * 100.0, 1) if (guar_down > 0 and d_mbps is not None) else None
        d_dict["up_pct_of_guaranteed"] = round((u_mbps / guar_up) * 100.0, 1) if (guar_up > 0 and u_mbps is not None) else None
        report.speed_tests.append(d_dict)

        if s["status"] == "ok":
            report.speed_summary.successful_tests += 1
            if d_mbps is not None:
                down_mbps_list.append(d_mbps)
            if u_mbps is not None:
                up_mbps_list.append(u_mbps)

            # SLA compliance: 80% of promised speed
            down_target = contract_down * 0.80
            up_target = contract_up * 0.80
            if (d_mbps or 0) >= down_target and (u_mbps or 0) >= up_target:
                compliant_tests += 1

        elif s["status"] == "skipped_busy":
            report.speed_summary.skipped_busy += 1

    report.speed_summary.total_tests = len(speed_rows)
    if report.speed_summary.successful_tests > 0:
        report.speed_summary.sla_compliance_pct = round(
            (compliant_tests / report.speed_summary.successful_tests) * 100.0, 1
        )
    if down_mbps_list:
        report.speed_summary.avg_down_mbps = round(sum(down_mbps_list) / len(down_mbps_list), 2)
        report.speed_summary.min_down_mbps = round(min(down_mbps_list), 2)
        report.speed_summary.max_down_mbps = round(max(down_mbps_list), 2)
        if contract_down > 0:
            report.speed_summary.avg_down_pct_of_offered = round((report.speed_summary.avg_down_mbps / contract_down) * 100.0, 1)
            report.speed_summary.min_down_pct_of_offered = round((report.speed_summary.min_down_mbps / contract_down) * 100.0, 1)
            report.speed_summary.max_down_pct_of_offered = round((report.speed_summary.max_down_mbps / contract_down) * 100.0, 1)
        if guar_down > 0:
            report.speed_summary.avg_down_pct_of_guaranteed = round((report.speed_summary.avg_down_mbps / guar_down) * 100.0, 1)
    if up_mbps_list:
        report.speed_summary.avg_up_mbps = round(sum(up_mbps_list) / len(up_mbps_list), 2)
        report.speed_summary.min_up_mbps = round(min(up_mbps_list), 2)
        report.speed_summary.max_up_mbps = round(max(up_mbps_list), 2)
        if contract_up > 0:
            report.speed_summary.avg_up_pct_of_offered = round((report.speed_summary.avg_up_mbps / contract_up) * 100.0, 1)
        if guar_up > 0:
            report.speed_summary.avg_up_pct_of_guaranteed = round((report.speed_summary.avg_up_mbps / guar_up) * 100.0, 1)

    # 4. Port Throttling Checks
    port_rows = conn.execute(
        """SELECT ts, proto, port, endpoint, bps, baseline_bps, ratio, verdict
           FROM port_check
           WHERE ts >= ? AND ts <= ?
           ORDER BY ts DESC""",
        (start, now)
    ).fetchall()

    for p in port_rows:
        report.port_checks.append(dict(p))
        if p["verdict"] in ("throttled", "blocked"):
            report.throttled_ports_count += 1

    # 5. Determine Overall SLA Verdict
    # Breach if: Uptime < 99.0%, or Packet Loss > 2.0%, or SLA compliance < 70%, or Port blocked
    if report.uptime_pct < 99.0 or report.ping_summary.loss_pct > 2.5 or report.speed_summary.sla_compliance_pct < 60.0:
        report.sla_verdict = "BREACHED"
    elif report.uptime_pct < 99.8 or report.ping_summary.loss_pct > 0.5 or report.throttled_ports_count > 0:
        report.sla_verdict = "DEGRADED"
    else:
        report.sla_verdict = "COMPLIANT"

    return report
