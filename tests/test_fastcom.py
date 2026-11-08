"""Fast.com engine: server parsing, stable speed, result shape; iPerf3 row labels."""
import json
import unittest
from unittest import mock

from nmb.speed import fastcom


API = {"client": {"ip": "198.51.100.7", "asn": "64500", "isp": "Example ISP", "location": {"city": "Szeged", "country": "HU"}},
       "targets": [{"url": "https://ipv4-c001-bud002-exisp-isp.1.oca.nflxvideo.net/speedtest?c=hu&n=64500&t=x",
                    "location": {"city": "Budapest", "country": "HU"}},
                   {"url": "http://not-https.example/speedtest?x=1", "location": {}}]}


class FastcomTest(unittest.TestCase):
    def test_targets_keep_only_https_and_label_the_oca(self):
        with mock.patch.object(fastcom, "_http_get", return_value=json.dumps(API).encode()):
            client, targets = fastcom.fetch_targets("tok")
        self.assertEqual(client["isp"], "Example ISP")
        self.assertEqual(len(targets), 1)
        t = targets[0]
        self.assertEqual(t.label, "bud002 c001 · exisp (ISP)")
        self.assertEqual(t.range_path("0-0"), "/speedtest/range/0-0?c=hu&n=64500&t=x")

    def test_stable_speed_ignores_the_ramp_up(self):
        self.assertEqual(fastcom._stable_mbps([50, 200, 400, 500, 510, 490, 500, 505]), 501.0)
        self.assertIsNone(fastcom._stable_mbps([]))

    def test_full_run_fills_every_field(self):
        tg = fastcom.FastTarget(url=API["targets"][0]["url"], host="ipv4-c001-bud002-exisp-isp.1.oca.nflxvideo.net",
                                city="Budapest", country="HU")

        def unloaded(targets, count=6):
            for x in targets:
                x.latency_samples, x.latency_ms, x.tcp_ms = [9.0, 10.0, 11.0], 9.0, 8.0

        transfer = {"mean_mbps": 480.0, "stable_mbps": 500.0, "peak_mbps": 520.0, "samples_mbps": [500.0],
                    "bytes": 1, "loaded_latency_ms": [20.0, 22.0], "errors": []}
        with mock.patch.object(fastcom, "fetch_token", return_value="tok"), \
             mock.patch.object(fastcom, "fetch_targets", return_value=(API["client"], [tg])), \
             mock.patch.object(fastcom, "measure_unloaded", side_effect=unloaded), \
             mock.patch.object(fastcom, "_transfer", return_value=transfer):
            r = fastcom.execute_fastcom_speedtest()
        self.assertEqual((r.status, r.engine, r.down_bps, r.ping_us), ("ok", "fastcom", 500_000_000, 9000))
        self.assertEqual(r.colo, "BUD002")
        self.assertEqual(r.down_loaded_lat_ms, 21.0)
        raw = json.loads(r.raw_json)
        self.assertEqual(raw["client"]["asn"], "64500")
        self.assertEqual(raw["servers"][0]["city"], "Budapest")

    def test_api_failure_is_an_error_row(self):
        with mock.patch.object(fastcom, "fetch_token", side_effect=OSError("offline")):
            r = fastcom.execute_fastcom_speedtest()
        self.assertEqual((r.status, r.engine), ("error", "fastcom"))


class IperfRowLabelTest(unittest.TestCase):
    def test_bare_address_gets_name_country_and_isp(self):
        from nmb.speed import iperf_directory as d
        d._label_cache.clear(); d._label_misses.clear()
        row = {"engine": "iperf3", "server_name": "iPerf3: 203.0.113.9:5201", "server_host": "203.0.113.9", "server_location": "TCP -P 4"}
        with mock.patch.object(d, "_read_cache", return_value={}), \
             mock.patch("socket.gethostbyname", return_value="203.0.113.9"), \
             mock.patch("nmb.netd.geoip.get_public_geoip", return_value={"city": "Frankfurt", "country_code": "DE", "isp": "Example Net"}):
            d.label_iperf_row(row)
        self.assertEqual(row["server_name"], "iPerf3: Frankfurt, DE • Example Net (203.0.113.9:5201)")
        self.assertEqual(row["server_location"], "DE · Example Net · TCP -P 4")
        self.assertEqual((row["server_country"], row["server_isp"]), ("DE", "Example Net"))
        d._label_cache.clear()

    def test_named_rows_and_other_engines_are_left_alone(self):
        from nmb.speed import iperf_directory as d
        for row in ({"engine": "iperf3", "server_name": "iPerf3: Vienna • X (1.2.3.4:5201)"},
                    {"engine": "ookla", "server_name": "iPerf3: 1.2.3.4:5201"}):
            before = dict(row)
            with mock.patch.object(d, "describe_server") as ds:
                d.label_iperf_row(row)
                ds.assert_not_called()
            self.assertEqual(row, before)


if __name__ == "__main__":
    unittest.main()
