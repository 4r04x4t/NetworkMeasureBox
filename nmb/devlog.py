"""NetworkMeasureBox Developer Logging System.

Provides high-resolution, deep diagnostic logging for developers and maintainers:
- High-precision timestamps (millisecond accuracy)
- File, line number, function name, and thread tagging
- Custom TRACE level (severity 5) for packet-level / wire-level inspection
- Dual persistence: Rotating file handler (/var/log/nmb/nmb_developer.log) + standard output
- In-memory thread-safe circular ring buffer for real-time live web console & REST API streaming
- Dynamic runtime log-level switching without service restart
"""
from __future__ import annotations

import collections
import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

# Register custom TRACE level (below DEBUG)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    """Log 'message % args' with severity 'TRACE'."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


# Attach trace method to Logger class
logging.Logger.trace = trace  # type: ignore[attr-defined]


class DevLogRecord:
    """Structured representation of a single log record for developer inspection."""

    __slots__ = (
        "id",
        "ts",
        "ts_iso",
        "level",
        "level_no",
        "logger",
        "func",
        "line",
        "pathname",
        "filename",
        "thread",
        "message",
        "exc",
    )

    def __init__(
        self,
        record_id: int,
        record: logging.LogRecord,
        formatted_message: str,
        exc_text: Optional[str] = None,
    ) -> None:
        self.id = record_id
        self.ts = record.created
        # ISO8601 string with millisecond precision
        dt = datetime.datetime.fromtimestamp(record.created)
        self.ts_iso = dt.strftime("%Y-%m-%d %H:%M:%S") + f".{int(record.msecs):03d}"
        self.level = record.levelname
        self.level_no = record.levelno
        self.logger = record.name
        self.func = record.funcName
        self.line = record.lineno
        self.pathname = record.pathname
        self.filename = record.filename
        self.thread = record.threadName
        self.message = formatted_message
        self.exc = exc_text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ts": int(self.ts * 1000),
            "ts_iso": self.ts_iso,
            "level": self.level,
            "level_no": self.level_no,
            "logger": self.logger,
            "func": self.func,
            "line": self.line,
            "filename": self.filename,
            "thread": self.thread,
            "message": self.message,
            "exc": self.exc,
        }


class DevLogFormatter(logging.Formatter):
    """High-density developer log formatter with milliseconds, code location, and thread."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s.%(msecs)03d [%(levelname)-7s] [%(name)s:%(funcName)s:%(lineno)d] [T:%(threadName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")


class DevLogBufferHandler(logging.Handler):
    """Thread-safe in-memory circular ring buffer for real-time live streaming."""

    def __init__(self, capacity: int = 5000) -> None:
        super().__init__()
        self.capacity = capacity
        self._buffer: collections.deque[DevLogRecord] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._counter = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            exc_text = None
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
            elif record.exc_text:
                exc_text = record.exc_text

            with self._lock:
                self._counter += 1
                rec_id = self._counter
                entry = DevLogRecord(rec_id, record, msg, exc_text)
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_records(
        self,
        min_level: Optional[str] = None,
        logger_prefix: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        since_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Filter and return buffer records formatted as dictionaries."""
        min_lvl_no = 0
        if min_level and min_level.upper() != "ALL":
            lvl_name = min_level.upper()
            if lvl_name == "TRACE":
                min_lvl_no = TRACE
            elif lvl_name == "WARN":
                min_lvl_no = logging.WARNING
            else:
                min_lvl_no = getattr(logging, lvl_name, 0)

        q = (search or "").strip().lower()
        l_pref = (logger_prefix or "").strip().lower()

        results: List[Dict[str, Any]] = []
        with self._lock:
            # Iterate in reverse for latest first, then reverse back
            for entry in reversed(self._buffer):
                if since_id is not None and entry.id <= since_id:
                    break

                if min_lvl_no > 0 and entry.level_no < min_lvl_no:
                    continue

                if l_pref and l_pref != "all":
                    if not entry.logger.lower().startswith(l_pref):
                        continue

                if q:
                    blob = f"{entry.logger} {entry.func} {entry.filename} {entry.message} {entry.exc or ''}".lower()
                    if q not in blob:
                        continue

                results.append(entry.to_dict())
                if len(results) >= limit:
                    break

        results.reverse()
        return results

    def clear(self) -> None:
        """Clear all buffered log records."""
        with self._lock:
            self._buffer.clear()

    @property
    def total_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._counter


# Singleton handler instances
_BUFFER_HANDLER: Optional[DevLogBufferHandler] = None
_FILE_HANDLER: Optional[RotatingFileHandler] = None
_CONSOLE_HANDLER: Optional[logging.StreamHandler] = None
_ACTIVE_LOG_FILE: Optional[str] = None
_SETUP_LOCK = threading.Lock()


def get_dev_log_buffer() -> DevLogBufferHandler:
    """Return the global in-memory developer log buffer handler."""
    global _BUFFER_HANDLER
    if _BUFFER_HANDLER is None:
        _BUFFER_HANDLER = DevLogBufferHandler(capacity=5000)
    return _BUFFER_HANDLER


def get_active_log_file() -> Optional[str]:
    """Return the path of the active rotating developer log file."""
    return _ACTIVE_LOG_FILE


def setup_dev_logging(
    cfg: Any = None,
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    max_bytes: int = 10485760,  # 10 MB
    backup_count: int = 5,
    console: bool = True,
) -> DevLogBufferHandler:
    """Initialize deep developer logging across the entire application."""
    global _BUFFER_HANDLER, _FILE_HANDLER, _CONSOLE_HANDLER, _ACTIVE_LOG_FILE

    with _SETUP_LOCK:
        # Determine log level
        if not level:
            if cfg and hasattr(cfg, "logging") and getattr(cfg.logging, "level", None):
                level = cfg.logging.level
            else:
                level = "DEBUG"

        lvl_name = level.upper()
        if lvl_name == "TRACE":
            lvl_no = TRACE
        elif lvl_name == "WARN":
            lvl_no = logging.WARNING
        else:
            lvl_no = getattr(logging, lvl_name, logging.DEBUG)

        root = logging.getLogger()
        root.setLevel(lvl_no)

        formatter = DevLogFormatter()

        # 1. Console Handler (stdout)
        if _CONSOLE_HANDLER is None and console:
            _CONSOLE_HANDLER = logging.StreamHandler(sys.stdout)
            _CONSOLE_HANDLER.setFormatter(formatter)
            _CONSOLE_HANDLER.setLevel(lvl_no)
            root.addHandler(_CONSOLE_HANDLER)
        elif _CONSOLE_HANDLER:
            _CONSOLE_HANDLER.setLevel(lvl_no)

        # 2. In-Memory Ring Buffer Handler
        if _BUFFER_HANDLER is None:
            _BUFFER_HANDLER = DevLogBufferHandler(capacity=5000)
            _BUFFER_HANDLER.setFormatter(formatter)
            _BUFFER_HANDLER.setLevel(TRACE)  # Buffer collects all details down to TRACE
            root.addHandler(_BUFFER_HANDLER)

        # 3. File Handler (Rotating)
        if not log_file:
            if cfg and hasattr(cfg, "logging") and getattr(cfg.logging, "file_path", None):
                log_file = cfg.logging.file_path
            else:
                # Default locations with fallbacks
                candidates = [
                    Path("/var/log/nmb/nmb_developer.log"),
                    Path("/var/lib/nmb/live/nmb_developer.log"),
                    Path("/tmp/nmb_developer.log"),
                ]
                for c in candidates:
                    try:
                        c.parent.mkdir(parents=True, exist_ok=True)
                        # Check write permission
                        test_file = c.parent / ".write_test"
                        test_file.touch()
                        test_file.unlink()
                        log_file = str(c)
                        break
                    except Exception:
                        continue
                if not log_file:
                    log_file = "/tmp/nmb_developer.log"

        if _FILE_HANDLER is None and log_file:
            try:
                target_p = Path(log_file)
                target_p.parent.mkdir(parents=True, exist_ok=True)
                _FILE_HANDLER = RotatingFileHandler(
                    log_file,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                _FILE_HANDLER.setFormatter(formatter)
                _FILE_HANDLER.setLevel(lvl_no)
                root.addHandler(_FILE_HANDLER)
                _ACTIVE_LOG_FILE = log_file
            except Exception as e:
                sys.stderr.write(f"[nmb.devlog] Warning: Could not initialize rotating log file {log_file}: {e}\n")
        elif _FILE_HANDLER:
            _FILE_HANDLER.setLevel(lvl_no)

        # Suppress overly chatty external third-party loggers if needed
        for noisy in ("urllib3", "requests"):
            n_log = logging.getLogger(noisy)
            if n_log.level < logging.INFO:
                n_log.setLevel(logging.INFO)

        log = logging.getLogger("nmb.devlog")
        log.info(
            "Developer logging initialized (level=%s, file=%s, buffer_capacity=5000)",
            lvl_name,
            _ACTIVE_LOG_FILE or "none",
        )

        return _BUFFER_HANDLER


def set_runtime_log_level(level_name: str) -> Dict[str, Any]:
    """Dynamically switch logging level at runtime across all handlers and loggers."""
    lvl_name = level_name.strip().upper()
    if lvl_name == "TRACE":
        lvl_no = TRACE
    elif lvl_name == "WARN":
        lvl_no = logging.WARNING
    else:
        lvl_no = getattr(logging, lvl_name, None)

    if lvl_no is None:
        raise ValueError(f"Invalid log level: {level_name}")

    root = logging.getLogger()
    prev_level = logging.getLevelName(root.level)
    root.setLevel(lvl_no)

    if _CONSOLE_HANDLER:
        _CONSOLE_HANDLER.setLevel(lvl_no)
    if _FILE_HANDLER:
        _FILE_HANDLER.setLevel(lvl_no)

    # Also adjust all existing nmb loggers
    for name in list(logging.root.manager.loggerDict.keys()):
        if name.startswith("nmb"):
            l = logging.getLogger(name)
            l.setLevel(lvl_no)

    log = logging.getLogger("nmb.devlog")
    log.info("Runtime logging level changed from %s to %s", prev_level, lvl_name)

    return {
        "status": "ok",
        "previous_level": prev_level,
        "new_level": lvl_name,
        "level_no": lvl_no,
    }


def read_raw_log_tail(max_lines: int = 500) -> str:
    """Read the tail of the active developer log file."""
    if not _ACTIVE_LOG_FILE or not os.path.exists(_ACTIVE_LOG_FILE):
        return "Log file not found or logging to file is disabled."

    try:
        with open(_ACTIVE_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-max_lines:])
    except Exception as e:
        return f"Error reading log file {_ACTIVE_LOG_FILE}: {e}"


# -------------------------------------------------------------------------
# Hardware & Linux Kernel Syslog System (Router-Grade Diagnostics)
# -------------------------------------------------------------------------

_ANSI_RE = re.compile(r"(\x1b|\^\[)\[[0-9;]*[a-zA-Z]")


def clean_ansi(text: str) -> str:
    """Strip ANSI escape sequences from log lines."""
    return _ANSI_RE.sub("", text)


def _parse_syslog_line(raw_line: str) -> Dict[str, Any]:
    """Parse, classify and enrich a single syslog or dmesg line."""
    clean = clean_ansi(raw_line).strip("\r\n")
    l_lower = clean.lower()

    # Determine severity / status level
    if any(k in l_lower for k in [
        "link is up", "link up at", "link up -", "carrier on",
        "link restored", "wan was restored", "wan(0) link up"
    ]):
        lvl = "link_up"
    elif "wlceventd" in l_lower and ("assoc" in l_lower or "auth" in l_lower) and "successful" in l_lower:
        lvl = "link_up"
    elif any(k in l_lower for k in [
        "link is down", "link down", "carrier off", "disassoc", "deauth",
        "connection terminated", "wan(0) link down"
    ]):
        lvl = "link_down"
    elif any(k in l_lower for k in [
        "dump_stack", "unwind_backtrace", "exception stack", "tainted:", "pc is at", "lr is at"
    ]):
        lvl = "stacktrace"
    elif any(k in l_lower for k in [
        "panic", "oops", "err -", "bad block", "timed out", "timeout"
    ]) or ("fail" in l_lower and "safe" not in l_lower and "default" not in l_lower) or ("error" in l_lower and "error code 0" not in l_lower):
        lvl = "error"
    elif any(k in l_lower for k in ["warn", "retry", "temporary", "dropped"]):
        lvl = "warn"
    else:
        lvl = "info"

    # Determine category
    is_kernel = "kernel:" in l_lower or clean.startswith("[<")
    is_network = any(k in l_lower for k in [
        "eth0", "eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7", "wlan0", "wlan1",
        "bcmgenet", "carrier", "phy", "dhcp", "pppd", "openvpn", "vpnserver", "inadyn",
        "ddns", "wlceventd", "acsd", "bsd:", "roamast", "1gbps", "1000 mbps", "full duplex",
        "link is", "network", "wpa_supplicant", "hostapd", "dnsmasq", "ppp0", "tun21",
        "net_ratelimit", "chanspec", "dfs state", "bridge", "bonding"
    ])
    is_nmb = any(k in l_lower for k in [
        "nmb-web", "nmb-probe", "nmb.speed", "nmb.db", "nmb.sniffer", "nmb.netd", "nmb.devlog", "speedtest"
    ])
    is_security = any(k in l_lower for k in [
        "sshd", "ssh-session", "pam_unix", "sudo", "systemd-logind", "accepted publickey", "session closed"
    ])

    if is_kernel and not is_network:
        cat = "kernel"
    elif is_network:
        cat = "network"
    elif is_nmb:
        cat = "nmb"
    elif is_security:
        cat = "security"
    elif is_kernel:
        cat = "kernel"
    else:
        cat = "system"

    # Parse standard syslog structure: <Mon> <Day> <Time> <Host> <Tag>: <Msg>
    ts = ""
    host = ""
    tag = ""
    msg = clean
    parts = clean.split(maxsplit=4)
    if len(parts) >= 5 and len(parts[0]) == 3 and parts[1].isdigit() and ":" in parts[2]:
        ts = f"{parts[0]} {parts[1]:>2} {parts[2]}"
        host = parts[3]
        remainder = parts[4]
        if ":" in remainder:
            p_tag, p_msg = remainder.split(":", 1)
            tag = p_tag.strip()
            msg = p_msg.strip()
        else:
            tag = ""
            msg = remainder
    elif clean.startswith("202") and len(parts) >= 3:
        ts = parts[0]
        host = parts[1]
        remainder = " ".join(parts[2:])
        if ":" in remainder:
            p_tag, p_msg = remainder.split(":", 1)
            tag = p_tag.strip()
            msg = p_msg.strip()
        else:
            msg = remainder

    return {
        "raw": clean,
        "ts": ts,
        "host": host,
        "tag": tag,
        "msg": msg,
        "category": cat,
        "level": lvl,
    }


def fetch_raw_system_logs(lines: int = 500, source: str = "all") -> List[str]:
    """Fetch raw system journal or kernel ring buffer log lines."""
    has_journalctl = shutil.which("journalctl") is not None

    if has_journalctl:
        if source == "kernel":
            cmd = ["journalctl", "-k", "-n", str(lines), "--no-pager"]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
                if p.returncode == 0 and p.stdout.strip():
                    return p.stdout.splitlines()
            except Exception:
                pass
        elif source == "network":
            k_lines = []
            try:
                pk = subprocess.run(["journalctl", "-k", "-n", str(min(lines * 2, 1200)), "--no-pager"], capture_output=True, text=True, timeout=5)
                if pk.returncode == 0:
                    k_lines = [l for l in pk.stdout.splitlines() if any(n in l.lower() for n in ("eth", "wlan", "bcmgenet", "link is", "carrier", "phy"))]
            except Exception:
                pass
            u_lines = []
            try:
                pu = subprocess.run(["journalctl", "-n", str(lines), "--no-pager"], capture_output=True, text=True, timeout=5)
                if pu.returncode == 0:
                    u_lines = pu.stdout.splitlines()
            except Exception:
                pass
            combined = list(dict.fromkeys(k_lines + u_lines))
            if combined:
                return combined
        elif source == "nmb":
            cmd = ["journalctl", "-u", "nmb-web", "-u", "nmb-probe", "-n", str(lines), "--no-pager"]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
                if p.returncode == 0 and p.stdout.strip():
                    return p.stdout.splitlines()
            except Exception:
                pass
        elif source == "security":
            cmd = ["journalctl", "-u", "ssh", "-u", "sshd", "-u", "systemd-logind", "-n", str(lines), "--no-pager"]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
                if p.returncode == 0 and p.stdout.strip():
                    return p.stdout.splitlines()
            except Exception:
                pass
        else:
            k_lines = []
            try:
                pk = subprocess.run(["journalctl", "-k", "-n", str(min(lines, 800)), "--no-pager"], capture_output=True, text=True, timeout=5)
                if pk.returncode == 0:
                    k_lines = pk.stdout.splitlines()
            except Exception:
                pass
            u_lines = []
            try:
                pu = subprocess.run(["journalctl", "-n", str(lines), "--no-pager"], capture_output=True, text=True, timeout=6)
                if pu.returncode == 0:
                    u_lines = pu.stdout.splitlines()
            except Exception:
                pass
            combined = list(dict.fromkeys(k_lines + u_lines))
            if combined:
                return combined

    # Fallback 1: dmesg -T for kernel ring buffer
    if source in ("kernel", "all", "network"):
        if shutil.which("dmesg"):
            try:
                p = subprocess.run(["dmesg", "-T"], capture_output=True, text=True, timeout=5)
                if p.returncode == 0 and p.stdout.strip():
                    dmesg_lines = p.stdout.splitlines()
                    if source == "kernel":
                        return dmesg_lines[-lines:]
            except Exception:
                pass

    # Fallback 2: /var/log/syslog or /var/log/messages or /var/log/kern.log
    for log_path in ("/var/log/syslog", "/var/log/messages", "/var/log/kern.log"):
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    file_lines = f.readlines()
                    if file_lines:
                        return [l.rstrip("\r\n") for l in file_lines[-lines:]]
            except Exception:
                continue

    # Fallback 3: internal developer log buffer
    buf = get_dev_log_buffer()
    records = buf.get_records(limit=lines)
    return [f"{r['ts_iso']} [{r['level']}] [{r['logger']}] {r['message']}" for r in records]


def get_system_syslog(
    lines: int = 300,
    source: str = "all",
    severity: str = "all",
    search: str = "",
) -> Dict[str, Any]:
    """Retrieve filtered, classified system and kernel syslog entries."""
    fetch_count = min(max(lines * 2, 400), 4000)
    if severity == "links" or source == "network":
        fetch_count = min(max(lines * 4, 1200), 4000)
    raw_lines = fetch_raw_system_logs(lines=fetch_count, source=source)

    entries = []
    kernel_cnt = 0
    network_cnt = 0
    error_cnt = 0
    link_cnt = 0

    s_lower = (source or "all").lower()
    sev_lower = (severity or "all").lower()
    q = (search or "").strip().lower()

    for idx, raw in enumerate(raw_lines):
        parsed = _parse_syslog_line(raw)
        parsed["id"] = idx + 1

        # Track global counters across the retrieved buffer
        if parsed["category"] == "kernel" or "kernel:" in parsed["raw"].lower():
            kernel_cnt += 1
        if parsed["category"] == "network" or parsed["level"] in ("link_up", "link_down"):
            network_cnt += 1
        if parsed["level"] in ("error", "stacktrace"):
            error_cnt += 1
        if parsed["level"] in ("link_up", "link_down"):
            link_cnt += 1

        # Apply source filter (if not already handled strictly by command)
        if s_lower == "kernel" and parsed["category"] != "kernel" and "kernel:" not in parsed["raw"].lower():
            continue
        elif s_lower == "network" and parsed["category"] != "network" and parsed["level"] not in ("link_up", "link_down"):
            continue
        elif s_lower == "nmb" and parsed["category"] != "nmb":
            continue
        elif s_lower == "security" and parsed["category"] != "security":
            continue

        # Apply severity filter
        if sev_lower == "errors" and parsed["level"] not in ("error", "stacktrace"):
            continue
        elif sev_lower == "warnings" and parsed["level"] != "warn":
            continue
        elif sev_lower == "links" and parsed["level"] not in ("link_up", "link_down"):
            continue

        # Apply text / regex search
        if q:
            blob = f"{parsed['raw']} {parsed['tag']} {parsed['msg']}".lower()
            if q not in blob:
                continue

        entries.append(parsed)

    # Return latest 'lines' entries
    if len(entries) > lines:
        entries = entries[-lines:]

    return {
        "status": "ok",
        "source": source,
        "severity": severity,
        "search": search,
        "count": len(entries),
        "stats": {
            "total_raw": len(raw_lines),
            "kernel": kernel_cnt,
            "network": network_cnt,
            "errors": error_cnt,
            "links": link_cnt,
        },
        "hostname": socket.gethostname(),
        "system_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
    }


def get_raw_system_syslog(
    lines: int = 1500,
    source: str = "all",
    severity: str = "all",
    search: str = "",
) -> str:
    """Return raw text system log suitable for download or console stream."""
    data = get_system_syslog(lines=lines, source=source, severity=severity, search=search)
    entries = data.get("entries", [])
    return "\n".join(e["raw"] for e in entries)
