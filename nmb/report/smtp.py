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


def format_plain_text_summary(report: ReportData) -> str:
    """Format technical plain-text message for ISP ticket systems."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    down_pct_str = f" ({report.speed_summary.avg_down_pct_of_offered:.1f}% of offered plan)" if getattr(report.speed_summary, "avg_down_pct_of_offered", None) is not None else ""
    up_pct_str = f" ({report.speed_summary.avg_up_pct_of_offered:.1f}% of offered plan)" if getattr(report.speed_summary, "avg_up_pct_of_offered", None) is not None else ""

    text = f"""*** ISP SERVICE SLA FAULT TICKET & TECHNICAL ESCALATION NOTICE ***

Customer Account ID : {report.account_id}
Circuit Reference   : {report.circuit_id}
Service Provider    : {report.isp_name}
Subscribed SLA Plan : {report.contract_down_mbps:.0f} Mbps Down / {report.contract_up_mbps:.0f} Mbps Up
Measurement Window  : Past {(report.end_ms - report.start_ms) // 3600000} Hours
Telemetry Timestamp : {now_str}
Hardware Unit ID    : {report.box_id}

================================================================================
EXECUTIVE TELEMETRY VERDICT: {report.sla_verdict}
================================================================================

1. AVAILABILITY & OUTAGES:
   - Measured Uptime         : {report.uptime_pct:.2f}%
   - Total Down Time         : {report.total_outage_sec} seconds
   - Total Outage Incidents  : {len(report.outages)}

2. LATENCY & PACKET LOSS (RFC 2681 / RFC 3550):
   - Overall Packet Loss     : {report.ping_summary.loss_pct:.2f}% ({report.ping_summary.total_lost} lost / {report.ping_summary.total_sent} sent)
   - Minimum Latency         : {report.ping_summary.rtt_min_ms or 'N/A'} ms
   - Mean Latency (RTT)      : {report.ping_summary.rtt_avg_ms or 'N/A'} ms
   - 95th Percentile (P95)   : {report.ping_summary.rtt_p95_ms or 'N/A'} ms
   - Mean Jitter             : {report.ping_summary.jitter_avg_ms or 'N/A'} ms

3. MEASURED BANDWIDTH & SLA COMPLIANCE:
   - Average Downlink        : {report.speed_summary.avg_down_mbps or 'N/A'} Mbps (Offered: {report.contract_down_mbps:.0f} Mbps{down_pct_str})
   - Average Uplink          : {report.speed_summary.avg_up_mbps or 'N/A'} Mbps (Offered: {report.contract_up_mbps:.0f} Mbps{up_pct_str})
   - SLA Speed Compliance    : {report.speed_summary.sla_compliance_pct:.0f}% of tests met required 80% SLA threshold

4. NET-NEUTRALITY & TRAFFIC SHAPING:
   - Throttled/Blocked Ports : {report.throttled_ports_count} detected

--------------------------------------------------------------------------------
NOTE FOR TICKET HANDLING TECHNICIAN:
This report was generated autonomously by customer-premises monitoring equipment.
Bandwidth tests are strictly executed under traffic-gated idle LAN conditions
(<500 kbps) to ensure measurements accurately reflect ISP edge/transit performance.
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
    plain_text = format_plain_text_summary(report)
    html_content = generate_html_dossier(report)

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
            pass

        log.info("successfully sent fault ticket email")
        return True
    except Exception as e:
        log.error("failed to send SMTP email: %s", e)
        return False
