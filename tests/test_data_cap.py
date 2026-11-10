"""Data caps for automatic tests, per link and per connection type (nmb/speed/data_cap.py).

2026-11-09 night on the real 1000/300 PPPoE line: the owner's schedule moved about 800 GB in 4 hours.
"""
import _box_isolation  # noqa: F401  (private measurement lock on a working box)
import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nmb.config import Config, DataCapConfig, load_config, save_config
from nmb.speed import data_cap, runner

SCHEMA = (Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


class PeriodTest(unittest.TestCase):
    def test_month_with_reset_day(self):
        caps = DataCapConfig(period="month", reset_day=15)
        self.assertEqual(data_cap.period_start(caps, datetime.date(2026, 11, 10)), datetime.date(2026, 10, 15))
        self.assertEqual(data_cap.period_start(caps, datetime.date(2026, 11, 15)), datetime.date(2026, 11, 15))
        self.assertEqual(data_cap.next_reset(caps, datetime.date(2026, 11, 10)), datetime.date(2026, 11, 15))
        self.assertEqual(data_cap.period_start(caps, datetime.date(2027, 1, 3)), datetime.date(2026, 12, 15))
        self.assertEqual(data_cap.next_reset(caps, datetime.date(2026, 12, 20)), datetime.date(2027, 1, 15))

    def test_day(self):
        caps = DataCapConfig(period="day")
        self.assertEqual(data_cap.period_start(caps, datetime.date(2026, 11, 10)), datetime.date(2026, 11, 10))
        self.assertEqual(data_cap.next_reset(caps, datetime.date(2026, 12, 31)), datetime.date(2027, 1, 1))


class LinkTest(unittest.TestCase):
    def test_link_classes(self):
        with mock.patch("nmb.netd.interfaces.usb_tether_kind", side_effect=lambda i: "tether" if i == "eth1" else None):
            self.assertEqual(data_cap.link_class("eth1"), "usb")
            self.assertEqual(data_cap.link_class("bond0"), "lag")
            self.assertEqual(data_cap.link_class("wlan0"), "wifi")
            self.assertEqual(data_cap.link_class("ppp0"), "wired")
            self.assertEqual(data_cap.link_class("eth0"), "wired")

    def test_usb_is_mobile_the_rest_use_the_isp_type(self):
        cfg = Config()
        cfg.isp.connection_type = "docsis"
        self.assertEqual(data_cap.connection_type(cfg, "usb"), "fwa")
        self.assertEqual(data_cap.connection_type(cfg, "wired"), "docsis")
        cfg.isp.connection_type = "nonsense"
        self.assertEqual(data_cap.connection_type(cfg, "wifi"), "other")


class CountAndStopTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.cfg.isp.connection_type = "fiber"
        self.cfg.data_cap = DataCapConfig(period="month", reset_day=1, wired_mb=1000)
        self.conn = _conn()
        self.wired = mock.patch.object(data_cap, "link_class", return_value="wired")
        self.wired.start()
        self.addCleanup(self.wired.stop)

    def _events(self):
        return [r[0] for r in self.conn.execute("SELECT kind FROM event ORDER BY id")]

    def test_link_cap_warns_then_stops(self):
        self.assertEqual(data_cap.add(self.conn, self.cfg, "ppp0", 500), [])
        self.assertEqual(data_cap.check(self.conn, self.cfg, "ppp0")[0], False)
        self.assertEqual(data_cap.add(self.conn, self.cfg, "ppp0", 350), ["data_cap_warning"])
        reached = data_cap.add(self.conn, self.cfg, "ppp0", 200)
        self.assertEqual(reached, ["data_cap_reached"])
        stop, why = data_cap.check(self.conn, self.cfg, "ppp0")
        self.assertTrue(stop)
        self.assertIn("data cap for wired reached (1050 of 1000 MB", why)
        self.assertEqual(self._events(), ["data_cap_warning", "data_cap_reached"])
        # no new event once it is over the cap
        self.assertEqual(data_cap.add(self.conn, self.cfg, "ppp0", 100), [])

    def test_a_new_period_starts_from_zero(self):
        data_cap.add(self.conn, self.cfg, "ppp0", 1200)
        self.assertTrue(data_cap.check(self.conn, self.cfg, "ppp0")[0])
        with mock.patch.object(data_cap, "period_start", return_value=datetime.date(2099, 1, 1)):
            self.assertFalse(data_cap.check(self.conn, self.cfg, "ppp0")[0])

    def test_type_cap_holds_when_stricter(self):
        self.cfg.data_cap.wired_mb = 0
        self.cfg.data_cap.by_type = {"fiber": 600}
        data_cap.add(self.conn, self.cfg, "ppp0", 700)
        stop, why = data_cap.check(self.conn, self.cfg, "ppp0")
        self.assertTrue(stop)
        self.assertIn("fiber connections", why)

    def test_no_caps_never_stop(self):
        self.cfg.data_cap = DataCapConfig()
        data_cap.add(self.conn, self.cfg, "ppp0", 10_000_000)
        self.assertFalse(data_cap.check(self.conn, self.cfg, "ppp0")[0])

    def test_usage_report(self):
        data_cap.add(self.conn, self.cfg, "ppp0", 250)
        u = data_cap.usage(self.conn, self.cfg)
        wired = next(l for l in u["links"] if l["link"] == "wired")
        self.assertEqual((wired["cap_mb"], wired["used_mb"], wired["reached"], wired["type"]), (1000, 250.0, False, "fiber"))
        self.assertEqual(u["period"], "month")

    def test_skipped_row_at_most_hourly(self):
        self.assertTrue(data_cap.note_skip_due(self.conn, "ppp0"))
        self.assertFalse(data_cap.note_skip_due(self.conn, "ppp0"))


class SettingsTest(unittest.TestCase):
    def test_clean_checks_and_keeps_the_rest(self):
        cur = DataCapConfig(wired_mb=5000, by_type={"fwa": 20000})
        new = data_cap.clean({"usb_mb": "1500", "period": "day"}, cur)
        self.assertEqual((new.wired_mb, new.usb_mb, new.period, new.by_type), (5000, 1500, "day", {"fwa": 20000}))
        new = data_cap.clean({"by_type": '{"satellite": 4000, "fiber": 0}'}, cur)
        self.assertEqual(new.by_type, {"satellite": 4000})
        for bad, word in (({"period": "week"}, "day or month"), ({"reset_day": 29}, "1-28"), ({"wired_mb": -5}, "0 to"),
                          ({"lag_mb": "lots"}, "whole number"), ({"by_type": {"lte": 5}}, "unknown connection type"),
                          ({"by_type": "[1]"}, "JSON object")):
            with self.assertRaises(data_cap.CapError) as ctx:
                data_cap.clean(bad, cur)
            self.assertIn(word, str(ctx.exception))

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nmb.conf"
            cfg = load_config(path)
            self.assertEqual(cfg.data_cap, DataCapConfig())
            cfg.data_cap = DataCapConfig(period="day", reset_day=7, wired_mb=0, wifi_mb=2000, usb_mb=1500, lag_mb=0,
                                         by_type={"fwa": 20000})
            save_config(cfg, path)
            self.assertEqual(load_config(path).data_cap, cfg.data_cap)


class RunnerTest(unittest.TestCase):
    def _cycle(self, trigger):
        cfg = Config()
        outcome = {}
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value=None), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("ppp0", "198.51.100.7", True)), \
             mock.patch.object(runner, "_usb_test_not_allowed", return_value=False), \
             mock.patch.object(data_cap, "check", return_value=(True, "data cap for wired reached (2000 of 1000 MB used by tests since 2026-11-01)")), \
             mock.patch.object(data_cap, "note_skip_due", return_value=False), \
             mock.patch.object(runner.db, "connect", side_effect=lambda *a, **k: _conn()), \
             mock.patch.object(runner, "_run_single_engine", side_effect=AssertionError("no test may run")) as eng:
            try:
                ok = runner._run_measurement_cycle(cfg, trigger=trigger, engine="cloudflare", outcome=outcome)
            except AssertionError:
                ok = "ran"
        return ok, outcome, eng.called

    def test_scheduled_tests_stop_at_the_cap(self):
        ok, outcome, ran = self._cycle("schedule")
        self.assertFalse(ok)
        self.assertTrue(outcome.get("data_limit"))
        self.assertIn("data cap for wired", outcome.get("data_cap", ""))
        self.assertFalse(ran)

    def test_manual_tests_still_run(self):
        _, outcome, ran = self._cycle("manual")
        self.assertNotIn("data_cap", outcome)
        self.assertTrue(ran)


if __name__ == "__main__":
    unittest.main()


class BotAlertTest(unittest.TestCase):
    def test_alert_fires_once_and_resolves(self):
        from nmb.bot import alerts
        conn = _conn()
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        cfg = Config()
        cfg.data_cap = DataCapConfig(period="month", wired_mb=100)
        eng = alerts.AlertMonitor.__new__(alerts.AlertMonitor)
        eng.cfg = cfg
        sent = []
        eng._broadcast = lambda key, **kw: sent.append((key, kw))
        with mock.patch.object(data_cap, "link_class", return_value="wired"):
            data_cap.add(conn, cfg, "ppp0", 150)
        eng.check_data_cap(conn)
        eng.check_data_cap(conn)
        self.assertEqual([k for k, _ in sent], ["data_cap_firing"])
        self.assertIn("wired (150 of 100 MB)", sent[0][1]["links"])
        cfg.data_cap.wired_mb = 0
        eng.check_data_cap(conn)
        self.assertEqual([k for k, _ in sent], ["data_cap_firing", "data_cap_resolved"])
