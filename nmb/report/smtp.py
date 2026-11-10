"""Automated SMTP dispatch system formatted specifically for ISP fault tickets.

Constructs multipart emails with plain-text summaries, embedded HTML dossiers,
and attached CSV telemetry files. Pure Python standard library (smtplib, email).
"""
from __future__ import annotations

import datetime
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from nmb.config import Config
from nmb.db import database as db
from nmb.report.csv_export import export_ping_summary_csv
from nmb.report.dossier import generate_html_dossier
from nmb.report.metrics import ReportData

log = logging.getLogger("nmb.report.smtp")


def _mbps_or_unset(v) -> str:
    return f"{v:.0f} Mbps" if v else "not set"


def _gate_text(cfg) -> str:
    """What the traffic gate really does with these settings (the text claimed "<500 kbps" for every box)."""
    sp = getattr(cfg, "speedtest", None) if cfg is not None else None
    if sp is None:
        return "Bandwidth tests wait for the LAN to be idle before they start."
    if getattr(sp, "idle_threshold_mode", "percent") == "fixed":
        limit = f"below {int(getattr(sp, 'idle_threshold_kbps', 500))} kbps of other traffic"
    else:
        limit = f"below {getattr(sp, 'idle_threshold_percent', 2.0):g} % of the line's speed in other traffic"
    stop = (" and stop when other traffic appears" if getattr(sp, "traffic_stop_enabled", False)
            else "; traffic that starts during a test is not stopped")
    return (f"Scheduled bandwidth tests start only when the traffic the box can see is {limit}{stop}; "
            "tests started by hand (Web UI, Telegram, remote) start at once. Traffic the box cannot see, "
            "such as devices behind another router, is not excluded.")


def format_plain_text_summary(report: ReportData, cfg=None) -> str:
    """Format technical plain-text message for ISP ticket systems."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    down_pct_str = f" ({report.speed_summary.avg_down_pct_of_offered:.1f}% of offered plan)" if getattr(report.speed_summary, "avg_down_pct_of_offered", None) is not None else ""
    up_pct_str = f" ({report.speed_summary.avg_up_pct_of_offered:.1f}% of offered plan)" if getattr(report.speed_summary, "avg_up_pct_of_offered", None) is not None else ""

    text = f"""*** ISP SERVICE SLA FAULT TICKET & TECHNICAL ESCALATION NOTICE ***

Customer Account ID : {report.account_id}
Circuit Reference   : {report.circuit_id}
Service Provider    : {report.isp_name}
Subscribed SLA Plan : {_mbps_or_unset(report.contract_down_mbps)} Down / {_mbps_or_unset(report.contract_up_mbps)} Up
Measurement Window  : Past {(report.end_ms - report.start_ms) // 3600000} Hours
Telemetry Timestamp : {now_str}
Hardware Unit ID    : {report.box_id}

================================================================================
EXECUTIVE TELEMETRY VERDICT: {report.sla_verdict}
================================================================================

1. AVAILABILITY & OUTAGES:
   - Measured Uptime         : {f"{report.uptime_pct:.2f}%" if report.uptime_known else "N/A (no ping measured)"}
   - Total Down Time         : {report.total_outage_sec} seconds
   - Total Outage Incidents  : {len(report.outages)}

2. LATENCY & PACKET LOSS (RFC 2681 / RFC 3550):
   - Overall Packet Loss     : {f"{report.ping_summary.loss_pct:.2f}%" if report.ping_summary.total_sent else "N/A"} ({report.ping_summary.total_lost} lost / {report.ping_summary.total_sent} sent)
   - Minimum Latency         : {report.ping_summary.rtt_min_ms or 'N/A'} ms
   - Mean Latency (RTT)      : {report.ping_summary.rtt_avg_ms or 'N/A'} ms
   - 95th Percentile (P95)   : {report.ping_summary.rtt_p95_ms or 'N/A'} ms
   - Mean Jitter             : {report.ping_summary.jitter_avg_ms or 'N/A'} ms

3. MEASURED BANDWIDTH & SLA COMPLIANCE:
   - Average Downlink        : {f"{report.speed_summary.avg_down_mbps} Mbps" if report.speed_summary.avg_down_mbps is not None else "N/A"} (Offered: {_mbps_or_unset(report.contract_down_mbps)}{down_pct_str})
   - Average Uplink          : {f"{report.speed_summary.avg_up_mbps} Mbps" if report.speed_summary.avg_up_mbps is not None else "N/A"} (Offered: {_mbps_or_unset(report.contract_up_mbps)}{up_pct_str})
   - SLA Speed Compliance    : {f"{report.speed_summary.sla_compliance_pct:.0f}%" if report.speed_summary.judged_tests else "N/A"} of tests reached the required speed ({"the guaranteed speed" if (report.guaranteed_down_mbps or report.guaranteed_up_mbps) else "80 % of the offered speed, NMB's rule"})

4. NET-NEUTRALITY & TRAFFIC SHAPING:
   - Throttled/Blocked Ports : {report.throttled_ports_count} detected

--------------------------------------------------------------------------------
NOTE FOR TICKET HANDLING TECHNICIAN:
This report was generated autonomously by customer-premises monitoring equipment.
{_gate_text(cfg)}
Tests against a server on the local network are not counted for the line.
Full standalone HTML telemetry dossier and raw CSV telemetry are attached.
--------------------------------------------------------------------------------
"""
    return text


def send_isp_ticket_email(
    cfg: Config,
    report: ReportData,
    recipients: Optional[List[str]] = None,
) -> bool:
    """Send formatted fault ticket report via SMTP with attached HTML and CSV."""
    if not cfg.smtp.enabled:
        log.warning("SMTP dispatch skipped: smtp.enabled is false in configuration")
        return False

    to_addrs = recipients or cfg.smtp.to_addrs
    if not to_addrs:
        log.error("SMTP dispatch failed: no recipient addresses specified")
        return False

    subject = f"[FAULT TICKET] {report.sla_verdict} - Account: {report.account_id} - Circuit: {report.circuit_id} - {report.isp_name}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = cfg.smtp.from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = smtplib.email.utils.formatdate(localtime=False)

    # 1. Plain text & HTML body
    plain_text = format_plain_text_summary(report, cfg)
    html_content = generate_html_dossier(report, lang=getattr(cfg.web, "language", "en"))

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(plain_text, "plain", "utf-8"))
    alt_part.attach(MIMEText(html_content, "html", "utf-8"))
    msg.attach(alt_part)

    # 2. Attach standalone HTML file
    html_attach = MIMEApplication(html_content.encode("utf-8"), _subtype="html")
    html_attach.add_header("Content-Disposition", "attachment", filename=f"telemetry_dossier_{report.account_id}.html")
    msg.attach(html_attach)

    # 3. Attach CSV telemetry
    try:
        conn = db.connect(readonly=True)
        csv_text = export_ping_summary_csv(conn, report.start_ms, report.end_ms)
        conn.close()
        csv_attach = MIMEApplication(csv_text.encode("utf-8"), _subtype="csv")
        csv_attach.add_header("Content-Disposition", "attachment", filename=f"ping_telemetry_{report.account_id}.csv")
        msg.attach(csv_attach)
    except Exception as e:
        log.warning("could not attach CSV to email: %s", e)

    # 4. Dispatch via SMTP
    try:
        log.info("dispatching fault ticket email to %s via %s:%d",
                 ", ".join(to_addrs), cfg.smtp.host, cfg.smtp.port)

        server = smtplib.SMTP(cfg.smtp.host, cfg.smtp.port, timeout=30)
        if cfg.smtp.tls:
            server.starttls()
        if cfg.smtp.user and cfg.smtp.password:
            server.login(cfg.smtp.user, cfg.smtp.password)

        server.send_message(msg)
        server.quit()

        # Log event to database
        try:
            conn = db.connect()
            with db.tx(conn):
                conn.execute(
                    "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'report', 'email_dispatched', ?)",
                    (db.now_ms(), f"Dispatched fault ticket to {', '.join(to_addrs)}")
                )
            conn.close()
        except Exception:
            log.debug("suppressed exception", exc_info=True)

        log.info("successfully sent fault ticket email")
        return True
    except Exception as e:
        log.error("failed to send SMTP email: %s", e)
        return False
