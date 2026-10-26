"""Lightweight Telegram Bot API client using standard library urllib.

Supports long-polling getUpdates, sendMessage (HTML format), and sendDocument
with multipart/form-data encoding without any external dependencies.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.bot.client")

API_BASE = "https://api.telegram.org/bot"


class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.endpoint = f"{API_BASE}{token}/"

    def _request(self, method: str, data: Optional[Dict[str, Any]] = None, timeout: float = 35.0) -> Optional[Dict[str, Any]]:
        url = self.endpoint + method
        headers = {"User-Agent": "NetworkMeasureBox/1.0"}
        body = None

        if data:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if res_data.get("ok"):
                    return res_data.get("result")
                log.warning("telegram API returned error: %s", res_data)
                return None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            log.warning("telegram HTTP %d (%s): %s", e.code, e.reason, err_body)
            return None
        except Exception as e:
            log.debug("telegram request %s failed: %s", method, e)
            return None

    def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> List[Dict[str, Any]]:
        payload = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        res = self._request("getUpdates", payload, timeout=float(timeout + 5))
        return res if isinstance(res, list) else []

    def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML") -> bool:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        res = self._request("sendMessage", payload, timeout=10.0)
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
