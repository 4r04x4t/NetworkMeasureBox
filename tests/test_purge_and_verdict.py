"""Tests for data purge, the SLA verdict wording and bot language purity."""
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nmb.bot.i18n import STRINGS, SUPPORTED_LANGUAGES, get_sla_verdict, t
from nmb.bot.messages import LANGUAGE_ORDER, MESSAGES
from nmb.common import purge


class PurgeTests(unittest.TestCase):
    def test_rejects_unknown_and_empty(self):
        with self.assertRaises(ValueError):
            purge.purge(None, ["config"])
        with self.assertRaises(ValueError):
            purge.purge(None, [])

    def test_deletes_only_selected_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "persist" / "reports"
            reports.mkdir(parents=True)
            (reports / "a.html").write_text("x")
            backups = Path(tmp) / "backups"
            backups.mkdir()
            (backups / "b.tar.gz").write_text("x")
            cfg = SimpleNamespace(system=SimpleNamespace(data_dir=tmp))
            with patch.object(purge.backup, "BACKUP_DIR", backups):
                result = purge.purge(cfg, ["reports"])
            self.assertEqual(result["deleted"]["reports"], 1)
            self.assertFalse((reports / "a.html").exists())
            self.assertTrue((backups / "b.tar.gz").exists())


class BotLanguageTests(unittest.TestCase):
    def test_verdict_is_translated_everywhere(self):
        for lang in SUPPORTED_LANGUAGES:
            for verdict in ("COMPLIANT", "DEGRADED", "BREACHED"):
                value = get_sla_verdict(verdict, lang)
                self.assertTrue(value)
                self.assertNotEqual(value, "BREACHED")

    def test_no_regulator_wording(self):
        pattern = re.compile(r"nmhh|szélessáv\.net|regulatory|hatósági minősítés", re.I)
        for lang in SUPPORTED_LANGUAGES:
            for key, value in STRINGS[lang].items():
                self.assertIsNone(pattern.search(str(value)), f"{lang}.{key}")

    def test_catalog_has_every_language(self):
        self.assertEqual(set(LANGUAGE_ORDER), set(SUPPORTED_LANGUAGES))
        for key, values in MESSAGES.items():
            self.assertEqual(len(values), 5, key)

    def test_foreign_catalog_has_no_hungarian_letters(self):
        for key, values in MESSAGES.items():
            for lang, value in zip(LANGUAGE_ORDER, values):
                if lang != "hu":
                    self.assertIsNone(re.search("[őűŐŰ]", value), f"{lang}.{key}")
            self.assertEqual(t(key, "de"), values[2])


if __name__ == "__main__":
    unittest.main()
