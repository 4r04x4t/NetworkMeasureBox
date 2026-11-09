"""The native RTR client's result: real ping minimum and jitter, client IP, bound to the asked link."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from nmb.speed import rtr

FINAL = {"type": "FINAL_RESULT", "testUuid": "t", "openTestUuid": "Oa", "down": 80.5, "up": 9.1,
         "pingMedian": 31.2, "pingMin": 27.4, "pingJitter": 3.3, "pingCount": 10, "downThreads": 3, "upThreads": 3}


def _run(final, bind_ip="192.168.1.4"):
    out = json.dumps(final) + "\n"
    with patch.object(rtr, "find_native_rmbt_client", return_value="/x/rmbt-client"), \
         patch.object(rtr.cancel, "run", return_value=SimpleNamespace(stdout=out, stderr="", returncode=0)) as run, \
         patch.object(rtr, "_client_ips", return_value=("198.51.100.7", None)):
        res = rtr._run_native_rmbt_speedtest("https://c01v4.netztest.at", 7, 3, "eth1", bind_ip)
    return res, run.call_args[0][0]


class NativeRtrTest(unittest.TestCase):
    def test_bound_link_client_ip_and_real_ping_stats(self):
        res, cmd = _run(FINAL)
        self.assertEqual(cmd[cmd.index("--bind") + 1], "192.168.1.4")
        self.assertEqual(res.client_ip, "198.51.100.7")
        self.assertEqual(res.ping_us, 27400)
        self.assertEqual(res.jitter_us, 3300)
        raw = json.loads(res.raw_json)
        self.assertEqual((raw["ping_min_ms"], raw["ping_median_ms"]), (27.4, 31.2))

    def test_old_binary_without_min_does_not_invent_numbers(self):
        old = {k: v for k, v in FINAL.items() if k not in ("pingMin", "pingJitter")}
        res, _ = _run(old)
        self.assertIsNone(res.jitter_us)                       # was a made-up 500 us
        self.assertIsNone(json.loads(res.raw_json)["ping_min_ms"])

    def test_no_bind_without_a_source_address(self):
        _, cmd = _run(FINAL, bind_ip=None)
        self.assertNotIn("--bind", cmd)


if __name__ == "__main__":
    unittest.main()
