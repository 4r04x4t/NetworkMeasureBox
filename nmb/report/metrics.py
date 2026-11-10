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




def effective_outage_ends(conn, rows, now: int) -> Dict[int, Optional[int]]:
    """The end of each outage as the data shows it, without changing the stored rows.

    An outage still open (no end) when a newer one starts was left by a probe that stopped (a restart or an
    update); one with answered pings after its start is over by the first of them. 2026-11-10: eight such
    rows, each "ongoing", added up to more than a day and showed 0 % availability."""
    ordered = sorted(rows, key=lambda r: r["start_ts"])
    ends: Dict[int, Optional[int]] = {}
    for i, r in enumerate(ordered):
        if r["end_ts"]:
            ends[r["id"]] = r["end_ts"]
            continue
        candidates = []
        if i + 1 < len(ordered):
            candidates.append(ordered[i + 1]["start_ts"])
        try:
            row = conn.execute("SELECT MIN(ts) FROM ping_minute WHERE ts >= ? AND lost < sent", (r["start_ts"],)).fetchone()
            if row and row[0]:
                candidates.append(int(row[0]))
        except Exception:
            pass
        ends[r["id"]] = min(candidates) if candidates else None
    return ends


def merged_length(spans) -> int:
    """Total length of time spans, overlaps counted once."""
    total, cur_s, cur_e = 0, None, None
    for s_, e_ in sorted(spans):
        if cur_e is None or s_ > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s_, e_
        else:
            cur_e = max(cur_e, e_)
    if cur_e is not None:
        total += cur_e - cur_s
    return total

def latest_measured_test(tests: List[dict]) -> Optional[dict]:
    """Return the newest test with results; a skipped test has no speed to show."""
    return next((t for t in tests if t.get("status") == "ok"), None)


def tests_for_display(tests: List[dict], measured: int = 25, skipped: int = 5) -> List[dict]:
    """Keep real results visible when frequent skipped runs would otherwise push them out."""
    done = [t for t in tests if t.get("status") != "skipped_busy"][:measured]
    other = [t for t in tests if t.get("status") == "skipped_busy"][:skipped]
    return sorted(done + other, key=lambda t: t.get("ts") or 0, reverse=True)

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
    rtt_median_ms: Optional[float] = None
    rtt_p95_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    rtt_stddev_ms: Optional[float] = None
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
    median_down_mbps: Optional[float] = None
    stddev_down_mbps: Optional[float] = None
    p95_down_mbps: Optional[float] = None
    max_down_mbps: Optional[float] = None
    min_down_mbps: Optional[float] = None
    avg_up_mbps: Optional[float] = None
    median_up_mbps: Optional[float] = None
    stddev_up_mbps: Optional[float] = None
    p95_up_mbps: Optional[float] = None
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

    # NMB's own evaluation against fixed thresholds; not a decision by any authority or ISP.
    sla_verdict: str = "COMPLIANT"  # COMPLIANT, DEGRADED, BREACHED
    sla_reasons: List[str] = field(default_factory=list)  # uptime, loss, speed, ports


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

    ends = effective_outage_ends(conn, outage_rows, now)
    spans = []
    for r in outage_rows:
        o_start = max(start, r["start_ts"])
        eff_end = ends.get(r["id"])
        o_end = min(now, eff_end) if eff_end else now
        dur_sec = max(0, int((o_end - o_start) / 1000))
        spans.append((o_start, max(o_start, o_end)))
        report.outages.append(OutageRecord(
            id=r["id"],
            start_ts=r["start_ts"],
            end_ts=r["end_ts"] if r["end_ts"] else (eff_end if eff_end and eff_end < now else None),
            duration_sec=dur_sec,
            cause=r["cause"] or "Unreachable",
        ))
    total_outage_ms = merged_length(spans)

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

    # Only targets the probe pings now: a switched-off one (the Local Gateway on PPPoE, the PPP peer as "ISP
    # First Hop") would keep showing a day of lost pings.
    target_map = {
        r["id"]: (r["addr"], r["label"])
        for r in conn.execute("SELECT id, addr, label FROM target WHERE enabled = 1").fetchall()
    }

    per_target_accum: Dict[int, dict] = {}
    minute_buckets: Dict[int, List[dict]] = {}

    total_sent = 0
    total_lost = 0
    all_avg_rtts: List[float] = []
    all_jitters: List[float] = []

    for r in ping_rows:
        tid = r["target_id"]
        if tid not in target_map:
            continue
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
        mid = len(all_avg_rtts) // 2
        report.ping_summary.rtt_median_ms = round(all_avg_rtts[mid], 2)
        p95_idx = min(len(all_avg_rtts) - 1, int(len(all_avg_rtts) * 0.95))
        report.ping_summary.rtt_p95_ms = round(all_avg_rtts[p95_idx], 2)
        report.ping_summary.rtt_max_ms = round(all_avg_rtts[-1], 2)
        if len(all_avg_rtts) > 1:
            mean = sum(all_avg_rtts) / len(all_avg_rtts)
            variance = sum((x - mean) ** 2 for x in all_avg_rtts) / (len(all_avg_rtts) - 1)
            report.ping_summary.rtt_stddev_ms = round(variance ** 0.5, 2)
        else:
            report.ping_summary.rtt_stddev_ms = 0.0

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

    # Cache dynamic dual-stack fallback once if needed
    fallback_ips = {}
    try:
        from nmb.netd.interfaces import get_dual_stack_ips
        fallback_ips = get_dual_stack_ips()
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    for s in speed_rows:
        d_dict = dict(s)
        try:
            from nmb.speed.iperf_directory import label_iperf_row
            label_iperf_row(d_dict)
        except Exception:
            log.debug("iperf server label failed", exc_info=True)
        d_mbps = (s["down_bps"] or 0) / 1_000_000.0 if s["down_bps"] else None
        u_mbps = (s["up_bps"] or 0) / 1_000_000.0 if s["up_bps"] else None
        d_dict["down_mbps"] = round(d_mbps, 2) if d_mbps is not None else None
        d_dict["up_mbps"] = round(u_mbps, 2) if u_mbps is not None else None

        # Fallback client IP and IPv6
        if not d_dict.get("client_ip"):
            d_dict["client_ip"] = fallback_ips.get("public_ipv4") or fallback_ips.get("ipv4")
        if not d_dict.get("client_ipv6"):
            d_dict["client_ipv6"] = fallback_ips.get("public_ipv6") or fallback_ips.get("ipv6")

        # Resolved ISP Name (Per-measurement provider detection)
        isp_name = getattr(cfg.isp, "name", None)
        if not isp_name or isp_name in ("Generic ISP", "Unknown"):
            try:
                from nmb.netd.geoip import get_public_geoip
                geo = get_public_geoip(d_dict.get("client_ip"))
                if geo.get("isp") and geo["isp"] != "Unknown ISP":
                    isp_name = geo["isp"]
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        d_dict["isp_name"] = isp_name or "Unknown ISP"

        # Speed percentage achieved compared to contracted (offered) and guaranteed speeds
        d_dict["down_pct_of_offered"] = round((d_mbps / contract_down) * 100.0, 1) if (contract_down > 0 and d_mbps is not None) else None
        d_dict["up_pct_of_offered"] = round((u_mbps / contract_up) * 100.0, 1) if (contract_up > 0 and u_mbps is not None) else None
        d_dict["down_pct_of_guaranteed"] = round((d_mbps / guar_down) * 100.0, 1) if (guar_down > 0 and d_mbps is not None) else None
        d_dict["up_pct_of_guaranteed"] = round((u_mbps / guar_up) * 100.0, 1) if (guar_up > 0 and u_mbps is not None) else None

        # Measurement status code classification (1–15)
        st_val = s["status"]
        conn_tech = (d_dict.get("connection_type") or "").lower()
        if st_val == "ok":
            if conn_tech in ("wifi", "wlan", "guest_wifi"):
                status_code = 14
                status_desc = "Wi-Fi measurement"
            elif guar_down > 0 and (d_mbps or 0) < guar_down:
                status_code = 6
                status_desc = "invalid: below the guaranteed speed"
            elif contract_down > 0 and (d_mbps or 0) < contract_down * 0.40:
                status_code = 6
                status_desc = "invalid: far below the expected speed"
            else:
                status_code = 1
                status_desc = "valid measurement"
        elif st_val == "skipped_busy":
            status_code = 9
            status_desc = "skipped: background traffic"
        elif st_val == "error":
            err_str = str(s["error"] or "").lower()
            if "timeout" in err_str or "timed out" in err_str:
                status_code = 7
                status_desc = "invalid: timeout"
            else:
                status_code = 12
                status_desc = "error"
        else:
            status_code = 1
            status_desc = "valid measurement"

        d_dict["status_code"] = status_code
        d_dict["status_desc"] = status_desc

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
        down_mbps_list.sort()
        report.speed_summary.avg_down_mbps = round(sum(down_mbps_list) / len(down_mbps_list), 2)
        mid_d = len(down_mbps_list) // 2
        report.speed_summary.median_down_mbps = round(down_mbps_list[mid_d], 2)
        p95_d_idx = min(len(down_mbps_list) - 1, int(len(down_mbps_list) * 0.95))
        report.speed_summary.p95_down_mbps = round(down_mbps_list[p95_d_idx], 2)
        report.speed_summary.min_down_mbps = round(down_mbps_list[0], 2)
        report.speed_summary.max_down_mbps = round(down_mbps_list[-1], 2)
        if len(down_mbps_list) > 1:
            mean_d = sum(down_mbps_list) / len(down_mbps_list)
            report.speed_summary.stddev_down_mbps = round((sum((x - mean_d) ** 2 for x in down_mbps_list) / (len(down_mbps_list) - 1)) ** 0.5, 2)
        else:
            report.speed_summary.stddev_down_mbps = 0.0

        if contract_down > 0:
            report.speed_summary.avg_down_pct_of_offered = round((report.speed_summary.avg_down_mbps / contract_down) * 100.0, 1)
            report.speed_summary.min_down_pct_of_offered = round((report.speed_summary.min_down_mbps / contract_down) * 100.0, 1)
            report.speed_summary.max_down_pct_of_offered = round((report.speed_summary.max_down_mbps / contract_down) * 100.0, 1)
        if guar_down > 0:
            report.speed_summary.avg_down_pct_of_guaranteed = round((report.speed_summary.avg_down_mbps / guar_down) * 100.0, 1)

    if up_mbps_list:
        up_mbps_list.sort()
        report.speed_summary.avg_up_mbps = round(sum(up_mbps_list) / len(up_mbps_list), 2)
        mid_u = len(up_mbps_list) // 2
        report.speed_summary.median_up_mbps = round(up_mbps_list[mid_u], 2)
        p95_u_idx = min(len(up_mbps_list) - 1, int(len(up_mbps_list) * 0.95))
        report.speed_summary.p95_up_mbps = round(up_mbps_list[p95_u_idx], 2)
        report.speed_summary.min_up_mbps = round(up_mbps_list[0], 2)
        report.speed_summary.max_up_mbps = round(up_mbps_list[-1], 2)
        if len(up_mbps_list) > 1:
            mean_u = sum(up_mbps_list) / len(up_mbps_list)
            report.speed_summary.stddev_up_mbps = round((sum((x - mean_u) ** 2 for x in up_mbps_list) / (len(up_mbps_list) - 1)) ** 0.5, 2)
        else:
            report.speed_summary.stddev_up_mbps = 0.0

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
    # BREACHED: uptime < 99.0%, packet loss > 2.5%, or under 60% of speed tests met the required speed.
    # DEGRADED: uptime < 99.8%, packet loss > 0.5%, or a throttled or blocked port.
    if report.uptime_pct < 99.8:
        report.sla_reasons.append("uptime")
    if report.ping_summary.loss_pct > 0.5:
        report.sla_reasons.append("loss")
    if report.speed_summary.sla_compliance_pct < 60.0:
        report.sla_reasons.append("speed")
    if report.throttled_ports_count > 0:
        report.sla_reasons.append("ports")

    if report.uptime_pct < 99.0 or report.ping_summary.loss_pct > 2.5 or report.speed_summary.sla_compliance_pct < 60.0:
        report.sla_verdict = "BREACHED"
    elif report.uptime_pct < 99.8 or report.ping_summary.loss_pct > 0.5 or report.throttled_ports_count > 0:
        report.sla_verdict = "DEGRADED"
    else:
        report.sla_verdict = "COMPLIANT"

    return report
