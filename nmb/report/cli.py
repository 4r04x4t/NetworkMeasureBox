"""CLI tool for generating reports, exporting CSVs, and dispatching ISP fault emails.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from nmb.config import load_config
from nmb.db import database as db
from nmb.report.csv_export import export_all_csvs
from nmb.report.dossier import generate_html_dossier, save_html_dossier
from nmb.report.metrics import aggregate_report_data
from nmb.report.smtp import send_isp_ticket_email

log = logging.getLogger("nmb.report")


def parse_window_hours(val: str) -> float:
    val = val.strip().lower()
    if val.endswith("d"):
        return float(val[:-1]) * 24.0
    if val.endswith("h"):
        return float(val[:-1])
    return float(val)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nmb-report",
        description="NetworkMeasureBox HTML dossier generator and ISP fault ticket dispatcher"
    )
    parser.add_argument("--config", "-c", help="Path to nmb.conf")
    parser.add_argument("--window", "-w", default="24h", help="Timeframe window (e.g. 24h, 7d, 30d)")
    parser.add_argument("--html", type=Path, help="Save standalone HTML dossier to specified path")
    parser.add_argument("--csv-dir", type=Path, help="Export raw CSV telemetry files into directory")
    parser.add_argument("--send-email", action="store_true", help="Dispatch ISP fault ticket email via SMTP")
    parser.add_argument("--to", help="Comma-separated recipient emails (overrides config)")
    parser.add_argument("--json-summary", action="store_true", help="Print aggregated metrics as JSON to stdout")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    cfg = load_config(args.config)
    hours = parse_window_hours(args.window)

    conn = db.connect()
    report = aggregate_report_data(conn, cfg, window_hours=hours)

    if args.json_summary:
        summary_dict = {
            "window_hours": hours,
            "verdict": report.sla_verdict,
            "uptime_pct": report.uptime_pct,
            "total_outage_sec": report.total_outage_sec,
            "outages_count": len(report.outages),
            "ping": {
                "loss_pct": report.ping_summary.loss_pct,
                "avg_rtt_ms": report.ping_summary.rtt_avg_ms,
                "p95_rtt_ms": report.ping_summary.rtt_p95_ms,
                "jitter_ms": report.ping_summary.jitter_avg_ms,
            },
            "speed": {
                "avg_down_mbps": report.speed_summary.avg_down_mbps,
                "avg_up_mbps": report.speed_summary.avg_up_mbps,
                "sla_compliance_pct": report.speed_summary.sla_compliance_pct,
            },
            "throttled_ports": report.throttled_ports_count,
        }
        print(json.dumps(summary_dict, indent=2))

    if args.html:
        save_html_dossier(report, args.html)
        print(f"HTML dossier saved: {args.html}")

    if args.csv_dir:
        files = export_all_csvs(conn, args.csv_dir, window_hours=hours)
        print(f"Exported {len(files)} CSV files into {args.csv_dir}")

    # Default action if neither html nor csv nor json requested: write to default reports dir
    if not args.html and not args.csv_dir and not args.json_summary and not args.send_email:
        default_dir = cfg.system.data_dir / "persist" / "reports"
        default_html = default_dir / f"dossier_{int(hours)}h.html"
        save_html_dossier(report, default_html)
        print(f"HTML dossier generated: {default_html}")

    if args.send_email:
        recipients = [a.strip() for a in args.to.split(",") if a.strip()] if args.to else None
        ok = send_isp_ticket_email(cfg, report, recipients)
        if ok:
            print("ISP fault ticket email successfully dispatched.")
        else:
            print("Failed to dispatch email (check SMTP configuration).", file=sys.stderr)
            conn.close()
            return 1

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
