"""Telegram client errors (2026-11-09: 22 requests in 5 s while Telegram answered 429/502)."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from nmb.bot import client as C


def _http(code, retry=None):
    body = {"ok": False, "error_code": code}
    if retry:
        body["parameters"] = {"retry_after": retry}
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps(body).encode()))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BackoffTest(unittest.TestCase):
    def test_get_updates_error_makes_the_caller_wait(self):
        cl = C.TelegramClient("t")
        with patch.object(C.urllib.request, "urlopen", side_effect=_http(429, 5)):
            with self.assertRaises(C.TelegramUnavailable) as e:
                cl.get_updates(offset=1, timeout=1)
        self.assertEqual(e.exception.retry_after, 5)
        with patch.object(C.urllib.request, "urlopen", side_effect=OSError("Network is unreachable")):
            with self.assertRaises(C.TelegramUnavailable):
                cl.get_updates(timeout=1)

    def test_no_updates_is_not_an_error(self):
        cl = C.TelegramClient("t")
        with patch.object(C.urllib.request, "urlopen", return_value=_Resp(b'{"ok":true,"result":[]}')):
            self.assertEqual(cl.get_updates(timeout=1), [])

    def test_message_is_sent_again_after_a_short_wait(self):
        cl = C.TelegramClient("t")
        answers = [_http(429, 2), _Resp(b'{"ok":true,"result":{"message_id":1}}')]
        with patch.object(C.urllib.request, "urlopen", side_effect=lambda *a, **k: (_ for _ in ()).throw(answers.pop(0))
                          if isinstance(answers[0], Exception) else answers.pop(0)), patch.object(C.time, "sleep") as sl:
            self.assertTrue(cl.send_message(1, "hi"))
        sl.assert_called_once_with(2.0)


if __name__ == "__main__":
    unittest.main()
