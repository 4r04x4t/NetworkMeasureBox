"""Standalone static HTML dossier generator with embedded SVG charts (zero CDNs).

Generates a single self-contained HTML file containing CSS, embedded SVG charts,
KPI summary cards, outage logs, and ISP fault escalation appendices.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from nmb.db import database as db
from nmb.report.metrics import ReportData
from nmb.report.svg_charts import (
    render_latency_chart,
    render_loss_chart,
    render_speedtest_chart,
)


def _format_datetime(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_html_dossier(report: ReportData) -> str:
    """Generate complete standalone HTML document string."""
    svg_latency = render_latency_chart(report.timeseries, report.outages)
    svg_loss = render_loss_chart(report.timeseries)
    svg_speed = render_speedtest_chart(
        report.speed_tests,
        report.contract_down_mbps,
        report.contract_up_mbps
    )

    verdict_colors = {
        "COMPLIANT": ("#10b981", "#064e3b", "SLA COMPLIANT — Normal Operational Parameters"),
        "DEGRADED": ("#f59e0b", "#78350f", "SERVICE DEGRADED — Performance Anomaly Detected"),
        "BREACHED": ("#ef4444", "#7f1d1d", "SLA BREACHED — Formal ISP Fault Ticket Warranted"),
    }
    badge_border, badge_bg, badge_desc = verdict_colors.get(
        report.sla_verdict, ("#38bdf8", "#0c4a6e", "TELEMETRY DOSSIER")
    )

    outage_rows_html = []
    if report.outages:
        for o in report.outages:
            start_str = _format_datetime(o.start_ts)
            end_str = _format_datetime(o.end_ts) if o.end_ts else "<span class='text-red'>ONGOING</span>"
            outage_rows_html.append(f"""<tr>
  <td>{start_str}</td>
  <td>{end_str}</td>
  <td><strong>{o.duration_sec}s</strong></td>
  <td>{o.cause}</td>
</tr>""")
    else:
        outage_rows_html.append("<tr><td colspan='4' class='text-center text-muted'>Zero downtime incidents recorded in this timeframe.</td></tr>")

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
        for s in report.speed_tests[:10]:
            ts_str = _format_datetime(s["ts"])
            d_pct = s.get("down_pct_of_offered")
            u_pct = s.get("up_pct_of_offered")
            if d_pct is None and s.get("down_mbps") and report.contract_down_mbps > 0:
                d_pct = round((s["down_mbps"] / report.contract_down_mbps) * 100.0, 1)
            if u_pct is None and s.get("up_mbps") and report.contract_up_mbps > 0:
                u_pct = round((s["up_mbps"] / report.contract_up_mbps) * 100.0, 1)

            st_color = "text-green" if s.get("status") == "ok" else "text-red"
            d_color = "#10b981" if (d_pct or 0) >= 80 else ("#f59e0b" if (d_pct or 0) >= 60 else "#ef4444")
            u_color = "#10b981" if (u_pct or 0) >= 80 else ("#f59e0b" if (u_pct or 0) >= 60 else "#ef4444")

            d_pct_badge = f" <span style='font-size:11px; color:{d_color}; font-weight:600;'>({d_pct:.1f}%)</span>" if d_pct is not None else ""
            u_pct_badge = f" <span style='font-size:11px; color:{u_color}; font-weight:600;'>({u_pct:.1f}%)</span>" if u_pct is not None else ""

            d_val = f"<strong>{s['down_mbps']:.1f} Mbps</strong>{d_pct_badge}" if s.get("down_mbps") else "-"
            u_val = f"<strong>{s['up_mbps']:.1f} Mbps</strong>{u_pct_badge}" if s.get("up_mbps") else "-"
            bb_val = f"{s['bufferbloat_grade']} (+{s['bufferbloat_delta_ms']:.1f} ms)" if s.get('bufferbloat_grade') else "-"
            tech_val = s.get('connection_type') or report.isp_connection_type
            v4 = s.get('client_ip')
            v6 = s.get('client_ipv6')
            if v4 and v6:
                client_ip_html = f"<div style='font-size:11px; font-family:monospace;'><span style='color:#38bdf8;' title='Public IPv4'>{v4}</span><br><span style='color:#a78bfa; font-size:10px;' title='Public IPv6'>{v6}</span></div>"
            elif v4:
                client_ip_html = f"<code style='font-size:11px; color:#38bdf8;'>{v4}</code>"
            elif v6:
                client_ip_html = f"<code style='font-size:10px; color:#a78bfa;'>{v6}</code>"
            else:
                client_ip_html = "<span class='text-muted'>-</span>"
            srv_desc = s.get('server_name') or 'Default Edge'
            if s.get('server_host'):
                srv_desc += f"<br><small style='color:var(--text-muted);'>{s.get('server_host')}</small>"
            res_link = f"<a href='{s.get('result_url')}' target='_blank' style='color:#38bdf8; font-weight:600; text-decoration:none;'>🔗 Megnyitás ↗</a>" if s.get('result_url') else "<span class='text-muted'>-</span>"

            speed_rows_html.append(f"""<tr>
  <td>{ts_str}</td>
  <td><span class="{st_color}">{s['status'].upper()}</span></td>
  <td><span class="badge" style="font-size:10px; background:#1e293b; color:#38bdf8; padding:2px 6px; border-radius:4px;">{tech_val.upper()}</span></td>
  <td>{client_ip_html}</td>
  <td>{d_val}</td>
  <td>{u_val}</td>
  <td>{ (s['ping_us'] // 1000) if s.get('ping_us') else '-' } ms</td>
  <td><strong>{bb_val}</strong></td>
  <td>{srv_desc}</td>
  <td>{res_link}</td>
</tr>""")
    else:
        speed_rows_html.append("<tr><td colspan='10' class='text-center text-muted'>No speedtest runs recorded.</td></tr>")

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
        port_rows_html.append("<tr><td colspan='5' class='text-center text-muted'>No net-neutrality port checks recorded.</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NetworkMeasureBox Telemetry Dossier — {report.account_id}</title>
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
    .container {{ max-width: 1040px; margin: 0 auto; }}
    .header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
      margin-bottom: 24px;
    }}
    .header h1 {{ font-size: 24px; color: var(--primary); font-weight: 700; }}
    .header p {{ color: var(--text-muted); font-size: 14px; margin-top: 4px; }}
    .meta-box {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      font-size: 13px;
    }}
    .verdict-banner {{
      background: {badge_bg};
      border: 1px solid {badge_border};
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .verdict-title {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
    .verdict-desc {{ font-size: 13px; color: #e2e8f0; margin-top: 2px; }}
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
    .kpi-label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }}
    .kpi-value {{ font-size: 26px; font-weight: 700; color: var(--text); margin-top: 4px; }}
    .kpi-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 2px; }}
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
    }}
    .nmb-svg {{ width: 100%; height: auto; display: block; border-radius: 6px; background: #0b1120; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; }}
    .text-green {{ color: var(--green); }}
    .text-amber {{ color: var(--amber); }}
    .text-red {{ color: var(--red); }}
    .text-muted {{ color: var(--text-muted); }}
    .text-center {{ text-align: center; }}
    .appendix {{
      background: #090e1a;
      border: 1px dashed var(--border);
      border-radius: 8px;
      padding: 16px;
      font-size: 12px;
      color: var(--text-muted);
      line-height: 1.6;
    }}
    @media print {{
      body {{ background: #ffffff; color: #000000; padding: 0; }}
      .section, .kpi-card, .meta-box {{ border-color: #cbd5e1; background: #f8fafc; }}
      .nmb-svg {{ background: #f1f5f9; }}
      :root {{ --text: #0f172a; --text-muted: #64748b; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <header class="header">
    <div>
      <h1>Network Quality Telemetry Dossier</h1>
      <p>Continuous edge measurement engine — Autonomous SLA verification</p>
      <p class="text-muted" style="margin-top: 6px;">Evaluation Window: {_format_datetime(report.start_ms)} &rarr; {_format_datetime(report.end_ms)}</p>
    </div>
    <div class="meta-box">
      <div><strong>ISP:</strong> {report.isp_name}</div>
      <div><strong>Access Tech:</strong> {report.isp_connection_type.upper()}</div>
      <div><strong>Account:</strong> {report.account_id}</div>
      <div><strong>Circuit:</strong> {report.circuit_id}</div>
      <div><strong>SLA Plan:</strong> {report.contract_down_mbps:.0f}M Down / {report.contract_up_mbps:.0f}M Up</div>
      <div><strong>Box Unit:</strong> {report.box_id}</div>
    </div>
  </header>

  <!-- Verdict Banner -->
  <div class="verdict-banner">
    <div>
      <div class="verdict-title">{report.sla_verdict}</div>
      <div class="verdict-desc">{badge_desc}</div>
    </div>
    <div style="font-size: 12px; text-align: right; color: #cbd5e1;">
      Generated: {_format_datetime(db.now_ms())}
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Uptime Availability</div>
      <div class="kpi-value { 'text-green' if report.uptime_pct >= 99.9 else 'text-red' }">{report.uptime_pct:.2f}%</div>
      <div class="kpi-sub">{len(report.outages)} outages ({report.total_outage_sec}s downtime)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Mean Latency & P95</div>
      <div class="kpi-value">{report.ping_summary.rtt_avg_ms or 0:.1f} <span style="font-size: 14px;">ms</span></div>
      <div class="kpi-sub">P95: {report.ping_summary.rtt_p95_ms or 0:.1f} ms | Jitter: {report.ping_summary.jitter_avg_ms or 0:.1f} ms</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Packet Loss Rate</div>
      <div class="kpi-value { 'text-green' if report.ping_summary.loss_pct < 0.5 else 'text-red' }">{report.ping_summary.loss_pct:.2f}%</div>
      <div class="kpi-sub">{report.ping_summary.total_lost:,} lost of {report.ping_summary.total_sent:,} packets</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Measured Downlink & Offered %</div>
      <div class="kpi-value">{report.speed_summary.avg_down_mbps or 0:.1f} <span style="font-size: 14px;">Mbps</span> <span style="font-size: 14px; color: #10b981;">({(report.speed_summary.avg_down_pct_of_offered or 0):.1f}%)</span></div>
      <div class="kpi-sub">Offered: {report.contract_down_mbps:.0f}M | Uplink: {report.speed_summary.avg_up_mbps or 0:.1f}M ({(report.speed_summary.avg_up_pct_of_offered or 0):.1f}%)</div>
    </div>
  </div>

  <!-- Latency Chart & Outages -->
  <div class="section">
    <div class="section-title">
      <span>High-Resolution Latency Timeline (RFC 2681)</span>
      <span class="text-muted" style="font-size: 12px;">Sub-second multi-target telemetry</span>
    </div>
    {svg_latency}
    <div style="margin-top: 16px;">
      <div class="section-title" style="margin-bottom: 6px; font-size: 14px;">Packet Loss Spikes</div>
      {svg_loss}
    </div>
    <div style="margin-top: 20px;">
      <h3 style="font-size: 14px; color: var(--text);">Outage Incident Log</h3>
      <table>
        <thead>
          <tr>
            <th>Start Time</th>
            <th>Resolution Time</th>
            <th>Duration</th>
            <th>Diagnostic Cause</th>
          </tr>
        </thead>
        <tbody>
          {''.join(outage_rows_html)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Multi-target Ping Breakdown -->
  <div class="section">
    <div class="section-title">Target Node Latency Breakdown</div>
    <table>
      <thead>
        <tr>
          <th>Target Node</th>
          <th>Sent</th>
          <th>Lost</th>
          <th>Loss Rate</th>
          <th>Avg RTT</th>
          <th>P95 RTT</th>
        </tr>
      </thead>
      <tbody>
        {''.join(target_rows_html)}
      </tbody>
    </table>
  </div>

  <!-- Bandwidth & SLA Section -->
  <div class="section">
    <div class="section-title">
      <span>Bandwidth Throughput vs Contract SLA</span>
      <span class="text-muted" style="font-size: 12px;">Idle-enforced Ookla / CDN verification</span>
    </div>
    {svg_speed}
    <div style="margin-top: 20px;">
      <h3 style="font-size: 14px; color: var(--text);">Speedtest Audit Log</h3>
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Status</th>
            <th>Access Tech</th>
            <th>Nyilvános IP</th>
            <th>Download (% Offered)</th>
            <th>Upload (% Offered)</th>
            <th>Ping</th>
            <th>Bufferbloat</th>
            <th>Tesztszerver (Név & Cím)</th>
            <th>Speedtest Link</th>
          </tr>
        </thead>
        <tbody>
          {''.join(speed_rows_html)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Net-Neutrality Port Throttling Section -->
  <div class="section">
    <div class="section-title">
      <span>Net-Neutrality & Traffic-Shaping Audit</span>
      <span class="{ 'text-green' if report.throttled_ports_count == 0 else 'text-red' }" style="font-size: 12px;">
        {report.throttled_ports_count} throttled/blocked ports detected
      </span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Port & Protocol</th>
          <th>Reference Endpoint</th>
          <th>Achievable Throughput</th>
          <th>Ratio vs Baseline (443)</th>
          <th>Traffic Verdict</th>
        </tr>
      </thead>
      <tbody>
        {''.join(port_rows_html)}
      </tbody>
    </table>
  </div>

  <!-- Appendix -->
  <div class="appendix">
    <strong>Technical Escalation & Verification Methodology Notice:</strong><br>
    This dossier was compiled autonomously by NetworkMeasureBox firmware running locally on-premises at the subscriber boundary.
    Latency measurements are conducted sub-second via native ICMP Echo requests across disparate neutral routing backbones.
    Bandwidth speedtests are executed strictly during traffic-gated periods (&lt;500 kbps background consumption) to preclude local LAN contention.
    All timestamps are recorded in UTC. This document represents admissible technical telemetry for customer support escalations, billing disputes, and regulatory complaints.
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
