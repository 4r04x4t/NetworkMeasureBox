"""Two processes with their own copy of the config must not undo each other's saves."""
import shutil
import tempfile
import unittest
from pathlib import Path

from nmb.config import load_config, save_config

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "nmb.conf.example"


class ConfigMergeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "nmb.conf"
        shutil.copy(EXAMPLE, self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_old_copy_does_not_wipe_token(self):
        web, bot = load_config(self.path), load_config(self.path)
        web.telegram.token = "123456:ABC"
        self.assertTrue(save_config(web, self.path))
        bot.storage.keep_days = 30          # the other process changes something else
        self.assertTrue(save_config(bot, self.path))
        fresh = load_config(self.path)
        self.assertEqual(fresh.telegram.token, "123456:ABC")
        self.assertEqual(fresh.storage.keep_days, 30)

    def test_own_change_still_wins_and_clearing_works(self):
        a = load_config(self.path)
        a.telegram.token = "1:X"
        save_config(a, self.path)
        b = load_config(self.path)
        b.telegram.token = ""                # an explicit clear is a change, so it is written
        save_config(b, self.path)
        self.assertEqual(load_config(self.path).telegram.token, "")

    def test_repeated_saves_of_one_process(self):
        a = load_config(self.path)
        a.storage.keep_days = 9
        save_config(a, self.path)
        a.storage.keep_days = 10
        save_config(a, self.path)
        self.assertEqual(load_config(self.path).storage.keep_days, 10)


if __name__ == "__main__":
    unittest.main()


class DriveConfigSecretsTest(unittest.TestCase):
    def test_empty_drive_secret_never_wipes_a_set_one(self):
        # 2026-11-08 on the box: a stale drive copy had "token =" and replaced the real Telegram token.
        from nmb.config import merge_drive_config
        current = "[telegram]\ntoken = 123:abc\n[network]\nwifi_psk = longenough1\n"
        drive = "[telegram]\ntoken =\n[network]\nwifi_psk = __KEEP_CURRENT__\n"
        out = merge_drive_config(drive, current)
        self.assertIn("token = 123:abc", out)
        self.assertIn("wifi_psk = longenough1", out)

    def test_a_new_secret_on_the_drive_still_applies(self):
        from nmb.config import merge_drive_config
        out = merge_drive_config("[telegram]\ntoken = 999:new\n", "[telegram]\ntoken = 123:abc\n")
        self.assertIn("token = 999:new", out)

    def test_unchanged_drive_copy_is_not_applied(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import nmb.config as C
        d = Path(tempfile.mkdtemp())
        etc, drive = d / "nmb.conf", d / "drive.conf"
        etc.write_text("[telegram]\ntoken = 123:abc\n[system]\nbox_id = a\n")
        drive.write_text("# header\n" + C.mask_secrets(etc.read_text()))
        os.utime(drive, (etc.stat().st_mtime + 60, etc.stat().st_mtime + 60))
        before = etc.read_text()
        with patch.object(C, "DEFAULT_CONFIG_PATH", etc), patch.object(C, "find_drive_config_path", return_value=drive), \
             patch.object(C, "sync_drive_config"):
            C.load_config()
        self.assertEqual(etc.read_text(), before)
