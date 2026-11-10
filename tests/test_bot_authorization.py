"""The bot authorises the person, not just the chat (audit bot H2/M2/L2/M4)."""
import time
import unittest
from unittest import mock

from nmb.bot.client import TelegramClient
from nmb.bot.daemon import CALLBACK_COMMANDS, TelegramDaemon
from nmb.config import Config

OWNER = 4242
GROUP = -100777
STRANGER = 999


class FakeClient:
    def __init__(self):
        self.sent = []
        self.answered = []

    def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return True

    def answer_callback_query(self, cb_id, *a, **kw):
        self.answered.append(cb_id)
        return True


def make(allowed):
    cfg = Config()
    cfg.telegram.token = "123:abc"
    cfg.telegram.allowed_chat_ids = list(allowed)
    with mock.patch("nmb.bot.daemon.CommandHandler"), mock.patch("nmb.bot.daemon.AlertMonitor"):
        d = TelegramDaemon(cfg)
    d.client = FakeClient()
    d.dispatched = []
    d._dispatch = lambda chat_id, text: d.dispatched.append((chat_id, text))
    return d


def msg(chat_id, user_id, text="/status", ctype=None, date=None, key="message"):
    ctype = ctype or ("private" if chat_id > 0 else "supergroup")
    return {"update_id": 1, key: {"chat": {"id": chat_id, "type": ctype}, "from": {"id": user_id},
                                  "text": text, "date": int(time.time()) if date is None else date}}


def cb(chat_id, user_id, data, ctype=None):
    ctype = ctype or ("private" if chat_id > 0 else "supergroup")
    return {"update_id": 2, "callback_query": {"id": "q1", "from": {"id": user_id}, "data": data,
                                               "message": {"chat": {"id": chat_id, "type": ctype}}}}


class PerUserTest(unittest.TestCase):
    def test_owner_private_chat_runs(self):
        d = make([OWNER])
        d.handle_update(msg(OWNER, OWNER))
        self.assertEqual(d.dispatched, [(OWNER, "/status")])

    def test_group_member_not_listed_is_ignored_silently(self):
        d = make([OWNER, GROUP])
        d.handle_update(msg(GROUP, STRANGER, "/reboot"))
        self.assertEqual(d.dispatched, [])
        self.assertEqual(d.client.sent, [], "the group must not get an Access Denied for each member")

    def test_listed_user_in_listed_group_runs(self):
        d = make([OWNER, GROUP])
        d.handle_update(msg(GROUP, OWNER))
        self.assertEqual(d.dispatched, [(GROUP, "/status")])

    def test_listed_group_alone_authorises_nobody(self):
        d = make([GROUP])
        d.handle_update(msg(GROUP, OWNER))
        self.assertEqual(d.dispatched, [])

    def test_listed_user_in_unlisted_group_is_refused(self):
        d = make([OWNER])
        d.handle_update(msg(-5555, OWNER))
        self.assertEqual(d.dispatched, [])

    def test_missing_sender_or_bot_sender_refused(self):
        d = make([OWNER, GROUP])
        u = msg(GROUP, OWNER)
        del u["message"]["from"]
        d.handle_update(u)
        u = msg(GROUP, OWNER)
        u["message"]["from"]["is_bot"] = True
        d.handle_update(u)
        self.assertEqual(d.dispatched, [])

    def test_stranger_private_chat_told_once(self):
        d = make([OWNER])
        for _ in range(5):
            d.handle_update(msg(STRANGER, STRANGER, "/reboot"))
        self.assertEqual(d.dispatched, [])
        self.assertEqual(len(d.client.sent), 1, "rate-limited Access Denied")


class UpdateKindsTest(unittest.TestCase):
    def test_edited_message_is_not_run(self):
        d = make([OWNER])
        d.handle_update(msg(OWNER, OWNER, "/reboot", key="edited_message"))
        self.assertEqual(d.dispatched, [])

    def test_stale_command_is_not_run(self):
        d = make([OWNER])
        d.handle_update(msg(OWNER, OWNER, "/kill 1234", date=int(time.time()) - 3600))
        self.assertEqual(d.dispatched, [])

    def test_fresh_command_runs(self):
        d = make([OWNER])
        d.handle_update(msg(OWNER, OWNER, date=int(time.time()) - 5))
        self.assertEqual(len(d.dispatched), 1)


class CallbackTest(unittest.TestCase):
    def test_known_button_runs(self):
        d = make([OWNER])
        d.handle_update(cb(OWNER, OWNER, "/test ookla"))
        d.handle_update(cb(OWNER, OWNER, "/lang de"))
        self.assertEqual([t for _, t in d.dispatched], ["/test ookla", "/lang de"])
        self.assertEqual(d.client.answered, ["q1", "q1"])

    def test_forged_callback_data_ignored(self):
        d = make([OWNER])
        for data in ("/reboot", "/kill 1", "/vpn add x", "/lang ../../x", "/mode a", "/test; reboot"):
            d.handle_update(cb(OWNER, OWNER, data))
        self.assertEqual(d.dispatched, [])

    def test_button_pressed_by_unlisted_group_member_ignored(self):
        d = make([OWNER, GROUP])
        d.handle_update(cb(GROUP, STRANGER, "/adblock off"))
        self.assertEqual(d.dispatched, [])

    def test_every_button_of_the_bot_is_allowed(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent / "nmb" / "bot"
        found = set()
        for f in ("commands.py", "i18n.py"):
            found |= set(re.findall(r'"callback_data": "(/[^"]+)"', (root / f).read_text()))
        found |= {"/adblock on", "/adblock off"}
        d = make([OWNER])
        for data in found:
            self.assertTrue(d._callback_allowed(data), data)
        self.assertTrue(found - {x for x in found if x.startswith("/lang ")} <= CALLBACK_COMMANDS)


class ReloadTest(unittest.TestCase):
    def test_endpoint_follows_token(self):
        c = TelegramClient("old")
        c.token = "new"
        self.assertIn("botnew/", c.endpoint)


if __name__ == "__main__":
    unittest.main()
