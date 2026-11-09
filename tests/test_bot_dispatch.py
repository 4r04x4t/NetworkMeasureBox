"""The bot keeps answering during a speed test (2026-11-09: silent for minutes)."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.bot import daemon as D


def _bot():
    cls = next(v for v in vars(D).values() if isinstance(v, type) and hasattr(v, "_dispatch"))
    bot = cls.__new__(cls)
    bot.commands = MagicMock()
    bot.client = MagicMock()
    bot.cfg = SimpleNamespace()
    return bot


class DispatchTest(unittest.TestCase):
    def test_speed_test_runs_in_a_thread_and_others_answer(self):
        bot = _bot()
        release = threading.Event()
        started = threading.Event()

        def handle(chat, text):
            if text.startswith("/test"):
                started.set()
                release.wait(5)
        bot.commands.handle_command.side_effect = handle
        with patch("nmb.bot.i18n.get_chat_lang", return_value="en"):
            bot._dispatch(1, "/test")
            self.assertTrue(started.wait(2))
            bot._dispatch(1, "/status")                 # answered while the test runs
            bot._dispatch(1, "/speedtest")              # a second test is refused politely
        self.assertIn(((1, "/status"),), [c[:1] for c in bot.commands.handle_command.call_args_list])
        bot.client.send_message.assert_called_once()
        self.assertIn("⏳", bot.client.send_message.call_args[0][1])
        release.set()
        bot._long_job.join(5)


if __name__ == "__main__":
    unittest.main()


class BotSandboxTest(unittest.TestCase):
    def test_bot_can_write_where_its_commands_write(self):
        # 2026-11-09: only /var/lib/nmb/live was writable, so /dyndns on|off|token, /heal state and the Ookla
        # licence (a new client every run, rate limits) all failed under the bot.
        from pathlib import Path
        unit = (Path(__file__).resolve().parent.parent / "systemd" / "nmb-telegram.service").read_text()
        rw = next(ln for ln in unit.splitlines() if ln.startswith("ReadWritePaths=")).split("=", 1)[1].split()
        for path in ("/var/lib/nmb", "/etc/nmb", "/run/nmb", "/var/log/nmb"):
            self.assertIn(path, rw)
