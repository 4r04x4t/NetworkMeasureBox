"""Outages are found when the route disappears and when only the local gateway still answers (2026-11-10)."""
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from nmb.probe import engine as E
from nmb.report import metrics

SCHEMA = (Path(E.__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


def _probe(roles):
    p = E.ProbeEngine.__new__(E.ProbeEngine)
    p.targets = {i + 1: E.TargetState(id=i + 1, addr=f"192.0.2.{i + 1}", label=r, role=r) for i, r in enumerate(roles)}
    p.outage_loss_ticks = 3
    return p


class OutageDecisionTest(unittest.TestCase):
    def test_gateway_answering_does_not_hide_an_internet_outage(self):
        p = _probe(["Local Gateway", "Public DNS", "Public DNS"])
        p.targets[2].consecutive_loss = p.targets[3].consecutive_loss = 5
        down, cause = p._outage_state()
        self.assertTrue(down)
        self.assertIn("local gateway answers", cause)

    def test_everything_lost(self):
        p = _probe(["Local Gateway", "Public DNS"])
        for t in p.targets.values():
            t.consecutive_loss = 5
        self.assertEqual(p._outage_state(), (True, "all probe targets unreachable"))

    def test_one_internet_target_answering_is_no_outage(self):
        p = _probe(["Local Gateway", "Public DNS", "Public DNS"])
        p.targets[2].consecutive_loss = 5
        self.assertFalse(p._outage_state()[0])

    def test_only_gateways_configured(self):
        p = _probe(["Local Gateway"])
        p.targets[1].consecutive_loss = 5
        self.assertTrue(p._outage_state()[0])

    def test_failed_send_counts_as_lost(self):
        p = _probe(["Public DNS"])
        p.ident, p.seq, p.is_raw, p.timeout_sec = 1, 0, False, 1.5
        p.pending_pings, p.sample_queue = {}, []
        p.sock = mock.Mock()
        p.sock.sendto.side_effect = OSError(101, "Network is unreachable")
        for _ in range(3):
            p._send_probes()
        self.assertEqual(p.targets[1].consecutive_loss, 3)
        self.assertTrue(p._outage_state()[0])


class OutageEndTest(unittest.TestCase):
    def test_gateway_answers_do_not_end_an_open_outage(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.168.1.1', 'gw', 'Local Gateway'), (102, '198.51.100.9', 'net', 'Public DNS')")
        conn.execute("INSERT INTO outage (id, start_ts, cause) VALUES (7, 1000, 'x')")
        conn.execute("INSERT INTO ping_minute (ts, target_id, sent, lost) VALUES (60000, 101, 60, 0), (60000, 102, 60, 60)")
        rows = conn.execute("SELECT * FROM outage").fetchall()
        self.assertIsNone(metrics.effective_outage_ends(conn, rows, 999999)[7])
        conn.execute("INSERT INTO ping_minute (ts, target_id, sent, lost) VALUES (120000, 102, 60, 10)")
        self.assertEqual(metrics.effective_outage_ends(conn, rows, 999999)[7], 120000)


if __name__ == "__main__":
    unittest.main()
