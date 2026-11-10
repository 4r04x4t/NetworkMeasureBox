"""Outages the box causes itself are not counted against the ISP (data-quality list of 2026-11-10, D4)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nmb.common import own_action
from nmb.config import Config
from nmb.db import database as db
from nmb.report import csv_export, metrics

H = 3_600_000
T0 = 1_794_200_000_000          # a fixed day; the report window is [T0, T0 + 24 h]


class _Db(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "nmb.db"
        patcher = mock.patch.dict(os.environ, {"NMB_LIVE_DB": str(self.path), "NMB_PERSIST_DB": str(self.path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = db.connect()
        db.init(self.conn)
        self.conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.0.2.53', 'DNS', 'Public DNS')")

    def tearDown(self):
        self.conn.close()

    def outage(self, start, end, cause="all probe targets unreachable"):
        self.conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, ?, ?)", (start, end, cause))

    def window(self, start, end, kind="mode_change"):
        self.conn.execute("INSERT INTO own_action (start_ts, end_ts, kind, source) VALUES (?, ?, ?, 'netd')", (start, end, kind))

    def report(self):
        return metrics.aggregate_report_data(self.conn, Config(), window_hours=24, end_ms=T0 + 24 * H)


class SpanTest(unittest.TestCase):
    def test_subtract(self):
        self.assertEqual(metrics.subtract_spans((0, 100), [(10, 20), (50, 200)]), [(0, 10), (20, 50)])
        self.assertEqual(metrics.subtract_spans((0, 100), [(-5, 500)]), [])
        self.assertEqual(metrics.merge_spans([(5, 9), (0, 6), (20, 30)]), [(0, 9), (20, 30)])


class ClassifyTest(_Db):
    def test_outage_inside_own_window_is_the_box_s(self):
        self.window(T0 + H, T0 + H + 60_000)
        self.outage(T0 + H + 20_000, T0 + H + 140_000)          # ends within the 120 s grace
        r = self.report()
        self.assertEqual(r.outages, [])
        self.assertEqual(len(r.own_outages), 1)
        self.assertEqual(r.own_outages[0].cause_kind, "own")
        self.assertEqual(r.total_outage_sec, 0)
        self.assertEqual(r.uptime_pct, 100.0)
        self.assertGreater(r.own_action_sec, 0)

    def test_only_the_rest_of_a_longer_outage_counts(self):
        self.window(T0 + H, T0 + H + 60_000)
        self.outage(T0 + H + 20_000, T0 + H + 20_000 + 600_000)  # 10 min; the window + grace covers 160 s
        r = self.report()
        self.assertEqual(len(r.outages), 1)
        o = r.outages[0]
        self.assertEqual(o.cause_kind, "isp")
        self.assertEqual(o.duration_sec, 600 - 160)
        self.assertEqual(o.own_sec, 160)
        self.assertEqual(r.total_outage_sec, 440)

    def test_isp_outage_without_own_action_counts_in_full(self):
        self.outage(T0 + 5 * H, T0 + 5 * H + 300_000)
        r = self.report()
        self.assertEqual([o.duration_sec for o in r.outages], [300])
        self.assertAlmostEqual(r.uptime_pct, (1 - 300 / 86400) * 100, places=3)

    def test_legacy_mode_change_event_stands_in_before_any_recorded_window(self):
        # a mode change event marks the END of the switch; it began up to 3 minutes earlier
        self.conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'netd', 'mode_change', 'x')",
                          (T0 + 2 * H + 100_000,))
        self.outage(T0 + 2 * H, T0 + 2 * H + 90_000)
        self.assertEqual(len(self.report().own_outages), 1)

    def test_legacy_events_ignored_once_windows_are_recorded(self):
        self.window(T0 + 1000, T0 + 2000)
        self.conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'netd', 'mode_change', 'x')",
                          (T0 + 2 * H + 100_000,))
        self.outage(T0 + 2 * H, T0 + 2 * H + 90_000)
        self.assertEqual(len(self.report().outages), 1)

    def test_lost_pings_in_own_window_do_not_count(self):
        self.window(T0 + H, T0 + H + 60_000)
        self.conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, ?, 120, 120)", (T0 + H,))
        self.conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, ?, 120, 0)", (T0 + 6 * H,))
        self.assertEqual(self.report().ping_summary.loss_pct, 0.0)

    def test_outage_csv_says_the_kind(self):
        self.window(T0 + H, T0 + H + 60_000)
        self.outage(T0 + H + 20_000, T0 + H + 100_000)
        self.outage(T0 + 5 * H, T0 + 5 * H + 300_000)
        lines = csv_export.export_outages_csv(self.conn, T0, T0 + 24 * H).splitlines()
        self.assertTrue(lines[0].endswith("cause,cause_kind,counted_sec,own_action_sec"))
        kinds = sorted(l.split(",")[7] for l in lines[1:])
        self.assertEqual(kinds, ["isp", "own"])

    def test_dossier_lists_own_outages_apart(self):
        from nmb.report.dossier import DOSSIER_I18N, generate_html_dossier
        self.window(T0 + H, T0 + H + 60_000)
        self.outage(T0 + H + 20_000, T0 + H + 100_000)
        r = self.report()
        for lang in ("en", "hu", "zh"):
            html = generate_html_dossier(r, lang=lang)
            self.assertIn(DOSSIER_I18N[lang]["outage_own_tag"], html)
            self.assertIn(DOSSIER_I18N[lang]["kpi_own_sub"].split("{")[0], html)


class RecordTest(_Db):
    def test_begin_end_and_stale_windows(self):
        a = own_action.begin("mode_change", "netd", "standalone -> mode_a")
        self.assertIsNotNone(a)
        own_action.end(a)
        b = own_action.begin("netd_stop", "netd", "stop")
        self.assertEqual(own_action.close_stale(), 1)
        rows = self.conn.execute("SELECT kind, end_ts IS NOT NULL FROM own_action ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("mode_change", 1), ("netd_stop", 1)])
        kinds = [r[0] for r in self.conn.execute("SELECT kind FROM event ORDER BY id")]
        self.assertEqual(kinds, ["own_action_start", "own_action_end", "own_action_start"])
        self.assertIsNotNone(b)

    def test_a_failed_record_never_stops_the_action(self):
        with mock.patch.object(own_action, "_connect", side_effect=OSError("disk")):
            self.assertIsNone(own_action.begin("mode_change", "netd"))
            own_action.end(5)
            with own_action.window("x", "netd"):
                pass

    def test_netd_mode_switch_is_an_own_action(self):
        from nmb.netd.daemon import NetworkDaemon
        d = NetworkDaemon.__new__(NetworkDaemon)
        d.current_mode_name, d.current_mode_inst = "standalone", mock.Mock()
        d.modes = {"mode_a": mock.Mock()}
        d._record_event = mock.Mock()
        d._dump_state = mock.Mock()
        self.assertTrue(d.switch_mode("mode_a", "test"))
        row = self.conn.execute("SELECT kind, detail, end_ts IS NOT NULL FROM own_action").fetchone()
        self.assertEqual((row[0], row[2]), ("mode_change", 1))
        self.assertIn("standalone -> mode_a", row[1])

    def test_no_outage_alert_while_the_box_has_its_own_line_down(self):
        from nmb.bot.alerts import AlertMonitor
        now = db.now_ms()
        self.conn.execute("INSERT INTO own_action (start_ts, end_ts, kind, source) VALUES (?, NULL, 'mode_change', 'netd')", (now - 20_000,))
        self.conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, NULL, 'x')", (now - 5_000,))
        cfg = Config()
        cfg.telegram.allowed_chat_ids = [1]
        mon = AlertMonitor(cfg, mock.Mock())
        mon._broadcast = mock.Mock()
        mon.check_outages(self.conn)
        mon._broadcast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
