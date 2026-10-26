"""Native SVG chart generator for standalone HTML reports.

Generates responsive, zero-CDN embedded SVG charts for latency timelines,
packet loss spikes, speedtest throughput vs SLA, and port-throttling checks.
"""
from __future__ import annotations

import datetime
from typing import List, Optional

from nmb.report.metrics import OutageRecord, TimeSeriesPoint


def _fmt_time(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
    return dt.strftime("%H:%M")


def render_latency_chart(
    timeseries: List[TimeSeriesPoint],
    outages: List[OutageRecord],
    width: int = 800,
    height: int = 240,
) -> str:
    """Generate SVG line chart showing RTT latency and jitter with outage shading."""
    if not timeseries:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">No latency telemetry recorded in this period</text></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 25, 35
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    t_min = timeseries[0].ts
    t_max = timeseries[-1].ts if timeseries[-1].ts > t_min else t_min + 1

    valid_rtts = [p.rtt_ms for p in timeseries if p.rtt_ms is not None]
    max_rtt = max(valid_rtts) if valid_rtts else 50.0
    y_max = max(10.0, max_rtt * 1.25)

    def x_coord(ts: int) -> float:
        return pad_left + ((ts - t_min) / (t_max - t_min)) * plot_w

    def y_coord(val: float) -> float:
        return pad_top + plot_h - (min(val, y_max) / y_max) * plot_h

    # Grid lines & Y-axis labels
    y_ticks = 4
    grid_lines = []
    for i in range(y_ticks + 1):
        v = (y_max / y_ticks) * i
        y_pos = y_coord(v)
        grid_lines.append(f'<line x1="{pad_left}" y1="{y_pos}" x2="{width - pad_right}" y2="{y_pos}" stroke="#334155" stroke-dasharray="3,3" stroke-width="1"/>')
        grid_lines.append(f'<text x="{pad_left - 8}" y="{y_pos + 4}" fill="#94a3b8" text-anchor="end" font-size="11">{int(v)}ms</text>')

    # X-axis time labels
    time_labels = []
    x_steps = min(6, len(timeseries))
    for i in range(x_steps):
        idx = int((len(timeseries) - 1) * (i / max(1, x_steps - 1)))
        pt = timeseries[idx]
        xp = x_coord(pt.ts)
        time_labels.append(f'<text x="{xp}" y="{height - 10}" fill="#94a3b8" text-anchor="middle" font-size="11">{_fmt_time(pt.ts)}</text>')

    # Outage background shading
    outage_rects = []
    for out in outages:
        o_s = max(t_min, out.start_ts)
        o_e = min(t_max, out.end_ts) if out.end_ts else t_max
        if o_e >= t_min and o_s <= t_max:
            x1 = x_coord(o_s)
            x2 = x_coord(o_e)
            w = max(4.0, x2 - x1)
            outage_rects.append(f'<rect x="{x1}" y="{pad_top}" width="{w}" height="{plot_h}" fill="#ef4444" fill-opacity="0.25"><title>Outage ({out.duration_sec}s)</title></rect>')

    # RTT line & area path
    pts = [(x_coord(p.ts), y_coord(p.rtt_ms)) for p in timeseries if p.rtt_ms is not None]
    path_d = ""
    area_d = ""
    if pts:
        path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area_d = f"{path_d} L {pts[-1][0]:.1f},{pad_top + plot_h} L {pts[0][0]:.1f},{pad_top + plot_h} Z"

    # Jitter line
    jit_pts = [(x_coord(p.ts), y_coord(p.jitter_ms)) for p in timeseries if p.jitter_ms is not None]
    jit_d = ("M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in jit_pts)) if jit_pts else ""

    svg = f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="rttGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
    </linearGradient>
  </defs>
  <!-- Background & Grid -->
  {''.join(grid_lines)}
  {''.join(outage_rects)}
  <!-- Data Area & Paths -->
  {f'<path d="{area_d}" fill="url(#rttGrad)"/>' if area_d else ''}
  {f'<path d="{path_d}" fill="none" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round"/>' if path_d else ''}
  {f'<path d="{jit_d}" fill="none" stroke="#f59e0b" stroke-width="1.6" stroke-dasharray="2,2"/>' if jit_d else ''}
  <!-- Time Labels -->
  {''.join(time_labels)}
  <!-- Legend -->
  <g transform="translate({width - 190}, 15)">
    <line x1="0" y1="0" x2="16" y2="0" stroke="#38bdf8" stroke-width="2"/>
    <text x="22" y="3" fill="#cbd5e1" font-size="11">Latency (RTT)</text>
    <line x1="100" y1="0" x2="116" y2="0" stroke="#f59e0b" stroke-width="2" stroke-dasharray="2,2"/>
    <text x="122" y="3" fill="#cbd5e1" font-size="11">Jitter</text>
  </g>
</svg>"""
    return svg


def render_loss_chart(
    timeseries: List[TimeSeriesPoint],
    width: int = 800,
    height: int = 150,
) -> str:
    """Generate SVG packet loss spike chart."""
    if not timeseries:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">No packet loss telemetry</text></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 20, 25
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    max_loss = max(p.loss_pct for p in timeseries)
    y_max = max(5.0, min(100.0, max_loss * 1.3))

    bar_width = max(2.0, (plot_w / max(1, len(timeseries))) - 1.5)
    bars = []

    for i, pt in enumerate(timeseries):
        if pt.loss_pct <= 0:
            continue
        x = pad_left + (i / max(1, len(timeseries))) * plot_w
        h = (min(pt.loss_pct, y_max) / y_max) * plot_h
        y = pad_top + plot_h - h
        color = "#ef4444" if pt.loss_pct >= 2.0 else "#fb7185"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{h:.1f}" fill="{color}"><title>{pt.loss_pct:.1f}% loss at {_fmt_time(pt.ts)}</title></rect>')

    y_axis = [
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}" stroke="#334155" stroke-width="1"/>',
        f'<text x="{pad_left - 8}" y="{pad_top + 5}" fill="#94a3b8" text-anchor="end" font-size="11">{y_max:.0f}%</text>',
        f'<text x="{pad_left - 8}" y="{pad_top + plot_h}" fill="#94a3b8" text-anchor="end" font-size="11">0%</text>',
    ]

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  {''.join(y_axis)}
  {''.join(bars)}
  <text x="{width - 25}" y="15" fill="#f87171" text-anchor="end" font-size="11">Packet Loss (%)</text>
</svg>"""


def render_speedtest_chart(
    speed_tests: List[dict],
    contract_down: float,
    contract_up: float,
    width: int = 800,
    height: int = 220,
) -> str:
    """Generate SVG bar chart comparing actual measured throughput vs contract SLA."""
    valid_tests = [t for t in reversed(speed_tests) if t.get("status") == "ok" and t.get("down_mbps")]
    if not valid_tests:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">No successful speedtests in period</text></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 30, 35
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    max_val = max([contract_down] + [t["down_mbps"] for t in valid_tests if t.get("down_mbps")])
    y_max = max(50.0, max_val * 1.2)

    def y_coord(val: float) -> float:
        return pad_top + plot_h - (min(val, y_max) / y_max) * plot_h

    # Baseline contract lines
    sla_line_y = y_coord(contract_down)
    sla_up_y = y_coord(contract_up)
    sla_markup = [
        f'<line x1="{pad_left}" y1="{sla_line_y}" x2="{width - pad_right}" y2="{sla_line_y}" stroke="#10b981" stroke-dasharray="4,4" stroke-width="1.5"/>',
        f'<text x="{width - pad_right}" y="{sla_line_y - 4}" fill="#10b981" text-anchor="end" font-size="10">Promised Down: {contract_down:.0f} Mbps</text>',
        f'<line x1="{pad_left}" y1="{sla_up_y}" x2="{width - pad_right}" y2="{sla_up_y}" stroke="#0ea5e9" stroke-dasharray="4,4" stroke-width="1.5"/>',
        f'<text x="{width - pad_right}" y="{sla_up_y - 4}" fill="#0ea5e9" text-anchor="end" font-size="10">Promised Up: {contract_up:.0f} Mbps</text>',
    ]

    # Grouped bars per test
    n_groups = len(valid_tests)
    group_w = plot_w / n_groups
    bar_w = min(22.0, (group_w - 12) / 2.0)
    bars_markup = []

    for i, t in enumerate(valid_tests):
        center_x = pad_left + (i + 0.5) * group_w
        down_mbps = t.get("down_mbps") or 0.0
        up_mbps = t.get("up_mbps") or 0.0

        # Downlink bar
        h_down = (down_mbps / y_max) * plot_h
        y_down = pad_top + plot_h - h_down
        x_down = center_x - bar_w - 1.5
        down_color = "#10b981" if down_mbps >= contract_down * 0.8 else "#f59e0b"
        bars_markup.append(f'<rect x="{x_down:.1f}" y="{y_down:.1f}" width="{bar_w:.1f}" height="{h_down:.1f}" fill="{down_color}" rx="2"><title>Download: {down_mbps:.1f} Mbps</title></rect>')

        # Uplink bar
        h_up = (up_mbps / y_max) * plot_h
        y_up = pad_top + plot_h - h_up
        x_up = center_x + 1.5
        up_color = "#0ea5e9" if up_mbps >= contract_up * 0.8 else "#f59e0b"
        bars_markup.append(f'<rect x="{x_up:.1f}" y="{y_up:.1f}" width="{bar_w:.1f}" height="{h_up:.1f}" fill="{up_color}" rx="2"><title>Upload: {up_mbps:.1f} Mbps</title></rect>')

        # Timestamp label
        ts_label = _fmt_time(t["ts"])
        bars_markup.append(f'<text x="{center_x:.1f}" y="{height - 10}" fill="#94a3b8" text-anchor="middle" font-size="10">{ts_label}</text>')

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  {''.join(sla_markup)}
  {''.join(bars_markup)}
  <g transform="translate({pad_left}, 15)">
    <rect x="0" y="0" width="12" height="12" fill="#10b981" rx="2"/>
    <text x="18" y="10" fill="#cbd5e1" font-size="11">Measured Download (Mbps)</text>
    <rect x="180" y="0" width="12" height="12" fill="#0ea5e9" rx="2"/>
    <text x="198" y="10" fill="#cbd5e1" font-size="11">Measured Upload (Mbps)</text>
  </g>
</svg>"""
