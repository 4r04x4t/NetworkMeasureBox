"""Regressions found by testing a clean install with every setting."""
import tempfile
import unittest
from pathlib import Path

from nmb.config import load_config, save_config
from nmb.netd import duckdns, explorer

ROOT = Path(__file__).resolve().parent.parent


def _config_with(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
    handle.write(text)
    handle.close()
    return Path(handle.name)


class ConfigResilienceTest(unittest.TestCase):
    def test_percent_sign_survives_save_and_load(self):
        path = _config_with("[isp]\nname = 100%net\n[web]\nadmin_password = a%b\n")
        cfg = load_config(path)
        self.assertEqual(cfg.isp.name, "100%net")
        self.assertTrue(save_config(cfg, path))
        self.assertEqual(load_config(path).web.admin_password, "a%b")

    def test_invalid_values_fall_back_to_defaults(self):
        path = _config_with("[probe]\nsocket_buffer_kb = abc\nbatch_flush_sec = x\n[smtp]\nenabled = maybe\n")
        cfg = load_config(path)
        self.assertEqual(cfg.probe.socket_buffer_kb, 256)
        self.assertEqual(cfg.probe.batch_flush_sec, 10.0)
        self.assertFalse(cfg.smtp.enabled)

    def test_unused_gate_settings_are_gone(self):
        self.assertNotIn("sample_window_sec", (ROOT / "config/nmb.conf.example").read_text())


class ImportsTest(unittest.TestCase):
    def test_ipv6_route_check_does_not_hit_a_missing_import(self):
        self.assertTrue(hasattr(duckdns, "socket"))
        self.assertTrue(hasattr(explorer, "os"))


class FactoryResetSafetyTest(unittest.TestCase):
    def test_cli_needs_explicit_confirmation(self):
        import subprocess
        import os
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        for args, code in (([], 2), (["--help"], 0), (["--keep-db"], 2)):
            run = subprocess.run([str(ROOT / "bin/nmb-factory-reset"), *args], capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, code)
            self.assertIn("Usage", run.stdout)

    def test_factory_settings_have_a_unique_wifi_password(self):
        from nmb.common.backup import _factory_config_text
        text = _factory_config_text()
        self.assertNotIn("NetworkMeasureBox123", text)
        self.assertNotEqual(text, _factory_config_text())

    def test_web_reset_requires_confirmation(self):
        self.assertIn('body_json.get("confirm") != "RESET"', (ROOT / "nmb/web/server.py").read_text())


class LogFindingsTest(unittest.TestCase):
    def test_self_heal_callers_use_the_real_signature(self):
        for path in ("nmb/bot/commands.py", "nmb/bot/alerts.py"):
            self.assertNotIn("auto_heal_all(self.cfg", (ROOT / path).read_text())

    def test_update_verification_is_isolated_and_has_time(self):
        source = (ROOT / "nmb/common/heal.py").read_text()
        self.assertIn("NMB_LIVE_DB=", source)
        self.assertIn("timeout=300", source)


class StopSwitchCoverageTest(unittest.TestCase):
    def test_blind_box_does_not_confirm_idle(self):
        from unittest.mock import patch
        from nmb.config import load_config
        from nmb.probe import cross_traffic
        blind = cross_traffic.ForeignTrafficMonitor("eth0", [], None)
        with patch.object(cross_traffic.ForeignTrafficMonitor, "for_config", return_value=blind):
            self.assertFalse(cross_traffic.network_confirmed_idle(load_config(ROOT / "config/nmb.conf.example")))


class SkippedTestDisplayTest(unittest.TestCase):
    def test_skipped_runs_do_not_replace_real_results(self):
        from nmb.report.metrics import latest_measured_test, tests_for_display
        tests = [{"ts": 100 - i, "status": "skipped_busy"} for i in range(40)] + [{"ts": 10, "status": "ok", "down_bps": 9}]
        self.assertEqual(latest_measured_test(tests)["down_bps"], 9)
        self.assertIsNone(latest_measured_test(tests[:40]))
        shown = tests_for_display(tests)
        self.assertEqual(len(shown), 6)
        self.assertIn(tests[-1], shown)


class IperfPortCheckTest(unittest.TestCase):
    def test_listening_port_is_found_without_connecting(self):
        import socket
        from nmb.speed.iperf import is_iperf_port_listening
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            self.assertFalse(is_iperf_port_listening(port))
            server.listen(1)
            self.assertTrue(is_iperf_port_listening(port))
            server.setblocking(False)
            with self.assertRaises(BlockingIOError):
                server.accept()


class SecurityRegressionTest(unittest.TestCase):
    def test_no_code_runs_from_world_writable_paths(self):
        self.assertNotIn("/tmp/nmb-install", (ROOT / "nmb/common/heal.py").read_text())
        self.assertNotIn("/tmp/nmb-bin", (ROOT / "nmb/speed/ookla.py").read_text())

    def test_sudoers_does_not_allow_ip(self):
        self.assertNotIn("/usr/sbin/ip,", (ROOT / "setup.sh").read_text())

    def test_control_characters_are_detected(self):
        from nmb.web.server import has_control_characters
        self.assertTrue(has_control_characters({"wifi_ssid": "x\nctrl_interface=/tmp"}))
        self.assertTrue(has_control_characters({"a": [{"b": "x\ry"}]}))
        self.assertFalse(has_control_characters({"wifi_ssid": "Árvíz % net", "n": 1}))

    def test_helper_refuses_option_like_packages_and_vpn_commands(self):
        import subprocess
        import tempfile
        helper = ROOT / "bin/nmb-helper"
        bad = subprocess.run(["sh", str(helper), "install-drivers", "-oAPT::Update::Pre-Invoke::=id"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("Refusing", bad.stderr)        # only allow-listed driver packages (2026-11-10)
        source = helper.read_text().split('case "${1:-}" in')[0]          # the functions before the main switch
        for line, code in (("PostUp = id", 1), ("up /tmp/x", 1), ("port 1194", 0)):
            with tempfile.NamedTemporaryFile("w", suffix=".conf") as conf:
                conf.write(line + "\n")
                conf.flush()
                run = subprocess.run(["sh", "-c", source + f'reject_unsafe_vpn_config "{conf.name}"'], capture_output=True)
                self.assertEqual(run.returncode, code, line)


class BootPartitionSecretsTest(unittest.TestCase):
    def test_secrets_are_masked_and_kept_on_import(self):
        from nmb.config import SECRET_MARK, mask_secrets, merge_drive_config
        current = "[web]\nadmin_password = a%b\nport = 80\n[telegram]\ntoken = T1\n"
        masked = mask_secrets(current)
        self.assertNotIn("a%b", masked)
        self.assertNotIn("T1", masked)
        self.assertIn("port = 80", masked)
        self.assertIn(SECRET_MARK, masked)
        edited = masked.replace("port = 80", "port = 81").replace(f"token = {SECRET_MARK}", "token = T2")
        merged = merge_drive_config(edited, current)
        self.assertIn("admin_password = a%b", merged)
        self.assertIn("token = T2", merged)
        self.assertIn("port = 81", merged)
        self.assertNotIn(SECRET_MARK, merge_drive_config(masked, ""))


class DataBudgetTest(unittest.TestCase):
    def test_limit_counts_only_today_and_zero_means_off(self):
        import sqlite3
        from nmb.speed import data_budget
        conn = sqlite3.connect(":memory:")
        conn.executescript((ROOT / "nmb/db/schema.sql").read_text())
        self.assertEqual(data_budget.limit_reached(conn, 0), (False, 0.0))
        data_budget.add_usage_mb(conn, 600)
        data_budget.add_usage_mb(conn, 500)
        self.assertEqual(data_budget.limit_reached(conn, 1000), (True, 1100.0))
        self.assertFalse(data_budget.limit_reached(conn, 2000)[0])
        conn.execute("UPDATE kv SET v = '2000-01-01|9999' WHERE k = ?", (data_budget.KV_KEY,))
        self.assertEqual(data_budget.used_today_mb(conn), 0.0)


class WirelessRouterTest(unittest.TestCase):
    def test_hostapd_steps_down_to_a_simple_setup(self):
        from nmb.netd.services import HOSTAPD_ATTEMPTS
        self.assertEqual(HOSTAPD_ATTEMPTS[0], {})
        self.assertEqual(HOSTAPD_ATTEMPTS[-1]["wifi_channel_width"], "20")

    def test_netd_reload_goes_through_systemd(self):
        self.assertIn("ExecReload=/bin/kill -HUP", (ROOT / "systemd/nmb-netd.service").read_text())
        self.assertIn('"reload", "nmb-netd.service"', (ROOT / "nmb/web/server.py").read_text())


class ServiceHardeningTest(unittest.TestCase):
    def test_web_server_does_not_run_as_root(self):
        unit = (ROOT / "systemd/nmb-web.service").read_text()
        self.assertIn("User=nmb", unit)
        self.assertNotIn("User=root", unit)

    def test_public_guard_covers_local_services_on_both_ip_versions(self):
        rules = (ROOT / "os/nmb-guard.nft").read_text()
        self.assertIn("{ 53, 80, 5201 } ip saddr", rules)
        self.assertIn("{ 53, 80, 5201 } ip6 saddr", rules)


class LostConfigTest(unittest.TestCase):
    def test_restoring_from_the_boot_copy_never_keeps_marks_or_the_shared_password(self):
        from nmb.config import SECRET_MARK, mask_secrets, merge_drive_config
        restored = merge_drive_config(mask_secrets("[network]\nwifi_psk = mine\n[web]\nport = 80\n"), "")
        self.assertNotIn(SECRET_MARK, restored)
        self.assertNotIn("mine", restored)
        default_only = merge_drive_config("[network]\nwifi_psk = NetworkMeasureBox123\n", "")
        self.assertNotIn("NetworkMeasureBox123", default_only)


class NewChecksTest(unittest.TestCase):
    def test_dmz_rules_isolate_the_lan_and_the_box(self):
        from unittest.mock import patch
        from nmb.netd import firewall
        with patch.object(firewall.shutil, "which", side_effect=lambda b: "/usr/sbin/nft" if b == "nft" else None), \
             patch.object(firewall, "_set_sysctl_forward"), \
             patch.object(firewall.subprocess, "run") as run:
            run.return_value.returncode = 0
            firewall.enable_nat_mode_a("eth0", ["br-lan"], dmz_iface="eth2")
        rules = run.call_args.kwargs["input"]
        self.assertIn('iifname "eth2" oifname "eth0" accept', rules)
        self.assertIn('iifname "eth2" drop', rules)
        self.assertLess(rules.index('iifname "eth2" oifname "eth0" accept'), rules.index('iifname {"br-lan"}'))

    def test_dns_interception_detection(self):
        from unittest.mock import patch
        from nmb.report import llm_bundle
        with patch.object(llm_bundle.socket, "socket") as sock:
            sock.return_value.recvfrom.side_effect = TimeoutError
            self.assertFalse(llm_bundle._detect_dns_interception()["intercepted"])
            sock.return_value.recvfrom.side_effect = None
            sock.return_value.recvfrom.return_value = (b"x" * 40, ("192.0.2.53", 53))
            self.assertTrue(llm_bundle._detect_dns_interception()["intercepted"])

    def test_alert_texts_exist_in_all_languages(self):
        from nmb.bot.i18n import ALERT_TEMPLATES
        for lang in ("en", "hu", "de", "fr", "uk"):
            for key in ("latency_firing", "latency_resolved", "jitter_firing", "jitter_resolved"):
                self.assertIn(key, ALERT_TEMPLATES[lang])

    def test_more_ports_are_checked(self):
        from nmb.speed.port_checker import DEFAULT_PORTS, TEST_HOSTS
        for port in (22, 5060, 6881):
            self.assertIn(port, DEFAULT_PORTS)
            self.assertIn(port, TEST_HOSTS)


class OoklaChecksumTest(unittest.TestCase):
    def test_setup_and_engine_share_the_pinned_hashes(self):
        from nmb.speed.ookla import OOKLA_SHA256
        setup = (ROOT / "setup.sh").read_text()
        for arch in ("x86_64", "aarch64", "armhf"):
            self.assertIn(OOKLA_SHA256[arch], setup)


class WebApiTest(unittest.TestCase):
    def test_post_handler_rejects_non_object_bodies(self):
        self.assertIn("must be a JSON object", (ROOT / "nmb/web/server.py").read_text())


if __name__ == "__main__":
    unittest.main()
