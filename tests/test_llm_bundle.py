"""
Unit tests for nmb.report.llm_bundle.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from nmb.config import Config
from nmb.db import database as db
from nmb.report.llm_bundle import (
    _get_cpu_and_thermal_telemetry,
    _get_phy_and_ethtool,
    _get_wifi_phy_telemetry,
    _get_nat_and_stun_telemetry,
    _get_dns_telemetry_matrix,
    _sanitize_config_text,
    generate_llm_diagnostic_bundle,
)


class TestLLMBundle(unittest.TestCase):

    def test_cpu_and_thermal_telemetry(self):
        res = _get_cpu_and_thermal_telemetry()
        self.assertIn("hardware_model", res)
        self.assertIn("soc_model", res)
        self.assertIn("userland_bitness", res)
        self.assertIn("disk_free_gb", res)
        self.assertIn("disk_total_gb", res)
        self.assertIn("disk_free_pct", res)
        self.assertIn("iowait_pct", res)
        self.assertIn("dmesg_io_errors", res)

    def test_phy_and_ethtool(self):
        res = _get_phy_and_ethtool("lo")
        self.assertIn("rps_cpus", res)
        self.assertIn("xps_cpus", res)
        self.assertIn("irqbalance_status", res)
        self.assertIn("offload_info", res)

    def test_wifi_phy_telemetry(self):
        res = _get_wifi_phy_telemetry("wlan0")
        self.assertIn("rssi_dbm", res)
        self.assertIn("rx_bitrate", res)
        self.assertIn("tx_bitrate", res)
        self.assertIn("tx_failed", res)
        self.assertIn("tx_retries", res)
        self.assertIn("missed_beacons", res)

    def test_nat_and_stun_classification(self):
        # Test Double NAT detection
        d_nat = _get_nat_and_stun_telemetry(
            local_ip="192.168.1.100",
            gateway_ip="192.168.1.1",
            hop2_ip="10.0.0.1",
            http_public_ip="198.51.100.55"
        )
        # A private hop 2 is a second router OR the ISP's point-to-point / PPP peer: only "possible"
        # (it said "Double NAT Detected" behind a router that dials PPPoE itself, 2026-11-10).
        self.assertIsNone(d_nat["is_double_nat"])
        self.assertFalse(d_nat["is_cgnat"])
        self.assertIn("Possibly double NAT", d_nat["verdict"])

        # A hop 2 that is a known PPP peer placeholder is not a NAT at all
        peer = _get_nat_and_stun_telemetry(
            local_ip="192.168.1.100", gateway_ip="192.168.1.1", hop2_ip="10.0.0.1",
            http_public_ip="198.51.100.55", ppp_peers=["10.0.0.1"])
        self.assertIs(peer["is_double_nat"], False)
        self.assertIn("PPP peer", peer["verdict"])

        # Test CGNAT detection
        cgnat = _get_nat_and_stun_telemetry(
            local_ip="192.168.1.50",
            gateway_ip="192.168.1.1",
            hop2_ip="100.64.0.1",
            http_public_ip="198.51.100.55"
        )
        self.assertTrue(cgnat["is_cgnat"])
        self.assertIn("carrier-grade NAT", cgnat["verdict"])

        # Test Clean Single NAT
        clean = _get_nat_and_stun_telemetry(
            local_ip="192.168.1.50",
            gateway_ip="192.168.1.1",
            hop2_ip="93.184.216.1",
            http_public_ip="93.184.216.34"
        )
        self.assertFalse(clean["is_cgnat"])
        self.assertFalse(clean["is_double_nat"])

    def test_dns_telemetry_matrix(self):
        # Test querying resolvers without throwing exception
        matrix = _get_dns_telemetry_matrix(gateway_ip="127.0.0.1")
        self.assertEqual(len(matrix), 4)
        for entry in matrix:
            self.assertIn("ip", entry)
            self.assertIn("label", entry)
            self.assertIn("role", entry)
            self.assertIn("ad_flag", entry)
            self.assertIn("status", entry)

    def test_config_sanitization(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(
                "[isp]\n"
                "account_id = ACC-DUMMY-99\n"
                "circuit_id = CKT-DUMMY-01\n"
                "secret_key = SuperSecret123\n"
                "[telegram]\n"
                "token = 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11\n"
                "allowed_chat_ids = 999888777\n"
                "[duckdns]\n"
                "domain = example-box.duckdns.org\n"
                "token = abcd-ef01-2345\n"
            )
            f_path = Path(f.name)

        try:
            sanitized = _sanitize_config_text(f_path)
            self.assertNotIn("SuperSecret123", sanitized)
            self.assertNotIn("999888777", sanitized)
            self.assertNotIn("ACC-DUMMY-99", sanitized)
            self.assertNotIn("CKT-DUMMY-01", sanitized)
            self.assertNotIn("example-box.duckdns.org", sanitized)
            self.assertIn("[REDACTED_SECRET]", sanitized)
            self.assertIn("[REDACTED_CHAT_ID]", sanitized)
            self.assertIn("[REDACTED_IDENTIFIER]", sanitized)
            self.assertIn("[REDACTED_DOMAIN]", sanitized)
        finally:
            f_path.unlink(missing_ok=True)

    # No GeoIP lookup over the internet and no real regulatory domain read (2026-11-10); the bundle must only
    # read, never set the domain.
    @patch("nmb.netd.geoip.set_wifi_regulatory_domain", side_effect=AssertionError("a report must not change the radio"))
    @patch("nmb.netd.geoip.get_wifi_regulatory_domain", return_value={"country_code": "00", "is_unset": True})
    @patch("nmb.netd.geoip.get_public_geoip", return_value={"country_code": "HU", "city": "Budapest", "isp": "Example ISP"})
    @patch("nmb.report.llm_bundle._get_detailed_mtr")
    def test_generate_llm_bundle_markdown(self, mock_mtr, _geo, _reg, _set_reg):
        mock_mtr.return_value = {
            "hubs": [
                {"count": 1, "host": "192.168.1.1", "Loss%": 0.0, "Snt": 30, "Last": 0.8, "Avg": 0.9, "Best": 0.6, "Wrst": 2.1, "StDev": 0.3},
                {"count": 2, "host": "10.0.0.1", "Loss%": 0.0, "Snt": 30, "Last": 2.1, "Avg": 2.3, "Best": 1.9, "Wrst": 4.5, "StDev": 0.5},
                {"count": 3, "host": "1.1.1.1", "Loss%": 0.0, "Snt": 30, "Last": 6.2, "Avg": 6.5, "Best": 6.0, "Wrst": 8.1, "StDev": 0.4},
            ],
            "raw": "HOST: speedtest  Loss%   Snt   Last   Avg  Best  Wrst StDev\n  1.|-- 192.168.1.1  0.0%    30    0.8   0.9   0.6   2.1   0.3",
            "target": "1.1.1.1",
            "cycles": 30,
        }
        cfg = Config()
        # Use a fresh database with the schema, never the box's own one.
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.db"
            conn = db.connect(live)
            db.init(conn)
            conn.close()
            with patch.dict(os.environ, {"NMB_LIVE_DB": str(live), "NMB_PERSIST_DB": str(Path(tmp) / "persist.db")}):
                bundle = generate_llm_diagnostic_bundle(cfg, force_refresh=True)
        self.assertIn("# NetworkMeasureBox - Comprehensive AI Diagnostic Bundle", bundle)
        self.assertIn("## 1. Operating System, Hardware & Thermal Telemetry", bundle)
        self.assertIn("## 2. Physical Link Layer & Interface Error Telemetry", bundle)
        self.assertIn("### 2.4 NIC Offloads & CPU Interrupt Steering", bundle)
        self.assertIn("## 3. Path MTU Discovery (PMTU) & NAT / CGNAT Topology", bundle)
        self.assertIn("## 4. Network Interfaces & IP Configuration", bundle)
        self.assertIn("### 4.1 Standalone Guest Wi-Fi Client Probe", bundle)
        self.assertIn("## 6. DNS Resolver & Multi-Server Benchmark", bundle)
        self.assertIn("### 6.1 Multi-Resolver DNS Benchmark & Hijacking Audit", bundle)
        self.assertIn("## 7. Latest Speed & Quality Measurement", bundle)
        self.assertIn("## 8. Continuous Ping Probe Telemetry & Loss Pattern Isolation", bundle)
        self.assertIn("## 9. Hop-by-Hop Multi-Sample MTR Path Telemetry", bundle)
        self.assertIn("## 10. LAN vs WAN Performance Isolation & iPerf3 Benchmark", bundle)
        self.assertIn("## 11. Active Queue Discipline", bundle)
        self.assertIn("## 14. Recent Warnings, Outages and the Box's Own Actions", bundle)
        self.assertIn("## 15. Sanitized Configuration", bundle)

        # Check that Section 9 guidance has no Hungarian leftover text
        self.assertNotIn("Ha az 1. vagy 2. ugrásnál", bundle)
        self.assertNotIn("vezérlősíkjának ICMP", bundle)
        self.assertIn("Diagnostic Guidance for LLM", bundle)
        self.assertIn("Control Plane Rate-Limiting", bundle)


if __name__ == "__main__":
    unittest.main()
