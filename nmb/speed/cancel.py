"""Cancellation of a running measurement, scoped to the thread that runs it."""
from __future__ import annotations

import contextlib
import subprocess
import threading
import time
from typing import Iterator, List, Optional

_local = threading.local()


class MeasurementCancelled(BaseException):
    """Derives from BaseException so the engines' broad handlers cannot start a fallback test."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason = ""

    def cancel(self, reason: str) -> None:
        self.reason = reason
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


@contextlib.contextmanager
def scope(token: CancelToken) -> Iterator[CancelToken]:
    _local.token = token
    try:
        yield token
    finally:
        _local.token = None


def is_requested() -> bool:
    token: Optional[CancelToken] = getattr(_local, "token", None)
    return bool(token and token.is_set())


def current_reason() -> str:
    token: Optional[CancelToken] = getattr(_local, "token", None)
    return token.reason if token else ""


def check() -> None:
    if is_requested():
        raise MeasurementCancelled()


def run(cmd: List[str], timeout: float) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output, text), but kills the process on cancellation."""
    if getattr(_local, "token", None) is None:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)

    check()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            out, err = proc.communicate(timeout=0.25)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            cancelled = is_requested()
            if not cancelled and time.monotonic() < deadline:
                continue
            proc.kill()
            out, err = proc.communicate()
            if cancelled:
                raise MeasurementCancelled() from None
            raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err) from None
