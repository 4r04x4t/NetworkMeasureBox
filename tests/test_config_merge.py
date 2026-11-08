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
