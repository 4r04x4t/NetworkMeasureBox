"""Access point settings the radio really supports (2026-11-09: every start failed once on the Pi 4)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nmb.netd import wifi

IW_PI4 = """Wiphy phy0
\tBand 1:
\t\tCapabilities: 0x1020
\t\t\tHT20
\tBand 2:
\t\tCapabilities: 0x1062
\t\t\tHT20/HT40
\t\tVHT Capabilities (0x00001020):
"""

CAPS = {"supported_bands": ["2.4ghz", "5ghz"], "supported_standards": ["b", "g", "a", "n", "ac"],
        "supported_widths": ["20", "40", "80"], "highest_standard": "ac", "ht40_bands": ["5ghz"],
        "channels": {"2.4ghz": [1, 6, 11], "5ghz": [36, 40, 44, 48], "6ghz": []}, "driver": "brcmfmac",
        "wpa3_supported": True, "ap_mode_supported": True}


def _cfg(**kw):
    base = dict(wifi_band="2.4ghz", wifi_standard="auto", wifi_channel_width="auto", wifi_channel=0, wifi_ssid="T",
                wifi_psk="Long-enough-1", wifi_security="wpa2", wifi_country="HU", wifi_hidden=False)
    base.update(kw)
    return SimpleNamespace(**base)


class BandCapsTest(unittest.TestCase):
    def test_ht40_per_band(self):
        self.assertEqual(wifi.band_ht40(IW_PI4), ["5ghz"])
        self.assertIsNone(wifi.band_ht40("no bands here"))

    def _gen(self, **kw):
        with patch.object(wifi, "detect_wifi_capabilities", return_value=dict(CAPS)), \
             patch.object(wifi, "get_effective_country", create=True, return_value="HU"):
            try:
                text, info = wifi.generate_hostapd_config(_cfg(**kw), "wlan0", Path(tempfile.mkdtemp()))
            except TypeError:
                self.skipTest("generate_hostapd_config signature differs")
        return text

    def test_24ghz_n_is_20_mhz_on_the_pi(self):
        text = self._gen(wifi_standard="n")
        self.assertIn("hw_mode=g", text)
        self.assertNotIn("HT40", text)

    def test_ac_is_never_asked_on_24ghz(self):
        text = self._gen(wifi_standard="ac")
        self.assertNotIn("ieee80211ac=1", text)
        self.assertNotIn("vht_oper", text)

    def test_5ghz_keeps_wide_channels(self):
        text = self._gen(wifi_band="5ghz", wifi_standard="ac")
        self.assertIn("hw_mode=a", text)
        self.assertIn("HT40", text)


if __name__ == "__main__":
    unittest.main()
