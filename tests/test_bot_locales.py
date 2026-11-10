"""Telegram bot languages in nmb/bot/locales: complete, same placeholders and HTML as English, no Hungarian."""
import json
import re
import unittest
from collections import Counter
from pathlib import Path

from nmb.bot import i18n as B

LOCALES = Path(__file__).resolve().parent.parent / "nmb" / "bot" / "locales"
PH = re.compile(r"\{[^}]*\}")
TAG = re.compile(r"</?([a-zA-Z0-9]+)")


class BotLocaleTest(unittest.TestCase):
    def _files(self):
        return {p.stem.replace("_", "-"): json.loads(p.read_text(encoding="utf-8")) for p in LOCALES.glob("*.json")}

    def test_every_language_is_complete(self):
        # the setup texts come from nmb/common/setup_texts.py for every language (tests/test_measurement_setup.py)
        en = set(B.STRINGS["en"]) - B.SHARED_KEYS
        for code, data in self._files().items():
            with self.subTest(lang=code):
                self.assertEqual(sorted(en - set(data["strings"])), [])
                self.assertEqual(set(data["alerts"]), set(B.ALERT_TEMPLATES["en"]))
                self.assertEqual([len(r) for r in data["keyboard"]], [len(r) for r in B._base_main_keyboard("en")["keyboard"]])
                self.assertIn(code, B.SUPPORTED_LANGUAGES)

    def test_placeholders_html_and_no_hungarian(self):
        for code, data in self._files().items():
            pairs = [(data["strings"][k], B.STRINGS["en"][k]) for k in data["strings"]]
            pairs += [(data["alerts"][k], B.ALERT_TEMPLATES["en"][k]) for k in data["alerts"]]
            for text, en in pairs:
                with self.subTest(lang=code, text=text[:40]):
                    self.assertEqual(Counter(PH.findall(text)), Counter(PH.findall(en)))
                    self.assertEqual(Counter(TAG.findall(text)), Counter(TAG.findall(en)))
                    self.assertIsNone(re.search(r"[őűŐŰ]", text))

    def test_buttons_of_every_language_reach_their_command(self):
        aliases = B.get_menu_aliases()
        for code in B.SUPPORTED_LANGUAGES:
            for row in B.get_main_keyboard(code)["keyboard"]:
                for button in row:
                    with self.subTest(lang=code, button=button["text"]):
                        self.assertIn(button["text"].lower(), aliases)

    def test_non_compliant_is_never_read_as_compliant(self):
        for code in B.SUPPORTED_LANGUAGES:
            with self.subTest(lang=code):
                self.assertNotEqual(B.get_sla_verdict("NEM MEGFELELŐ", code), B.get_sla_verdict("MEGFELELŐ", code))


class NoInlineLanguageTest(unittest.TestCase):
    def test_commands_have_no_inline_language_chains(self):
        # Texts written as `"..." if lang == "hu" else ...` reach only the languages listed there.
        src = (Path(__file__).resolve().parent.parent / "nmb" / "bot" / "commands.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"if lang == \"[a-z-]+\" else", src))


if __name__ == "__main__":
    unittest.main()
