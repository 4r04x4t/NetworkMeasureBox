"""Tests for WAN failover decisions and the impossible speed test cleanup."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.common import purge
from nmb.config import NetworkConfig
from nmb.netd import modes


class FailoverTests(unittest.TestCase):
    def setUp(self):
        net = NetworkConfig()
        net.wan_interface, net.wan2_interface, net.wan_mode, net.wan2_gateway = "eth0", "eth1", "failover", "10.0.0.1"
        self.mode = modes.ModeA(net, MagicMock())

    def _tick(self, ping_code):
        calls = []

        def run(cmd, check=False):
            calls.append(cmd)
            return SimpleNamespace(returncode=ping_code if "ping" in cmd[0] else 0)

        with patch.object(modes.shutil, "which", side_effect=lambda n: f"/bin/{n}"), patch.object(modes.interfaces, "run_cmd", run):
            self.mode.check_wan_failover()
        return [c for c in calls if "ping" not in c[0]]

    def test_switches_after_three_failures_and_returns_after_three_successes(self):
        self.assertEqual(self._tick(1) + self._tick(1), [])
        self.assertIn("replace", self._tick(1)[0])
        self.assertTrue(self.mode.on_wan2)
        self.assertEqual(self._tick(0) + self._tick(0), [])
        self.assertIn("del", self._tick(0)[0])
        self.assertFalse(self.mode.on_wan2)

    def test_single_mode_does_nothing(self):
        self.mode.cfg.wan_mode = "single"
        for _ in range(4):
            self.assertEqual(self._tick(1), [])
        self.assertFalse(self.mode.on_wan2)


class CleanupTests(unittest.TestCase):
    def test_backs_up_then_deletes_only_impossible_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.db"
            conn = sqlite3.connect(live)
            conn.execute("CREATE TABLE speedtest (down_bps INT, up_bps INT)")
            conn.executemany("INSERT INTO speedtest VALUES (?, ?)", [(900_000_000, 300_000_000), (100, 80_000_000_000)])
            conn.commit()
            conn.close()
            fresh = lambda *a, **k: sqlite3.connect(live)
            with patch.object(purge.db, "connect", fresh), patch.object(purge.db, "snapshot"), \
                    patch.object(purge.db, "tx", lambda c: c):
                result = purge.delete_impossible_speedtests(1050, Path(tmp) / "b")
            self.assertEqual(result["deleted"], 1)
            count = lambda p: sqlite3.connect(p).execute("SELECT COUNT(*) FROM speedtest").fetchone()[0]
            self.assertEqual(count(live), 1)
            self.assertEqual(count(result["backup"]), 2)
            self.assertEqual(os.stat(result["backup"]).st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()
