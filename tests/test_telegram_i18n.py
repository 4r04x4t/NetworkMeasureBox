"""Comprehensive unit tests for multilingual Telegram bot functionality and foreign-language purity."""
import os
import tempfile
import unittest
from pathlib import Path

from nmb.bot.client import TelegramClient
from nmb.bot.commands import CommandHandler
from nmb.bot.alerts import AlertMonitor
from nmb.bot.i18n import (
    DEFAULT_LANGUAGE,
    LANG_INFO,
    SUPPORTED_LANGUAGES,
    STRINGS,
    ALERT_TEMPLATES,
    format_alert,
    get_chat_lang,
    get_language_keyboard,
    get_main_keyboard,
    get_menu_aliases,
    get_nmhh_status,
    get_sla_verdict,
    set_chat_lang,
    t,
)
from nmb.config import Config
from nmb.db import database as db


class MockTelegramClient:
    def __init__(self):
        self.sent_messages = []
        self.sent_documents = []
        self.sent_photos = []
        self.last_reply_markup = None

    def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML", reply_markup: dict = None) -> bool:
        self.sent_messages.append((chat_id, text, parse_mode))
        self.last_reply_markup = reply_markup
        return True

    def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        return True

    def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False) -> bool:
        return True

    def send_document(self, chat_id: int, filename: str, content: bytes, caption: str = "") -> bool:
        self.sent_documents.append((chat_id, filename, content, caption))
        return True

    def send_photo(self, chat_id: int, photo_bytes: bytes, caption: str = "", filename: str = "image.png") -> bool:
        self.sent_photos.append((chat_id, photo_bytes, caption, filename))
        return True


class TestTelegramI18n(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

        self.db_path = self.tmp_path / "nmb.db"
        self.orig_live_env = os.environ.get("NMB_LIVE_DB")
        self.orig_persist_env = os.environ.get("NMB_PERSIST_DB")
        os.environ["NMB_LIVE_DB"] = str(self.db_path)
        os.environ["NMB_PERSIST_DB"] = str(self.db_path)

        conn = db.connect()
        db.init(conn)
        conn.close()

        self.cfg = Config()
        self.cfg.system.box_id = "test-box-i18n"
        self.cfg.telegram.enabled = True
        self.cfg.telegram.token = "123456:TEST_TOKEN"
        self.cfg.telegram.allowed_chat_ids = [10001, 10002, 10003]

        self.mock_client = MockTelegramClient()
        self.handler = CommandHandler(self.cfg, self.mock_client)

    def tearDown(self):
        if self.orig_live_env is not None:
            os.environ["NMB_LIVE_DB"] = self.orig_live_env
        else:
            os.environ.pop("NMB_LIVE_DB", None)

        if self.orig_persist_env is not None:
            os.environ["NMB_PERSIST_DB"] = self.orig_persist_env
        else:
            os.environ.pop("NMB_PERSIST_DB", None)

        self.tmpdir.cleanup()

    def test_supported_languages(self):
        expected = ["hu", "en", "de", "fr", "uk"]
        self.assertEqual(sorted(SUPPORTED_LANGUAGES), sorted(expected))
        for lang in expected:
            self.assertIn(lang, LANG_INFO)
            self.assertIn("name", LANG_INFO[lang])
            self.assertIn("flag", LANG_INFO[lang])

    def test_chat_lang_persistence(self):
        # Default when nothing saved
        self.assertEqual(get_chat_lang(10001, self.cfg), "en")

        # Set valid language
        self.assertTrue(set_chat_lang(10001, "de"))
        self.assertEqual(get_chat_lang(10001, self.cfg), "de")

        # Set another chat
        self.assertTrue(set_chat_lang(10002, "uk"))
        self.assertEqual(get_chat_lang(10002, self.cfg), "uk")
        # Chat 10001 remains de
        self.assertEqual(get_chat_lang(10001, self.cfg), "de")

        # Reject invalid language
        self.assertFalse(set_chat_lang(10001, "es"))
        self.assertEqual(get_chat_lang(10001, self.cfg), "de")

    def test_main_keyboards_all_languages(self):
        for lang in SUPPORTED_LANGUAGES:
            kb = get_main_keyboard(lang)
            self.assertIn("keyboard", kb)
            self.assertTrue(kb.get("resize_keyboard"))
            self.assertTrue(kb.get("persistent"))
            rows = kb["keyboard"]
            self.assertEqual(len(rows), 5)
            # Row 5 has the language button
            self.assertTrue(any("Language" in b["text"] or "Nyelv" in b["text"] or "Sprache" in b["text"] or "Langue" in b["text"] or "Мова" in b["text"] for b in rows[4]))

    def test_language_keyboard(self):
        kb = get_language_keyboard()
        self.assertIn("inline_keyboard", kb)
        rows = kb["inline_keyboard"]
        all_cb = [btn["callback_data"] for row in rows for btn in row]
        for lang in SUPPORTED_LANGUAGES:
            self.assertIn(f"/lang {lang}", all_cb)

    def test_menu_aliases_mapping(self):
        aliases = get_menu_aliases()
        # Ensure buttons from all 5 languages are mapped
        self.assertEqual(aliases["📊 gyors sebességmérés"], "/test")
        self.assertEqual(aliases["📊 quick speed test"], "/test")
        self.assertEqual(aliases["📊 schneller speedtest"], "/test")
        self.assertEqual(aliases["📊 test de débit rapide"], "/test")
        self.assertEqual(aliases["📊 швидкий тест швидкості"], "/test")

        self.assertEqual(aliases["📈 nmhh riport letöltése"], "/report")
        self.assertEqual(aliases["📈 download nmhh report"], "/report")
        self.assertEqual(aliases["📈 nmhh-bericht herunterladen"], "/report")

        self.assertEqual(aliases["🌐 nyelv / language"], "/lang")
        self.assertEqual(aliases["🌐 sprache / language"], "/lang")

    def test_nmhh_status_and_sla_verdicts(self):
        for lang in SUPPORTED_LANGUAGES:
            badge_ok, desc_ok = get_nmhh_status(1, lang)
            self.assertTrue("MEGFELELŐ" in badge_ok or "COMPLIANT" in badge_ok or "KONFORM" in badge_ok or "CONFORME" in badge_ok or "ВІДПОВІДАЄ" in badge_ok)

            v_ok = get_sla_verdict("MEGFELELT", lang)
            self.assertTrue(len(v_ok) > 0)

    def test_foreign_language_zero_hungarian_text_purity(self):
        """CRITICAL: Foreign languages (en, de, fr, uk) must NOT contain Hungarian marker words."""
        hu_markers = [
            " és ", " vagy ", "nem ", "állapot", "sebesség", "mérés", "késleltetés",
            "szolgáltató", "letöltés", "feltöltés", "csomagvesztés", "rendszerállapot",
            "parancsok", "súgó", "mentés", "kapcsolódva"
        ]

        for lang in ("en", "de", "fr", "uk"):
            for key, val in STRINGS[lang].items():
                val_lower = str(val).lower()
                for marker in hu_markers:
                    self.assertNotIn(
                        marker, val_lower,
                        f"Purity violation: Hungarian marker '{marker.strip()}' found in {lang}['{key}']: {val}"
                    )

            for key, val in ALERT_TEMPLATES[lang].items():
                val_lower = str(val).lower()
                for marker in hu_markers:
                    self.assertNotIn(
                        marker, val_lower,
                        f"Purity violation: Hungarian marker '{marker.strip()}' found in ALERT_TEMPLATES['{lang}']['{key}']: {val}"
                    )

    def test_lang_command_switch_and_reply_keyboard(self):
        chat_id = 10001
        # Switch to German
        self.handler.handle_command(chat_id, "/lang de")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        _, text, _ = self.mock_client.sent_messages[-1]
        self.assertIn("Deutsch", text)
        self.assertIn("erfolgreich", text)
        # Reply keyboard should now be German
        kb = self.mock_client.last_reply_markup
        self.assertIsNotNone(kb)
        self.assertEqual(kb["keyboard"][0][0]["text"], "📊 Schneller Speedtest")

        # Now test that clicking the German button triggers speedtest
        self.handler.handle_command(chat_id, "📊 Schneller Speedtest")
        _, test_msg, _ = self.mock_client.sent_messages[-1]
        self.assertIn("Speedtest", test_msg)
        # Make sure no Hungarian in the German message
        self.assertNotIn("Sebességmérés indítása", test_msg)

    def test_multilingual_commands_purity(self):
        """Test commands in different languages and verify zero Hungarian words."""
        chat_id = 10001
        hu_markers = [" és ", " vagy ", "állapot", "sebesség", "késleltetés", "szolgáltató"]

        # German
        set_chat_lang(chat_id, "de")
        self.mock_client.sent_messages.clear()
        self.handler.handle_command(chat_id, "/help")
        _, help_de, _ = self.mock_client.sent_messages[-1]
        self.assertIn("Verwaltungs-Chatbot", help_de)
        for m in hu_markers:
            self.assertNotIn(m, help_de.lower())

        # French
        set_chat_lang(chat_id, "fr")
        self.mock_client.sent_messages.clear()
        self.handler.handle_command(chat_id, "/help")
        _, help_fr, _ = self.mock_client.sent_messages[-1]
        self.assertIn("Chatbot de Gestion", help_fr)
        for m in hu_markers:
            self.assertNotIn(m, help_fr.lower())

        # Ukrainian
        set_chat_lang(chat_id, "uk")
        self.mock_client.sent_messages.clear()
        self.handler.handle_command(chat_id, "/help")
        _, help_uk, _ = self.mock_client.sent_messages[-1]
        self.assertIn("Керуючий чат-бот", help_uk)
        for m in hu_markers:
            self.assertNotIn(m, help_uk.lower())


if __name__ == "__main__":
    unittest.main()
