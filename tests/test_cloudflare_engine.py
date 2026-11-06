"""Tests for Cloudflare throughput accounting without network access."""
import unittest
from unittest.mock import patch

from nmb.speed import cloudflare as cf


class CloudflareEngineTests(unittest.TestCase):
    def test_meter_ignores_ramp_up_and_after_window(self):
        meter = cf._ByteMeter()
        meter.add(100, 1.0, 2.0, 8.0)
        meter.add(200, 5.0, 2.0, 8.0)
        meter.add(400, 9.0, 2.0, 8.0)
        self.assertEqual(meter.bytes, 200)

    def test_impossible_result_is_discarded(self):
        self.assertIsNone(cf._plausible_mbps(80000.0, 1000.0, "upload"))
        self.assertEqual(cf._plausible_mbps(940.0, 1000.0, "upload"), 940.0)
        self.assertEqual(cf._plausible_mbps(5000.0, None, "upload"), 5000.0)

    def test_throughput_uses_post_warmup_window(self):
        def worker(conn, meter, start, window, stop_at):
            start.wait()
            meter.add(6_000_000, window[0] + 0.001, window[0], window[1])

        with patch.object(cf, "_new_connection", return_value=object()):
            mbps, errors = cf._measure_throughput(worker, streams=2, duration=0.2, warmup=0.1)
        self.assertEqual(errors, [])
        self.assertAlmostEqual(mbps, 12_000_000 * 8 / (0.1 * 1_000_000))

    def test_no_connection_returns_error(self):
        with patch.object(cf, "_new_connection", side_effect=OSError("down")):
            mbps, errors = cf._measure_throughput(lambda *a: None, streams=2, duration=0.1, warmup=0.0)
        self.assertEqual(mbps, 0.0)
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
