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
            # Only an answer from the internet ends an outage; the local gateway answering does not
            # (2026-11-10, the probe decides the same way).
            row = conn.execute(
                "SELECT MIN(m.ts) FROM ping_minute m LEFT JOIN target t ON t.id = m.target_id "
                "WHERE m.ts >= ? AND m.lost < m.sent AND COALESCE(t.role, 'Public DNS') != 'Local Gateway'",
                (r["start_ts"],)).fetchone()
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

LEGACY_BEFORE_MS = 180_000     # a mode change event marks the END of the switch; it began up to 3 min earlier
LEGACY_AFTER_MS = 30_000
OWN_KINDS_LEGACY = ("mode_change", "mode_change_failed", "mode_setting_changed")
MIN_ISP_OUTAGE_SEC = 30        # what is left of an outage after the box's own windows; less is the box's


def merge_spans(spans) -> List[tuple]:
    out: List[list] = []
    for s_, e_ in sorted(spans):
        if out and s_ <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e_)
        else:
            out.append([s_, e_])
    return [tuple(x) for x in out]


def subtract_spans(span: tuple, windows: List[tuple]) -> List[tuple]:
    """The parts of span not covered by the (merged) windows."""
    parts = [span]
    for ws, we in windows:
        nxt = []
        for s_, e_ in parts:
            if we <= s_ or ws >= e_:
                nxt.append((s_, e_))
                continue
            if s_ < ws:
                nxt.append((s_, ws))
            if we < e_:
                nxt.append((we, e_))
        parts = nxt
    return [p for p in parts if p[1] > p[0]]


def own_action_windows(conn, start: int, end: int) -> List[tuple]:
    """When the box itself had its connection down, with the time the line needs to come back.

    Recorded windows (table own_action, since 2026-11-10); before the first recorded window, the netd
    mode change events stand in for them (each marks the end of a switch that began up to 3 minutes
    earlier). An outage in these windows cannot be put on the ISP.
    """
    from nmb.common.own_action import GRACE_AFTER_MS, GRACE_BEFORE_MS, MAX_OPEN_MS
    windows: List[tuple] = []
    first_recorded = None
    try:
        first = conn.execute("SELECT MIN(start_ts) FROM own_action").fetchone()
        first_recorded = first[0] if first and first[0] else None
        # failover_rebuild: the box reacting to the line (USB failover, PPPoE seen or lost); not its own doing
        for r in conn.execute(
                "SELECT start_ts, end_ts FROM own_action WHERE kind != 'failover_rebuild' AND start_ts <= ? "
                "AND COALESCE(end_ts, start_ts + ?) >= ?",
                (end, MAX_OPEN_MS, start - GRACE_AFTER_MS)).fetchall():
            ws = r[0] - GRACE_BEFORE_MS
            we = (r[1] if r[1] else min(end, r[0] + MAX_OPEN_MS)) + GRACE_AFTER_MS
            windows.append((ws, we))
    except Exception:
        pass   # no own_action table in an old database
    try:
        until = first_recorded if first_recorded else end + LEGACY_BEFORE_MS
        q = ("SELECT ts FROM event WHERE kind IN (%s) AND ts >= ? AND ts <= ? AND ts < ?"
             % ",".join("?" * len(OWN_KINDS_LEGACY)))
        for (ts,) in conn.execute(q, (*OWN_KINDS_LEGACY, start - LEGACY_AFTER_MS, end + LEGACY_BEFORE_MS, until)).fetchall():
            windows.append((ts - LEGACY_BEFORE_MS, ts + LEGACY_AFTER_MS))
    except Exception:
        pass
    return merge_spans(windows)


def latest_measured_test(tests: List[dict]) -> Optional[dict]:
    """Return the newest test of the line with results; a skipped test has no speed to show, and a test
    against a server on the local network measured the home network, not the line."""
    return next((t for t in tests if t.get("status") == "ok" and t.get("scope") != "lan"), None)


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
    duration_sec: int          # the part counted against the line (the box's own windows taken out)
    cause: str
    cause_kind: str = "isp"    # "isp" or "own" (the box's own mode change, update, restart)
    own_sec: int = 0           # the part that fell into the box's own windows


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
    judged_tests: int = 0        # tests judged against a required speed; 0 = compliance unknown


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
    outages: List[OutageRecord] = field(default_factory=list)          # counted against the line
    own_outages: List[OutageRecord] = field(default_factory=list)      # the box's own, not counted
    own_action_sec: int = 0      # time the box itself had the connection down; left out of availability

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
    own_windows = [(max(start, a), min(now, b)) for a, b in own_action_windows(conn, start, now) if b > start and a < now]
    spans = []
    for r in outage_rows:
        o_start = max(start, r["start_ts"])
        eff_end = ends.get(r["id"])
        o_end = max(o_start, min(now, eff_end) if eff_end else now)
        isp_parts = subtract_spans((o_start, o_end), own_windows)
        isp_ms = sum(b - a for a, b in isp_parts)
        own_ms = (o_end - o_start) - isp_ms
        rec = OutageRecord(
            id=r["id"],
            start_ts=r["start_ts"],
            end_ts=r["end_ts"] if r["end_ts"] else (eff_end if eff_end and eff_end < now else None),
            duration_sec=max(0, int(isp_ms / 1000)),
            cause=r["cause"] or "Unreachable",
            own_sec=max(0, int(own_ms / 1000)),
        )
        # The box's own only when it began while the box had its line down; one that began before (the
        # line failed first, the box reacted) stays the line's, for the part outside the windows.
        began_in_window = any(a <= o_start <= b for a, b in own_windows)
        if own_ms > 0 and began_in_window and rec.duration_sec < MIN_ISP_OUTAGE_SEC:
            rec.cause_kind = "own"
            rec.duration_sec, rec.own_sec = 0, max(0, int((o_end - o_start) / 1000))
            report.own_outages.append(rec)
            continue
        spans.extend(isp_parts)
        report.outages.append(rec)
    total_outage_ms = merged_length(spans)

    # The box's own windows are not the line's time at all: out of the counted time, not "up" or "down".
    own_ms_total = merged_length(own_windows)
    report.own_action_sec = int(own_ms_total / 1000)
    window_duration_ms = max(1, now - start - own_ms_total)
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

    def _in_own_window(ts: int) -> bool:
        return any(a < ts + 60_000 and ts < b for a, b in own_windows)

    for r in ping_rows:
        tid = r["target_id"]
        if tid not in target_map:
            continue
        if own_windows and _in_own_window(r["ts"]):
            continue     # pings lost while the box itself had the line down say nothing about the line
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
                  engine, colo, bound_iface, client_ip_source, server_ip
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
        try:
            from nmb.speed.iperf_directory import label_iperf_row
            label_iperf_row(d_dict)
        except Exception:
            log.debug("iperf server label failed", exc_info=True)
        d_mbps = (s["down_bps"] or 0) / 1_000_000.0 if s["down_bps"] else None
        u_mbps = (s["up_bps"] or 0) / 1_000_000.0 if s["up_bps"] else None
        d_dict["down_mbps"] = round(d_mbps, 2) if d_mbps is not None else None
        d_dict["up_mbps"] = round(u_mbps, 2) if u_mbps is not None else None

        # No fallback: a test without a recorded public address shows none. The report used to put
        # today's address (or the LAN address) next to tests from days ago.

        # Resolved ISP Name (Per-measurement provider detection)
        # The configured ISP, or one looked up for the row's OWN public address; never today's address or a
        # LAN address (geoip looks up the current connection when it gets none or a private one).
        isp_name = getattr(cfg.isp, "name", None)
        if not isp_name or isp_name in ("Generic ISP", "Unknown"):
            isp_name = None
            from nmb.common.netaddr import global_ip
            own_ip = global_ip(d_dict.get("client_ip")) or global_ip(d_dict.get("client_ipv6"))
            if own_ip:
                try:
                    from nmb.netd.geoip import get_public_geoip
                    geo = get_public_geoip(own_ip)
                    if geo.get("isp") and geo["isp"] != "Unknown ISP":
                        isp_name = geo["isp"]
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
        d_dict["isp_name"] = isp_name or ""

        # Speed percentage achieved compared to contracted (offered) and guaranteed speeds
        d_dict["down_pct_of_offered"] = round((d_mbps / contract_down) * 100.0, 1) if (contract_down > 0 and d_mbps is not None) else None
        d_dict["up_pct_of_offered"] = round((u_mbps / contract_up) * 100.0, 1) if (contract_up > 0 and u_mbps is not None) else None
        d_dict["down_pct_of_guaranteed"] = round((d_mbps / guar_down) * 100.0, 1) if (guar_down > 0 and d_mbps is not None) else None
        d_dict["up_pct_of_guaranteed"] = round((u_mbps / guar_up) * 100.0, 1) if (guar_up > 0 and u_mbps is not None) else None

        # Measurement status code (shared with the detailed CSV: nmb/report/status_codes.py)
        from nmb.report.status_codes import classify
        status_code, status_desc = classify(
            s["status"], s["error"], d_mbps, u_mbps,
            bound_iface=d_dict.get("bound_iface"),
            connection_type=d_dict.get("connection_type"),
            contract_down=contract_down, contract_up=contract_up,
            guaranteed_down=guar_down, guaranteed_up=guar_up)

        d_dict["status_code"] = status_code
        d_dict["status_desc"] = status_desc

        # A test against a server on the local network measured the LAN, not the ISP's line: listed,
        # but left out of the line's figures.
        from nmb.report.status_codes import speed_scope
        d_dict["scope"] = speed_scope(d_dict)
        if d_dict["scope"] == "lan":
            for k in ("down_pct_of_offered", "up_pct_of_offered", "down_pct_of_guaranteed", "up_pct_of_guaranteed"):
                d_dict[k] = None          # a LAN test is no share of the ISP's speed
        report.speed_tests.append(d_dict)

        if s["status"] == "ok" and d_dict["scope"] == "lan":
            continue
        if s["status"] == "ok":
            report.speed_summary.successful_tests += 1
            if d_mbps is not None:
                down_mbps_list.append(d_mbps)
            if u_mbps is not None:
                up_mbps_list.append(u_mbps)

            # Required speed: the guaranteed speed when one is set, otherwise NMB's rule of 80 % of the
            # offered speed (the guaranteed speed was ignored even when set, until 2026-11-10). A direction
            # that was not measured is not judged.
            down_target = guar_down if guar_down > 0 else contract_down * 0.80
            up_target = guar_up if guar_up > 0 else contract_up * 0.80
            judged = [(got, need) for got, need in ((d_mbps, down_target), (u_mbps, up_target))
                      if got is not None and need > 0]
            if judged:
                report.speed_summary.judged_tests += 1
                if all(got >= need for got, need in judged):
                    compliant_tests += 1

        elif s["status"] == "skipped_busy":
            report.speed_summary.skipped_busy += 1

    report.speed_summary.total_tests = len(speed_rows)
    if report.speed_summary.judged_tests > 0:
        report.speed_summary.sla_compliance_pct = round(
            (compliant_tests / report.speed_summary.judged_tests) * 100.0, 1
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
    # Only what was measured counts: no pings means no loss figure, no judged test no compliance figure;
    # with neither, there is no verdict ("UNKNOWN") instead of "COMPLIANT" with 100 % and 0 %.
    loss_known = report.ping_summary.total_sent > 0
    speed_known = report.speed_summary.judged_tests > 0
    loss = report.ping_summary.loss_pct if loss_known else 0.0
    compliance = report.speed_summary.sla_compliance_pct if speed_known else 100.0
    if report.uptime_pct < 99.8:
        report.sla_reasons.append("uptime")
    if loss > 0.5:
        report.sla_reasons.append("loss")
    if compliance < 60.0:
        report.sla_reasons.append("speed")
    if report.throttled_ports_count > 0:
        report.sla_reasons.append("ports")

    if not loss_known and not speed_known:
        report.sla_verdict = "UNKNOWN"
    elif report.uptime_pct < 99.0 or loss > 2.5 or compliance < 60.0:
        report.sla_verdict = "BREACHED"
    elif report.uptime_pct < 99.8 or loss > 0.5 or report.throttled_ports_count > 0:
        report.sla_verdict = "DEGRADED"
    else:
        report.sla_verdict = "COMPLIANT"

    return report
