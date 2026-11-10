"""CSV exports: old columns keep their place, new facts appended, ranges, events, formula safety (2026-11-10)."""
import csv
import io
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _box_isolation  # noqa: F401  (private measurement lock on a working box)

from nmb.report import csv_export as ce

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()
OLD_SPEED_HEADER = [
    "timestamp_iso", "timestamp_ms", "trigger", "status", "engine", "colo", "connection_type",
    "client_ip", "client_ipv6", "isp_name", "down_mbps", "up_mbps", "down_pct_of_offered", "up_pct_of_offered", "ping_ms",
    "jitter_ms", "loss_pct", "bufferbloat_grade", "bufferbloat_delta_ms", "down_loaded_lat_ms", "up_loaded_lat_ms",
    "server_id", "server_name", "server_host", "server_location", "result_url", "error"]


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _rows(text, delim=","):
    return list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=delim))


class RangeTest(unittest.TestCase):
    NOW = 1_794_300_000_000

    def test_defaults(self):
        self.assertEqual(ce.parse_export_range({}, self.NOW, 24.0), (self.NOW - 86_400_000, self.NOW))
        self.assertEqual(ce.parse_export_range({}, self.NOW, None), (0, self.NOW))

    def test_days_dates_and_epoch(self):
        self.assertEqual(ce.parse_export_range({"days": ["7"]}, self.NOW, 24.0)[0], self.NOW - 7 * 86_400_000)
        start, end = ce.parse_export_range({"from": ["2026-11-01"], "to": ["2026-11-01"]}, self.NOW, None)
        self.assertEqual(end - start, 86_400_000 - 1)                  # the whole day, UTC
        self.assertEqual(ce.parse_export_range({"from": ["5"], "to": ["9"]}, self.NOW, None), (5, 9))

    def test_bad_input_refused(self):
        for qs in ({"from": ["yesterday"]}, {"days": ["-1"]}, {"hours": ["0"]}, {"from": ["9"], "to": ["5"]}):
            with self.assertRaises(ValueError, msg=qs):
                ce.parse_export_range(qs, self.NOW, None)


class SpeedCsvTest(unittest.TestCase):
    def test_old_columns_first_then_the_new_facts(self):
        conn = _db()
        conn.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'standalone', 1)")
        conn.execute(
            "INSERT INTO speedtest (ts, trigger, status, engine, down_bps, up_bps, bound_iface, bound_ip, retransmits, "
            "tcp_window, cycle_ts, duration_ms, nmb_version, box_mode) VALUES "
            "(1794222960000, 'schedule', 'ok', 'cloudflare', 900000000, 300000000, 'eth0', '192.168.8.2', 0, NULL, "
            "1794222900000, 31500, 'abc1234', 'standalone')")
        rows = _rows(ce.export_speedtests_csv(conn, 0, 2 ** 62, box_id="nmb-01"))
        head, row = rows[0], dict(zip(rows[0], rows[1]))
        self.assertEqual(head[:27], OLD_SPEED_HEADER)
        self.assertEqual(head[27:], ["row_id", "time_zone", "cycle_time_iso", "duration_s", "bound_iface", "bound_ip",
                                     "retransmits", "tcp_window", "box_id", "nmb_version", "box_mode",
                                     "client_ip_source", "server_ip", "servers_all"])
        self.assertEqual(row["cycle_time_iso"], "2026-11-09T11:15:00+00:00")
        self.assertEqual(row["timestamp_iso"], "2026-11-09T11:16:00+00:00")   # the engine's own start
        self.assertEqual((row["duration_s"], row["retransmits"], row["box_mode"]), ("31.5", "0", "standalone"))
        self.assertEqual((row["box_id"], row["nmb_version"], row["time_zone"]), ("nmb-01", "abc1234", "UTC"))

    def test_formula_text_from_outside_is_never_a_formula(self):
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, server_name, error) "
                     "VALUES (1, 'manual', 'error', 'ookla', '=HYPERLINK(\"x\")', '+cmd')")
        row = dict(zip(*_rows(ce.export_speedtests_csv(conn, 0, 2 ** 62))))
        self.assertEqual(row["server_name"], "'=HYPERLINK(\"x\")")
        self.assertEqual(row["error"], "'+cmd")


class EventsAndPingTest(unittest.TestCase):
    def test_events_csv(self):
        conn = _db()
        conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (5, 'info', 'netd', 'mode_change', '@x')")
        rows = _rows(ce.export_events_csv(conn, 0, 10))
        self.assertEqual(rows[0], ["event_id", "time_iso", "time_ms", "time_zone", "severity", "source", "kind", "detail"])
        self.assertEqual(rows[1][6:], ["mode_change", "'@x"])

    def test_ping_csv_has_the_target_role(self):
        conn = _db()
        conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.0.2.1', 'GW', 'Local Gateway')")
        conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, 60000, 120, 0)")
        rows = _rows(ce.export_ping_summary_csv(conn, 0, 10 ** 6))
        self.assertEqual(rows[0][-2:], ["target_role", "time_zone"])
        self.assertEqual(rows[1][-2:], ["Local Gateway", "UTC"])


class RunnerRowTest(unittest.TestCase):
    def test_each_engine_has_its_own_start_and_the_run_s_start(self):
        from nmb.speed import runner
        conn = _db()
        conn.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'mode_a', 1)")
        conn.commit()
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"),
                              iperf=SimpleNamespace(target_host="iperf.example", target_port=5201, duration=10,
                                                    protocol="tcp", parallel=4, reverse=False, bidir=False,
                                                    auto_direction="download"))
        with mock.patch("nmb.speed.iperf.run_iperf_client_test", return_value={"status": "ok", "bps": 9e8}), \
                mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", None, True)), \
                mock.patch.object(runner, "_nmb_version", return_value="abc1234"):
            runner._run_single_engine("iperf3", cfg, "schedule", None, conn, 1000, target_iface=None)
        row = conn.execute("SELECT ts, cycle_ts, duration_ms, nmb_version, box_mode FROM speedtest").fetchone()
        self.assertEqual(row["cycle_ts"], 1000)
        self.assertGreater(row["ts"], 1000)                            # not the run's start any more
        self.assertIsNotNone(row["duration_ms"])
        self.assertEqual((row["nmb_version"], row["box_mode"]), ("abc1234", "mode_a"))


class VersionTest(unittest.TestCase):
    def test_installed_version_from_the_updater_file(self):
        from nmb.common import updater, version
        with mock.patch.object(updater, "COMMIT_FILE", SimpleNamespace(read_text=lambda **k: "d3703b13446db375ac\n")):
            self.assertEqual(version.installed_version(), "d3703b1")


if __name__ == "__main__":
    unittest.main()
