"""The shared secret / personal-data matcher (nmb/common/redact.py)."""
import unittest

from nmb.common import redact


class RedactTest(unittest.TestCase):
    def test_secret_keys(self):
        for k in ("admin_password", "wifi_psk", "token", "auth_key", "authkey", "api_key", "pppoe_password",
                  "private_key", "preshared_key", "smtp_password", "secret"):
            self.assertTrue(redact.is_secret_key(k), k)
        for k in ("mode", "wifi_band", "interval_min", "provider"):
            self.assertFalse(redact.is_secret_key(k), k)

    def test_personal_keys(self):
        for k in ("pppoe_user", "username", "user", "account_id", "circuit_id", "to_addrs", "from_addr",
                  "allowed_chat_ids", "domain", "public_endpoint", "case_id"):
            self.assertTrue(redact.is_personal_key(k), k)
        for k in ("mode", "wifi_ssid_hidden", "interval_min"):
            self.assertFalse(redact.is_personal_key(k), k)

    def test_config_text(self):
        text = ("[tailscale]\nauth_key = tskey-auth-EXAMPLE\n[network]\npppoe_user = someone@example.net\n"
                "wifi_psk = first-line\n  continued-secret-line\nmode = auto\n"
                "[collector]\nurl = https://u:p@collector.example.org/x\n")
        out = redact.redact_config_text(text)
        for leaked in ("tskey-auth-EXAMPLE", "someone@example.net", "first-line", "continued-secret-line", "u:p@"):
            self.assertNotIn(leaked, out)
        self.assertIn("mode = auto", out)
        self.assertIn("collector.example.org", out)
        kept = redact.redact_config_text(text, personal=False)
        self.assertIn("someone@example.net", kept)
        self.assertNotIn("tskey-auth-EXAMPLE", kept)

    def test_scrub_text(self):
        self.assertEqual(redact.scrub_text("mail me at a.b@example.com"), "mail me at <redacted>")
        self.assertEqual(redact.scrub_text("http://x:y@h.example/p"), "http://<redacted>@h.example/p")


if __name__ == "__main__":
    unittest.main()


class ExportsUseTheSharedMatcherTest(unittest.TestCase):
    """Every place that copies the settings off the box masks the same keys (2026-11-10)."""
    SAMPLE = ("[tailscale]\nauth_key = tskey-auth-EXAMPLE\n[network]\npppoe_user = someone@example.net\n"
              "pppoe_password = hunter2-example\nwifi_psk = first-line\n  continued-secret-line\nmode = auto\n"
              "[telegram]\nallowed_chat_ids = 123456789\n[proxy]\nusername = proxyuser-example\n")
    LEAKS = ("tskey-auth-EXAMPLE", "someone@example.net", "hunter2-example", "first-line", "continued-secret-line",
             "123456789", "proxyuser-example")

    def test_ai_bundle_config(self):
        import tempfile
        from pathlib import Path
        from nmb.report import llm_bundle
        p = Path(tempfile.mkdtemp(prefix="nmb-test-redact-")) / "nmb.conf"
        p.write_text(self.SAMPLE)
        out = llm_bundle._sanitize_config_text(p)
        for leaked in self.LEAKS:
            self.assertNotIn(leaked, out)
        self.assertIn("mode = auto", out)

    def test_boot_partition_copy(self):
        from nmb import config
        out = config.mask_secrets(self.SAMPLE)
        for leaked in self.LEAKS:
            self.assertNotIn(leaked, out)
        self.assertIn("mode = auto", out)
        self.assertIn(config.SECRET_MARK, out)
        # reading the masked copy back keeps every current value
        merged = config.merge_drive_config(out, self.SAMPLE)
        for value in ("tskey-auth-EXAMPLE", "someone@example.net", "123456789", "proxyuser-example"):
            self.assertIn(value, merged)
        import configparser
        parsed = configparser.ConfigParser(interpolation=None)
        parsed.read_string(merged)                       # still a valid file with the multi-line value
        self.assertEqual(parsed.get("network", "wifi_psk"), "first-line\ncontinued-secret-line")
