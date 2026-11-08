"""The root-only copy of typed-in secrets (2026-11-08: an update wiped the Telegram token)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.common import secret_keep as K

CONF = "[telegram]\ntoken = 123:abc\n[network]\nwifi_psk = mysecret99\nwifi_ssid = X\n"


class SecretKeepTest(unittest.TestCase):
    def setUp(self):
        self.p = patch.object(K, "KEEP_FILE", Path(tempfile.mkdtemp()) / "keep")
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_wiped_token_and_factory_psk_are_found_and_restored(self):
        K.update(CONF, now=1000)
        self.assertEqual(oct(K.KEEP_FILE.stat().st_mode & 0o777), "0o600")
        broken = "[telegram]\ntoken =\n[network]\nwifi_psk = NetworkMeasureBox123\nwifi_ssid = X\n"
        self.assertEqual([n for n, _ in K.lost(broken)], ["network.wifi_psk", "telegram.token"])
        text, names = K.restore(broken)
        self.assertEqual(names, ["network.wifi_psk", "telegram.token"])
        self.assertIn("token = 123:abc", text)
        self.assertIn("wifi_psk = mysecret99", text)
        self.assertIn("wifi_ssid = X", text)

    def test_empty_or_factory_values_are_never_kept(self):
        K.update("[telegram]\ntoken =\n[network]\nwifi_psk = NetworkMeasureBox123\n", now=1)
        self.assertEqual(K.lost("[telegram]\ntoken =\n"), [])

    def test_a_new_value_replaces_the_old_and_old_entries_expire(self):
        K.update(CONF, now=1000)
        K.update(CONF.replace("123:abc", "456:def"), now=2000)
        self.assertIn("token = 456:def", K.restore("[telegram]\ntoken =\n")[0])
        K.update("[x]\na = 1\n", now=1000 + 31 * 86400)
        self.assertEqual(K.lost("[telegram]\ntoken =\n"), [])

    def test_nothing_lost_means_no_change(self):
        K.update(CONF, now=1)
        self.assertEqual(K.restore(CONF), (CONF, []))


if __name__ == "__main__":
    unittest.main()
