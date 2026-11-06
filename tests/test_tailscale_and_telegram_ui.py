"""Unit tests for Tailscale management module and WebUI Telegram / Tailscale integration."""
import json
import unittest
from unittest.mock import patch, MagicMock

from nmb.config import Config, TailscaleConfig, load_config, save_config
from nmb.netd import tailscale
from nmb.web.i18n import TRANSLATIONS
from nmb.web.templates import get_dashboard_html


class TestTailscaleAndTelegramUI(unittest.TestCase):
    def test_i18n_keys_present_all_languages(self):
        """Verify that all required i18n keys exist across all 5 supported languages."""
        required_keys = [
            "tab_telegram",
            "subtab_telegram",
            "subtab_tailscale",
            "tailscale_title",
            "tailscale_desc",
            "tailscale_ip_v4",
            "tailscale_ip_v6",
            "tailscale_magic_dns",
            "tailscale_hostname",
            "tailscale_direct_link",
            "tailscale_peers",
            "tailscale_auth_key",
            "tailscale_btn_up",
            "tailscale_btn_down",
            "tailscale_btn_logout",
            "tailscale_btn_login_web",
            "telegram_title",
            "telegram_desc",
            "telegram_step1",
            "telegram_step2",
            "telegram_step3",
            "telegram_enable",
            "telegram_token",
            "telegram_chats",
            "telegram_loss_thresh",
            "telegram_lat_thresh",
            "telegram_btn_save",
            "telegram_btn_start",
            "telegram_btn_stop",
            "telegram_btn_restart",
            "telegram_btn_test",
        ]
        for lang in ["en", "hu", "de", "fr", "uk"]:
            trans = TRANSLATIONS.get(lang, {})
            for key in required_keys:
                self.assertIn(key, trans, f"Missing key '{key}' in language '{lang}'")

    def test_dashboard_html_contains_elements(self):
        """Verify dashboard HTML contains Telegram tab and Tailscale subtab markup."""
        html = get_dashboard_html()
        self.assertIn('onclick="switchTab(\'tab-telegram\')"', html)
        self.assertIn('id="tab-telegram"', html)
        self.assertIn('id="rsub-telegram"', html)
        self.assertIn('onclick="switchRouterSubtab(\'rsub-telegram\')"', html)
        self.assertIn('id="btn-subtab-tailscale"', html)
        self.assertIn('id="subtab-content-tailscale"', html)
        self.assertIn('id="pivpn-ts-badge"', html)
        self.assertIn('id="tailscale-login-banner"', html)
        self.assertIn('id="tailscale-direct-links"', html)

    def test_tailscale_config_defaults(self):
        """Test TailscaleConfig defaults."""
        tc = TailscaleConfig()
        self.assertFalse(tc.enabled)
        self.assertFalse(tc.accept_routes)
        self.assertFalse(tc.accept_dns)
        self.assertFalse(tc.advertise_exit_node)
        self.assertEqual(tc.hostname, "networkmeasurebox")

    @patch("shutil.which")
    def test_tailscale_installed_check(self, mock_which):
        mock_which.return_value = "/usr/bin/tailscale"
        self.assertTrue(tailscale.is_tailscale_installed())
        mock_which.return_value = None
        self.assertFalse(tailscale.is_tailscale_installed())

    @patch("nmb.netd.tailscale.is_tailscale_installed", return_value=True)
    @patch("nmb.netd.tailscale.is_tailscaled_active", return_value=True)
    @patch("subprocess.run")
    def test_tailscale_status_parse(self, mock_run, mock_active, mock_inst):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "BackendState": "Running",
                "TailscaleIPs": ["100.64.1.2", "fd7a:115c:a1e0::1"],
                "Self": {
                    "DNSName": "raspberrypi.tailnet.ts.net.",
                    "HostName": "raspberrypi"
                },
                "Peer": {
                    "peer1": {
                        "HostName": "my-phone",
                        "TailscaleIPs": ["100.64.1.3"],
                        "OS": "iOS",
                        "Online": True
                    }
                }
            })
        )
        status = tailscale.get_tailscale_status()
        self.assertEqual(status["backend_state"], "Running")
        self.assertEqual(status["tailscale_ips"], ["100.64.1.2", "fd7a:115c:a1e0::1"])
        self.assertEqual(status["dns_name"], "raspberrypi.tailnet.ts.net")
        self.assertEqual(len(status["peers"]), 1)
        self.assertEqual(status["peers"][0]["HostName"], "my-phone")

    @patch("nmb.netd.tailscale.is_tailscale_installed", return_value=True)
    @patch("subprocess.run")
    def test_tailscale_up_flags(self, mock_run, mock_inst):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = tailscale.tailscale_up(
            auth_key="tskey-auth-123",
            ssh=True,
            accept_routes=False,
            accept_dns=False,
            advertise_exit_node=False
        )
        self.assertTrue(res["ok"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("--accept-routes=false", cmd)
        self.assertIn("--accept-dns=false", cmd)
        self.assertIn("--advertise-exit-node=false", cmd)
        self.assertIn("--ssh", cmd)
        self.assertIn("--authkey=tskey-auth-123", cmd)

    def test_telegram_config_persistence(self):
        """Verify telegram alert flags serialize and deserialize properly."""
        import tempfile
        from pathlib import Path
        cfg = Config()
        cfg.telegram.enabled = True
        cfg.telegram.token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        cfg.telegram.allowed_chat_ids = [987654321, -100123456789]
        cfg.telegram.alert_loss_threshold_pct = 7.5
        cfg.telegram.alert_latency_threshold_ms = 125.0
        cfg.telegram.alert_on_loss = False
        cfg.telegram.alert_on_latency = True

        with tempfile.TemporaryDirectory() as td:
            conf_path = Path(td) / "test.conf"
            saved = save_config(cfg, conf_path)
            self.assertTrue(saved)

            loaded = load_config(conf_path)
            self.assertTrue(loaded.telegram.enabled)
            self.assertEqual(loaded.telegram.token, "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
            self.assertEqual(loaded.telegram.allowed_chat_ids, [987654321, -100123456789])
            self.assertEqual(loaded.telegram.alert_loss_threshold_pct, 7.5)
            self.assertEqual(loaded.telegram.alert_latency_threshold_ms, 125.0)
            self.assertFalse(loaded.telegram.alert_on_loss)
            self.assertTrue(loaded.telegram.alert_on_latency)

    def test_mobile_responsive_css_rules(self):
        """Verify dashboard HTML has required mobile responsive styles and meta viewport."""
        html = get_dashboard_html()
        self.assertIn('name="viewport"', html)
        self.assertIn('viewport-fit=cover', html)
        self.assertIn('.data-table-wrap, .table-wrap, .table-container, .tasks-table-wrap', html)
        self.assertIn('overflow-x: auto !important', html)
        self.assertIn('white-space: nowrap !important', html)
        self.assertIn('max-width: 100vw', html)

    def test_telegram_token_input_protection(self):
        """Verify dashboard HTML protects telegram token input from polling wipeout."""
        html = get_dashboard_html()
        self.assertIn('telegram-token-saved-badge', html)
        self.assertIn('dataset.dirty', html)
        self.assertIn('clearTelegramDirty', html)
        self.assertIn('loadTelegramStatus(true)', html)


if __name__ == "__main__":
    unittest.main()
