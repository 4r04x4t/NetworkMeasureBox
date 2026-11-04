import unittest
from nmb.speed.traceroute import (
    _parse_traceroute_line,
    classify_hop_type,
    run_traceroute,
    stop_traceroute,
    is_traceroute_running,
    get_latest_traceroute,
)

class TestTracerouteEngine(unittest.TestCase):
    def test_parse_traceroute_lines(self):
        # 1. Standard LAN hop
        line1 = " 1  _gateway (192.168.8.1)  0.334 ms  0.294 ms  0.275 ms"
        h1 = _parse_traceroute_line(line1)
        self.assertIsNotNone(h1)
        self.assertEqual(h1["hop"], 1)
        self.assertEqual(h1["ip"], "192.168.8.1")
        self.assertEqual(h1["host"], "_gateway")
        self.assertEqual(h1["rtt_ms"], 0.3)
        self.assertEqual(len(h1["rtts"]), 3)
        self.assertEqual(h1["loss_pct"], 0.0)
        self.assertEqual(h1["status"], "ok")
        self.assertEqual(h1["hop_type"], "lan")

        # 2. ISP router with reverse DNS
        line2 = " 2  lo0.bdr1.bud.invitel.net (213.163.38.1)  4.120 ms  4.095 ms  4.050 ms"
        h2 = _parse_traceroute_line(line2)
        self.assertIsNotNone(h2)
        self.assertEqual(h2["hop"], 2)
        self.assertEqual(h2["ip"], "213.163.38.1")
        self.assertEqual(h2["host"], "lo0.bdr1.bud.invitel.net")
        self.assertEqual(h2["hop_type"], "public")

        # 3. Timeout line
        line3 = " 3  * * *"
        h3 = _parse_traceroute_line(line3)
        self.assertIsNotNone(h3)
        self.assertEqual(h3["hop"], 3)
        self.assertEqual(h3["ip"], "*")
        self.assertEqual(h3["loss_pct"], 100.0)
        self.assertEqual(h3["status"], "timeout")
        self.assertEqual(h3["hop_type"], "timeout")

        # 4. Partial timeout with leading star
        line4 = " 4  * cloudflare.bix.hu (193.188.137.27)  7.653 ms * *"
        h4 = _parse_traceroute_line(line4)
        self.assertIsNotNone(h4)
        self.assertEqual(h4["hop"], 4)
        self.assertEqual(h4["ip"], "193.188.137.27")
        self.assertEqual(h4["host"], "cloudflare.bix.hu")
        self.assertEqual(h4["rtt_ms"], 7.65)
        self.assertEqual(len(h4["rtts"]), 1)
        self.assertAlmostEqual(h4["loss_pct"], 66.7, places=1)
        self.assertEqual(h4["status"], "ok")

        # 5. IPv6 line
        line5 = " 5  2001:db8::1 (2001:db8::1)  1.234 ms  1.120 ms  1.050 ms"
        h5 = _parse_traceroute_line(line5)
        self.assertIsNotNone(h5)
        self.assertEqual(h5["hop"], 5)
        self.assertEqual(h5["ip"], "2001:db8::1")

    def test_classify_hop_type(self):
        self.assertEqual(classify_hop_type("192.168.1.1"), "lan")
        self.assertEqual(classify_hop_type("10.0.0.1"), "lan")
        self.assertEqual(classify_hop_type("172.16.0.1"), "lan")
        self.assertEqual(classify_hop_type("100.64.0.1"), "cgnat")
        self.assertEqual(classify_hop_type("1.1.1.1"), "public")
        self.assertEqual(classify_hop_type("1.1.1.1", target_ip="1.1.1.1"), "target")
        self.assertEqual(classify_hop_type("*"), "timeout")

    def test_run_and_stop_traceroute(self):
        # Validation checks
        res_empty = run_traceroute(target="")
        self.assertEqual(res_empty["status"], "error")

        res_dash = run_traceroute(target="-invalid")
        self.assertEqual(res_dash["status"], "error")

        # Stop command
        stop_res = stop_traceroute()
        self.assertEqual(stop_res["status"], "ok")

if __name__ == "__main__":
    unittest.main()
