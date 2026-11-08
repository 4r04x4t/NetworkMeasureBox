"""Web UI languages in nmb/web/locales: complete, same placeholders and HTML as English, no Hungarian."""
import json
import re
import unittest
from collections import Counter
from pathlib import Path

from nmb.web.i18n import LOCALE_LANGUAGES, TRANSLATIONS

LOCALES = Path(__file__).resolve().parent.parent / "nmb" / "web" / "locales"
PLACEHOLDER = re.compile(r"\{[a-zA-Z_0-9]*\}|%[sd]")
TAG = re.compile(r"</?([a-zA-Z0-9]+)")
HUNGARIAN_ONLY = re.compile(r"[őűŐŰ]")


def _load(code):
    return json.loads((LOCALES / f"{code.replace('-', '_')}.json").read_text(encoding="utf-8"))


class LocaleFilesTest(unittest.TestCase):
    def test_every_language_has_every_key(self):
        en = set(TRANSLATIONS["en"])
        for code in LOCALE_LANGUAGES:
            with self.subTest(lang=code):
                data = _load(code)
                self.assertEqual(sorted(en - set(data)), [], f"{code}: missing keys")
                self.assertEqual(sorted(set(data) - en), [], f"{code}: keys English does not have")

    def test_placeholders_and_html_match_english(self):
        en = TRANSLATIONS["en"]
        for code in LOCALE_LANGUAGES:
            for key, text in _load(code).items():
                if key not in en:
                    continue
                with self.subTest(lang=code, key=key):
                    self.assertTrue(text.strip() or not en[key].strip(), "empty translation")
                    self.assertEqual(Counter(PLACEHOLDER.findall(text)), Counter(PLACEHOLDER.findall(en[key])))
                    self.assertEqual(Counter(TAG.findall(text)), Counter(TAG.findall(en[key])))

    def test_no_hungarian_in_other_languages(self):
        for code in LOCALE_LANGUAGES:
            for key, text in _load(code).items():
                with self.subTest(lang=code, key=key):
                    self.assertIsNone(HUNGARIAN_ONLY.search(text))


if __name__ == "__main__":
    unittest.main()
