"""Lightweight Telegram Bot API client using standard library urllib.

Supports long-polling getUpdates, sendMessage (HTML format), and sendDocument
with multipart/form-data encoding without any external dependencies.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.bot.client")

API_BASE = "https://api.telegram.org/bot"


class TelegramUnavailable(Exception):
    """getUpdates failed (HTTP error or no network): the caller must wait before asking again."""

    def __init__(self, reason: str, retry_after: float = 0.0):
        super().__init__(reason)
        self.retry_after = retry_after


class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self._tls = threading.local()   # the last error per thread: the alert and speed-test threads share the client

    @property
    def endpoint(self) -> str:
        # Built from the current token: a SIGHUP reload that sets a new token used the old URL before.
        return f"{API_BASE}{self.token}/"

    def _request(self, method: str, data: Optional[Dict[str, Any]] = None, timeout: float = 35.0) -> Optional[Dict[str, Any]]:
        url = self.endpoint + method
        headers = {"User-Agent": "NetworkMeasureBox/1.0"}
        body = None

        if data:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        self._tls.last_error = ""
        self._tls.retry_after = 0.0
        for attempt in (1, 2):
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    if res_data.get("ok"):
                        return res_data.get("result")
                    log.warning("telegram API returned error: %s", res_data)
                    self._tls.last_error = "api error"
                    return None
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                try:
                    self._tls.retry_after = float((json.loads(err_body).get("parameters") or {}).get("retry_after") or 0)
                except (ValueError, AttributeError):
                    self._tls.retry_after = 0.0
                self._tls.last_error = f"HTTP {e.code}"
                log.warning("telegram %s: HTTP %d (%s): %s", method, e.code, e.reason, err_body[:200])
                # A message asked to wait a few seconds is sent once more instead of being lost.
                if e.code == 429 and method != "getUpdates" and attempt == 1 and 0 < self._tls.retry_after <= 10:
                    time.sleep(self._tls.retry_after)
                    continue
                return None
            except Exception as e:
                self._tls.last_error = f"{type(e).__name__}: {e}"
                log.debug("telegram request %s failed: %s", method, e)
                return None
        return None

    def get_me(self) -> Optional[Dict[str, Any]]:
        res = self._request("getMe", timeout=8.0)
        return res if isinstance(res, dict) else None

    def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> List[Dict[str, Any]]:
        payload = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        res = self._request("getUpdates", payload, timeout=float(timeout + 5))
        if res is None and getattr(self._tls, "last_error", ""):
            # 2026-11-09: an error returned [] at once, and the loop asked again ~8 times a second.
            raise TelegramUnavailable(self._tls.last_error, self._tls.retry_after)
        return res if isinstance(res, list) else []

    def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML", reply_markup: Optional[Dict[str, Any]] = None) -> bool:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        res = self._request("sendMessage", payload, timeout=10.0)
        return res is not None

    def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        payload = {"chat_id": chat_id, "action": action}
        res = self._request("sendChatAction", payload, timeout=5.0)
        return res is not None

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None, show_alert: bool = False) -> bool:
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        res = self._request("answerCallbackQuery", payload, timeout=5.0)
        return res is not None

    def send_document(self, chat_id: int, filename: str, content: bytes, caption: str = "") -> bool:
        """Send document using multipart/form-data."""
        boundary = "----------------NMBBoundary7MA4YWxkTrZu0gW"
        url = self.endpoint + "sendDocument"

        body = bytearray()
        # chat_id
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(f"{chat_id}\r\n".encode())

        # caption
        if caption:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(f"{caption}\r\n".encode())
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\n')
            body.extend(b"HTML\r\n")

        # file
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode())
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(content)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(url, data=bytes(body), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "NetworkMeasureBox/1.0",
        })

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return bool(res_data.get("ok"))
        except Exception as e:
            log.warning("failed to send document to telegram: %s", e)
            return False

    def send_photo(self, chat_id: int, photo_bytes: bytes, caption: str = "", filename: str = "image.png") -> bool:
        """Send photo using multipart/form-data."""
        boundary = "----------------NMBBoundaryPhoto7MA4YWxkTrZu0gW"
        url = self.endpoint + "sendPhoto"

        body = bytearray()
        # chat_id
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(f"{chat_id}\r\n".encode())

        # caption
        if caption:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(f"{caption}\r\n".encode())
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\n')
            body.extend(b"HTML\r\n")

        # photo file
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode())
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(photo_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(url, data=bytes(body), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "NetworkMeasureBox/1.0",
        })

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return bool(res_data.get("ok"))
        except Exception as e:
            log.warning("failed to send photo to telegram: %s", e)
            return False
