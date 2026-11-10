"""Tests for bundle privacy masking and honest labels."""
import sqlite3
import unittest

from nmb.report import llm_bundle as lb


class BundleHelpersTests(unittest.TestCase):
    def test_masks_subscriber_identifiers(self):
        text = "ip 87.97.24.117 ssid my_net mac e4:5f:01:d9:d8:61 ts foo.ts.net 100.66.57.12 fd7a:115c:a1e0::4e3a:390d"
        out = lb._mask_sensitive(text, ["87.97.24.117", "my_net", ""])
        for secret in ("87.97.24.117", "my_net", "d9:d8:61", "foo.ts.net", "100.66.57.12", "fd7a:115c"):
            self.assertNotIn(secret, out)
        self.assertIn("e4:5f:01:xx:xx:xx", out)

    def test_private_first_hop_is_not_called_isp(self):
        self.assertIn("Upstream", lb._hop_role_label("ISP First Hop", "10.0.0.1"))
        self.assertEqual(lb._hop_role_label("ISP First Hop", "84.2.1.1"), "ISP First Hop")

    def test_speed_statistics(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE speedtest (ts INT, engine TEXT, status TEXT, down_bps INT, up_bps INT, "
                     "client_ip_source TEXT, server_host TEXT)")
        conn.executemany("INSERT INTO speedtest VALUES (5, 'rtr', ?, ?, ?, NULL, NULL)", [("ok", 900e6, 300e6), ("ok", 700e6, 300e6), ("skipped_busy", None, None)])
        conn.execute("INSERT INTO speedtest VALUES (5, 'iperf3', 'ok', 940e6, NULL, 'local', '192.168.8.20')")
        conn.execute("INSERT INTO speedtest VALUES (5, 'cloudflare', 'ok', NULL, 300e6, 'engine', NULL)")
        table = "\n".join(lb._speed_statistics(conn, 0))
        self.assertIn("`rtr` | 2 | 1", table)
        self.assertIn("`iperf3 (LAN)` | 1 | 0", table)          # apart from the line's figures
        self.assertIn("`cloudflare` | 1 | 0 | -- | -- | -- | 300 |", table)   # an upload-only ok test is ok


if __name__ == "__main__":
    unittest.main()
