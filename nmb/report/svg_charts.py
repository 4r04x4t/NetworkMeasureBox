"""Native SVG chart generator for standalone HTML reports.

Generates responsive, zero-CDN embedded SVG charts for latency timelines,
packet loss spikes, speedtest throughput vs SLA, and port-throttling checks.
"""
from __future__ import annotations

import datetime
from typing import List, Optional

from nmb.report.metrics import OutageRecord, TimeSeriesPoint

CHART_I18N = {
    "hu": {
        "no_speed_data": "Nincs sikeres sebességmérés ebben az időszakban",
        "no_compliance_data": "Nincs elegendő SLA megfelelőségi adat",
        "no_latency_data": "Nincs rögzített válaszidő telemetria ebben az időszakban",
        "no_loss_data": "Nincs csomagvesztési telemetria",
        "no_jitter_data": "Nincs késleltetés-ingadozás (jitter) adat",
        "offered_down": "Kínált Letöltés",
        "guar_down": "Garantált Letöltés",
        "offered_up": "Kínált Feltöltés",
        "guar_up": "Garantált Feltöltés",
        "measured_down": "Mért Letöltés (Mbps)",
        "measured_up": "Mért Feltöltés (Mbps)",
        "compliance_100": "100% Kínált sebesség",
        "compliance_80": "80% Minimális elvárás",
        "compliance_down": "Letöltés Megfelelőség %",
        "compliance_up": "Feltöltés Megfelelőség %",
        "latency_rtt": "Válaszidő (RTT)",
        "jitter": "Jitter",
        "packet_loss": "Csomagvesztés (%)",
        "jitter_ms": "Késleltetés-ingadozás (Jitter ms)",
        "outage": "Kimaradás",
        "loss_at": "vesztés ekkor:",
        "download": "Letöltés",
        "upload": "Feltöltés",
    },
    "en": {
        "no_speed_data": "No successful speed tests recorded in this period",
        "no_compliance_data": "No SLA compliance data available",
        "no_latency_data": "No latency telemetry recorded in this period",
        "no_loss_data": "No packet loss telemetry",
        "no_jitter_data": "No latency jitter telemetry",
        "offered_down": "Contracted Download",
        "guar_down": "Guaranteed Download",
        "offered_up": "Contracted Upload",
        "guar_up": "Guaranteed Upload",
        "measured_down": "Measured Download (Mbps)",
        "measured_up": "Measured Upload (Mbps)",
        "compliance_100": "100% Contracted Speed",
        "compliance_80": "80% Expected Threshold",
        "compliance_down": "Download Compliance %",
        "compliance_up": "Upload Compliance %",
        "latency_rtt": "Latency (RTT)",
        "jitter": "Jitter",
        "packet_loss": "Packet Loss (%)",
        "jitter_ms": "Latency Jitter (ms)",
        "outage": "Outage",
        "loss_at": "loss at",
        "download": "Download",
        "upload": "Upload",
    },
    "de": {
        "no_speed_data": "Keine erfolgreichen Geschwindigkeitsmessungen in diesem Zeitraum",
        "no_compliance_data": "Keine SLA-Konformitätsdaten verfügbar",
        "no_latency_data": "Keine Latenz-Telemetrie in diesem Zeitraum erfasst",
        "no_loss_data": "Keine Paketverlust-Telemetrie",
        "no_jitter_data": "Keine Jitter-Telemetriedaten",
        "offered_down": "Gebuchter Download",
        "guar_down": "Garantierter Download",
        "offered_up": "Gebuchter Upload",
        "guar_up": "Garantierter Upload",
        "measured_down": "Gemessener Download (Mbps)",
        "measured_up": "Gemessener Upload (Mbps)",
        "compliance_100": "100% Gebuchte Bandbreite",
        "compliance_80": "80% Mindesterwartung",
        "compliance_down": "Download-Konformität %",
        "compliance_up": "Upload-Konformität %",
        "latency_rtt": "Latenz (RTT)",
        "jitter": "Jitter",
        "packet_loss": "Paketverlust (%)",
        "jitter_ms": "Latenzschwankung (Jitter ms)",
        "outage": "Ausfall",
        "loss_at": "Verlust um",
        "download": "Download",
        "upload": "Upload",
    },
    "fr": {
        "no_speed_data": "Aucun test de débit réussi enregistré durant cette période",
        "no_compliance_data": "Aucune donnée de conformité SLA disponible",
        "no_latency_data": "Aucune télémétrie de latence enregistrée durant cette période",
        "no_loss_data": "Aucune télémétrie de perte de paquets",
        "no_jitter_data": "Aucune donnée de gigue de latence",
        "offered_down": "Débit Descendant Souscrit",
        "guar_down": "Débit Descendant Garanti",
        "offered_up": "Débit Montant Souscrit",
        "guar_up": "Débit Montant Garanti",
        "measured_down": "Débit Descendant Mesuré (Mbps)",
        "measured_up": "Débit Montant Mesuré (Mbps)",
        "compliance_100": "100% Débit Souscrit",
        "compliance_80": "80% Seuil Attendu",
        "compliance_down": "Conformité Descendante %",
        "compliance_up": "Conformité Montante %",
        "latency_rtt": "Latence (RTT)",
        "jitter": "Gigue",
        "packet_loss": "Perte de Paquets (%)",
        "jitter_ms": "Gigue de Latence (ms)",
        "outage": "Coupure",
        "loss_at": "perte à",
        "download": "Téléchargement",
        "upload": "Téléversement",
    },
    "uk": {
        "no_speed_data": "У цей період не зафіксовано успішних вимірювань швидкості",
        "no_compliance_data": "Немає достатніх даних відповідності SLA",
        "no_latency_data": "У цей період не зафіксовано телеметрії затримки",
        "no_loss_data": "Немає телеметрії втрати пакетів",
        "no_jitter_data": "Немає даних коливання затримки (джитера)",
        "offered_down": "Заявлене завантаження",
        "guar_down": "Гарантоване завантаження",
        "offered_up": "Заявлене вивантаження",
        "guar_up": "Гарантоване вивантаження",
        "measured_down": "Виміряне завантаження (Mbps)",
        "measured_up": "Виміряне вивантаження (Mbps)",
        "compliance_100": "100% Заявлена швидкість",
        "compliance_80": "80% Очікуваний мінімум",
        "compliance_down": "Відповідність завантаження %",
        "compliance_up": "Відповідність вивантаження %",
        "latency_rtt": "Затримка (RTT)",
        "jitter": "Джитер",
        "packet_loss": "Втрата пакетів (%)",
        "jitter_ms": "Коливання затримки (Джитер мс)",
        "outage": "Перерва",
        "loss_at": "втрата о",
        "download": "Завантаження",
        "upload": "Вивантаження",
    },
}


def _t(key: str, lang: str = "hu") -> str:
    t_map = CHART_I18N.get(lang, CHART_I18N["en"])
    return t_map.get(key, CHART_I18N["en"].get(key, key))


def _fmt_time(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
    return dt.strftime("%H:%M")


def render_latency_chart(
    timeseries: List[TimeSeriesPoint],
    outages: List[OutageRecord],
    width: int = 800,
    height: int = 240,
    lang: str = "hu",
) -> str:
    """Generate SVG line chart showing RTT latency and jitter with outage shading."""
    if not timeseries:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">{_t("no_latency_data", lang)}</text></svg>'

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
            outage_rects.append(f'<rect x="{x1}" y="{pad_top}" width="{w}" height="{plot_h}" fill="#ef4444" fill-opacity="0.25"><title>{_t("outage", lang)} ({out.duration_sec}s)</title></rect>')

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

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
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
  <g transform="translate({width - 230}, 15)">
    <line x1="0" y1="0" x2="16" y2="0" stroke="#38bdf8" stroke-width="2"/>
    <text x="22" y="3" fill="#cbd5e1" font-size="11">{_t("latency_rtt", lang)}</text>
    <line x1="120" y1="0" x2="136" y2="0" stroke="#f59e0b" stroke-width="2" stroke-dasharray="2,2"/>
    <text x="142" y="3" fill="#cbd5e1" font-size="11">{_t("jitter", lang)}</text>
  </g>
</svg>"""


def render_loss_chart(
    timeseries: List[TimeSeriesPoint],
    width: int = 800,
    height: int = 150,
    lang: str = "hu",
) -> str:
    """Generate SVG packet loss spike chart."""
    if not timeseries:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">{_t("no_loss_data", lang)}</text></svg>'

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
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{h:.1f}" fill="{color}"><title>{pt.loss_pct:.1f}% {_t("loss_at", lang)} {_fmt_time(pt.ts)}</title></rect>')

    y_axis = [
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}" stroke="#334155" stroke-width="1"/>',
        f'<text x="{pad_left - 8}" y="{pad_top + 5}" fill="#94a3b8" text-anchor="end" font-size="11">{y_max:.0f}%</text>',
        f'<text x="{pad_left - 8}" y="{pad_top + plot_h}" fill="#94a3b8" text-anchor="end" font-size="11">0%</text>',
    ]

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  {''.join(y_axis)}
  {''.join(bars)}
  <text x="{width - 25}" y="15" fill="#f87171" text-anchor="end" font-size="11">{_t("packet_loss", lang)}</text>
</svg>"""


def render_jitter_chart(
    timeseries: List[TimeSeriesPoint],
    width: int = 800,
    height: int = 180,
    lang: str = "hu",
) -> str:
    """Generate SVG chart for latency jitter variations over time."""
    valid_jit = [p for p in timeseries if p.jitter_ms is not None]
    if not valid_jit:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">{_t("no_jitter_data", lang)}</text></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 25, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    t_min = valid_jit[0].ts
    t_max = valid_jit[-1].ts if valid_jit[-1].ts > t_min else t_min + 1

    max_j = max(p.jitter_ms for p in valid_jit)
    y_max = max(10.0, max_j * 1.3)

    def x_coord(ts: int) -> float:
        return pad_left + ((ts - t_min) / (t_max - t_min)) * plot_w

    def y_coord(val: float) -> float:
        return pad_top + plot_h - (min(val, y_max) / y_max) * plot_h

    grid_lines = []
    y_ticks = 3
    for i in range(y_ticks + 1):
        v = (y_max / y_ticks) * i
        y_pos = y_coord(v)
        grid_lines.append(f'<line x1="{pad_left}" y1="{y_pos}" x2="{width - pad_right}" y2="{y_pos}" stroke="#334155" stroke-dasharray="3,3" stroke-width="1"/>')
        grid_lines.append(f'<text x="{pad_left - 8}" y="{y_pos + 4}" fill="#94a3b8" text-anchor="end" font-size="11">{v:.1f}ms</text>')

    pts = [(x_coord(p.ts), y_coord(p.jitter_ms)) for p in valid_jit]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts) if pts else ""
    area_d = f"{path_d} L {pts[-1][0]:.1f},{pad_top + plot_h} L {pts[0][0]:.1f},{pad_top + plot_h} Z" if pts else ""

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="jitGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.0"/>
    </linearGradient>
  </defs>
  {''.join(grid_lines)}
  {f'<path d="{area_d}" fill="url(#jitGrad)"/>' if area_d else ''}
  {f'<path d="{path_d}" fill="none" stroke="#f59e0b" stroke-width="2.2" stroke-linecap="round"/>' if path_d else ''}
  <text x="{width - 25}" y="15" fill="#f59e0b" text-anchor="end" font-size="11">{_t("jitter_ms", lang)}</text>
</svg>"""


def render_compliance_chart(
    speed_tests: List[dict],
    contract_down: float,
    contract_up: float,
    width: int = 800,
    height: int = 220,
    lang: str = "hu",
) -> str:
    """Generate SVG timeline of speed compliance ratio (% of offered/contracted speed)."""
    # Tests of the line only (a LAN server's test measured the home network); an unmeasured direction is
    # left out of its line, never drawn as 0 %.
    valid_tests = [t for t in reversed(speed_tests) if t.get("status") == "ok" and t.get("scope") != "lan"
                   and (t.get("down_mbps") is not None or t.get("up_mbps") is not None)]
    if not valid_tests or contract_down <= 0:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">{_t("no_compliance_data", lang)}</text></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 25, 35
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    n = len(valid_tests)
    def x_coord(i: int) -> float:
        return pad_left + (i / max(1, n - 1)) * plot_w if n > 1 else pad_left + plot_w / 2

    y_max = 140.0  # Percentage scale up to 140%
    def y_coord(pct: float) -> float:
        return pad_top + plot_h - (min(pct, y_max) / y_max) * plot_h

    # 100% and 80% guideline marks
    guidelines = [
        f'<line x1="{pad_left}" y1="{y_coord(100.0)}" x2="{width - pad_right}" y2="{y_coord(100.0)}" stroke="#10b981" stroke-dasharray="4,4" stroke-width="1.5"/>',
        f'<text x="{width - pad_right}" y="{y_coord(100.0) - 4}" fill="#10b981" text-anchor="end" font-size="10">{_t("compliance_100", lang)}</text>',
        f'<line x1="{pad_left}" y1="{y_coord(80.0)}" x2="{width - pad_right}" y2="{y_coord(80.0)}" stroke="#f59e0b" stroke-dasharray="3,3" stroke-width="1.2"/>',
        f'<text x="{width - pad_right}" y="{y_coord(80.0) - 4}" fill="#f59e0b" text-anchor="end" font-size="10">{_t("compliance_80", lang)}</text>',
    ]

    pts_d = []
    pts_u = []
    circles = []

    for i, t_point in enumerate(valid_tests):
        x = x_coord(i)
        d_m = t_point.get("down_mbps")
        u_m = t_point.get("up_mbps")
        if d_m is not None and contract_down > 0:
            d_pct = (d_m / contract_down) * 100.0
            pts_d.append((x, y_coord(d_pct)))
            d_col = "#10b981" if d_pct >= 80 else ("#f59e0b" if d_pct >= 60 else "#ef4444")
            circles.append(f'<circle cx="{x:.1f}" cy="{y_coord(d_pct):.1f}" r="4" fill="{d_col}"><title>{_t("download", lang)}: {d_pct:.1f}% ({d_m:.1f} Mbps)</title></circle>')
        if u_m is not None and contract_up > 0:
            pts_u.append((x, y_coord((u_m / contract_up) * 100.0)))

    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_d) if pts_d else ""
    path_u = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_u) if pts_u else ""

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  {''.join(guidelines)}
  {f'<path d="{path_d}" fill="none" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round"/>' if path_d else ''}
  {f'<path d="{path_u}" fill="none" stroke="#34d399" stroke-width="2.0" stroke-dasharray="3,3" stroke-linecap="round"/>' if path_u else ''}
  {''.join(circles)}
  <g transform="translate({pad_left}, 15)">
    <line x1="0" y1="0" x2="16" y2="0" stroke="#38bdf8" stroke-width="2.5"/>
    <text x="22" y="4" fill="#cbd5e1" font-size="11">{_t("compliance_down", lang)}</text>
    <line x1="200" y1="0" x2="216" y2="0" stroke="#34d399" stroke-width="2" stroke-dasharray="3,3"/>
    <text x="222" y="4" fill="#cbd5e1" font-size="11">{_t("compliance_up", lang)}</text>
  </g>
</svg>"""


def render_speedtest_chart(
    speed_tests: List[dict],
    contract_down: float,
    contract_up: float,
    guaranteed_down: float = 0.0,
    guaranteed_up: float = 0.0,
    width: int = 800,
    height: int = 240,
    lang: str = "hu",
) -> str:
    """Generate SVG chart comparing actual measured throughput vs contract SLA & guarantee.
    
    If contract or guaranteed values are 0 (unconfigured), no misleading 0 Mbps lines are drawn.
    """
    valid_tests = [t for t in reversed(speed_tests) if t.get("status") == "ok" and t.get("scope") != "lan"
                   and t.get("down_mbps") is not None]
    if not valid_tests:
        return f'<svg viewBox="0 0 {width} {height}" class="nmb-svg"><text x="{width//2}" y="{height//2}" fill="#94a3b8" text-anchor="middle" font-size="14">{_t("no_speed_data", lang)}</text></svg>'

    pad_left, pad_right, pad_top, pad_bottom = 60, 20, 30, 35
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    comp_vals = [t["down_mbps"] for t in valid_tests if t.get("down_mbps")]
    if contract_down > 0:
        comp_vals.append(contract_down)
    if guaranteed_down > 0:
        comp_vals.append(guaranteed_down)

    max_val = max(comp_vals) if comp_vals else 50.0
    y_max = max(50.0, max_val * 1.2)

    def y_coord(val: float) -> float:
        return pad_top + plot_h - (min(val, y_max) / y_max) * plot_h

    # Baseline contract & guarantee lines (ONLY when configured > 0, NEVER show 0 Mbps lines!)
    sla_markup = []
    if contract_down > 0:
        sla_line_y = y_coord(contract_down)
        sla_markup.extend([
            f'<line x1="{pad_left}" y1="{sla_line_y}" x2="{width - pad_right}" y2="{sla_line_y}" stroke="#ec4899" stroke-dasharray="4,4" stroke-width="1.5"/>',
            f'<text x="{width - pad_right}" y="{sla_line_y - 4}" fill="#ec4899" text-anchor="end" font-size="10">{_t("offered_down", lang)}: {contract_down:.0f} Mbps</text>',
        ])
    if guaranteed_down > 0:
        guar_line_y = y_coord(guaranteed_down)
        sla_markup.extend([
            f'<line x1="{pad_left}" y1="{guar_line_y}" x2="{width - pad_right}" y2="{guar_line_y}" stroke="#f43f5e" stroke-dasharray="2,2" stroke-width="1.5"/>',
            f'<text x="{width - pad_right}" y="{guar_line_y - 4}" fill="#f43f5e" text-anchor="end" font-size="10">{_t("guar_down", lang)}: {guaranteed_down:.0f} Mbps</text>',
        ])
    if contract_up > 0:
        sla_up_y = y_coord(contract_up)
        sla_markup.extend([
            f'<line x1="{pad_left}" y1="{sla_up_y}" x2="{width - pad_right}" y2="{sla_up_y}" stroke="#34d399" stroke-dasharray="4,4" stroke-width="1.2"/>',
            f'<text x="{width - pad_right}" y="{sla_up_y - 4}" fill="#34d399" text-anchor="end" font-size="10">{_t("offered_up", lang)}: {contract_up:.0f} Mbps</text>',
        ])

    # Grouped bars per test
    n_groups = len(valid_tests)
    group_w = plot_w / n_groups
    bar_w = min(22.0, (group_w - 12) / 2.0)
    bars_markup = []

    for i, t_point in enumerate(valid_tests):
        center_x = pad_left + (i + 0.5) * group_w
        down_mbps = t_point.get("down_mbps") or 0.0
        up_measured = t_point.get("up_mbps") is not None
        up_mbps = t_point.get("up_mbps") or 0.0

        # Downlink bar
        h_down = (down_mbps / y_max) * plot_h
        y_down = pad_top + plot_h - h_down
        x_down = center_x - bar_w - 1.5

        if contract_down > 0:
            down_color = "#38bdf8" if down_mbps >= contract_down * 0.8 else ("#f59e0b" if down_mbps >= (guaranteed_down or 1) else "#ef4444")
        else:
            down_color = "#38bdf8"

        bars_markup.append(f'<rect x="{x_down:.1f}" y="{y_down:.1f}" width="{bar_w:.1f}" height="{h_down:.1f}" fill="{down_color}" rx="2"><title>{_t("download", lang)}: {down_mbps:.1f} Mbps</title></rect>')

        # Uplink bar
        h_up = (up_mbps / y_max) * plot_h
        y_up = pad_top + plot_h - h_up
        x_up = center_x + 1.5
        up_color = ("#34d399" if up_mbps >= contract_up * 0.8 else "#f59e0b") if contract_up > 0 else "#34d399"
        if up_measured:
            bars_markup.append(f'<rect x="{x_up:.1f}" y="{y_up:.1f}" width="{bar_w:.1f}" height="{h_up:.1f}" fill="{up_color}" rx="2"><title>{_t("upload", lang)}: {up_mbps:.1f} Mbps</title></rect>')

        # Timestamp label
        ts_label = _fmt_time(t_point["ts"])
        bars_markup.append(f'<text x="{center_x:.1f}" y="{height - 10}" fill="#94a3b8" text-anchor="middle" font-size="10">{ts_label}</text>')

    return f"""<svg viewBox="0 0 {width} {height}" class="nmb-svg" xmlns="http://www.w3.org/2000/svg">
  {''.join(sla_markup)}
  {''.join(bars_markup)}
  <g transform="translate({pad_left}, 15)">
    <rect x="0" y="0" width="12" height="12" fill="#38bdf8" rx="2"/>
    <text x="18" y="10" fill="#cbd5e1" font-size="11">{_t("measured_down", lang)}</text>
    <rect x="180" y="0" width="12" height="12" fill="#34d399" rx="2"/>
    <text x="198" y="10" fill="#cbd5e1" font-size="11">{_t("measured_up", lang)}</text>
  </g>
</svg>"""


# More languages (same keys as English).
_CHART_KEYS = ("no_speed_data", "no_compliance_data", "no_latency_data", "no_loss_data", "no_jitter_data", "offered_down", "guar_down",
               "offered_up", "guar_up", "measured_down", "measured_up", "compliance_100", "compliance_80", "compliance_down", "compliance_up",
               "latency_rtt", "jitter", "packet_loss", "jitter_ms", "outage", "loss_at", "download", "upload")
for _lang, _texts in {
    "ro": ("Nicio măsurare de viteză reușită în această perioadă", "Nu există date despre respectarea SLA", "Nicio telemetrie de latență în această perioadă",
           "Nicio telemetrie de pierdere a pachetelor", "Nicio telemetrie de jitter", "Descărcare contractată", "Descărcare garantată", "Încărcare contractată",
           "Încărcare garantată", "Descărcare măsurată (Mbps)", "Încărcare măsurată (Mbps)", "100% din viteza contractată", "Prag așteptat de 80%",
           "% respectare la descărcare", "% respectare la încărcare", "Latență (RTT)", "Jitter", "Pierdere de pachete (%)", "Jitter de latență (ms)",
           "Întrerupere", "pierdere la", "Descărcare", "Încărcare"),
    "it": ("Nessun test di velocità riuscito in questo periodo", "Nessun dato sul rispetto dello SLA", "Nessuna telemetria di latenza in questo periodo",
           "Nessuna telemetria di perdita di pacchetti", "Nessuna telemetria di jitter", "Download contrattuale", "Download garantito", "Upload contrattuale",
           "Upload garantito", "Download misurato (Mbps)", "Upload misurato (Mbps)", "100% della velocità contrattuale", "Soglia attesa dell'80%",
           "% rispetto in download", "% rispetto in upload", "Latenza (RTT)", "Jitter", "Perdita di pacchetti (%)", "Jitter della latenza (ms)",
           "Interruzione", "perdita alle", "Download", "Upload"),
    "es": ("No hay pruebas de velocidad correctas en este periodo", "No hay datos de cumplimiento del SLA", "No hay telemetría de latencia en este periodo",
           "No hay telemetría de pérdida de paquetes", "No hay telemetría de jitter", "Descarga contratada", "Descarga garantizada", "Subida contratada",
           "Subida garantizada", "Descarga medida (Mbps)", "Subida medida (Mbps)", "100% de la velocidad contratada", "Umbral esperado del 80%",
           "% de cumplimiento en descarga", "% de cumplimiento en subida", "Latencia (RTT)", "Jitter", "Pérdida de paquetes (%)", "Jitter de la latencia (ms)",
           "Corte", "pérdida a las", "Descarga", "Subida"),
    "pt": ("Não há testes de velocidade bem-sucedidos neste período", "Não há dados de cumprimento do SLA", "Não há telemetria de latência neste período",
           "Não há telemetria de perda de pacotes", "Não há telemetria de jitter", "Download contratado", "Download garantido", "Upload contratado",
           "Upload garantido", "Download medido (Mbps)", "Upload medido (Mbps)", "100% da velocidade contratada", "Limiar esperado de 80%",
           "% de cumprimento no download", "% de cumprimento no upload", "Latência (RTT)", "Jitter", "Perda de pacotes (%)", "Jitter da latência (ms)",
           "Falha", "perda às", "Download", "Upload"),
    "pt-br": ("Nenhum teste de velocidade bem-sucedido neste período", "Não há dados de cumprimento do SLA", "Nenhuma telemetria de latência neste período",
              "Nenhuma telemetria de perda de pacotes", "Nenhuma telemetria de jitter", "Download contratado", "Download garantido", "Upload contratado",
              "Upload garantido", "Download medido (Mbps)", "Upload medido (Mbps)", "100% da velocidade contratada", "Limite esperado de 80%",
              "% de cumprimento no download", "% de cumprimento no upload", "Latência (RTT)", "Jitter", "Perda de pacotes (%)", "Jitter da latência (ms)",
              "Queda", "perda às", "Download", "Upload"),
    "zh": ("此期间没有成功的测速记录", "没有 SLA 达标数据", "此期间没有延迟遥测数据", "没有丢包遥测数据", "没有延迟抖动遥测数据",
           "合同下载速度", "保证下载速度", "合同上传速度", "保证上传速度", "实测下载（Mbps）", "实测上传（Mbps）", "合同速度的 100%",
           "预期门槛 80%", "下载达标率 %", "上传达标率 %", "延迟（RTT）", "抖动", "丢包（%）", "延迟抖动（ms）", "中断", "丢包于", "下载", "上传"),
}.items():
    CHART_I18N[_lang] = dict(zip(_CHART_KEYS, _texts))
