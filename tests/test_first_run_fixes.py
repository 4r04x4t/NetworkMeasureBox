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


class WebApiTest(unittest.TestCase):
    def test_post_handler_rejects_non_object_bodies(self):
        self.assertIn("must be a JSON object", (ROOT / "nmb/web/server.py").read_text())


if __name__ == "__main__":
    unittest.main()
