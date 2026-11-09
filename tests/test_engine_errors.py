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
