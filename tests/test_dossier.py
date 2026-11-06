"""Unit tests for standalone HTML dossier generator and multi-language localization."""
import unittest
from pathlib import Path
import tempfile

from nmb.report.dossier import DOSSIER_I18N, generate_html_dossier, save_html_dossier
from nmb.report.metrics import (
    OutageRecord,
    PingSummary,
    ReportData,
    SpeedtestSummary,
    TargetPingStats,
)


class TestDossierI18n(unittest.TestCase):
    def setUp(self):
        self.sample_report = ReportData(
            box_id="testbox-01",
            start_ms=1700000000000,
            end_ms=1700086400000,
            uptime_pct=99.95,
            total_outage_sec=45,
            outages=[
                OutageRecord(
                    id=1,
                    start_ts=1700010000000,
                    end_ts=1700010045000,
                    duration_sec=45,
                    cause="Upstream gateway unreachable",
                )
            ],
            target_stats=[
                TargetPingStats(
                    target_id=1,
                    addr="1.1.1.1",
                    label="Cloudflare DNS",
                    sent=1000,
                    lost=2,
                    loss_pct=0.2,
                    avg_rtt_ms=12.4,
                    p95_rtt_ms=18.6,
                )
            ],
            speed_tests=[
                {
                    "ts": 1700020000000,
                    "down_mbps": 912.4,
                    "up_mbps": 320.1,
                    "ping_us": 12400,
                    "engine": "ookla",
                    "server_name": "Telekom Edge",
                    "client_ip": "87.97.24.117",
                    "isp_name": "DIGI Kft.",
                    "status": "ok",
                    "bufferbloat_grade": "A",
                    "bufferbloat_delta_ms": 14.2,
                    "nmhh_code": 1,
                    "nmhh_desc": "Valid",
                }
            ],
            speed_summary=SpeedtestSummary(
                total_tests=1,
                successful_tests=1,
                avg_down_mbps=912.4,
                median_down_mbps=912.4,
                p95_down_mbps=912.4,
                min_down_mbps=912.4,
                max_down_mbps=912.4,
                stddev_down_mbps=0.0,
                avg_up_mbps=320.1,
                median_up_mbps=320.1,
                p95_up_mbps=320.1,
                min_up_mbps=320.1,
                max_up_mbps=320.1,
                stddev_up_mbps=0.0,
                avg_down_pct_of_offered=91.2,
                avg_up_pct_of_offered=106.7,
                avg_down_pct_of_guaranteed=304.1,
                avg_up_pct_of_guaranteed=320.1,
                sla_compliance_pct=100.0,
            ),
            ping_summary=PingSummary(
                total_sent=1000,
                total_lost=2,
                loss_pct=0.2,
                rtt_avg_ms=12.4,
                rtt_median_ms=11.9,
                rtt_p95_ms=18.6,
                rtt_min_ms=9.2,
                rtt_max_ms=45.1,
                rtt_stddev_ms=2.3,
                jitter_avg_ms=1.1,
            ),
            timeseries=[],
            port_checks=[
                {
                    "port": 443,
                    "proto": "tcp",
                    "endpoint": "probe.port443.example",
                    "bps": 50000000,
                    "ratio": 1.0,
                    "verdict": "ok",
                }
            ],
            throttled_ports_count=0,
            sla_verdict="COMPLIANT",
            contract_down_mbps=1000.0,
            contract_up_mbps=300.0,
            guaranteed_down_mbps=300.0,
            guaranteed_up_mbps=100.0,
            isp_name="DIGI Kft.",
            isp_connection_type="ftth",
            account_id="ACC-9988",
            circuit_id="CR-1122",
        )

    def test_all_languages_supported(self):
        for lang in ("hu", "en", "de", "fr", "uk"):
            html = generate_html_dossier(self.sample_report, lang=lang)
            self.assertIn(f'<html lang="{lang}">', html)
            self.assertIn(DOSSIER_I18N[lang]["header_title"], html)
            self.assertIn("DIGI Kft.", html)
            self.assertIn("testbox-01", html)

    def test_neutral_branding(self):
        """Report title should not claim to be the official government body NMHH in title."""
        for lang in ("hu", "en", "de", "fr", "uk"):
            html = generate_html_dossier(self.sample_report, lang=lang)
            self.assertNotIn("Nemzeti Média- és Hírközlési Hatóság (NMHH) & Szélessáv.net Riport", html)
            self.assertIn(DOSSIER_I18N[lang]["header_title"], html)

    def test_no_hungarian_leakage_in_foreign_languages(self):
        """English, German, French, and Ukrainian dossiers must not contain untranslated Hungarian terms."""
        for lang in ("en", "de", "fr", "uk"):
            html = generate_html_dossier(self.sample_report, lang=lang)
            self.assertNotIn("MÉRŐPONT:", html)
            self.assertNotIn("Helyhez kötött", html)
            self.assertNotIn("Garantált Letöltés", html)
            self.assertNotIn("Kínált (Névleges)", html)
            self.assertNotIn("Értékelési időablak:", html)
            self.assertNotIn("SZERZŐDÉSSZERŰ MŰKÖDÉS", html)
            self.assertNotIn("Csomagvesztés Aránya", html)

    def test_unconfigured_contract_speeds_no_zero_mbps(self):
        """When speeds are 0 or unconfigured, it must not display '0 Mb/s' or '0% teljesülés'."""
        unconfigured_report = ReportData(
            box_id="testbox-02",
            start_ms=1700000000000,
            end_ms=1700086400000,
            uptime_pct=100.0,
            total_outage_sec=0,
            outages=[],
            target_stats=[],
            speed_tests=[],
            speed_summary=SpeedtestSummary(
                total_tests=0,
                successful_tests=0,
                avg_down_mbps=0.0,
                median_down_mbps=0.0,
                p95_down_mbps=0.0,
                min_down_mbps=0.0,
                max_down_mbps=0.0,
                stddev_down_mbps=0.0,
                avg_up_mbps=0.0,
                median_up_mbps=0.0,
                p95_up_mbps=0.0,
                min_up_mbps=0.0,
                max_up_mbps=0.0,
                stddev_up_mbps=0.0,
                avg_down_pct_of_offered=0.0,
                avg_up_pct_of_offered=0.0,
                avg_down_pct_of_guaranteed=0.0,
                avg_up_pct_of_guaranteed=0.0,
                sla_compliance_pct=0.0,
            ),
            ping_summary=PingSummary(
                total_sent=0,
                total_lost=0,
                loss_pct=0.0,
                rtt_avg_ms=0.0,
                rtt_median_ms=0.0,
                rtt_p95_ms=0.0,
                rtt_min_ms=0.0,
                rtt_max_ms=0.0,
                rtt_stddev_ms=0.0,
                jitter_avg_ms=0.0,
            ),
            timeseries=[],
            port_checks=[],
            throttled_ports_count=0,
            sla_verdict="COMPLIANT",
            contract_down_mbps=0.0,
            contract_up_mbps=0.0,
            guaranteed_down_mbps=0.0,
            guaranteed_up_mbps=0.0,
            isp_name="Generic ISP",
            isp_connection_type="unknown",
            account_id="",
            circuit_id="",
        )

        for lang in ("hu", "en", "de", "fr", "uk"):
            html = generate_html_dossier(unconfigured_report, lang=lang)
            # Must NOT display misleading 0 Mb/s cards
            self.assertNotIn("0 Mb/s", html)
            self.assertNotIn("Garantált teljesülése: 0%", html)
            # Must contain the unconfigured notice
            self.assertIn(DOSSIER_I18N[lang]["unconfigured_speeds_notice"], html)

    def test_save_html_dossier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "dossier.html"
            res = save_html_dossier(self.sample_report, out_path, lang="en")
            self.assertTrue(res.exists())
            text = res.read_text(encoding="utf-8")
            self.assertIn("Broadband Quality", text)


if __name__ == "__main__":
    unittest.main()
