"""Unit tests for DuckDNS DynDNS client and Telegram /dyndns commands."""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from nmb.config import Config, DuckDNSConfig, load_config, save_config
import nmb.netd.duckdns as dd
from nmb.bot.commands import CommandHandler


class TestDuckDNS(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conf_path = os.path.join(self.tmp_dir.name, "nmb.conf")
        self.cfg = Config()
        self.cfg.system.config_path = self.conf_path
        self.cfg.duckdns = DuckDNSConfig(
            enabled=True,
            domain="my-test-box",
            token="test-token-12345",
            update_interval_min=10,
            custom_ip="",
        )
        save_config(self.cfg, target_path=self.conf_path)

        # Reset duckdns module internal state
        dd.stop_duckdns_service()
        with dd._duckdns_lock:
            dd._duckdns_state["last_update_ts"] = 0.0
            dd._duckdns_state["last_status"] = "never_run"
            dd._duckdns_state["last_ip"] = ""
            dd._duckdns_state["detected_ip"] = ""
            dd._duckdns_state["next_update_ts"] = 0.0

    def tearDown(self):
        dd.stop_duckdns_service()
        self.tmp_dir.cleanup()

    def test_clean_domain(self):
        self.assertEqual(dd.clean_domain("mybox.duckdns.org"), "mybox")
        self.assertEqual(dd.clean_domain("MYBOX.DUCKDNS.ORG "), "mybox")
        self.assertEqual(dd.clean_domain("mybox"), "mybox")
        self.assertEqual(dd.clean_domain("  custom-name  "), "custom-name")
        # dynv6 domain/zone preservation
        self.assertEqual(dd.clean_domain("myzone.v6.army", provider="dynv6"), "myzone.v6.army")
        self.assertEqual(dd.clean_domain("https://test.dynv6.net/", provider="dynv6"), "test.dynv6.net")

    @patch("urllib.request.urlopen")
    def test_update_dynv6_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"addresses updated"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = dd.update_duckdns(
            domain="sample.v6.army",
            token="valid-dynv6-token",
            ip="203.0.113.10",
            ipv6="2001:db8::1",
            provider="dynv6",
        )
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["success"])
        self.assertEqual(res["provider"], "dynv6")
        self.assertEqual(res["fqdn"], "sample.v6.army")
        self.assertEqual(res["ip"], "203.0.113.10")
        self.assertEqual(res["ipv6"], "2001:db8::1")

    @patch("urllib.request.urlopen")
    def test_update_duckdns_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"OK\n198.51.100.42\n\nUPDATED\n"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = dd.update_duckdns(domain="my-test-box", token="test-token-12345")
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["success"])
        self.assertEqual(res["ip"], "198.51.100.42")
        self.assertEqual(res["domain"], "my-test-box")
        self.assertEqual(res["fqdn"], "my-test-box.duckdns.org")

        st = dd.get_duckdns_status(self.cfg)
        self.assertEqual(st["last_status"], "OK")
        self.assertEqual(st["last_ip"], "198.51.100.42")
        self.assertEqual(st["detected_ip"], "198.51.100.42")
        self.assertTrue(st["token_set"])

    @patch("urllib.request.urlopen")
    def test_update_duckdns_failure(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"KO\n"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = dd.update_duckdns(domain="my-test-box", token="invalid-token")
        self.assertEqual(res["status"], "error")
        self.assertFalse(res["success"])

        st = dd.get_duckdns_status(self.cfg)
        self.assertEqual(st["last_status"], "KO")

    def test_get_duckdns_status_keys(self):
        st = dd.get_duckdns_status(self.cfg)
        for expected_key in (
            "enabled", "domain", "fqdn", "token_set", "update_interval_min",
            "interval_min", "custom_ip", "last_update_ts", "next_update_ts",
            "detected_ip", "running", "last_update", "next_update", "next_update_seconds"
        ):
            self.assertIn(expected_key, st)
        self.assertEqual(st["interval_min"], 10)
        self.assertEqual(st["update_interval_min"], 10)
        self.assertEqual(st["domain"], "my-test-box")
        self.assertEqual(st["fqdn"], "my-test-box.duckdns.org")

    # IPv6 detection can take seconds on a real network; the test waits only 0.15 s.
    @patch("nmb.netd.duckdns.detect_public_ipv6", return_value=None)
    @patch("nmb.netd.duckdns.update_duckdns")
    def test_wake_daemon_on_interval_change(self, mock_update, _mock_v6):
        mock_update.return_value = {"status": "ok", "success": True, "ip": "1.2.3.4", "message": "OK"}

        # Start daemon with 60 min interval
        self.cfg.duckdns.update_interval_min = 60
        dd.start_duckdns_service(lambda: self.cfg)
        time.sleep(0.15)

        st1 = dd.get_duckdns_status(self.cfg)
        self.assertTrue(st1["running"])
        self.assertEqual(st1["update_interval_min"], 60)
        # Next update should be approximately 3600s in the future
        self.assertGreater(st1["next_update_seconds"], 3500)

        # Change interval to 2 minutes and wake daemon
        self.cfg.duckdns.update_interval_min = 2
        dd.wake_duckdns_daemon()
        time.sleep(0.15)

        st2 = dd.get_duckdns_status(self.cfg)
        self.assertEqual(st2["update_interval_min"], 2)
        # Next update seconds must now be capped around 120s!
        self.assertLessEqual(st2["next_update_seconds"], 125)

        dd.stop_duckdns_service()
        self.assertFalse(dd.get_duckdns_status()["running"])


class TestDuckDNSTelegram(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conf_path = os.path.join(self.tmp_dir.name, "nmb.conf")
        self.cfg = Config()
        self.cfg.system.config_path = self.conf_path
        self.cfg.duckdns = DuckDNSConfig(
            enabled=True,
            domain="tg-box",
            token="test-tg-token",
            update_interval_min=10,
            custom_ip="",
        )
        save_config(self.cfg, target_path=self.conf_path)

        self.mock_client = MagicMock()
        self.handler = CommandHandler(self.cfg, self.mock_client)

    def tearDown(self):
        dd.stop_duckdns_service()
        self.tmp_dir.cleanup()

    def test_cmd_dyndns_status(self):
        self.handler.handle_command(12345, "/dyndns")
        self.mock_client.send_message.assert_called_once()
        args, _ = self.mock_client.send_message.call_args
        msg = args[1]
        self.assertIn("DuckDNS Dynamic DNS", msg)
        self.assertIn("tg-box.duckdns.org", msg)
        self.assertIn("10 minutes", msg)

    @patch("nmb.netd.duckdns.update_duckdns")
    def test_cmd_dyndns_update(self, mock_update):
        mock_update.return_value = {
            "status": "ok",
            "success": True,
            "ip": "203.0.113.99",
            "domain": "tg-box",
            "fqdn": "tg-box.duckdns.org",
            "updated": True,
            "message": "DuckDNS response: OK (IP Updated)",
        }
        self.handler.handle_command(12345, "/dyndns update")
        # Should have sent progress + success message
        self.assertGreaterEqual(self.mock_client.send_message.call_count, 2)
        last_msg = self.mock_client.send_message.call_args_list[-1][0][1]
        self.assertIn("DuckDNS synchronized", last_msg)
        self.assertIn("203.0.113.99", last_msg)

    def test_cmd_dyndns_interval(self):
        self.handler.handle_command(12345, "/dyndns interval 5")
        self.assertEqual(self.cfg.duckdns.update_interval_min, 5)
        # Verify saved to disk
        reloaded = load_config(self.conf_path)
        self.assertEqual(reloaded.duckdns.update_interval_min, 5)

        last_msg = self.mock_client.send_message.call_args[0][1]
        self.assertIn("DuckDNS interval updated", last_msg)
        self.assertIn("5 minutes", last_msg)

    def test_cmd_dyndns_toggle(self):
        self.handler.handle_command(12345, "/dyndns off")
        self.assertFalse(self.cfg.duckdns.enabled)
        reloaded = load_config(self.conf_path)
        self.assertFalse(reloaded.duckdns.enabled)

        self.handler.handle_command(12345, "/dyndns on")
        self.assertTrue(self.cfg.duckdns.enabled)
        reloaded2 = load_config(self.conf_path)
        self.assertTrue(reloaded2.duckdns.enabled)


if __name__ == "__main__":
    unittest.main()
