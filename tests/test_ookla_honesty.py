"""Ookla results must name the server they used and back off when Ookla rate-limits."""
import json
import unittest
from unittest import mock

from nmb.speed import anti_ban
from nmb.speed import ookla
from nmb.speed.ookla import SpeedtestResult
from nmb.speed.runner import _flag_server_mismatch

LIMIT_TEXT = "[error] Limit reached: Too many requests received."


class ClientCooldownTest(unittest.TestCase):
    def setUp(self):
        anti_ban.clear_quarantine()

    def tearDown(self):
        anti_ban.clear_quarantine()

    def test_limit_text_is_a_client_limit(self):
        self.assertTrue(anti_ban.is_client_rate_limit(LIMIT_TEXT))
        self.assertFalse(anti_ban.is_client_rate_limit("Connection timed out"))

    def test_cooldown_doubles_and_resets_on_success(self):
        first = anti_ban.mark_client_rate_limited()
        second = anti_ban.mark_client_rate_limited()
        self.assertEqual(second, first * 2)
        self.assertGreater(anti_ban.client_cooldown_remaining(), 0)
        anti_ban.mark_client_ok()
        self.assertEqual(anti_ban.client_cooldown_remaining(), 0)
        self.assertEqual(anti_ban.mark_client_rate_limited(), first)

    def test_cooldown_is_capped(self):
        for _ in range(10):
            last = anti_ban.mark_client_rate_limited()
        self.assertEqual(last, anti_ban.CLIENT_COOLDOWN_MAX_SEC)


class NoDisguisedFallbackTest(unittest.TestCase):
    def test_failed_ookla_is_returned_as_error(self):
        failed = SpeedtestResult(status="error", error=LIMIT_TEXT)
        with mock.patch.object(ookla, "run_official_ookla", return_value=failed), \
             mock.patch.object(ookla, "run_speedtest_cli") as cli:
            res = ookla.execute_speedtest(server_id=10390)
        self.assertEqual(res.status, "error")
        cli.assert_not_called()

    def test_chosen_server_never_uses_untargeted_cli(self):
        with mock.patch.object(ookla, "run_official_ookla", return_value=None), \
             mock.patch.object(ookla, "run_speedtest_cli") as cli:
            res = ookla.execute_speedtest(server_id=10390)
        self.assertEqual(res.status, "error")
        cli.assert_not_called()

    def test_native_stream_fallback_is_gone(self):
        self.assertFalse(hasattr(ookla, "run_native_fallback"))


class ServerMismatchTest(unittest.TestCase):
    def test_mismatch_is_recorded(self):
        res = SpeedtestResult(status="ok", server_id=3787, raw_json=json.dumps({"a": 1}))
        _flag_server_mismatch(res, 10390)
        self.assertEqual(json.loads(res.raw_json)["requested_server_id"], 10390)

    def test_matching_server_is_left_alone(self):
        res = SpeedtestResult(status="ok", server_id=10390, raw_json="{}")
        _flag_server_mismatch(res, 10390)
        self.assertEqual(res.raw_json, "{}")


if __name__ == "__main__":
    unittest.main()
