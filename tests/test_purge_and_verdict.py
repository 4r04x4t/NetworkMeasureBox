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


    def test_measurements_go_in_slices_and_events_stay(self):
        # 2026-11-10: one DELETE of everything filled the 256 MB RAM disk with write-ahead log.
        import sqlite3
        from nmb.db import database as db
        schema = (Path(purge.__file__).resolve().parent.parent / "db" / "schema.sql").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.db"
            c = sqlite3.connect(live)
            c.executescript(schema)
            hour = 3600 * 1000
            c.executemany("INSERT INTO ping_sample (ts, target_id, rtt_us) VALUES (?, 1, 5000)",
                          [(i * 60_000, ) for i in range(3 * 24 * 60)])           # three days, one per minute
            c.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (1, 'info', 'x', 'y', 'z')")
            c.commit()
            c.close()
            slices = []
            real = purge._purge_table_sliced
            with patch.object(db, "get_live_db", return_value=live), \
                 patch.object(db, "snapshot"), \
                 patch.object(purge, "_purge_table_sliced", side_effect=lambda *a: slices.append(a[1]) or real(*a)):
                purge._purge_tables(["measurements"])
            c = sqlite3.connect(live)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM ping_sample").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM event").fetchone()[0], 1)
            c.close()
            self.assertIn("ping_sample", slices)
            self.assertEqual(purge.SLICE_MS, 6 * hour)

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
        # The first five languages live in the MESSAGES tuples, the others in nmb/bot/locales/*.json.
        self.assertTrue(set(LANGUAGE_ORDER) <= set(SUPPORTED_LANGUAGES))
        for key, values in MESSAGES.items():
            self.assertEqual(len(values), len(LANGUAGE_ORDER), key)
            for lang in SUPPORTED_LANGUAGES:
                self.assertIn(key, STRINGS[lang], f"{lang}.{key}")

    def test_foreign_catalog_has_no_hungarian_letters(self):
        for key, values in MESSAGES.items():
            for lang, value in zip(LANGUAGE_ORDER, values):
                if lang != "hu":
                    self.assertIsNone(re.search("[őűŐŰ]", value), f"{lang}.{key}")
            self.assertEqual(t(key, "de"), values[2])


if __name__ == "__main__":
    unittest.main()
