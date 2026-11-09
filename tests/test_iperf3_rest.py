"""A public iPerf3 server that fails every test is rested (2026-11-08: 282 of 283 failed, tried every minute)."""
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nmb.speed import runner


def _db(rows):
    conn = sqlite3.connect(":memory:")
    conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
    for ts, status, host in rows:
        conn.execute("INSERT INTO speedtest(ts, trigger, status, engine, server_host) VALUES (?, 'schedule', ?, 'iperf3', ?)",
                     (ts, status, host))
    return conn


class Iperf3RestTest(unittest.TestCase):
    def test_five_failures_in_a_row_rest_the_server(self):
        now = 10_000_000
        conn = _db([(now - i * 60000, "error", "185.3.160.57") for i in range(5, 0, -1)])
        self.assertTrue(runner._iperf3_failing(conn, "185.3.160.57", now))
        self.assertFalse(runner._iperf3_failing(conn, "96.45.41.167", now))

    def test_one_success_or_old_failures_keep_it(self):
        now = 100_000_000_000
        rows = [(now - i * 60000, "error", "h") for i in range(5, 1, -1)] + [(now - 60000, "ok", "h")]
        self.assertFalse(runner._iperf3_failing(_db(rows), "h", now))
        old = [(now - 7 * 3600_000 - i, "error", "h") for i in range(5)]
        self.assertFalse(runner._iperf3_failing(_db(old), "h", now))   # tried again after 6 h

    def test_rested_server_is_left_out_of_the_schedule(self):
        cfg = SimpleNamespace(iperf=SimpleNamespace(target_host="good", target_port=5201, extra_servers="bad:5201"))
        with patch.object(runner, "_answers", return_value=True), \
             patch.object(runner, "_iperf3_failing", side_effect=lambda conn, h: h == "bad"):
            self.assertEqual(runner._usable_iperf3_servers(cfg, object()), [("good", 5201)])


if __name__ == "__main__":
    unittest.main()
