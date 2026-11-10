"""Tests for foreign traffic detection, measurement cancellation and retry timing."""
import _box_isolation  # noqa: F401  (private measurement lock on a working box)
import sys
import threading
import unittest
from unittest.mock import patch

from nmb.netd import upnp_wan
from nmb.probe import cross_traffic
from nmb.probe.traffic_gate import get_effective_threshold_kbps
from nmb.speed import cancel
from nmb.speed.scheduler import next_retry_time


class ThresholdTest(unittest.TestCase):
    def test_percent_mode_is_capped_on_fast_lines(self):
        self.assertEqual(get_effective_threshold_kbps(1000.0), 20000.0)
        self.assertEqual(get_effective_threshold_kbps(1000.0, strict=True), 500.0)
        self.assertEqual(get_effective_threshold_kbps(10.0, strict=True), 200.0)


class MonitorTest(unittest.TestCase):
    def _sample_pair(self, monitor, first, second, times=(10.0, 11.0)):
        with patch.object(cross_traffic.time, "monotonic", side_effect=times), \
             patch.object(cross_traffic, "read_counters", side_effect=[first, second]):
            self.assertIsNone(monitor.sample())
            return monitor.sample()

    def test_inline_ignores_own_uplink_traffic(self):
        monitor = cross_traffic.ForeignTrafficMonitor("eth0", ["eth1"], None)
        kbps = self._sample_pair(
            monitor,
            {"eth0": (0, 0), "eth1": (0, 0)},
            {"eth0": (100_000_000, 0), "eth1": (1000, 0)},
        )
        self.assertEqual(kbps, 8.0)

    def test_router_mode_subtracts_own_traffic(self):
        monitor = cross_traffic.ForeignTrafficMonitor("eth0", [], "http://192.0.2.1/ctl")
        with patch.object(upnp_wan, "read_wan_bytes", side_effect=[(0, 0), (2_000_000, 0)]):
            kbps = self._sample_pair(monitor, {"eth0": (0, 0)}, {"eth0": (1_000_000, 0)})
        self.assertAlmostEqual(kbps, 16000.0 - 8000.0 * 1.1)

    def test_wrapped_router_counter(self):
        self.assertEqual(cross_traffic.counter_delta(5, 2 ** 32 - 5), 10)

    def test_visibility(self):
        self.assertEqual(cross_traffic.ForeignTrafficMonitor("e", ["l"], "u").visibility, "inline")
        self.assertEqual(cross_traffic.ForeignTrafficMonitor("e", [], "u").visibility, "router")
        self.assertEqual(cross_traffic.ForeignTrafficMonitor("e", [], None).visibility, "none")

    def test_short_burst_does_not_abort(self):
        monitor = cross_traffic.ForeignTrafficMonitor("e", ["l"], None)
        values = [None, 9000.0, 9000.0, 0.0, 9000.0, 9000.0, 9000.0]
        stop = threading.Event()
        detected = threading.Event()
        with patch.object(cross_traffic, "INLINE_INTERVAL_SEC", 0.001), \
             patch.object(monitor, "sample", side_effect=values + [0.0] * 1000):
            cross_traffic.watch(monitor, 5000.0, stop, lambda _: detected.set())
            self.assertTrue(detected.wait(2.0))
        stop.set()


class StrictnessTest(unittest.TestCase):
    def test_router_read_failure_counts_as_busy(self):
        monitor = cross_traffic.ForeignTrafficMonitor("e", [], "http://192.0.2.1/ctl")
        with patch.object(upnp_wan, "read_wan_bytes", return_value=None):
            self.assertEqual(monitor.router_kbps(), float("inf"))

    def test_blind_box_runs_no_scheduled_speed_test(self):
        import os
        import tempfile
        from pathlib import Path
        from nmb.config import load_config
        from nmb.db import database as db
        from nmb.speed import runner

        root = Path(runner.__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"NMB_LIVE_DB": f"{tmp}/l.db"}):
            conn = db.connect()
            conn.executescript((root / "db" / "schema.sql").read_text())
            conn.close()
            blind = cross_traffic.ForeignTrafficMonitor("eth0", [], None)
            outcome = {}
            cfg = load_config("config/nmb.conf.example")
            self.assertFalse(cfg.speedtest.traffic_stop_enabled)
            cfg.speedtest.traffic_stop_enabled = True
            with patch.object(cross_traffic.ForeignTrafficMonitor, "for_config", return_value=blind), \
                 patch.object(runner, "_run_single_engine") as engine:
                ok = runner.run_measurement_cycle(cfg, trigger="schedule", outcome=outcome)
            engine.assert_not_called()
            self.assertFalse(ok)
            self.assertTrue(outcome["blind"])

    def test_disabled_feature_never_builds_a_monitor(self):
        from nmb.config import load_config
        from nmb.probe.traffic_gate import IdleCheckResult, TrafficGate
        from nmb.speed import runner

        cfg = load_config("config/nmb.conf.example")
        cleared = IdleCheckResult(False, 9000.0, 1.0, 20000.0, 1000.0)
        with patch.object(cross_traffic.ForeignTrafficMonitor, "for_config") as build, \
             patch.object(TrafficGate, "wait_for_idle", return_value=cleared), \
             patch.object(runner, "db"):
            runner.run_measurement_cycle(cfg, trigger="schedule", run_port_check=False)
        build.assert_not_called()


class CancelTest(unittest.TestCase):
    def test_cancel_kills_running_process(self):
        token = cancel.CancelToken()
        threading.Timer(0.2, token.cancel, args=("busy",)).start()
        with cancel.scope(token), self.assertRaises(cancel.MeasurementCancelled):
            cancel.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60)
        self.assertEqual(token.reason, "busy")

    def test_cancel_is_not_caught_as_exception(self):
        self.assertFalse(issubclass(cancel.MeasurementCancelled, Exception))

    def test_other_threads_are_not_cancelled(self):
        token = cancel.CancelToken()
        token.cancel("busy")
        result = []
        with cancel.scope(token):
            thread = threading.Thread(target=lambda: result.append(cancel.is_requested()))
            thread.start()
            thread.join()
        self.assertEqual(result, [False])


class RetryTest(unittest.TestCase):
    def test_retry_stops_before_next_scheduled_test(self):
        self.assertEqual(next_retry_time(1000.0, 1300.0), 1300.0)
        self.assertEqual(next_retry_time(1100.0, 1300.0), 0.0)


class AbortPathTest(unittest.TestCase):
    def test_aborted_run_saves_no_values_and_skips_port_check(self):
        import sqlite3
        from pathlib import Path
        from types import SimpleNamespace
        from nmb.speed import runner

        conn = sqlite3.connect(":memory:")
        schema = Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql"
        conn.executescript(schema.read_text())
        token = cancel.CancelToken()
        token.cancel("aborted: test")

        def engine(**_):
            raise cancel.MeasurementCancelled()

        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"))
        with patch.object(runner, "execute_cloudflare_speedtest", side_effect=engine), \
             patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.0.2.2", True)), \
             cancel.scope(token):
            res = runner._run_single_engine("cloudflare", cfg, "schedule", None, conn, 1, target_iface=None)
        self.assertEqual(res.status, "skipped_busy")
        row = conn.execute("SELECT status, down_bps, error FROM speedtest").fetchone()
        self.assertEqual(row, ("skipped_busy", None, "aborted: test"))
        self.assertEqual(conn.execute("SELECT kind FROM event").fetchone()[0], "speedtest_aborted")
        self.assertFalse(runner.is_speedtest_running())


class UpnpTest(unittest.TestCase):
    def test_control_url_found(self):
        xml = (b'<root xmlns="urn:schemas-upnp-org:device-1-0"><service><serviceType>' + upnp_wan.SERVICE.encode()
               + b'</serviceType><controlURL>/ctl/CommonIfCfg</controlURL></service></root>')
        self.assertEqual(upnp_wan.control_url_from_description("http://192.0.2.1:5000/d.xml", xml),
                         "http://192.0.2.1:5000/ctl/CommonIfCfg")

    def test_foreign_host_and_dtd_rejected(self):
        xml = (b'<root><service><serviceType>' + upnp_wan.SERVICE.encode()
               + b'</serviceType><controlURL>http://203.0.113.9/x</controlURL></service></root>')
        self.assertIsNone(upnp_wan.control_url_from_description("http://192.0.2.1/d.xml", xml))
        with self.assertRaises(ValueError):
            upnp_wan.control_url_from_description("http://192.0.2.1/d.xml", b'<!DOCTYPE x><root/>')


if __name__ == "__main__":
    unittest.main()
