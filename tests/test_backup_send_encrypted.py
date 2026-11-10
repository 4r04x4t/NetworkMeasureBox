"""/backup send is encrypted by default (audit bot H1, owner's decision 2026-11-10)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nmb.bot.commands import CommandHandler
from nmb.common import backup
from nmb.config import Config
from tests.test_telegram_bot import MockTelegramClient

PASS = "correct horse battery staple"


class BackupSendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.archive = self.dir / "nmb-backup-x.tar.gz"
        self.archive.write_bytes(b"[telegram]\ntoken = 123:SECRET\n")
        p = mock.patch.object(backup, "BACKUP_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)
        self.cfg = Config()
        self.cfg.telegram.allowed_chat_ids = [1]
        self.client = MockTelegramClient()
        self.h = CommandHandler(self.cfg, self.client)

    def texts(self):
        return "\n".join(m[1] for m in self.client.sent_messages)

    def test_without_passphrase_nothing_is_sent(self):
        self.h.handle_command(1, "/backup send nmb-backup-x.tar.gz")
        self.assertEqual(self.client.sent_documents, [])
        self.assertIn("plain", self.texts())

    def test_short_passphrase_counts_as_none(self):
        self.cfg.telegram.backup_passphrase = "short"
        self.h.handle_command(1, "/backup send nmb-backup-x.tar.gz")
        self.assertEqual(self.client.sent_documents, [])

    @unittest.skipUnless(shutil.which("gpg"), "gpg not installed")
    def test_encrypted_by_default_and_opens_with_gpg(self):
        self.cfg.telegram.backup_passphrase = PASS
        self.h.handle_command(1, "/backup send nmb-backup-x.tar.gz")
        self.assertEqual(len(self.client.sent_documents), 1)
        _chat, name, content, caption = self.client.sent_documents[0]
        self.assertEqual(name, "nmb-backup-x.tar.gz.gpg")
        self.assertNotIn(b"SECRET", content)
        self.assertIn("gpg -d", caption)
        enc = self.dir / name
        enc.write_bytes(content)
        with tempfile.TemporaryDirectory() as home:
            out = subprocess.run(["gpg", "--homedir", home, "--batch", "--pinentry-mode", "loopback",
                                  "--passphrase", PASS, "-d", str(enc)], capture_output=True, check=False)
            self.assertEqual(out.stdout, self.archive.read_bytes())
            bad = subprocess.run(["gpg", "--homedir", home, "--batch", "--pinentry-mode", "loopback",
                                  "--passphrase", "wrong passphrase!!", "-d", str(enc)], capture_output=True, check=False)
            self.assertNotEqual(bad.returncode, 0)

    def test_passphrase_never_on_the_command_line(self):
        self.cfg.telegram.backup_passphrase = PASS
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, b"ENC", b"")

        with mock.patch.object(backup.shutil, "which", return_value="/usr/bin/gpg"), \
                mock.patch.object(backup.subprocess, "run", fake_run):
            self.h.handle_command(1, "/backup send nmb-backup-x.tar.gz")
        self.assertFalse(any(PASS in str(a) for a in seen["cmd"]))
        self.assertIn("--passphrase-fd", seen["cmd"])
        self.assertEqual(self.client.sent_documents[0][2], b"ENC")

    def test_encryption_failure_sends_nothing(self):
        self.cfg.telegram.backup_passphrase = PASS
        with mock.patch.object(backup.shutil, "which", return_value=None):
            self.h.handle_command(1, "/backup send nmb-backup-x.tar.gz")
        self.assertEqual(self.client.sent_documents, [])

    def test_plain_on_request_with_warning(self):
        self.h.handle_command(1, "/backup send nmb-backup-x.tar.gz plain")
        self.assertEqual(self.client.sent_documents[0][1], "nmb-backup-x.tar.gz")
        self.assertIn("⚠️", self.texts())

    def test_path_traversal_still_refused(self):
        self.cfg.telegram.backup_passphrase = PASS
        self.h.handle_command(1, "/backup send ../../etc/passwd plain")
        self.assertEqual(self.client.sent_documents, [])


class PassphraseRuleTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(backup.passphrase_problem(PASS), "")
        self.assertEqual(backup.passphrase_problem("x" * 11), "short")
        self.assertEqual(backup.passphrase_problem(" " + PASS), "invalid")
        self.assertEqual(backup.passphrase_problem(PASS + "\n"), "invalid")

    def test_config_round_trip_and_masked(self):
        from nmb.common.redact import is_secret_key
        self.assertTrue(is_secret_key("backup_passphrase"))
        with tempfile.TemporaryDirectory() as d:
            from nmb import config as c
            cfg = c.Config()
            cfg.telegram.backup_passphrase = "p%ss #word with spaces"
            path = Path(d) / "nmb.conf"
            with mock.patch.object(c, "save_config", wraps=c.save_config):
                c.save_config(cfg, path)
            self.assertEqual(c.load_config(path).telegram.backup_passphrase, "p%ss #word with spaces")


if __name__ == "__main__":
    unittest.main()
