"""A speed test engine that raises is a failed measurement of that engine, never a lost cycle.

2026-11-09 on the box: while it had no internet, RTR's control-server request raised URLError out of
the scheduled cycle (24 tracebacks in an hour): no error row, and the engines after it did not run.
"""
import sqlite3
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.speed import runner
from nmb.speed.rmbt import connection, control


class EngineRaisesTest(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
        return conn

    def test_network_error_is_stored_as_a_failed_test(self):
        conn = self._conn()
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"))
        boom = urllib.error.URLError(OSError(101, "Network is unreachable"))
        with mock.patch.object(runner, "execute_rtr_speedtest", side_effect=boom), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("ppp0", "192.0.2.9", True)):
            res = runner._run_single_engine("rtr", cfg, "schedule", None, conn, 1, target_iface=None)
        self.assertEqual(res.status, "error")
        self.assertIn("unreachable", res.error)
        row = conn.execute("SELECT status, engine, error FROM speedtest").fetchone()
        self.assertEqual(row[:2], ("error", "rtr"))


class RmbtControlBoundTest(unittest.TestCase):
    def tearDown(self):
        connection.set_bind_target(interface=None, bind_ip=None)

    def test_no_unbound_retry_when_bound(self):
        connection.set_bind_target(interface="ppp0", bind_ip="192.0.2.9")
        opener = mock.MagicMock()
        opener.open.side_effect = urllib.error.URLError(OSError(22, "Invalid argument"))
        with mock.patch.object(control.urllib.request, "build_opener", return_value=opener), \
             mock.patch.object(control.urllib.request, "urlopen") as unbound:
            with self.assertRaises(RuntimeError) as ctx:
                control._post("https://example.invalid/x", {}, False)
        unbound.assert_not_called()
        self.assertIn("ppp0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class RouterWanDownTest(unittest.TestCase):
    """2026-11-09: DIGI refused the PPPoE login ("Too many sessions") for some minutes and router mode had no
    WAN; 19 scheduled tests in an hour then ran over the USB hotspot (the wrong line, and mobile data)."""

    def _cycle(self, target_iface=None, addr=None):
        from nmb.config import Config
        cfg = Config()
        outcome = {}
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value="ppp0"), \
             mock.patch("nmb.netd.interfaces._usable_address", return_value=addr), \
             mock.patch.object(runner, "_run_single_engine", side_effect=AssertionError("no test may run")) as eng:
            try:
                ok = runner._run_measurement_cycle(cfg, trigger="schedule", engine="cloudflare",
                                                   target_iface=target_iface, outcome=outcome)
            except AssertionError:
                ok = None
        return ok, outcome, eng.called

    def test_no_test_while_the_router_wan_is_down(self):
        ok, outcome, ran = self._cycle()
        self.assertFalse(ok)
        self.assertTrue(outcome.get("wan_down"))
        self.assertFalse(ran)

    def test_a_chosen_interface_still_runs(self):
        _, outcome, _ = self._cycle(target_iface="eth1")
        self.assertNotIn("wan_down", outcome)
