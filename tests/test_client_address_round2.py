"""Second data-quality round (2026-11-10): the iPerf3 client address, LAN tests, the bot's status codes,
and the collector's corrections behind a box-to-token binding."""
import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _box_isolation  # noqa: F401  (private measurement lock on a working box)

from nmb.common import netaddr

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


class AddressRuleTest(unittest.TestCase):
    def test_local_server_gives_the_local_address(self):
        with mock.patch.object(netaddr, "lookup_public_ip") as look:
            self.assertEqual(netaddr.client_address_for_test("192.168.8.218", "192.168.8.20"),
                             ("192.168.8.218", None, "local"))
            self.assertEqual(netaddr.client_address_for_test("fd00::5", "fd00::1"), (None, "fd00::5", "local"))
        look.assert_not_called()

    def test_internet_server_behind_nat_asks_over_the_same_source(self):
        with mock.patch.object(netaddr, "lookup_public_ip", return_value="198.51.100.7") as look:
            self.assertEqual(netaddr.client_address_for_test("192.168.8.218", "203.0.113.50"),
                             ("198.51.100.7", None, "lookup"))
        look.assert_called_once_with("192.168.8.218")

    def test_public_source_address_is_used_as_is(self):
        with mock.patch.object(netaddr, "lookup_public_ip") as look:
            self.assertEqual(netaddr.client_address_for_test("2001:db8::9", "2001:db8:1::1"),
                             (None, "2001:db8::9", "socket"))
        look.assert_not_called()

    def test_failed_lookup_is_empty_never_the_lan_address(self):
        with mock.patch.object(netaddr, "lookup_public_ip", return_value=None):
            self.assertEqual(netaddr.client_address_for_test("192.168.8.218", "203.0.113.50"), (None, None, None))

    def test_cgnat_server_is_not_local(self):
        self.assertFalse(netaddr.is_local_ip("100.64.1.1"))
        self.assertTrue(netaddr.is_local_ip("10.1.2.3"))


class IperfRowTest(unittest.TestCase):
    def _run(self, remote, lookup):
        from nmb.speed import runner
        conn = _db()
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"),
                              iperf=SimpleNamespace(target_host=remote, target_port=5201, duration=10, protocol="tcp",
                                                    parallel=4, reverse=False, bidir=False, auto_direction="download"))
        fake = {"status": "ok", "bps": 9e8, "local_host": "192.168.8.218", "remote_host": remote}
        with mock.patch("nmb.speed.iperf.run_iperf_client_test", return_value=fake), \
                mock.patch("nmb.common.netaddr.lookup_public_ip", return_value=lookup), \
                mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", None, True)):
            runner._run_single_engine("iperf3", cfg, "schedule", None, conn, 1, target_iface=None)
        return conn.execute("SELECT client_ip, client_ip_source FROM speedtest").fetchone()

    def test_lan_server(self):
        self.assertEqual(tuple(self._run("192.168.8.20", None)), ("192.168.8.218", "local"))

    def test_internet_server(self):
        self.assertEqual(tuple(self._run("203.0.113.50", "198.51.100.7")), ("198.51.100.7", "lookup"))


class LanTestNotCountedTest(unittest.TestCase):
    def test_lan_iperf_is_listed_but_not_in_the_line_s_figures(self):
        from nmb.config import Config
        from nmb.report.metrics import aggregate_report_data
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, client_ip, client_ip_source) "
                     "VALUES (1794222900000, 'schedule', 'ok', 'iperf3', 940000000, '192.168.8.218', 'local')")
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, up_bps, client_ip_source) "
                     "VALUES (1794222960000, 'schedule', 'ok', 'cloudflare', 500000000, 300000000, 'engine')")
        cfg = Config()
        cfg.isp.contract_down_mbps, cfg.isp.contract_up_mbps = 1000.0, 300.0
        r = aggregate_report_data(conn, cfg, window_hours=24, end_ms=1794222960000 + 1000)
        self.assertEqual(len(r.speed_tests), 2)
        self.assertEqual([t["scope"] for t in r.speed_tests], ["internet", "lan"])
        self.assertEqual(r.speed_summary.successful_tests, 1)
        self.assertEqual(r.speed_summary.avg_down_mbps, 500.0)
        # 500 < 80 % of 1000: not compliant; with a 400 Mbit/s guaranteed speed it is
        self.assertEqual(r.speed_summary.sla_compliance_pct, 0.0)
        cfg.isp.guaranteed_down_mbps, cfg.isp.guaranteed_up_mbps = 400.0, 100.0
        r = aggregate_report_data(conn, cfg, window_hours=24, end_ms=1794222960000 + 1000)
        self.assertEqual(r.speed_summary.sla_compliance_pct, 100.0)

    def test_speed_csv_says_where_the_address_came_from(self):
        from nmb.report.csv_export import export_speedtests_csv
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, client_ip_source) VALUES (1, 'manual', 'ok', 'iperf3', 'local')")
        head, row = [l.split(",") for l in export_speedtests_csv(conn, 0, 10).splitlines()]
        self.assertEqual(dict(zip(head, row))["client_ip_source"], "local")


class BotCodeTest(unittest.TestCase):
    def test_codes_do_not_mean_something_else_than_in_the_dossier(self):
        from nmb.bot.i18n import SUPPORTED_LANGUAGES, get_measurement_status
        for lang in SUPPORTED_LANGUAGES:
            for code in ("6d", "6u", 6):
                text = get_measurement_status(code, lang)[1]
                self.assertTrue(text.startswith(("6:", "6：")), (lang, code, text))
        src = (Path(__file__).resolve().parent.parent / "nmb" / "bot" / "commands.py").read_text()
        self.assertNotIn("status_code = 14", src)
        self.assertNotIn("status_code = 15", src)


class CollectorTest(unittest.TestCase):
    UID = "nmb-abcd-efgh-jkmn"

    def _server_db(self):
        from nmb.collector import server
        conn = sqlite3.connect(":memory:")
        conn.executescript(server.SCHEMA)
        return conn

    def _payload(self, **extra):
        return {"box_uid": self.UID, "speedtests": [{"id": 7, "ts": 1, "status": "ok", "engine": "rtr", "loss_pct": 0.0,
                                                     "server_location": "Vienna, Austria (BEREC Cluster)"}], **extra}

    def test_another_valid_token_cannot_write_into_a_box(self):
        from nmb.collector import server
        conn = self._server_db()
        server.ingest(conn, self._payload(), "team-a", "192.0.2.1", active_tokens={"team-a", "team-b"})
        with self.assertRaises(PermissionError):
            server.ingest(conn, self._payload(), "team-b", "192.0.2.2", active_tokens={"team-a", "team-b"})
        # once team-a's token is revoked, the box may move to another token
        server.ingest(conn, self._payload(), "team-b", "192.0.2.2", active_tokens={"team-b"})

    def test_corrections_clear_the_made_up_values_of_the_box_s_own_rows(self):
        from nmb.collector import server
        conn = self._server_db()
        server.ingest(conn, self._payload(), "team-a", "192.0.2.1", active_tokens={"team-a"})
        out = server.ingest(conn, {"box_uid": self.UID, "corrections": [
            {"id": 7, "field": "loss_pct", "value": None},
            {"id": 7, "field": "server_location", "value": None},
            {"id": 7, "field": "box_uid", "value": "nmb-other-box-xx"},          # not a correctable field
            {"id": 8, "field": "loss_pct", "value": None}]}, "team-a", "192.0.2.1", active_tokens={"team-a"})
        self.assertEqual(out["corrected"], 2)
        row = conn.execute("SELECT loss_pct, server_location, box_uid FROM speedtest WHERE src_id = 7").fetchone()
        self.assertEqual(row, (None, None, self.UID))

    def test_client_sends_corrections_only_for_rows_already_sent(self):
        from nmb.collector import client
        from nmb.db import corrections
        conn = _db()
        for i in (1, 2):
            conn.execute("INSERT INTO speedtest (id, ts, trigger, status, engine, loss_pct) VALUES (?, 1, 'schedule', 'ok', 'rtr', 0.0)", (i,))
        conn.execute("INSERT INTO kv (k, v, ts) VALUES (?, '1', 1)", (client.KV_LAST_SPEED,))
        conn.commit()
        corrections.apply(conn)
        cfg = SimpleNamespace(collector=SimpleNamespace(share_diagnostics=False, case_id="", allow_remote_control=False),
                              system=SimpleNamespace(box_id="nmb-01"), isp=None)
        with mock.patch.object(client, "box_uid", return_value=self.UID):
            payload = client.build_payload(conn, cfg)
        self.assertEqual([(c["id"], c["field"]) for c in payload["corrections"]], [(1, "loss_pct")])
        self.assertIsNotNone(payload["_correction_cursor"])
        self.assertEqual([r["id"] for r in payload["speedtests"]], [2])
        self.assertIsNone(payload["speedtests"][0]["loss_pct"])           # unsent rows go corrected anyway


if __name__ == "__main__":
    unittest.main()
