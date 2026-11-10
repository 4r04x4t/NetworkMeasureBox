"""The Wi-Fi country list: every country of the wireless regulatory database, validated (2026-11-10)."""
import re
import tempfile
import unittest
from pathlib import Path

from nmb.config import load_config
from nmb.netd import regdomains
from nmb.web.i18n import TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent


class RegdomainListTest(unittest.TestCase):
    def test_list_covers_the_regulatory_database(self):
        self.assertEqual(len(regdomains.REGDOMAINS), 181)          # wireless-regdb 2026.05.30 without "00"
        for code, dfs in regdomains.REGDOMAINS.items():
            self.assertRegex(code, r"^[A-Z]{2}$")
            self.assertIn(dfs, ("", "ETSI", "FCC", "JP"))
        self.assertEqual((regdomains.REGDOMAINS["HU"], regdomains.REGDOMAINS["US"], regdomains.REGDOMAINS["JP"]),
                         ("ETSI", "FCC", "JP"))
        # the old list's countries are all still there
        for code in ("AT", "DE", "FR", "GB", "HU", "UA", "US"):
            self.assertIn(code, regdomains.REGDOMAINS)

    def test_normalize(self):
        self.assertEqual(regdomains.normalize_country("hu"), "HU")
        self.assertEqual(regdomains.normalize_country(" AUTO "), "auto")
        self.assertEqual(regdomains.normalize_country("00"), "00")
        for bad in ("XX", "", None, "HUN", "h1", "auto; reboot"):
            self.assertIsNone(regdomains.normalize_country(bad), bad)

    def test_choices_are_sorted_pairs(self):
        choices = regdomains.country_choices()
        self.assertEqual(len(choices), 181)
        self.assertEqual(choices, sorted(choices))
        self.assertIn(["HU", "ETSI"], choices)


class ConfigCountryTest(unittest.TestCase):
    def _load(self, value):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nmb.conf"
            p.write_text(f"[network]\nwifi_country_code = {value}\n")
            return load_config(p).network.wifi_country_code

    def test_known_country_is_kept(self):
        self.assertEqual(self._load("hu"), "HU")
        self.assertEqual(self._load("BR"), "BR")

    def test_unknown_country_falls_back_to_auto(self):
        # hostapd refuses an unknown country code and the access point would not start at all
        with self.assertLogs("nmb.config", level="WARNING"):
            self.assertEqual(self._load("XX"), "AUTO")


class CountryUiTest(unittest.TestCase):
    def test_page_has_no_fixed_country_names(self):
        html = (ROOT / "nmb/web/assets/dashboard.html").read_text(encoding="utf-8")
        select = re.search(r'<select id="cfg-wifi-country".*?</select>', html, re.S).group(0)
        values = re.findall(r'<option value="([^"]+)"', select)
        self.assertEqual(values, ["auto", "00", "HU"])                # the rest comes from the box, named by the browser
        self.assertNotIn("Hungary", select)
        js = (ROOT / "nmb/web/assets/dashboard.js").read_text(encoding="utf-8")
        self.assertIn("Intl.DisplayNames", js)
        self.assertIn("d.wifi_countries", js)

    def test_new_texts_in_every_language(self):
        for lang, texts in TRANSLATIONS.items():
            for key in ("rt_country_world", "rt_country_hint", "rt_country_auto"):
                self.assertIn(key, texts, f"{lang}: {key}")
        self.assertNotEqual(TRANSLATIONS["de"]["rt_country_hint"], TRANSLATIONS["en"]["rt_country_hint"])


if __name__ == "__main__":
    unittest.main()
