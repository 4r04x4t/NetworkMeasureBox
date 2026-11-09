"""hostapd HT/VHT flags from the radio's own capabilities (Raspberry Pi 4, BCM43455, 1x1).

2026-11-09: with the default Wi-Fi settings (band, standard and width on auto) hostapd refused the fixed
`vht_capab=[SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1]` (the radio has no STBC) and the access point fell back
to 802.11n at 20 MHz on 5 GHz. The radio's `iw phy` output from that box is below.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.config import Config
from nmb.netd import wifi

IW_PHY_PI4 = """	Band 1:
		Capabilities: 0x1020
			HT20
			Static SM Power Save
			RX HT20 SGI
			No RX STBC
			Max AMSDU length: 3839 bytes
			DSSS/CCK HT40
		Maximum RX AMPDU length 65535 bytes (exponent: 0x003)
		Minimum RX AMPDU time spacing: 16 usec (0x07)
		HT TX/RX MCS rate indexes supported: 0-7
		Bitrates (non-HT):
		Frequencies:
	Band 2:
		Capabilities: 0x1062
			HT20/HT40
			Static SM Power Save
			RX HT20 SGI
			RX HT40 SGI
			No RX STBC
			Max AMSDU length: 3839 bytes
			DSSS/CCK HT40
		Maximum RX AMPDU length 65535 bytes (exponent: 0x003)
		Minimum RX AMPDU time spacing: 16 usec (0x07)
		HT TX/RX MCS rate indexes supported: 0-7
		VHT Capabilities (0x00001020):
			Max MPDU length: 3895
			Supported Channel Width: neither 160 nor 80+80
			short GI (80 MHz)
			SU Beamformee
		VHT RX MCS set:
			1 streams: MCS 0-9
			2 streams: not supported
			3 streams: not supported
			4 streams: not supported
			5 streams: not supported
			6 streams: not supported
			7 streams: not supported
			8 streams: not supported
		VHT RX highest supported: 0 Mbps
		VHT TX MCS set:
			1 streams: MCS 0-9
			2 streams: not supported
			3 streams: not supported
			4 streams: not supported
			5 streams: not supported
			6 streams: not supported
			7 streams: not supported
			8 streams: not supported
		VHT TX highest supported: 0 Mbps
		VHT extended NSS: not supported
		Bitrates (non-HT):
		Frequencies:
	Supported commands:
"""


class BandFlagsTest(unittest.TestCase):
    def test_pi4_flags_per_band(self):
        f = wifi.band_flags(IW_PHY_PI4)
        self.assertEqual(f["2.4ghz"]["ht"], ["[SHORT-GI-20]", "[DSSS_CCK-40]"])
        self.assertEqual(f["5ghz"]["ht"], ["[SHORT-GI-20]", "[SHORT-GI-40]", "[DSSS_CCK-40]"])
        self.assertEqual(f["5ghz"]["vht"], ["[SHORT-GI-80]", "[SU-BEAMFORMEE]"])
        self.assertEqual(f["2.4ghz"]["vht"], [])

    def test_ht40_direction(self):
        self.assertEqual([wifi.ht40_direction("5ghz", c) for c in (36, 40, 44, 48, 149, 153)], ["+", "-", "+", "-", "+", "-"])
        self.assertEqual([wifi.ht40_direction("2.4ghz", c) for c in (1, 6, 7, 11)], ["+", "+", "+", "-"])

    def _conf(self, **net):
        cfg = Config().network
        for k, v in net.items():
            setattr(cfg, k, v)
        caps = {"supported_bands": ["2.4ghz", "5ghz"], "supported_standards": ["b", "g", "a", "n", "ac"],
                "highest_standard": "ac", "supported_widths": ["20", "40", "80"], "ht40_bands": ["5ghz"],
                "band_flags": wifi.band_flags(IW_PHY_PI4), "channels": {}}
        with tempfile.TemporaryDirectory() as d, patch.object(wifi, "detect_wifi_capabilities", return_value=caps), \
             patch("nmb.netd.geoip.set_wifi_regulatory_domain"):
            text, meta = wifi.generate_hostapd_config(cfg, "wlan0", Path(d))
        return {l.split("=", 1)[0]: l.split("=", 1)[1] for l in text.splitlines() if "=" in l}, meta

    def test_default_settings_give_ac_80_with_only_real_flags(self):
        c, meta = self._conf(wifi_band="auto", wifi_standard="auto", wifi_channel_width="auto", wifi_channel=0,
                             wifi_country_code="HU")
        self.assertEqual((meta["effective_band"], meta["effective_standard"], meta["effective_width_mhz"]), ("5ghz", "ac", 80))
        self.assertEqual(c["ht_capab"], "[HT40+][SHORT-GI-20][SHORT-GI-40]")   # no DSSS/CCK on 5 GHz
        self.assertEqual(c["vht_capab"], "[SHORT-GI-80][SU-BEAMFORMEE]")
        self.assertNotIn("STBC", c["vht_capab"])
        self.assertEqual((c["vht_oper_chwidth"], c["vht_oper_centr_freq_seg0_idx"]), ("1", "42"))

    def test_owner_setting_24_n_unchanged(self):
        c, meta = self._conf(wifi_band="2.4ghz", wifi_standard="n", wifi_channel_width="auto", wifi_country_code="HU")
        self.assertEqual(meta["effective_width_mhz"], 20)
        self.assertEqual(c["ht_capab"], "[SHORT-GI-20]")
        self.assertNotIn("vht_capab", c)

    def test_channel_40_pairs_downwards(self):
        c, _ = self._conf(wifi_band="5ghz", wifi_standard="n", wifi_channel_width="40", wifi_channel=40, wifi_country_code="HU")
        self.assertTrue(c["ht_capab"].startswith("[HT40-]"))

    def test_160_is_not_claimed_from_a_negative_sentence(self):
        self.assertIn("neither 160 nor 80+80", IW_PHY_PI4)
        import re
        self.assertIsNone(re.search(r"Supported Channel Width: 160", IW_PHY_PI4))


if __name__ == "__main__":
    unittest.main()
