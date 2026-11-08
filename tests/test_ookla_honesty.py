"""Ookla results must name the server they used and back off when Ookla rate-limits."""
import json
import unittest
from unittest import mock

from nmb.speed import anti_ban
from nmb.speed import ookla
from nmb.speed.ookla import SpeedtestResult
from nmb.speed.runner import _flag_server_mismatch

# Never touch the box's real Ookla cooldown file.
import tempfile as _tf
from pathlib import Path as _P
from nmb.speed import anti_ban as _ab
_ab.CLIENT_COOLDOWN_FILE = _P(_tf.mkdtemp(prefix="nmb-test-")) / "ookla_cooldown.json"


LIMIT_TEXT = "[error] Limit reached: Too many requests received."


class ClientCooldownTest(unittest.TestCase):
    def setUp(self):
        anti_ban.clear_quarantine()

    def tearDown(self):
        anti_ban.clear_quarantine()

    def test_limit_text_is_a_client_limit(self):
        self.assertTrue(anti_ban.is_client_rate_limit(LIMIT_TEXT))
        self.assertFalse(anti_ban.is_client_rate_limit("Connection timed out"))

    def test_cooldown_doubles_and_resets_on_success(self):
        first = anti_ban.mark_client_rate_limited()
        second = anti_ban.mark_client_rate_limited()
        self.assertEqual(second, first * 2)
        self.assertGreater(anti_ban.client_cooldown_remaining(), 0)
        anti_ban.mark_client_ok()
        self.assertEqual(anti_ban.client_cooldown_remaining(), 0)
        self.assertEqual(anti_ban.mark_client_rate_limited(), first)

    def test_cooldown_survives_a_restart(self):
        anti_ban.mark_client_rate_limited()
        anti_ban.mark_client_rate_limited()
        # A restart loses the module state; the file keeps it.
        anti_ban._client_limited_until = 0.0
        anti_ban._client_cooldown_sec = anti_ban.CLIENT_COOLDOWN_MIN_SEC
        self.assertGreater(anti_ban.client_cooldown_remaining(), anti_ban.CLIENT_COOLDOWN_MIN_SEC)
        self.assertEqual(anti_ban.mark_client_rate_limited(), anti_ban.CLIENT_COOLDOWN_MIN_SEC * 4)

    def test_cooldown_is_capped(self):
        for _ in range(10):
            last = anti_ban.mark_client_rate_limited()
        self.assertEqual(last, anti_ban.CLIENT_COOLDOWN_MAX_SEC)


class NoDisguisedFallbackTest(unittest.TestCase):
    def test_failed_ookla_is_returned_as_error(self):
        failed = SpeedtestResult(status="error", error=LIMIT_TEXT)
        with mock.patch.object(ookla, "run_official_ookla", return_value=failed), \
             mock.patch.object(ookla, "run_speedtest_cli") as cli:
            res = ookla.execute_speedtest(server_id=10390)
        self.assertEqual(res.status, "error")
        cli.assert_not_called()

    def test_chosen_server_never_uses_untargeted_cli(self):
        with mock.patch.object(ookla, "run_official_ookla", return_value=None), \
             mock.patch.object(ookla, "run_speedtest_cli") as cli:
            res = ookla.execute_speedtest(server_id=10390)
        self.assertEqual(res.status, "error")
        cli.assert_not_called()

    def test_native_stream_fallback_is_gone(self):
        self.assertFalse(hasattr(ookla, "run_native_fallback"))

    def test_paused_ookla_is_not_replaced_by_another_engine(self):
        import sqlite3
        from pathlib import Path
        from types import SimpleNamespace
        from nmb.speed import runner

        anti_ban.clear_quarantine()
        anti_ban.mark_client_rate_limited()
        try:
            conn = sqlite3.connect(":memory:")
            conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
            cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"))
            with mock.patch.object(runner, "execute_rtr_speedtest") as rtr, \
                 mock.patch.object(runner, "execute_cloudflare_speedtest") as cf, \
                 mock.patch.object(runner, "execute_speedtest") as ook, \
                 mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.0.2.2", True)):
                res = runner._run_single_engine("ookla", cfg, "schedule", 10390, conn, 1, target_iface=None)
            rtr.assert_not_called()
            cf.assert_not_called()
            ook.assert_not_called()
            self.assertEqual(res.status, "error")
            self.assertIn("paused", res.error)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM speedtest").fetchone()[0], 0)
        finally:
            anti_ban.clear_quarantine()


class ServerMismatchTest(unittest.TestCase):
    def test_mismatch_is_recorded(self):
        res = SpeedtestResult(status="ok", server_id=3787, raw_json=json.dumps({"a": 1}))
        _flag_server_mismatch(res, 10390)
        self.assertEqual(json.loads(res.raw_json)["requested_server_id"], 10390)

    def test_matching_server_is_left_alone(self):
        res = SpeedtestResult(status="ok", server_id=10390, raw_json="{}")
        _flag_server_mismatch(res, 10390)
        self.assertEqual(res.raw_json, "{}")


class ErrorRowReportTest(unittest.TestCase):
    def test_report_accepts_failed_speed_tests(self):
        import sqlite3
        import tempfile
        import time
        from pathlib import Path
        from nmb.config import load_config
        from nmb.report.metrics import aggregate_report_data

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript((Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text())
        now = int(time.time() * 1000)
        conn.execute("INSERT INTO speedtest(ts, trigger, status, error, engine) VALUES (?, 'schedule', 'error', 'Ookla rate limit: paused for another 5 min', 'ookla')", (now,))
        conn.execute("INSERT INTO speedtest(ts, trigger, status, error, engine) VALUES (?, 'schedule', 'error', 'connection timed out', 'ookla')", (now - 1,))
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(Path(tmp) / "nmb.conf")
            data = aggregate_report_data(conn, cfg, window_hours=24.0)
        self.assertIsNotNone(data)


class HourlyOoklaTest(unittest.TestCase):
    def setUp(self):
        anti_ban.clear_quarantine()

    def tearDown(self):
        anti_ban.clear_quarantine()

    def _run(self, trigger):
        import sqlite3
        from pathlib import Path
        from types import SimpleNamespace
        from nmb.speed import runner
        conn = sqlite3.connect(":memory:")
        conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"))
        failed = SpeedtestResult(status="error", error="connection refused")
        with mock.patch.object(runner, "execute_speedtest", return_value=failed) as ook, \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.0.2.2", True)):
            runner._run_single_engine("ookla", cfg, trigger, 10390, conn, 1, target_iface=None)
        return ook.call_count, conn.execute("SELECT COUNT(*) FROM speedtest").fetchone()[0]

    def test_scheduled_ookla_runs_at_most_hourly(self):
        self.assertEqual(self._run("schedule"), (1, 1))
        self.assertEqual(self._run("schedule"), (0, 0))  # within the hour: not asked, nothing stored
        self.assertGreater(anti_ban.scheduled_wait_remaining(), 3500)

    def test_manual_test_is_not_held_back(self):
        self._run("schedule")
        self.assertEqual(self._run("manual")[0], 1)


class EngineIntervalTest(unittest.TestCase):
    def _db(self):
        import sqlite3
        from pathlib import Path
        from nmb.speed import runner
        conn = sqlite3.connect(":memory:")
        conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
        return conn

    def test_engine_runs_only_after_its_interval(self):
        from types import SimpleNamespace
        from nmb.speed.runner import _engine_due
        conn = self._db()
        cfg = SimpleNamespace(speedtest=SimpleNamespace(rtr_interval_min=30, cloudflare_interval_min=0))
        now = 10_000_000_000
        self.assertTrue(_engine_due(conn, cfg, "rtr", now))
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine) VALUES (?, 'schedule', 'ok', 'rtr')", (now - 10 * 60_000,))
        self.assertFalse(_engine_due(conn, cfg, "rtr", now))
        self.assertTrue(_engine_due(conn, cfg, "rtr", now + 20 * 60_000))
        self.assertTrue(_engine_due(conn, cfg, "cloudflare", now))  # 0 = every run

    def test_ookla_interval_cannot_go_below_an_hour(self):
        import tempfile
        from pathlib import Path
        from nmb.config import load_config, save_config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nmb.conf"
            cfg = load_config(path)
            cfg.speedtest.ookla_interval_min = 5
            cfg.speedtest.rtr_interval_min = 15
            save_config(cfg, path)
            again = load_config(path)
        self.assertEqual((again.speedtest.ookla_interval_min, again.speedtest.rtr_interval_min), (60, 15))
        self.assertGreaterEqual(anti_ban.scheduled_wait_remaining(60), 0.0)


class OoklaOnlyFallbackTest(unittest.TestCase):
    def setUp(self):
        anti_ban.clear_quarantine()

    def tearDown(self):
        anti_ban.clear_quarantine()

    def _cycle(self):
        from nmb.speed import runner
        ran = []
        cfg = load_cfg()
        cfg.speedtest.automated_engine = "ookla"
        with mock.patch.object(runner, "_run_single_engine", side_effect=lambda eng, *a, **k: ran.append(eng) or SpeedtestResult(status="ok")), \
             mock.patch.object(runner, "_engine_due", return_value=True), \
             mock.patch.object(runner, "_iperf3_usable", return_value=self.iperf_ok), \
             mock.patch.object(runner, "_usable_iperf3_servers", return_value=[("iperf.example", 5201)] if self.iperf_ok else []):
            runner.run_measurement_cycle(cfg, trigger="schedule", force=True, run_port_check=False, engine=self.engine)
        return ran

    iperf_ok = False
    engine = "ookla"

    def test_iperf3_joins_the_mixed_run_when_its_server_answers(self):
        self.engine, self.iperf_ok = "all", True
        self.assertEqual(self._cycle(), ["ookla", "cloudflare", "fastcom", "rtr", "iperf3"])
        self.iperf_ok = False
        self.assertEqual(self._cycle(), ["ookla", "cloudflare", "fastcom", "rtr"])

    def test_iperf3_joins_the_ookla_fallback_too(self):
        anti_ban.mark_client_rate_limited()
        self.iperf_ok = True
        self.assertEqual(self._cycle(), ["cloudflare", "fastcom", "rtr", "iperf3"])

    def test_iperf3_alone_runs_only_with_a_working_server(self):
        self.engine, self.iperf_ok = "iperf3", True
        self.assertEqual(self._cycle(), ["iperf3"])
        self.iperf_ok = False
        self.assertEqual(self._cycle(), [])

    def test_several_iperf3_servers_each_get_a_run(self):
        from types import SimpleNamespace
        from nmb.speed.runner import iperf3_servers
        cfg = SimpleNamespace(iperf=SimpleNamespace(target_host="a.example", target_port=5201,
                                                    extra_servers="b.example:5202, a.example:5201, -bad, c.example"))
        self.assertEqual(iperf3_servers(cfg), [("a.example", 5201), ("b.example", 5202), ("c.example", 5201)])
        self.engine = "iperf3"
        from nmb.speed import runner
        with mock.patch.object(runner, "_usable_iperf3_servers", return_value=[("a", 1), ("b", 2)]):
            self.iperf_ok = True
            ran = []
            cfg2 = load_cfg()
            with mock.patch.object(runner, "_run_single_engine", side_effect=lambda eng, c, *a, **k: ran.append(c.iperf.target_host) or SpeedtestResult(status="ok")), \
                 mock.patch.object(runner, "_engine_due", return_value=True), \
                 mock.patch.object(runner, "_iperf3_usable", return_value=True):
                runner.run_measurement_cycle(cfg2, trigger="schedule", force=True, run_port_check=False, engine="iperf3")
        self.assertEqual(ran, ["a", "b"])

    def test_iperf3_needs_a_server(self):
        from types import SimpleNamespace
        from nmb.speed.runner import _iperf3_usable
        self.assertFalse(_iperf3_usable(SimpleNamespace(iperf=SimpleNamespace(target_host="", target_port=5201))))
        self.assertFalse(_iperf3_usable(SimpleNamespace(iperf=SimpleNamespace(target_host="127.0.0.1", target_port=1))))

    def test_other_engines_run_while_ookla_is_paused(self):
        anti_ban.mark_client_rate_limited()
        self.assertEqual(self._cycle(), ["cloudflare", "fastcom", "rtr"])

    def test_ookla_runs_when_it_may(self):
        self.assertEqual(self._cycle(), ["ookla"])


def load_cfg():
    import tempfile
    from pathlib import Path
    from nmb.config import load_config
    return load_config(Path(tempfile.mkdtemp()) / "nmb.conf")


class BusyIperfTest(unittest.TestCase):
    def test_busy_iperf_server_adds_no_row(self):
        import sqlite3
        from pathlib import Path
        from types import SimpleNamespace
        from nmb.speed import runner
        conn = sqlite3.connect(":memory:")
        conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"),
                              iperf=SimpleNamespace(target_host="iperf.example", target_port=5201, duration=10, protocol="tcp",
                                                    parallel=1, reverse=False, bidir=False))
        busy = {"status": "error", "error": "the server is busy running a test. try again later"}
        with mock.patch("nmb.speed.iperf.run_iperf_client_test", return_value=busy), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.0.2.2", True)):
            runner._run_single_engine("iperf3", cfg, "schedule", None, conn, 1, target_iface=None)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM speedtest").fetchone()[0], 0)


class IperfBothDirectionsTest(unittest.TestCase):
    def test_download_then_upload_in_one_row(self):
        import sqlite3
        from pathlib import Path
        from types import SimpleNamespace
        from nmb.speed import runner
        conn = sqlite3.connect(":memory:")
        conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"),
                              iperf=SimpleNamespace(target_host="iperf.example", target_port=5201, duration=10, protocol="tcp",
                                                    parallel=4, reverse=False, bidir=False, auto_direction="both"))
        calls = []

        def fake(**kw):
            calls.append(kw["reverse"])
            return {"status": "ok", "bps": 900_000_000 if kw["reverse"] else 300_000_000, "rtt_ms": 12.0}

        with mock.patch("nmb.speed.iperf.run_iperf_client_test", side_effect=fake), \
             mock.patch.object(runner.time, "sleep"), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.0.2.2", True)):
            runner._run_single_engine("iperf3", cfg, "schedule", None, conn, 1, target_iface=None)
        self.assertEqual(calls, [True, False])
        row = conn.execute("SELECT engine, down_bps, up_bps FROM speedtest").fetchone()
        self.assertEqual(row, ("iperf3", 900_000_000, 300_000_000))


class IperfServerNameTest(unittest.TestCase):
    def test_name_from_directory_then_geoip(self):
        from nmb.speed import iperf_directory as d
        from nmb.speed.runner import _iperf_label
        d._label_cache.clear()
        with mock.patch.object(d, "_read_cache", return_value={"servers": [{"host": "185.180.12.40", "site": "Vienna", "provider": "DATAPACKET", "country": "AT"}]}):
            self.assertEqual(_iperf_label("185.180.12.40", 5201), "iPerf3: Vienna • DATAPACKET (185.180.12.40:5201)")
        d._label_cache.clear()
        with mock.patch.object(d, "_read_cache", return_value={}), \
             mock.patch("socket.gethostbyname", return_value="203.0.113.9"), \
             mock.patch("nmb.netd.geoip.get_public_geoip", return_value={"city": "Frankfurt", "country_code": "DE", "isp": "Example Net"}):
            self.assertEqual(_iperf_label("203.0.113.9", 5201), "iPerf3: Frankfurt, DE • Example Net (203.0.113.9:5201)")
        d._label_cache.clear()


if __name__ == "__main__":
    unittest.main()
