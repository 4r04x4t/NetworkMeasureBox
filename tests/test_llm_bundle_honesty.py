"""The diagnostic bundle only concludes what its data shows (data-quality list of 2026-11-10, D7/D8)."""
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.netd import interfaces
from nmb.report import llm_bundle as lb

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()
T0 = 1_794_200_000_000


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class LossPatternTest(unittest.TestCase):
    def test_bursts_in_explained_windows_leave_no_residual_loss(self):
        conn = _db()
        conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.0.2.1', 'GW', 'Local Gateway')")
        # a 290 s burst (580 samples at 0.5 s) during an own action, nothing else lost
        for i in range(580):
            conn.execute("INSERT INTO ping_sample (target_id, ts, rtt_us) VALUES (101, ?, NULL)", (T0 + 1000 + i * 500,))
        probe = {"id": 101, "sent": 100_000, "lost": 580}
        windows = [(T0, T0 + 400_000)]
        stats = lb._get_loss_pattern_telemetry(conn, T0 - 1, [probe], windows=windows, interval_ms=500)[101]
        self.assertEqual(stats["residual_loss_pct"], 0.0)
        self.assertEqual((stats["runs_total"], stats["runs_explained"]), (1, 1))
        self.assertIn("own actions", stats["pattern"])

    def test_scattered_loss_outside_windows_remains(self):
        conn = _db()
        conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.0.2.1', 'GW', 'Local Gateway')")
        for i in range(600):                                   # one lost ping every minute, outside windows
            conn.execute("INSERT INTO ping_sample (target_id, ts, rtt_us) VALUES (101, ?, NULL)", (T0 + i * 60_000,))
        probe = {"id": 101, "sent": 72_000, "lost": 600}
        stats = lb._get_loss_pattern_telemetry(conn, T0 - 1, [probe], windows=[], interval_ms=500)[101]
        self.assertAlmostEqual(stats["residual_loss_pct"], 600 / 72_000 * 100, places=2)
        self.assertEqual(stats["pattern"], "Scattered single drops")

    def test_a_target_that_never_answers_has_no_invented_streak(self):
        stats = lb._get_loss_pattern_telemetry(_db(), 0, [{"id": 7, "sent": 100, "lost": 99}])[7]
        self.assertIsNone(stats["max_consecutive"])


class PppPeerTest(unittest.TestCase):
    def test_remembered_peer_is_known_behind_another_router(self):
        conn = _db()
        with mock.patch.object(interfaces, "ppp_peer_addresses", return_value=["10.0.0.1"]):
            self.assertEqual(interfaces.known_ppp_peers(conn), ["10.0.0.1"])      # seen while dialling
        with mock.patch.object(interfaces, "ppp_peer_addresses", return_value=[]):
            self.assertEqual(interfaces.known_ppp_peers(conn), ["10.0.0.1"])      # remembered later

    def test_a_first_hop_that_never_answers_is_not_pinged(self):
        conn = _db()
        conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '10.0.0.1', 'ISP First Hop', 'ISP First Hop')")
        import time
        now = int(time.time() * 1000)
        for i in range(30):
            conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, ?, 120, 120)", (now - i * 60_000,))
        self.assertTrue(interfaces.first_hop_never_answers(conn, "10.0.0.1"))
        conn.execute("UPDATE ping_minute SET lost = 119 WHERE ts = (SELECT MAX(ts) FROM ping_minute)")
        self.assertFalse(interfaces.first_hop_never_answers(conn, "10.0.0.1"))

    def test_role_label(self):
        self.assertIn("PPP peer", lb._hop_role_label("ISP First Hop", "10.0.0.1", ["10.0.0.1"]))
        self.assertIn("Upstream", lb._hop_role_label("ISP First Hop", "10.0.0.1"))


class PmtuTest(unittest.TestCase):
    def _run(self, answers, mode):
        def fake(cmd, **kw):
            size = int(cmd[cmd.index("-s") + 1])
            return SimpleNamespace(returncode=0 if answers.get(size) else 1, stdout="", stderr="")
        with mock.patch.object(lb.subprocess, "run", side_effect=fake):
            return lb._get_path_mtu_discovery("eth0", box_mode=mode)

    def test_nothing_answers_is_unknown_not_1480(self):
        r = self._run({}, "standalone")
        self.assertIsNone(r["discovered_pmtu"])
        self.assertFalse(r["is_pppoe"])
        self.assertIn("unknown", r["note"])

    def test_advice_depends_on_who_clamps(self):
        behind = self._run({1464: True, 56: True}, "standalone")
        self.assertEqual(behind["discovered_pmtu"], 1492)
        self.assertIn("behind another router", behind["note"])
        self.assertNotIn("strongly recommended", behind["note"])
        router = self._run({1464: True, 56: True}, "mode_a")
        self.assertIn("clamps the TCP MSS", router["note"])


class VersionAndEventsTest(unittest.TestCase):
    def test_version_from_the_installed_file(self):
        with mock.patch("nmb.common.version.installed_version", return_value="abc1234"):
            self.assertEqual(lb._nmb_version(), "abc1234 (installed)")

    def test_events_query_uses_the_stored_severities(self):
        src = Path(lb.__file__).read_text()
        self.assertIn("severity IN ('warn', 'crit')", src)
        self.assertIn("'own_action_start'", src)


if __name__ == "__main__":
    unittest.main()
