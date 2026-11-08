"""The guided USB scenario: lease detection, snapshot and restore, step flow (no real network)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.selftest import live, scenario

JOURNAL = """DHCPDISCOVER(eth0) 00:ad:24:8f:70:87
DHCPACK(eth0) 192.168.77.120 00:ad:24:8f:70:87 laptop
DHCPACK(br-lan) 192.168.100.120 00:ad:24:8f:70:87 laptop
DHCPACK(br-lan) 192.168.100.116 b0:5a:da:b3:dc:6a
"""


class AcksTest(unittest.TestCase):
    def test_fresh_leases_per_interface(self):
        with patch.object(live, "run", return_value=SimpleNamespace(stdout=JOURNAL, returncode=0)):
            self.assertEqual(scenario.Scenario.acks_since(0, "eth0", "192.168.77."), ["192.168.77.120"])
            self.assertEqual(scenario.Scenario.acks_since(0, "br-lan", "192.168.100."),
                             ["192.168.100.116", "192.168.100.120"])
            self.assertEqual(scenario.Scenario.acks_since(0, "eth0", "192.168.100."), [])


class SnapshotRestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = patch.object(scenario, "SNAPSHOT", self.tmp / "snap.json")
        self.p.start()
        self.addCleanup(self.p.stop)
        self.calls = []

    def _cfg(self):
        return SimpleNamespace(network=SimpleNamespace(wifi_enabled=False),
                               wifi_share=SimpleNamespace(enabled=False, lan_interface="eth0"))

    def test_snapshot_keeps_the_first_original(self):
        scenario.SNAPSHOT.write_text(json.dumps({"wifi_enabled": False, "ts": 1}))
        sc = scenario.Scenario(live.Report(), self._cfg())
        with patch.object(live, "run") as run, patch.object(live, "_db"):
            sc.snapshot()
        run.assert_not_called()   # an unfinished run's snapshot is the real original
        self.assertEqual(json.loads(scenario.SNAPSHOT.read_text())["ts"], 1)

    def test_restore_puts_every_setting_back(self):
        scenario.SNAPSHOT.write_text(json.dumps({"override_mode": None, "wifi_enabled": False,
                                                 "wifi_share_enabled": False, "wifi_share_lan": "eth0",
                                                 "wlan0_connected": True}))
        api = MagicMock(return_value={"status": "ok"})
        conn = MagicMock()
        with patch.object(scenario.Scenario, "api", api), patch.object(live, "run") as run, \
             patch("nmb.db.database.connect", return_value=conn), patch.object(scenario.time, "sleep"):
            self.assertTrue(scenario.restore(verbose=False))
        self.assertIn(("POST", "/api/config", {"wifi_enabled": False}), [c.args for c in api.call_args_list])
        self.assertIn(("POST", "/api/wifi-share/save", {"enabled": False, "lan_interface": "eth0"}),
                      [c.args for c in api.call_args_list])
        cmds = [" ".join(c.args[0]) for c in run.call_args_list]
        self.assertIn("nmcli device set eth0 managed yes", cmds)
        self.assertIn("nmcli device connect wlan0", cmds)
        self.assertTrue(any(COUNT in c for c in cmds for COUNT in [scenario.COUNT_TABLE]))
        self.assertFalse(scenario.SNAPSHOT.exists())
        self.assertTrue(any("DELETE FROM kv" in str(c) for c in conn.execute.call_args_list))

    def test_restore_without_snapshot_does_nothing(self):
        with patch.object(live, "run") as run:
            self.assertFalse(scenario.restore(verbose=False))
        run.assert_not_called()


class FlowTest(unittest.TestCase):
    def test_failed_preflight_changes_nothing(self):
        with patch.object(live, "_cfg"), patch.object(scenario, "s_preflight", return_value=False), \
             patch.object(scenario.Scenario, "snapshot") as snap, patch.object(scenario, "_finish", return_value=1), \
             patch.object(scenario, "restore") as rest:
            self.assertEqual(scenario.run_usb(scenario.STEPS), 1)
        snap.assert_not_called()
        rest.assert_not_called()

    def test_a_crashing_step_still_restores(self):
        tmp = Path(tempfile.mkdtemp()) / "snap.json"
        tmp.write_text("{}")

        def boom(sc):
            raise RuntimeError("cable")
        with patch.object(scenario, "SNAPSHOT", tmp), patch.object(live, "_cfg"), \
             patch.object(scenario, "s_preflight", return_value=True), patch.object(scenario.Scenario, "snapshot"), \
             patch.dict(scenario.STEP_FUNCS, {"router": boom}), patch.object(scenario, "restore") as rest, \
             patch.object(live, "run"), patch.object(scenario, "_finish", side_effect=lambda rep, sc: 1 if rep.counts()["FAIL"] else 0), \
             patch("builtins.print"):
            self.assertEqual(scenario.run_usb(["router"]), 1)
        rest.assert_called_once()

    def test_plan_lists_the_steps(self):
        text = scenario.plan(["router", "guard"])
        self.assertIn("router", text)
        self.assertIn("guard", text)
        self.assertNotIn("usb-speed  ", text)


if __name__ == "__main__":
    unittest.main()
