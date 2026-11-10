"""Fixes for what the independent review of the 2026-11-10 data-quality work confirmed."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _box_isolation  # noqa: F401  (private measurement lock on a working box)

from nmb.config import Config
from nmb.db import corrections
from nmb.db import database as db
from nmb.report import metrics

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()
T0 = 1_794_200_000_000
H = 3_600_000


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _report(conn, cfg=None):
    return metrics.aggregate_report_data(conn, cfg or Config(), window_hours=24, end_ms=T0 + 24 * H)


class VerdictTest(unittest.TestCase):
    def test_no_data_is_no_verdict(self):
        r = _report(_db())
        self.assertEqual(r.sla_verdict, "UNKNOWN")       # it said COMPLIANT with 100 % and 0 %
        self.assertEqual(r.speed_summary.judged_tests, 0)

    def test_unmeasured_direction_is_not_judged(self):
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps) VALUES (?, 'schedule', 'ok', 'iperf3', 900000000)",
                     (T0 + H,))
        cfg = Config()
        cfg.isp.contract_down_mbps, cfg.isp.contract_up_mbps = 1000.0, 300.0
        r = _report(conn, cfg)
        self.assertEqual((r.speed_summary.judged_tests, r.speed_summary.sla_compliance_pct), (1, 100.0))


class LanScopeTest(unittest.TestCase):
    def test_legacy_lan_iperf_row_is_lan(self):
        from nmb.report.status_codes import speed_scope
        self.assertEqual(speed_scope({"engine": "iperf3", "server_host": "192.168.8.20"}), "lan")
        self.assertEqual(speed_scope({"engine": "iperf3", "server_host": "192.168.8.20:5201"}), "lan")
        self.assertEqual(speed_scope({"engine": "iperf3", "server_host": "203.0.113.5"}), "internet")
        self.assertEqual(speed_scope({"engine": "rtr", "server_host": "vie2-httpv4.netztest.at:443"}), "internet")

    def test_detailed_csv_does_not_judge_a_lan_test(self):
        from nmb.report.csv_export import export_detailed_speedtests_csv
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, server_host, client_ip, client_ip_source) "
                     "VALUES (1, 'manual', 'ok', 'iperf3', 100000000, '192.168.8.20', '192.168.8.218', 'local')")
        row = export_detailed_speedtests_csv(conn, 0, 10, contract_down_mbps=1000, guaranteed_down_mbps=300,
                                             default_isp="ISP").lstrip("﻿").splitlines()[1].split(";")
        self.assertEqual((row[2], row[4], row[8]), ("LAN", "--", ""))
        self.assertIn("not judged", row[10])

    def test_lan_server_is_not_named_after_the_box_s_town(self):
        from nmb.speed import iperf_directory as d
        d._label_cache.clear()
        with mock.patch.object(d, "socket", create=True), \
                mock.patch("socket.gethostbyname", return_value="192.168.8.20"), \
                mock.patch("nmb.netd.geoip.get_public_geoip") as geo:
            out = d.describe_server("192.168.8.20", 5201)
        geo.assert_not_called()
        self.assertEqual(out["source"], "lan")


class DossierTest(unittest.TestCase):
    def test_nothing_invented_in_the_tables(self):
        from nmb.report.dossier import generate_html_dossier
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, server_host, client_ip, client_ip_source) "
                     "VALUES (?, 'manual', 'ok', 'iperf3', 900000000, '192.168.8.20', '192.168.8.218', 'local')", (T0 + H,))
        html = generate_html_dossier(_report(conn), lang="en")
        self.assertNotIn("<td>0.00%</td>", html)          # invented minimum loss
        import re
        self.assertIsNone(re.search(r"(?<![0-9])0\.00 Mb/s", html))
        self.assertIn("· LAN", html)
        self.assertNotIn("(90%)", html)                    # no share of the ISP's speed for a LAN test

    def test_charts_leave_out_lan_tests_and_unmeasured_directions(self):
        from nmb.report.svg_charts import render_compliance_chart, render_speedtest_chart
        tests = [{"status": "ok", "scope": "lan", "down_mbps": 940.0, "up_mbps": 940.0, "ts": T0},
                 {"status": "ok", "scope": "internet", "down_mbps": 500.0, "up_mbps": None, "ts": T0 + 1}]
        bars = render_speedtest_chart(tests, 1000, 300, 0, 0)
        self.assertNotIn("940.0 Mbps", bars)
        self.assertNotIn("Upload: 0.0", bars)
        comp = render_compliance_chart(tests, 1000, 300)
        self.assertNotIn("stroke-dasharray=\"3,3\" stroke-linecap", comp.split("<g")[0].replace('d=""', ""))


class IspNameTest(unittest.TestCase):
    def test_no_lookup_of_today_s_address_for_a_row_without_one(self):
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps) VALUES (?, 'schedule', 'ok', 'rtr', 1)", (T0 + H,))
        cfg = Config()
        cfg.isp.name = ""
        with mock.patch("nmb.netd.geoip.get_public_geoip") as geo:
            r = _report(conn, cfg)
        geo.assert_not_called()
        self.assertEqual(r.speed_tests[0]["isp_name"], "")


class SmtpTest(unittest.TestCase):
    def test_texts_follow_the_settings(self):
        from nmb.report.smtp import format_plain_text_summary
        cfg = Config()
        cfg.speedtest.idle_threshold_mode, cfg.speedtest.idle_threshold_percent = "percent", 2.0
        text = format_plain_text_summary(_report(_db()), cfg)
        self.assertNotIn("500 kbps", text)
        self.assertNotIn("80% SLA threshold", text)
        self.assertIn("2 %", text)


class OwnWindowTest(unittest.TestCase):
    def test_a_failover_does_not_hide_the_line_s_outage(self):
        conn = _db()
        # the line fails at T0+1h; 40 s later the box fails over to USB (a reaction, not its own doing)
        conn.execute("INSERT INTO own_action (start_ts, end_ts, kind, source) VALUES (?, ?, 'failover_rebuild', 'netd')",
                     (T0 + H + 40_000, T0 + H + 70_000))
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, ?, 'x')", (T0 + H, T0 + H + 100_000))
        r = _report(conn)
        self.assertEqual([o.duration_sec for o in r.outages], [100])

    def test_an_outage_that_began_before_an_own_window_stays_the_line_s(self):
        conn = _db()
        conn.execute("INSERT INTO own_action (start_ts, end_ts, kind, source) VALUES (?, ?, 'mode_change', 'netd')",
                     (T0 + H + 60_000, T0 + H + 61_000))
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, ?, 'x')", (T0 + H, T0 + H + 150_000))
        r = _report(conn)
        self.assertEqual(len(r.outages), 1)
        self.assertEqual(r.own_outages, [])


class RunnerTest(unittest.TestCase):
    def test_engine_due_counts_the_run_s_start(self):
        from nmb.speed import runner
        conn = _db()
        # last hourly run started at T0, iPerf3 itself 3 minutes into it
        conn.execute("INSERT INTO speedtest (ts, cycle_ts, trigger, status, engine) VALUES (?, ?, 'schedule', 'ok', 'iperf3')",
                     (T0 + 180_000, T0))
        cfg = SimpleNamespace(speedtest=SimpleNamespace(iperf3_interval_min=60))
        self.assertTrue(runner._engine_due(conn, cfg, "iperf3", T0 + H))

    def test_aborted_row_has_its_facts(self):
        from nmb.speed import runner
        conn = _db()
        with mock.patch.object(runner, "_nmb_version", return_value="abc1234"):
            runner._record_aborted(conn, "schedule", "rtr", 1000, "aborted: x", started_ms=5000)
        row = conn.execute("SELECT ts, cycle_ts, nmb_version FROM speedtest").fetchone()
        self.assertEqual(tuple(row), (5000, 1000, "abc1234"))


class CorrectionPassBTest(unittest.TestCase):
    def test_second_pass(self):
        conn = _db()
        rows = [
            ("cloudflare", T0, 8000, 0, 8.0, 8.0, "A+", 0.0, None, None, None, None),
            ("rtr", T0, 15000, None, None, None, None, None, json.dumps({"engine": "rtr-nettest", "ping_min_ms": 15.0, "ping_median_ms": 15.0}), None, None, None),
            ("iperf3", T0, None, None, None, None, None, None, None, "192.168.8.20", None, "192.168.8.218"),
            ("cloudflare", corrections.CLOUDFLARE_FIX_MS + 1, 8000, 400, 8.0, 20.0, "A", 12.0, None, None, None, None),
        ]
        for eng, ts, ping, jit, dl, ul, gr, de, raw, host, cip, bip in rows:
            conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, ping_us, jitter_us, down_loaded_lat_ms, up_loaded_lat_ms, "
                         "bufferbloat_grade, bufferbloat_delta_ms, raw_json, server_host, client_ip, bound_ip) "
                         "VALUES (?, 'schedule', 'ok', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (ts, eng, ping, jit, dl, ul, gr, de, raw, host, cip, bip))
        conn.execute("INSERT INTO kv (k, v, ts) VALUES (?, '0', 1)", (corrections.MARKER,))   # pass 1 ran before
        conn.commit()
        corrections.apply(conn)
        get = lambda i, f: conn.execute(f"SELECT {f} FROM speedtest WHERE id = ?", (i,)).fetchone()[0]
        self.assertIsNone(get(1, "jitter_us"))
        self.assertIsNone(get(1, "down_loaded_lat_ms")); self.assertIsNone(get(1, "bufferbloat_grade"))
        self.assertIsNone(get(2, "ping_us"))
        self.assertEqual((get(3, "client_ip_source"), get(3, "client_ip")), ("local", "192.168.8.218"))
        self.assertEqual((get(4, "jitter_us"), get(4, "bufferbloat_grade")), (400, "A"))      # newer: untouched
        self.assertEqual(corrections.apply(conn), 0)


class CollectorPollTest(unittest.TestCase):
    def test_poll_only_for_the_box_s_own_token(self):
        from nmb.collector import server
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(server.SCHEMA)
        uid = "nmb-abcd-efgh-jkmn"
        server.ingest(conn, {"box_uid": uid}, "team-a", "192.0.2.1", active_tokens={"team-a", "team-b"})
        with self.assertRaises(PermissionError):
            server.poll(conn, {"box_uid": uid, "allow_remote_control": True}, "team-b", {"team-a", "team-b"})
        self.assertEqual(server.poll(conn, {"box_uid": uid, "allow_remote_control": True}, "team-a", {"team-a", "team-b"}), [])

    def test_summary_leaves_out_lan_tests(self):
        from nmb.collector import server
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(server.SCHEMA)
        uid = "nmb-abcd-efgh-jkmn"
        import time
        now = int(time.time() * 1000)
        server.ingest(conn, {"box_uid": uid, "speedtests": [
            {"id": 1, "ts": now, "status": "ok", "engine": "iperf3", "down_bps": 940_000_000, "client_ip_source": "local"},
            {"id": 2, "ts": now, "status": "ok", "engine": "rtr", "down_bps": 500_000_000, "client_ip_source": "lookup"}]},
            "team-a", "192.0.2.1", active_tokens={"team-a"})
        s = server.box_summary(conn, uid)
        self.assertEqual(s["ok_tests"], 1)
        self.assertEqual(s["avg_down_bps"], 500_000_000)


class BotTestCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = str(Path(self.tmp.name) / "nmb.db")
        p = mock.patch.dict(os.environ, {"NMB_LIVE_DB": path, "NMB_PERSIST_DB": path})
        p.start()
        self.addCleanup(p.stop)
        conn = db.connect()
        db.init(conn)
        conn.close()

    @mock.patch("nmb.bot.commands.run_measurement_cycle", return_value=True)
    def test_unmeasured_upload_is_no_deficit(self, _cycle):
        from nmb.bot.commands import CommandHandler
        from tests.test_telegram_bot import MockTelegramClient
        conn = db.connect()
        with db.tx(conn):
            conn.execute("INSERT INTO speedtest (ts, trigger, status, down_bps, up_bps, ping_us, engine) "
                         "VALUES (?, 'telegram', 'ok', 900000000, NULL, NULL, 'iperf3')", (db.now_ms(),))
        conn.close()
        cfg = Config()
        cfg.telegram.allowed_chat_ids = [1]
        cfg.isp.guaranteed_down_mbps, cfg.isp.guaranteed_up_mbps = 300.0, 50.0
        client = MockTelegramClient()
        CommandHandler(cfg, client).handle_command(1, "/test iperf3")
        text = client.sent_messages[-1][1]
        self.assertIn("900.0 Mbps", text)
        self.assertNotIn("0.0 Mbps", text.replace("900.0 Mbps", ""))
        self.assertNotIn("UPLOAD DEFICIT", text)


if __name__ == "__main__":
    unittest.main()


class ServerFactsTest(unittest.TestCase):
    def test_server_address_and_all_fast_com_servers_in_the_csv(self):
        from nmb.report.csv_export import export_detailed_speedtests_csv, export_speedtests_csv
        conn = _db()
        raw = json.dumps({"engine": "fastcom", "servers": [{"host": "203.0.113.1"}, {"host": "203.0.113.2"}]})
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, server_name, server_host, server_ip, raw_json) "
                     "VALUES (1, 'manual', 'ok', 'fastcom', 'Fast.com (Netflix)', 'oca.example', '203.0.113.1', ?)", (raw,))
        head, row = [l.split(",") for l in export_speedtests_csv(conn, 0, 10).splitlines()]
        r = dict(zip(head, row))
        self.assertEqual((r["server_ip"], r["servers_all"]), ("203.0.113.1", "203.0.113.1 203.0.113.2"))
        d_head, d_row = [l.split(";") for l in export_detailed_speedtests_csv(conn, 0, 10).lstrip("﻿").splitlines()]
        self.assertEqual(dict(zip(d_head, d_row))["Server address"], "203.0.113.1")

    def test_rtr_names_its_measurement_server(self):
        from nmb.speed import rtr
        final = {"type": "FINAL_RESULT", "down": 80.0, "up": 9.0, "pingMedian": 10.0, "pingMin": 9.0, "pingJitter": 0.3, "pingCount": 10}
        out = "Server:   vie2-httpv4.netztest.at:443 (TLS)\n" + json.dumps(final) + "\n"
        with mock.patch.object(rtr, "find_native_rmbt_client", return_value="/x/rmbt"), \
                mock.patch.object(rtr.cancel, "run", return_value=SimpleNamespace(stdout=out, stderr="", returncode=0)), \
                mock.patch.object(rtr, "_client_ips", return_value=(None, None)):
            res = rtr._run_native_rmbt_speedtest("https://c01v4.netztest.at", 7, 3, "eth0", "192.0.2.2")
        self.assertEqual(res.server_name, "RTR-NetTest (vie2-httpv4.netztest.at)")
        self.assertIsNone(res.server_ip)                    # a host name, no address was reported

    def test_cloudflare_records_the_edge_address_it_used(self):
        from nmb.speed import cloudflare
        cloudflare._peer_ips.clear()
        sock = SimpleNamespace(getpeername=lambda: ("198.51.100.20", 443))
        cloudflare._note_peer(sock); cloudflare._note_peer(sock)
        res = cloudflare.CloudflareSpeedResult(status="ok", server_ips=["198.51.100.20"]).to_speedtest_result()
        self.assertEqual(res.server_ip, "198.51.100.20")

    def test_ping_csv_is_streamed_in_pieces(self):
        from nmb.report.csv_export import iter_ping_summary_csv
        conn = _db()
        conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.0.2.1', 'x', 'Public DNS')")
        for i in range(4500):
            conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, ?, 120, 0)", (i * 60_000,))
        conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, ?, 0, 0)", (5000 * 60_000,))
        parts = list(iter_ping_summary_csv(conn, 0, 10 ** 12, batch=2000))
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(p.count("\n") for p in parts), 4502)
        self.assertEqual(parts[-1].splitlines()[-1].split(",")[7], "")       # no pings: no loss figure

    def test_dossier_states_no_unchecked_conformity(self):
        from nmb.report.dossier import DOSSIER_I18N, generate_html_dossier
        html = generate_html_dossier(_report(_db()), lang="en")
        self.assertNotIn("BEREC compliant", html)
        self.assertNotIn("v2.5", html)
        for lang, tr in DOSSIER_I18N.items():
            self.assertNotIn("strictly", tr["legal_appendix_body"])
        self.assertNotIn("2003. évi C. törvény", DOSSIER_I18N["hu"]["legal_appendix_body"])


class DossierEscapeTest(unittest.TestCase):
    def test_values_are_escaped_once(self):
        from nmb.report.dossier import generate_html_dossier
        conn = _db()
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, server_name, server_ip) "
                     "VALUES (?, 'manual', 'ok', 'ookla', 1, 'A & B <x>', '203.0.113.9')", (T0 + H,))
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, ?, 'cut & <y>')", (T0 + 2 * H, T0 + 2 * H + 90_000))
        html = generate_html_dossier(_report(conn), lang="en")
        self.assertIn("A &amp; B &lt;x&gt;", html)
        self.assertNotIn("&amp;amp;", html)
        self.assertIn("cut &amp; &lt;y&gt;", html)
        self.assertIn("<code>203.0.113.9</code>", html)
