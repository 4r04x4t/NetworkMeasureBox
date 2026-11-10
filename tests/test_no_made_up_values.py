"""No value is stored or exported that was not measured (data-quality list of 2026-11-10, D1-D9)."""
import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _box_isolation  # noqa: F401  (private measurement lock on a working box)

from nmb.common.netaddr import global_ip, split_global
from nmb.db import corrections
from nmb.report import csv_export
from nmb.report.status_codes import classify
from nmb.speed import cloudflare, ookla, rtr

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class AddressTest(unittest.TestCase):
    def test_only_public_addresses(self):
        for private in ("192.168.8.218", "10.0.0.1", "100.64.3.4", "fe80::1", "fd42::1", "127.0.0.1", "x", ""):
            self.assertIsNone(global_ip(private), private)
        self.assertEqual(global_ip("8.8.8.8"), "8.8.8.8")
        self.assertEqual(split_global("2606:4700::1111"), (None, "2606:4700::1111"))


class BufferbloatTest(unittest.TestCase):
    def test_no_loaded_sample_gives_no_grade(self):
        self.assertEqual(ookla.calculate_bufferbloat(10.0, None, None), (None, None))   # was ('A+', 0.0)

    def test_only_sampled_directions_count(self):
        self.assertEqual(ookla.calculate_bufferbloat(10.0, 90.0, None), ("C", 80.0))


class OoklaTest(unittest.TestCase):
    def _run(self, data):
        out = SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr="")
        with mock.patch.object(ookla, "find_or_install_ookla_binary", return_value="/x/speedtest"), \
                mock.patch.object(ookla.cancel, "run", return_value=out), \
                mock.patch.object(ookla, "ookla_env", return_value=None):
            return ookla.run_official_ookla()

    def test_missing_loss_is_unknown_and_lan_address_is_not_the_client_ip(self):
        res = self._run({"download": {"bandwidth": 100_000_000}, "upload": {"bandwidth": 40_000_000},
                         "ping": {"latency": 9.1, "jitter": 0.0},
                         "interface": {"internalIp": "192.168.8.218", "externalIp": "192.168.8.218", "name": "eth0"},
                         "server": {"id": 1, "name": "S", "host": "h", "port": 8080}})
        self.assertIsNone(res.loss_pct)
        self.assertIsNone(res.client_ip)
        self.assertEqual(res.bound_ip, "192.168.8.218")
        self.assertEqual(res.jitter_us, 0)                      # a measured 0 stays 0
        self.assertEqual((res.bufferbloat_grade, res.bufferbloat_delta_ms), (None, None))

    def test_no_bandwidth_is_an_error_not_zero(self):
        res = self._run({"ping": {"latency": 9.1}, "interface": {}, "server": {}})
        self.assertEqual(res.status, "error")
        self.assertIsNone(res.down_bps)


class CloudflareTest(unittest.TestCase):
    def test_no_loss_no_client_town_as_server_place_no_lan_ip(self):
        meta = cloudflare.CloudflareMeta()
        meta.client_ip, meta.colo, meta.city, meta.country = "10.1.2.3", "BUD", "Hometown", "HU"
        res = cloudflare.CloudflareSpeedResult(status="ok", down_bps=1, up_bps=1, meta=meta).to_speedtest_result()
        self.assertIsNone(res.loss_pct)
        self.assertIsNone(res.client_ip)
        self.assertEqual(res.server_location, "Cloudflare BUD")
        raw = json.loads(res.raw_json)
        self.assertEqual(raw["client_city"], "Hometown")
        self.assertNotIn("city", raw)

    def test_one_sample_has_no_jitter(self):
        with mock.patch.object(cloudflare.socket, "getaddrinfo"), \
                mock.patch.object(cloudflare, "_tcp_connect_ms", side_effect=[8.0, OSError("x")]), \
                mock.patch.object(cloudflare.time, "sleep"):
            median, jitter, _ = cloudflare.measure_idle_latency(count=2)
        self.assertEqual(median, 8.0)
        self.assertIsNone(jitter)


class RtrTest(unittest.TestCase):
    FINAL = {"type": "FINAL_RESULT", "testUuid": "t", "openTestUuid": None, "down": 80.5, "up": 9.1,
             "pingMedian": 31.2, "pingMin": 27.4, "pingJitter": 0.4996, "pingCount": 10}

    def _run(self, final, extra=""):
        out = extra + json.dumps(final) + "\n"
        with mock.patch.object(rtr, "find_native_rmbt_client", return_value="/x/rmbt-client"), \
                mock.patch.object(rtr.cancel, "run", return_value=SimpleNamespace(stdout=out, stderr="", returncode=0)), \
                mock.patch.object(rtr, "_client_ips", return_value=(None, None)):
            return rtr._run_native_rmbt_speedtest("https://c01v4.netztest.at", 7, 3, "eth0", "192.0.2.2")

    def test_no_placeholders(self):
        res = self._run(self.FINAL, "Server:   203.0.113.9:443 (TLS)\n")
        self.assertIsNone(res.loss_pct)
        self.assertIsNone(res.colo)
        self.assertIsNone(res.server_location)
        self.assertIsNone(res.result_url)                       # no home page as a result link
        self.assertEqual(res.server_host, "203.0.113.9:443")
        self.assertEqual(res.jitter_us, 500)                    # rounded, not truncated (0.4996 ms)

    def test_no_ping_is_none_not_zero(self):
        res = self._run({k: v for k, v in self.FINAL.items() if k not in ("pingMin", "pingMedian", "pingJitter")})
        self.assertIsNone(res.ping_us)

    def test_client_ip_never_from_a_cache(self):
        with mock.patch("nmb.netd.interfaces.get_dual_stack_ips", return_value={"ipv4": "198.51.100.1"}) as dual:
            self.assertEqual(rtr._client_ips("eth0", None), (None, None))
        dual.assert_not_called()


class IperfRowTest(unittest.TestCase):
    def test_lan_address_rtt_and_port_are_not_stored_as_measurements(self):
        from nmb.speed import runner
        conn = _db()
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"),
                              iperf=SimpleNamespace(target_host="iperf.example", target_port=5201, duration=10,
                                                    protocol="tcp", parallel=4, reverse=False, bidir=False,
                                                    auto_direction="upload"))
        fake = {"status": "ok", "bps": 300_000_000, "rtt_ms": 22.5, "local_host": "192.168.8.218",
                "tcp_window": None, "retransmits": 3}
        with mock.patch("nmb.speed.iperf.run_iperf_client_test", return_value=fake), \
                mock.patch("nmb.common.netaddr.lookup_public_ip", return_value=None), \
                mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", None, True)):
            runner._run_single_engine("iperf3", cfg, "schedule", None, conn, 1, target_iface=None)
        row = conn.execute("SELECT client_ip, ping_us, up_loaded_lat_ms, colo, bound_ip FROM speedtest").fetchone()
        self.assertIsNone(row["client_ip"])          # the lookup gave nothing: empty, never the LAN address
        self.assertIsNone(row["ping_us"])
        self.assertEqual(row["up_loaded_lat_ms"], 22.5)
        self.assertIsNone(row["colo"])
        self.assertEqual(row["bound_ip"], "192.168.8.218")


class StatusCodeTest(unittest.TestCase):
    def test_nothing_judged_against_unset_speeds(self):
        self.assertEqual(classify("ok", None, 5.0, 1.0)[0], 1)

    def test_guaranteed_upload_counts_too(self):
        code, text = classify("ok", None, 950.0, 20.0, guaranteed_down=300, guaranteed_up=50)
        self.assertEqual(code, 6)
        self.assertIn("upload", text)

    def test_wifi_from_the_real_interface(self):
        self.assertEqual(classify("ok", None, 250.0, 50.0, bound_iface="wlan0", connection_type="fiber")[0], 14)
        self.assertEqual(classify("ok", None, 250.0, 50.0, bound_iface="wwan0")[0], 1)

    def test_skip_reasons(self):
        self.assertEqual(classify("skipped_busy", "skipped: other devices' traffic is not visible", None, None)[0], 9)
        self.assertEqual(classify("skipped_busy", "skipped: automated speedtest is set to manual mode", None, None)[0], 10)
        self.assertEqual(classify("error", "read timed out", None, None)[0], 7)


class DetailedCsvTest(unittest.TestCase):
    def setUp(self):
        self.conn = _db()
        self.conn.execute("INSERT INTO speedtest (ts, trigger, status, down_bps, up_bps, ping_us, client_ip, engine, bound_iface) "
                          "VALUES (1794222900000, 'schedule', 'ok', 950000000, 20000000, NULL, NULL, 'rtr', 'eth0')")

    def _rows(self, **kw):
        text = csv_export.export_detailed_speedtests_csv(self.conn, 0, 2 ** 62, **kw)
        self.assertTrue(text.startswith("﻿"))
        return [line.split(";") for line in text.lstrip("﻿").splitlines()]

    def test_unset_speeds_are_not_invented(self):
        head, row = self._rows()
        self.assertEqual(head[:9], ["Time", "IP address", "ISP", "Download", "Download %", "Upload", "Upload %",
                                    "Latency", "Status"])            # the old columns keep their order
        self.assertEqual(row[4], "--")
        self.assertEqual(row[6], "--")
        self.assertEqual(row[7], "--")                               # no "0 ms"
        self.assertEqual(row[8], "1")
        self.assertEqual(row[9], "UTC")

    def test_configured_guarantee_judges_both_directions(self):
        _, row = self._rows(contract_down_mbps=1000, contract_up_mbps=300, guaranteed_down_mbps=300, guaranteed_up_mbps=50)
        self.assertEqual(row[8], "6")
        self.assertIn("upload", row[10])

    def test_speed_csv_has_no_made_up_isp_or_engine(self):
        self.conn.execute("INSERT INTO speedtest (ts, trigger, status, ping_us, jitter_us) VALUES (2, 'manual', 'ok', 0, 0)")
        self.conn.execute("UPDATE speedtest SET engine = NULL WHERE ts = 2")
        text = csv_export.export_speedtests_csv(self.conn, 0, 2 ** 62)
        self.assertNotIn("Unknown ISP", text)
        self.assertNotIn(",ookla,", text)


class CorrectionTest(unittest.TestCase):
    def test_made_up_values_cleared_once_with_originals_kept(self):
        conn = _db()
        rows = [
            ("rtr", 0.0, 500, json.dumps({"engine": "rtr-nettest-native-c"}), "VIE", "Vienna, Austria (BEREC Cluster)", None, None),
            ("rtr", 0.0, 500, json.dumps({"engine": "rtr-nettest-native-c", "ping_count": 10}), None, None, None, None),
            ("cloudflare", 0.0, 400, None, "BUD", "Hometown, HU", "https://speed.cloudflare.com", "192.168.8.218"),
            ("ookla", 0.0, 300, json.dumps({"ping": {}}), None, "Budapest, Hungary", "https://www.speedtest.net/result/1", "198.51.100.4"),
            ("ookla", 0.5, 300, json.dumps({"packetLoss": 0.5}), None, None, None, None),
        ]
        for eng, loss, jit, raw, colo, loc, url, ip in rows:
            conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, loss_pct, jitter_us, raw_json, colo, "
                         "server_location, result_url, client_ip) VALUES (1, 'schedule', 'ok', ?, ?, ?, ?, ?, ?, ?, ?)",
                         (eng, loss, jit, raw, colo, loc, url, ip))
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, ping_us, tcp_window, colo, up_bps) "
                     "VALUES (1, 'schedule', 'ok', 'iperf3', 22500, 'Block: 128 KB', 'Port 5201', 300000000)")
        conn.commit()
        n = corrections.apply(conn)
        self.assertGreater(n, 0)
        self.assertEqual(corrections.apply(conn), 0)
        get = lambda i, f: conn.execute(f"SELECT {f} FROM speedtest WHERE id = ?", (i,)).fetchone()[0]
        self.assertIsNone(get(1, "loss_pct")); self.assertIsNone(get(1, "jitter_us")); self.assertIsNone(get(1, "colo"))
        self.assertIsNone(get(1, "server_location"))
        self.assertEqual(get(2, "jitter_us"), 500)                   # a real value from the new client stays
        self.assertEqual(get(3, "server_location"), "Cloudflare BUD")
        self.assertIsNone(get(3, "result_url")); self.assertIsNone(get(3, "client_ip"))
        self.assertIsNone(get(4, "loss_pct")); self.assertEqual(get(4, "client_ip"), "198.51.100.4")
        self.assertEqual(get(4, "result_url"), "https://www.speedtest.net/result/1")
        self.assertEqual(get(5, "loss_pct"), 0.5)                    # measured by Ookla: kept
        self.assertIsNone(get(6, "ping_us")); self.assertEqual(get(6, "up_loaded_lat_ms"), 22.5)
        self.assertIsNone(get(6, "tcp_window")); self.assertIsNone(get(6, "colo"))
        kept = conn.execute("SELECT old_value FROM speedtest_correction WHERE speedtest_id = 1 AND field = 'jitter_us'").fetchone()
        self.assertEqual(kept[0], "500")


class BotStatusTest(unittest.TestCase):
    def test_not_judged_without_a_guaranteed_speed_in_every_language(self):
        from nmb.bot.i18n import SUPPORTED_LANGUAGES, get_measurement_status
        for lang in SUPPORTED_LANGUAGES:
            badge, text = get_measurement_status(0, lang)
            self.assertIn("⚪", badge, lang)
            self.assertNotEqual(get_measurement_status(1, lang)[0], badge)


if __name__ == "__main__":
    unittest.main()
