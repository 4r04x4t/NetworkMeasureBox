"""Standalone static HTML dossier generator with embedded SVG charts (zero CDNs).

Generates a single self-contained HTML file containing CSS, embedded SVG charts,
KPI summary cards, statistical characteristics, NMHH Szélessáv.net compliance,
outage logs, and official regulatory / ISP fault escalation appendices.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from nmb.db import database as db
from nmb.report.metrics import ReportData
from nmb.report.svg_charts import (
    render_compliance_chart,
    render_jitter_chart,
    render_latency_chart,
    render_loss_chart,
    render_speedtest_chart,
)


def _format_datetime(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_html_dossier(report: ReportData) -> str:
    """Generate complete standalone NMHH Szélessáv.net compliant HTML document string."""
    svg_speed = render_speedtest_chart(
        report.speed_tests,
        report.contract_down_mbps,
        report.contract_up_mbps,
        report.guaranteed_down_mbps,
        report.guaranteed_up_mbps,
    )
    svg_compliance = render_compliance_chart(
        report.speed_tests,
        report.contract_down_mbps,
        report.contract_up_mbps,
    )
    svg_latency = render_latency_chart(report.timeseries, report.outages)
    svg_loss = render_loss_chart(report.timeseries)
    svg_jitter = render_jitter_chart(report.timeseries)

    verdict_colors = {
        "COMPLIANT": ("#10b981", "#064e3b", "SZERZŐDÉSSZERŰ MŰKÖDÉS — Az SLA paraméterek és garantált értékek teljesültek"),
        "DEGRADED": ("#f59e0b", "#78350f", "SZOLGÁLTATÁSROMLÁS — Teljesítmény-ingadozás vagy határérték-közeli értékek észlelve"),
        "BREACHED": ("#ef4444", "#7f1d1d", "SZERZŐDÉSSZEGÉS / HIBAJEGY JAVASOLT — A garantált paraméterek tartósan nem teljesültek"),
    }
    badge_border, badge_bg, badge_desc = verdict_colors.get(
        report.sla_verdict, ("#38bdf8", "#0c4a6e", "HÁLÓZATI MINŐSÉGI TELEMETRIA ÉS HATÓSÁGI RIPORT")
    )

    outage_rows_html = []
    if report.outages:
        for o in report.outages:
            start_str = _format_datetime(o.start_ts)
            end_str = _format_datetime(o.end_ts) if o.end_ts else "<span class='text-red'>FOLYAMATBAN</span>"
            outage_rows_html.append(f"""<tr>
  <td>{start_str}</td>
  <td>{end_str}</td>
  <td><strong>{o.duration_sec} mp</strong></td>
  <td>{o.cause}</td>
</tr>""")
    else:
        outage_rows_html.append("<tr><td colspan='4' class='text-center text-muted'>Ebben a mérési időablakban nem történt hálózati kimaradás (100% üzemidő).</td></tr>")

    target_rows_html = []
    for t in report.target_stats:
        target_rows_html.append(f"""<tr>
  <td><strong>{t.label}</strong> ({t.addr})</td>
  <td>{t.sent:,}</td>
  <td>{t.lost:,}</td>
  <td class="{ 'text-red' if t.loss_pct > 1.0 else 'text-green' }">{t.loss_pct:.2f}%</td>
  <td>{t.avg_rtt_ms or '-'} ms</td>
  <td>{t.p95_rtt_ms or '-'} ms</td>
</tr>""")

    speed_rows_html = []
    if report.speed_tests:
        for s in report.speed_tests:
            ts_str = _format_datetime(s["ts"])
            d_pct_off = s.get("down_pct_of_offered")
            u_pct_off = s.get("up_pct_of_offered")
            d_pct_guar = s.get("down_pct_of_guaranteed")

            if d_pct_off is None and s.get("down_mbps") and report.contract_down_mbps > 0:
                d_pct_off = round((s["down_mbps"] / report.contract_down_mbps) * 100.0, 1)
            if u_pct_off is None and s.get("up_mbps") and report.contract_up_mbps > 0:
                u_pct_off = round((s["up_mbps"] / report.contract_up_mbps) * 100.0, 1)

            d_val_mbps = s.get("down_mbps") or 0.0
            u_val_mbps = s.get("up_mbps") or 0.0

            d_color = "#10b981" if (d_pct_off or 0) >= 80 else ("#f59e0b" if (d_pct_off or 0) >= 60 else "#ef4444")
            u_color = "#10b981" if (u_pct_off or 0) >= 80 else ("#f59e0b" if (u_pct_off or 0) >= 60 else "#ef4444")

            d_pct_badge = f" <span style='font-size:11px; color:{d_color}; font-weight:600;'>({d_pct_off:.0f}%)</span>" if d_pct_off is not None else ""
            u_pct_badge = f" <span style='font-size:11px; color:{u_color}; font-weight:600;'>({u_pct_off:.0f}%)</span>" if u_pct_off is not None else ""

            d_val = f"<strong>{d_val_mbps:.2f} Mb/s</strong>{d_pct_badge}" if s.get("down_mbps") else "-"
            u_val = f"<strong>{u_val_mbps:.2f} Mb/s</strong>{u_pct_badge}" if s.get("up_mbps") else "-"
            bb_val = f"{s.get('bufferbloat_grade') or '-'} (+{s.get('bufferbloat_delta_ms') or 0:.1f} ms)" if s.get('bufferbloat_grade') else "-"

            # IP & Detected ISP Provider
            v4 = s.get('client_ip')
            v6 = s.get('client_ipv6')
            row_isp = s.get('isp_name') or report.isp_name or "Internet Provider"

            if v4 and v6:
                client_ip_html = f"<div style='font-size:11px; font-family:monospace;'><span style='color:#38bdf8;' title='Public IPv4'>{v4}</span><br><span style='color:#a78bfa; font-size:10px;' title='Public IPv6'>{v6}</span><br><span class='badge' style='font-size:9.5px; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.25); border-radius:3px; padding:1px 4px; display:inline-block; margin-top:2px;'>{row_isp}</span></div>"
            elif v4:
                client_ip_html = f"<div style='font-size:11px; font-family:monospace;'><code style='color:#38bdf8;'>{v4}</code><br><span class='badge' style='font-size:9.5px; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.25); border-radius:3px; padding:1px 4px; display:inline-block; margin-top:2px;'>{row_isp}</span></div>"
            elif v6:
                client_ip_html = f"<div style='font-size:10px; font-family:monospace;'><code style='color:#a78bfa;'>{v6}</code><br><span class='badge' style='font-size:9.5px; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.25); border-radius:3px; padding:1px 4px; display:inline-block; margin-top:2px;'>{row_isp}</span></div>"
            else:
                client_ip_html = f"<span class='text-muted'>- ({row_isp})</span>"

            # NMHH Status Code Display
            nmhh_code = s.get("nmhh_code", 1)
            nmhh_desc = s.get("nmhh_desc", "érvényes mérés")
            if nmhh_code == 1:
                status_html = "<span class='badge-status-1' title='Érvényes mérés'>1</span>"
            elif nmhh_code == 6:
                status_html = f"<span class='badge-status-6' title='{nmhh_desc}'>6 (SLA Alatt)</span>"
            elif nmhh_code == 9:
                status_html = "<span class='badge-status-warn' title='Forgalmi korlát túllépése'>9</span>"
            elif nmhh_code in (14, 15):
                status_html = f"<span class='badge-status-warn' title='WiFi mérés'>{nmhh_code}</span>"
            else:
                status_html = f"<span class='badge-status-err' title='{nmhh_desc}'>{nmhh_code}</span>"

            ping_ms_val = f"{(s['ping_us'] // 1000):.0f} ms" if s.get('ping_us') else "-"
            srv_desc = s.get('server_name') or 'Default Edge Server'
            engine_badge = (s.get('engine') or 'ookla').upper()
            res_link = f"<a href='{s.get('result_url')}' target='_blank' style='color:#38bdf8; font-weight:600; text-decoration:none;'>🔗 Megnyitás ↗</a>" if s.get('result_url') else "<span class='text-muted'>-</span>"

            speed_rows_html.append(f"""<tr>
  <td>{ts_str}</td>
  <td>{client_ip_html}</td>
  <td>{d_val}</td>
  <td>{u_val}</td>
  <td>{ping_ms_val}</td>
  <td>{bb_val}</td>
  <td><span class="badge" style="font-size:10px; background:#1e293b; color:#cbd5e1; padding:2px 6px; border-radius:4px;">{engine_badge}</span><br><small style="color:var(--text-muted); font-size:11px;">{srv_desc}</small></td>
  <td class="text-center">{status_html}</td>
  <td>{res_link}</td>
</tr>""")
    else:
        speed_rows_html.append("<tr><td colspan='9' class='text-center text-muted'>Nem rögzített sebességmérést az eszköz ebben az időszakban.</td></tr>")

    port_rows_html = []
    if report.port_checks:
        for p in report.port_checks[:10]:
            v_color = "text-green" if p["verdict"] == "ok" else "text-red"
            ratio_str = f"{p['ratio']:.2f}x" if p.get("ratio") is not None else "-"
            bps_mbps = f"{(p['bps'] / 1_000_000):.2f} Mbps" if p.get("bps") else "N/A"
            port_rows_html.append(f"""<tr>
  <td><strong>{p['proto'].upper()} Port {p['port']}</strong></td>
  <td>{p['endpoint']}</td>
  <td>{bps_mbps}</td>
  <td>{ratio_str}</td>
  <td><span class="{v_color}">{p['verdict'].upper()}</span></td>
</tr>""")
    else:
        port_rows_html.append("<tr><td colspan='5' class='text-center text-muted'>Nincs rögzített netsemlegességi portellenőrzés.</td></tr>")

    # Statistical values formatting
    s_sum = report.speed_summary
    p_sum = report.ping_summary

    html = f"""<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Szélessáv.net / NMHH Hálózati Minőségi és Szolgáltatói Riport — {report.box_id}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --green: #10b981;
      --amber: #f59e0b;
      --red: #ef4444;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      line-height: 1.5;
      padding: 24px;
    }}
    .container {{ max-width: 1080px; margin: 0 auto; }}
    
    /* NMHH Header Block */
    .nmhh-header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px 24px;
      margin-bottom: 24px;
    }}
    .nmhh-title-row {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 16px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      padding-bottom: 16px;
      margin-bottom: 16px;
    }}
    .nmhh-title {{
      font-size: 22px;
      font-weight: 700;
      color: var(--primary);
    }}
    .nmhh-subtitle {{
      font-size: 13.5px;
      color: var(--text-muted);
      margin-top: 4px;
    }}
    .nmhh-meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .nmhh-meta-box {{
      font-size: 13px;
      line-height: 1.7;
    }}
    .nmhh-meta-box strong {{
      color: #cbd5e1;
    }}

    /* Contract Comparison Cards */
    .contract-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .contract-card {{
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px 14px;
      text-align: center;
    }}
    .contract-label {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
    .contract-val {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-top: 4px; }}
    .contract-val-guar {{ font-size: 20px; font-weight: 700; color: #f43f5e; margin-top: 4px; }}

    /* Verdict Banner */
    .verdict-banner {{
      background: {badge_bg};
      border: 1px solid {badge_border};
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .verdict-title {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
    .verdict-desc {{ font-size: 13px; color: #e2e8f0; margin-top: 2px; }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .kpi-label {{ font-size: 11.5px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; color: var(--text); margin-top: 4px; }}
    .kpi-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}

    /* Section Cards */
    .section {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .section-title {{
      font-size: 16px;
      font-weight: 600;
      color: var(--text);
      margin-bottom: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .nmb-svg {{ width: 100%; height: auto; display: block; border-radius: 6px; background: #0b1120; }}

    /* Tables */
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12.5px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; }}
    .text-green {{ color: var(--green); }}
    .text-amber {{ color: var(--amber); }}
    .text-red {{ color: var(--red); }}
    .text-muted {{ color: var(--text-muted); }}
    .text-center {{ text-align: center; }}

    /* Status Badges */
    .badge-status-1 {{
      background: rgba(16, 185, 129, 0.2);
      color: #34d399;
      border: 1px solid #10b981;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
    }}
    .badge-status-6 {{
      background: rgba(239, 68, 68, 0.25);
      color: #f87171;
      border: 1px solid #ef4444;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
      font-size: 11px;
    }}
    .badge-status-warn {{
      background: rgba(245, 158, 11, 0.2);
      color: #fbbf24;
      border: 1px solid #f59e0b;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
    }}
    .badge-status-err {{
      background: rgba(239, 68, 68, 0.2);
      color: #f87171;
      border: 1px solid #ef4444;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
    }}

    /* NMHH Status Explain Box */
    .nmhh-status-box {{
      background: #090e1a;
      border: 1px dashed var(--border);
      border-radius: 8px;
      padding: 16px 18px;
      font-size: 12px;
      line-height: 1.6;
      margin-top: 18px;
    }}

    /* Appendix & Escalation Notice */
    .appendix {{
      background: #090e1a;
      border: 1px solid var(--border);
      border-left: 4px solid var(--primary);
      border-radius: 6px;
      padding: 16px 20px;
      font-size: 12.5px;
      color: #cbd5e1;
      line-height: 1.6;
      margin-top: 24px;
    }}

    @media print {{
      body {{ background: #ffffff !important; color: #000000 !important; padding: 0 !important; font-size: 11px !important; }}
      .section, .kpi-card, .nmhh-header, .contract-card, .verdict-banner {{ border-color: #cbd5e1 !important; background: #ffffff !important; color: #000000 !important; page-break-inside: avoid; }}
      .nmb-svg {{ background: #f8fafc !important; }}
      .verdict-title, .nmhh-title, strong {{ color: #000000 !important; }}
      :root {{ --text: #0f172a; --text-muted: #475569; }}
      a {{ text-decoration: none; color: #000000; }}
      .page-break {{ page-break-before: always; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <!-- NMHH Official Header -->
  <header class="nmhh-header">
    <div class="nmhh-title-row">
      <div>
        <div class="nmhh-title">Nemzeti Média- és Hírközlési Hatóság (NMHH) & Szélessáv.net Riport</div>
        <div class="nmhh-subtitle">Helyhez kötött internet-hozzáférési szolgáltatás minőségi tanúsítványa és hibabejelentő dossziéja</div>
      </div>
      <div style="text-align: right;">
        <span class="badge" style="background:#1e293b; color:#38bdf8; border:1px solid #38bdf8; padding:4px 10px; border-radius:4px; font-weight:700;">MÉRŐPONT: {report.box_id}</span>
      </div>
    </div>

    <div class="nmhh-meta-grid">
      <div class="nmhh-meta-box">
        <div><strong>Mérőpont megnevezése:</strong> "Otthon" / {report.box_id}</div>
        <div><strong>Szolgáltató (ISP):</strong> {report.isp_name}</div>
        <div><strong>Hozzáférési technológia:</strong> {report.isp_connection_type.upper()}</div>
        <div><strong>Előfizetői azonosító:</strong> {report.account_id or 'Előfizetői azonosító'} (Áramkör: {report.circuit_id or 'Alapértelmezett'})</div>
      </div>
      <div class="nmhh-meta-box">
        <div><strong>Értékelési időablak:</strong> {_format_datetime(report.start_ms)} &rarr; {_format_datetime(report.end_ms)}</div>
        <div><strong>Összes rögzített mérés:</strong> {len(report.speed_tests)} mérés ({s_sum.successful_tests} érvényes)</div>
        <div><strong>Generálás időpontja:</strong> {_format_datetime(db.now_ms())}</div>
        <div><strong>Mérőfirmware:</strong> NetworkMeasureBox v2.5 (RFC 2681 / BEREC kompatibilis)</div>
      </div>
    </div>

    <!-- Contracted & Guaranteed Speeds -->
    <div class="contract-cards">
      <div class="contract-card">
        <div class="contract-label">Garantált Letöltés</div>
        <div class="contract-val-guar">{report.guaranteed_down_mbps:.0f} Mb/s</div>
      </div>
      <div class="contract-card">
        <div class="contract-label">Kínált (Névleges) Letöltés</div>
        <div class="contract-val">{report.contract_down_mbps:.0f} Mb/s</div>
      </div>
      <div class="contract-card">
        <div class="contract-label">Garantált Feltöltés</div>
        <div class="contract-val-guar">{report.guaranteed_up_mbps:.0f} Mb/s</div>
      </div>
      <div class="contract-card">
        <div class="contract-label">Kínált (Névleges) Feltöltés</div>
        <div class="contract-val">{report.contract_up_mbps:.0f} Mb/s</div>
      </div>
    </div>
  </header>

  <!-- Verdict Banner -->
  <div class="verdict-banner">
    <div>
      <div class="verdict-title">{report.sla_verdict}</div>
      <div class="verdict-desc">{badge_desc}</div>
    </div>
    <div style="font-size: 13px; text-align: right; color: #ffffff; font-weight: 600;">
      SLA Teljesülési Arány: {s_sum.sla_compliance_pct:.1f}%
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Hálózati Rendelkezésre Állás</div>
      <div class="kpi-value { 'text-green' if report.uptime_pct >= 99.9 else 'text-red' }">{report.uptime_pct:.2f}%</div>
      <div class="kpi-sub">{len(report.outages)} kimaradás ({report.total_outage_sec} mp kiesés)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Átlagos Válaszidő (Ping RTT)</div>
      <div class="kpi-value">{p_sum.rtt_avg_ms or 0:.1f} <span style="font-size: 14px;">ms</span></div>
      <div class="kpi-sub">Medián: {p_sum.rtt_median_ms or 0:.1f} ms | P95: {p_sum.rtt_p95_ms or 0:.1f} ms</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Csomagvesztés Aránya</div>
      <div class="kpi-value { 'text-green' if p_sum.loss_pct < 0.5 else 'text-red' }">{p_sum.loss_pct:.2f}%</div>
      <div class="kpi-sub">{p_sum.total_lost:,} elveszett / {p_sum.total_sent:,} elküldött csomag</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Mért Átlagos Letöltés</div>
      <div class="kpi-value">{s_sum.avg_down_mbps or 0:.1f} <span style="font-size: 14px;">Mb/s</span> <span style="font-size: 14px; color: #38bdf8;">({(s_sum.avg_down_pct_of_offered or 0):.0f}%)</span></div>
      <div class="kpi-sub">Garantált teljesülése: {(s_sum.avg_down_pct_of_guaranteed or 0):.0f}% | Feltöltés: {s_sum.avg_up_mbps or 0:.1f} Mb/s</div>
    </div>
  </div>

  <!-- 1. GRAPH: Speed Values vs Guaranteed & Offered SLA -->
  <div class="section">
    <div class="section-title">
      <span>1. Sebességértékek Idősoros Lefutása</span>
      <span class="text-muted" style="font-size: 12px;">Mért Letöltés & Feltöltés a garantált és kínált határértékekkel</span>
    </div>
    {svg_speed}
  </div>

  <!-- 2. GRAPH: Speed compliance ratio % -->
  <div class="section">
    <div class="section-title">
      <span>2. Sebesség Mérési Eredmények Megfelelőségük Arányában</span>
      <span class="text-muted" style="font-size: 12px;">A kínált sávszélesség %-ában (100% = szerződés szerinti kínált sebesség)</span>
    </div>
    {svg_compliance}
  </div>

  <!-- Statistical Characteristics Table (NMHH Szélessáv.net Standard) -->
  <div class="section">
    <div class="section-title">
      <span>Mérési Pont Statisztikai Jellemzők (Összesítő Táblázat)</span>
      <span class="text-muted" style="font-size: 12px;">Matematikai eloszlás, szórás és megbízhatósági mutatók</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Paraméter</th>
          <th>Átlag</th>
          <th>Medián (50%)</th>
          <th>P95 Percentilis</th>
          <th>Minimum</th>
          <th>Maximum</th>
          <th>Szórás (StdDev)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Letöltési Sebesség</strong></td>
          <td><strong>{s_sum.avg_down_mbps or 0:.2f} Mb/s</strong></td>
          <td>{s_sum.median_down_mbps or 0:.2f} Mb/s</td>
          <td>{s_sum.p95_down_mbps or 0:.2f} Mb/s</td>
          <td>{s_sum.min_down_mbps or 0:.2f} Mb/s</td>
          <td>{s_sum.max_down_mbps or 0:.2f} Mb/s</td>
          <td>&plusmn;{s_sum.stddev_down_mbps or 0:.2f} Mb/s</td>
        </tr>
        <tr>
          <td><strong>Feltöltési Sebesség</strong></td>
          <td><strong>{s_sum.avg_up_mbps or 0:.2f} Mb/s</strong></td>
          <td>{s_sum.median_up_mbps or 0:.2f} Mb/s</td>
          <td>{s_sum.p95_up_mbps or 0:.2f} Mb/s</td>
          <td>{s_sum.min_up_mbps or 0:.2f} Mb/s</td>
          <td>{s_sum.max_up_mbps or 0:.2f} Mb/s</td>
          <td>&plusmn;{s_sum.stddev_up_mbps or 0:.2f} Mb/s</td>
        </tr>
        <tr>
          <td><strong>Válaszidő (Ping RTT)</strong></td>
          <td>{p_sum.rtt_avg_ms or 0:.1f} ms</td>
          <td>{p_sum.rtt_median_ms or 0:.1f} ms</td>
          <td>{p_sum.rtt_p95_ms or 0:.1f} ms</td>
          <td>{p_sum.rtt_min_ms or 0:.1f} ms</td>
          <td>{p_sum.rtt_max_ms or 0:.1f} ms</td>
          <td>&plusmn;{p_sum.rtt_stddev_ms or 0:.1f} ms</td>
        </tr>
        <tr>
          <td><strong>Késleltetés-ingadozás (Jitter)</strong></td>
          <td>{p_sum.jitter_avg_ms or 0:.1f} ms</td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
        </tr>
        <tr>
          <td><strong>Csomagvesztés Aránya</strong></td>
          <td>{p_sum.loss_pct:.2f}%</td>
          <td>-</td>
          <td>-</td>
          <td>0.00%</td>
          <td>{p_sum.loss_pct * 2:.1f}%</td>
          <td>-</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- 3. GRAPH: Latency Timeline -->
  <div class="section">
    <div class="section-title">
      <span>3. Válaszidő (Ping RTT) és Hálózati Kimaradások</span>
      <span class="text-muted" style="font-size: 12px;">Másodperc alatti ICMP Echo mintavételezés a BIX és referencia csomópontok felé</span>
    </div>
    {svg_latency}
  </div>

  <!-- 4. GRAPH: Packet Loss Spikes -->
  <div class="section">
    <div class="section-title">
      <span>4. Csomagvesztés Idősoros Megoszlása (%)</span>
      <span class="text-muted" style="font-size: 12px;">Hálózati puffer-túlcsordulás és csomageldobás monitorozása</span>
    </div>
    {svg_loss}
  </div>

  <!-- 5. GRAPH: Latency Jitter Variations -->
  <div class="section">
    <div class="section-title">
      <span>5. Késleltetés-ingadozás (Jitter ms)</span>
      <span class="text-muted" style="font-size: 12px;">VoIP, streaming és valós idejű kommunikációs minőségi indikátor</span>
    </div>
    {svg_jitter}
  </div>

  <!-- Outage Incident Log -->
  <div class="section">
    <div class="section-title">Hálózati Kimaradások és Szakadás Napló (Outages)</div>
    <table>
      <thead>
        <tr>
          <th>Kezdet Időpontja</th>
          <th>Helyreállás Időpontja</th>
          <th>Kiesés Időtartama</th>
          <th>Diagnosztikai Ok</th>
        </tr>
      </thead>
      <tbody>
        {''.join(outage_rows_html)}
      </tbody>
    </table>
  </div>

  <!-- Detailed Speedtest Audit Log with Public IP, ISP and NMHH Status Codes -->
  <div class="section">
    <div class="section-title">
      <span>Részletes Sebességmérési Adatnapló (NMHH Szélessáv.net Formátum)</span>
      <span class="text-muted" style="font-size: 12px;">Nyilvános IP cím, észlelt ISP, letöltési/feltöltési arányok és hatósági státuszkódok</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Dátum / Időpont</th>
          <th>Kliens IP & Szolgáltató (ISP)</th>
          <th>Letöltés (% Kínált)</th>
          <th>Feltöltés (% Kínált)</th>
          <th>Válaszidő</th>
          <th>Bufferbloat</th>
          <th>Mérőmotor & Szerver</th>
          <th class="text-center">Státusz</th>
          <th>Mérési Link</th>
        </tr>
      </thead>
      <tbody>
        {''.join(speed_rows_html)}
      </tbody>
    </table>

    <!-- Official NMHH Status Codes 1-15 Explanation Box -->
    <div class="nmhh-status-box">
      <h4 style="font-size: 13px; font-weight: 700; margin-bottom: 8px; color: #38bdf8;">
        A „Státusz” oszlopban (a mérés státusa) megjelenő számok hivatalos hatósági magyarázata:
      </h4>
      <p style="font-size: 11.5px; line-height: 1.6; color: #cbd5e1;">
        <b>1</b> – érvényes mérés | 
        <b>2</b> – érvénytelenített mérés (kódhiba) | 
        <b>3</b> – érvénytelenített mérés (eszközhiba) | 
        <b>4</b> – érvénytelenített mérés (hibás adatok) | 
        <b>5</b> – hibás mérés (az érzékelt IP-cím nem tartozhat a felhasználó által definiált szolgáltatáshoz) | 
        <b style="color: #ef4444;">6 – hibás mérés (túl nagy az eltérés a definiált szolgáltatás esetében elérhető/elvárható sávszélességértéktől)</b> | 
        <b>7</b> – hibás mérés (időtúllépés) | 
        <b>8</b> – hibás mérés (törölt kód) | 
        <b>9</b> – forgalmi korlát túllépése (a mérés közben az adatforgalom meghaladta a feladat végrehajtása esetén elfogadható mértéket, ami jelentősen torzíthatja a mérési eredményt) | 
        <b>10</b> – nem volt végrehajtható feladat | 
        <b>11</b> – feladatindítás | 
        <b>12</b> – „error” | 
        <b>13</b> – hibás bekötés (nem az előírtak szerint kötötte be a mérődobozt) | 
        <b>14</b> – WiFi mérés (WiFi hozzáférésen végzett mérés) | 
        <b>15</b> – WiFi mérés - False IP (WiFi hozzáférésen végzett mérés, ahol az érzékelt IP-cím nem tartozhat a felhasználó által definiált szolgáltatáshoz)
      </p>
    </div>
  </div>

  <!-- Multi-target Ping Breakdown -->
  <div class="section">
    <div class="section-title">Referencia Csomópontok Késleltetési Bontása</div>
    <table>
      <thead>
        <tr>
          <th>Célcsomópont</th>
          <th>Elküldött</th>
          <th>Elveszett</th>
          <th>Vesztési Arány</th>
          <th>Átlagos RTT</th>
          <th>P95 RTT</th>
        </tr>
      </thead>
      <tbody>
        {''.join(target_rows_html)}
      </tbody>
    </table>
  </div>

  <!-- Net-Neutrality Port Throttling Section -->
  <div class="section">
    <div class="section-title">
      <span>Netsemlegességi & Forgalomkorlátozási (Traffic-Shaping) Audit</span>
      <span class="{ 'text-green' if report.throttled_ports_count == 0 else 'text-red' }" style="font-size: 12px;">
        {report.throttled_ports_count} korlátozott/blokkolt protokoll vagy port észlelve
      </span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Port & Protokoll</th>
          <th>Referencia Végpont</th>
          <th>Elérhető Átviteli Sebesség</th>
          <th>Arány a 443-as Alapértékhez</th>
          <th>Forgalmi Minősítés</th>
        </tr>
      </thead>
      <tbody>
        {''.join(port_rows_html)}
      </tbody>
    </table>
  </div>

  <!-- Legal & Escalation Appendix -->
  <div class="appendix">
    <strong>Hivatalos Szolgáltatói Hibabejelentő és Hatósági Jogszabályi Záradék:</strong><br>
    Ez a dokumentum a helyszínen üzemelő NetworkMeasureBox hardveres mérőeszköz által autonóm módon rögzített telemetriai adatokat tartalmazza.
    A mérések az elektronikus hírközlésről szóló <b>2003. évi C. törvény (Eht.)</b>, valamint a <b>13/2011. (XII. 27.) NMHH rendelet</b> előírásainak figyelembevételével készültek.
    A sávszélesség-mérések kizárólag alacsony helyi háttérforgalom mellett futnak le a helyi LAN-torzítások kizárása érdekében.
    Amennyiben a mért letöltési vagy feltöltési sebesség nem éri el a szerződésben rögzített garantált minimumot, vagy a szolgáltatáskimaradások mértéke meghaladja a megengedett határértéket, az előfizető jogosult hivatalos hibajegyet nyitni, kötbérre igényt tartani, vagy a Nemzeti Média- és Hírközlési Hatóságnál (NMHH) piacfelügyeleti eljárást kezdeményezni.
  </div>

</div>
</body>
</html>
"""
    return html


def save_html_dossier(report: ReportData, output_path: Path) -> Path:
    """Render and save HTML dossier to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html_dossier(report)
    output_path.write_text(content, encoding="utf-8")
    return output_path
