"""Unit tests for headless device features:
- Deep invasive diagnostics logger & boot drive snapshot
- Strict wired Ethernet interface prioritization
- Ookla anti-ban, server quarantine & circuit breaker fallback
- User-Agent headless client generator
"""
import unittest
import unittest.mock as mock
from pathlib import Path

from nmb.config import load_config
from nmb.common.user_agent import (
    generate_fresh_user_agent,
    get_effective_user_agent,
    list_user_agent_presets,
)
from nmb.netd.interfaces import (
    is_wired_interface,
    find_active_wired_interface,
    find_preferred_measurement_interface,
)
from nmb.speed.anti_ban import (
    is_ookla_ban_error,
    quarantine_server,
    is_server_quarantined,
    get_quarantined_servers,
    clear_quarantine,
    get_smart_rotated_server,
)
from nmb.report.invasive_logger import (
    generate_invasive_snapshot,
    read_latest_invasive_snapshot_file,
    get_cached_invasive_snapshot,
)


class TestHeadlessFeatures(unittest.TestCase):
    def setUp(self):
        clear_quarantine()

    def tearDown(self):
        clear_quarantine()

    def test_user_agent_generation(self):
        ua_chrome = generate_fresh_user_agent("desktop_chrome")
        self.assertIn("Chrome/", ua_chrome)
        self.assertIn("Mozilla/5.0", ua_chrome)

        ua_firefox = generate_fresh_user_agent("desktop_firefox")
        self.assertIn("Firefox/", ua_firefox)

        ua_headless = generate_fresh_user_agent("headless_client")
        self.assertIn("HeadlessChrome/", ua_headless)

        presets = list_user_agent_presets()
        self.assertGreaterEqual(len(presets), 5)

    def test_wired_interface_prioritization(self):
        # Ethernet interface name identification
        self.assertTrue(is_wired_interface("eth0"))
        self.assertTrue(is_wired_interface("enp3s0"))
        self.assertTrue(is_wired_interface("eno1"))
        self.assertFalse(is_wired_interface("wlan0"))
        self.assertFalse(is_wired_interface("wlp4s0"))
        self.assertFalse(is_wired_interface("lo"))
        self.assertFalse(is_wired_interface("docker0"))

        cfg = load_config()

        # When wired Ethernet cable is connected, it MUST override wireless/config
        cfg.network.wan_interface = "wlan0"  # Even if config points to wlan0
        with mock.patch("nmb.netd.interfaces.find_active_wired_interface", return_value=("eth0", "192.168.1.50")):
            iface, ip, is_wired = find_preferred_measurement_interface(cfg)
            self.assertEqual(iface, "eth0")
            self.assertEqual(ip, "192.168.1.50")
            self.assertTrue(is_wired)

        # When no wired cable is connected, uses configured/wireless interface
        with mock.patch("nmb.netd.interfaces.find_active_wired_interface", return_value=None):
            with mock.patch("nmb.netd.interfaces.interface_exists", side_effect=lambda x: x == "wlan0"):
                with mock.patch("nmb.netd.interfaces.get_ip_addresses", return_value=["192.168.4.10/24"]):
                    iface, ip, is_wired = find_preferred_measurement_interface(cfg)
                    self.assertEqual(iface, "wlan0")
                    self.assertEqual(ip, "192.168.4.10")
                    self.assertFalse(is_wired)

    def test_ookla_anti_ban_and_quarantine(self):
        # 1. Detection of rate-limits and bans
        ban_msgs = [
            "HTTP 429 Too Many Requests",
            "Rate limit exceeded: client throttled",
            "Configuration - Could not retrieve speedtest configuration",
            "Selection failed",
            "Connection refused by server",
        ]
        for msg in ban_msgs:
            is_ban, reason = is_ookla_ban_error(msg)
            self.assertTrue(is_ban, f"Failed to detect ban in: {msg}")

        ok_msgs = [
            "Connection timed out",
            "DNS lookup failed",
        ]
        for msg in ok_msgs:
            is_ban, _ = is_ookla_ban_error(msg)
            self.assertFalse(is_ban, f"False positive ban detection for: {msg}")

        # 2. Quarantine operations
        quarantine_server(9999, duration_sec=3600, reason="HTTP 429")
        self.assertTrue(is_server_quarantined(9999))
        quarantined = get_quarantined_servers()
        self.assertIn(9999, quarantined)
        self.assertGreater(quarantined[9999], 0)

        # 3. Smart server rotation bypasses quarantined servers
        mock_fleet = [
            {"id": 9999, "name": "Banned Server", "host": "banned.net"},
            {"id": 1111, "name": "Healthy Server 1", "host": "srv1.net"},
            {"id": 2222, "name": "Healthy Server 2", "host": "srv2.net"},
        ]
        with mock.patch("nmb.speed.ookla.get_available_servers", return_value=mock_fleet):
            # Target server is quarantined -> picks healthy alternative
            chosen = get_smart_rotated_server(target_server_id=9999)
            self.assertIn(chosen, (1111, 2222))
            self.assertNotEqual(chosen, 9999)

        clear_quarantine()
        self.assertFalse(is_server_quarantined(9999))

    def test_invasive_diagnostic_logger(self):
        md, snap = generate_invasive_snapshot(force_write=True)
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 500)
        self.assertIn("# 🕵️ NetworkMeasureBox — Invasive Developer Diagnostic Snapshot", md)
        self.assertIn("System & Hardware Telemetry", md)
        self.assertIn("Network Interfaces & Statistics", md)
        self.assertIn("Active Sockets & Listening Ports", md)
        self.assertIn("SQLite Database Health", md)

        # Cached read
        cached_md = read_latest_invasive_snapshot_file()
        self.assertIsNotNone(cached_md)
        self.assertGreater(len(cached_md), 100)

    def test_crash_trap_and_diagnostic_bundle(self):
        from nmb.report.crash_trap import (
            format_crash_report,
            save_crash_report,
            list_crash_reports,
            clear_crash_reports,
            create_diagnostic_bundle,
        )
        import tarfile

        # 1. Test formatting crash report with local variables
        secret_token = "SUPER_SECRET_TOKEN_XYZ"
        regular_var = "diagnostic_test_value"
        try:
            raise ValueError("Deliberate test exception for crash introspection")
        except ValueError as exc:
            md, meta = format_crash_report(type(exc), exc, exc.__traceback__, thread_name="TestThread")
            self.assertIn("Fatal Crash Incident Report", md)
            self.assertIn("Deliberate test exception", md)
            self.assertIn("regular_var", md)
            self.assertIn("diagnostic_test_value", md)
            # Secret should be redacted
            self.assertNotIn("SUPER_SECRET_TOKEN_XYZ", md)
            self.assertIn("[REDACTED SECRET]", md)

            # 2. Test saving crash report
            saved = save_crash_report(md, meta)
            self.assertGreater(len(saved), 0)

            # 3. Test listing crash reports
            reports = list_crash_reports()
            self.assertGreater(len(reports), 0)
            self.assertTrue(any("crash_" in r["filename"] for r in reports))

            # 4. Test creating diagnostic bundle (.tar.gz)
            bundle = create_diagnostic_bundle()
            self.assertTrue(bundle.is_file())
            self.assertTrue(tarfile.is_tarfile(bundle))
            with tarfile.open(bundle, "r:gz") as tar:
                names = tar.getnames()
                self.assertTrue(any("diagnostics" in n for n in names))
                self.assertTrue(any("crashes" in n for n in names))

            # Clean up
            cleared = clear_crash_reports()
            self.assertGreaterEqual(cleared, 1)

    def test_enforce_wired_default_route_priority(self):
        from nmb.netd.interfaces import enforce_wired_default_route_priority

        # When no wired interface, returns False
        with mock.patch("nmb.netd.interfaces.find_active_wired_interface", return_value=None):
            self.assertFalse(enforce_wired_default_route_priority())

        # When wired interface is active and route metric > 50, adjusts route
        with mock.patch("nmb.netd.interfaces.find_active_wired_interface", return_value=("eth0", "192.168.1.10")):
            mock_ip_out = "default via 192.168.1.1 dev eth0 metric 600\ndefault via 192.168.1.1 dev wlan0 metric 100"
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    mock.Mock(stdout=mock_ip_out),  # ip route show default
                    mock.Mock(returncode=0),        # ip route replace
                ]
                res = enforce_wired_default_route_priority()
                self.assertTrue(res)
                mock_run.assert_any_call(
                    ["ip", "route", "replace", "default", "via", "192.168.1.1", "dev", "eth0", "metric", "50"],
                    check=False,
                    capture_output=True
                )


    def test_web_default_port_and_unprivileged_fallback(self):
        from nmb.config import WebConfig
        web_cfg = WebConfig()
        self.assertEqual(web_cfg.port, 80, "Default router HTTP port should be 80")

        # Test NMBServer unprivileged fallback logic
        from nmb.web.server import NMBServer
        from nmb.config import Config

        cfg = Config()
        cfg.web.port = 80
        cfg.web.host = "127.0.0.1"

        # Mock server_bind to raise PermissionError on first call (port 80), succeed on second call (port 8080)
        with mock.patch("socketserver.TCPServer.server_bind") as mock_bind, \
             mock.patch("socketserver.TCPServer.server_activate") as mock_act:
            mock_bind.side_effect = [PermissionError(13, "Permission denied"), None]
            server = NMBServer(cfg)
            self.assertEqual(server.server_address, ("127.0.0.1", 8080))
            self.assertEqual(cfg.web.port, 8080)
            self.assertEqual(mock_bind.call_count, 2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
