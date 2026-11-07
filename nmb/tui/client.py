"""Client for the box's own REST API, the same one the WebGUI uses."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from nmb.config import load_config


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, url: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None):
        env_password = os.environ.get("NMB_PASSWORD")
        cfg = None
        if not (url and (password or env_password)):
            cfg = load_config()
        port = cfg.web.port if cfg else 80
        self.url = (url or os.environ.get("NMB_URL") or f"http://127.0.0.1:{port}").rstrip("/")
        self.user = user or os.environ.get("NMB_USER") or (cfg.web.admin_username if cfg else "admin")
        self.password = password or env_password or (cfg.web.admin_password if cfg else "")

    def _request(self, method: str, path: str, body: Optional[dict], timeout: float) -> Tuple[int, bytes, str]:
        data = json.dumps(body or {}).encode() if method == "POST" else None
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        request = urllib.request.Request(self.url + path, data=data, method=method, headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "")
        except (OSError, ValueError) as e:
            raise ApiError(f"Cannot reach the box at {self.url}: {e}") from e

    def call(self, method: str, path: str, body: Optional[dict] = None, timeout: float = 30.0) -> Dict[str, Any]:
        if method == "GET" and body:
            path = f"{path}?{urllib.parse.urlencode(body)}"
        status, raw, _ = self._request(method, path, body if method == "POST" else None, timeout)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except ValueError:
            parsed = {"text": raw.decode("utf-8", "replace")}
        if not isinstance(parsed, dict):
            parsed = {"items": parsed}
        parsed.setdefault("http_status", status)
        return parsed

    def download(self, path: str, query: Optional[dict] = None, directory: str = ".") -> str:
        target = f"{path}?{urllib.parse.urlencode(query)}" if query else path
        status, raw, _ = self._request("GET", target, None, 120.0)
        if status != 200:
            raise ApiError(f"HTTP {status}: {raw[:200].decode('utf-8', 'replace')}")
        name = path.rstrip("/").rsplit("/", 1)[-1] or "download"
        out = Path(directory) / f"nmb-{name}"
        out.write_bytes(raw)
        return str(out)
