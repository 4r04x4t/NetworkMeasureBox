"""The automatic-mode scenario and the mode check (no real network)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.config import Config
from nmb.selftest import live, scenario as S, scenario_auto as SA


class AutoPreflightTest(unittest.TestCase):
    def _sc(self):
        cfg = Config()
        cfg.usb_uplink.enabled = True
        sc = S.Scenario(live.Report(), cfg)
        return sc

    def test_no_usb_means_no_start(self):
        sc = self._sc()
        with patch.object(SA, "_mode", return_value="standalone"), patch.object(S.Scenario, "carrier", return_value=True), \
             patch.object(S.Scenario, "internet", return_value=True), \
             patch("nmb.netd.usb_uplink.uplink_interface", return_value=None), patch.dict("os.environ", {}, clear=False), \
             patch("builtins.print"):
            self.assertFalse(SA.a_preflight(sc))
        self.assertIn("USB tethering", sc.rep.rows[-1]["check"])

    def test_allow_offline_overrides(self):
        sc = self._sc()
        with patch.object(SA, "_mode", return_value="standalone"), patch.object(S.Scenario, "carrier", return_value=True), \
             patch.object(S.Scenario, "internet", return_value=True), \
             patch("nmb.netd.usb_uplink.uplink_interface", return_value=None), \
             patch.dict("os.environ", {"NMB_SCENARIO_ALLOW_OFFLINE": "1"}), patch.object(live, "weak_psk", return_value=False):
            self.assertTrue(SA.a_preflight(sc))
        self.assertEqual(sc.rep.rows[-1]["status"], live.WARN)

    def test_router_step_fails_when_router_mode_comes_too_early(self):
        sc = self._sc()
        modes = iter(["standalone"] + ["mode_a"] * 100)
        carrier = iter([False] * 100)
        with patch.object(SA, "_mode", side_effect=lambda: next(modes)), \
             patch.object(S.Scenario, "carrier", side_effect=lambda i: next(carrier)), \
             patch.object(S.Scenario, "internet", return_value=True), patch.object(S.time, "sleep"), \
             patch.object(SA.time, "sleep"), patch.object(SA, "_reason", return_value="no cable"), \
             patch.object(live, "run", return_value=SimpleNamespace(returncode=0, stdout="")), \
             patch.object(live, "tailscale_online", return_value=True), patch("builtins.print"):
            SA.a_router(sc)
        row = next(r for r in sc.rep.rows if r["check"] == "router mode after the grace time")
        self.assertEqual(row["status"], live.FAIL)      # switched at once: a rebooting router would knock it over


class RestoreModeTest(unittest.TestCase):
    def test_restore_puts_the_mode_back(self):
        snap = Path(tempfile.mkdtemp()) / "snap.json"
        snap.write_text(json.dumps({"override_mode": None, "network_mode": "standalone", "wifi_enabled": False}))
        api = MagicMock(return_value={"status": "ok"})
        with patch.object(S, "SNAPSHOT", snap), patch.object(S.Scenario, "api", api), patch.object(live, "run"), \
             patch("nmb.db.database.connect"), patch.object(S.time, "sleep"):
            S.restore(verbose=False)
        self.assertIn(("POST", "/api/config", {"wifi_enabled": False, "network_mode": "standalone"}),
                      [c.args for c in api.call_args_list])


class MarkdownTest(unittest.TestCase):
    def test_table_escapes_pipes(self):
        rep = live.Report()
        with patch("builtins.print"):
            rep.add("mode", "a|b", live.FAIL, "x | y")
        md = live.to_markdown(rep, ["mode"])
        self.assertIn("| ❌ | mode | a\\|b | x \\| y |", md)
        self.assertIn("1 failed", md)


class ModeCheckTest(unittest.TestCase):
    def test_access_point_outside_router_mode_fails(self):
        rep = live.Report()
        cfg = Config()
        with patch.object(live, "_netd_state", return_value={"active_mode": "standalone", "configured_mode": "standalone",
                                                             "details": {"interface": "eth0"}}), \
             patch.object(live, "_db", side_effect=Exception("no db")), \
             patch.object(live, "run", return_value=SimpleNamespace(returncode=0, stdout="")), \
             patch("nmb.netd.interfaces.get_ip_addresses", return_value=["192.168.8.218/24"]), \
             patch("nmb.netd.interfaces.get_carrier", return_value=True), patch("builtins.print"):
            live.g_mode(rep, cfg)
        row = next(r for r in rep.rows if r["check"] == "no access point outside router mode")
        self.assertEqual(row["status"], live.FAIL)


if __name__ == "__main__":
    unittest.main()
