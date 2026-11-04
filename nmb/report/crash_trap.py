"""Invasive Crash Trapper, Local Variable Introspector & Emergency Diagnostic Dumper.

Intercepts unhandled Python exceptions and thread failures across all NMB services,
extracting local variables, full call stacks, and hardware/network states,
then persists an incident report both locally and to the FAT32 boot partition
so developers and AI assistants can immediately reconstruct the failure without device access.
"""
from __future__ import annotations

import datetime
import inspect
import json
import logging
import os
import sys
import tarfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.report.crash")

CRASH_DIR = Path("/var/log/nmb/crashes")
FALLBACK_CRASH_DIR = Path.home() / ".local/share/nmb/crashes"
MAX_CRASH_REPORTS = 15

_orig_sys_excepthook = sys.excepthook
_orig_threading_excepthook = getattr(threading, "excepthook", None)
_trap_installed = False
_trap_lock = threading.Lock()


def get_boot_drive_crashes_target() -> Optional[Path]:
    """Find appropriate location on FAT32 boot partition for emergency crash dumps."""
    candidates = [
        Path("/boot/firmware/nmb_crashes"),
        Path("/boot/nmb_crashes"),
        Path("/mnt/boot/nmb_crashes"),
    ]
    for c in candidates:
        parent = c.parent
        if parent.is_dir():
            try:
                c.mkdir(parents=True, exist_ok=True)
                test_file = c / ".nmb_write_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink(missing_ok=True)
                return c
            except (PermissionError, OSError):
                continue
    return None


def _sanitize_repr(val: Any, max_len: int = 180) -> str:
    """Safely format variable value representation without leaking huge objects."""
    try:
        r = repr(val)
        if len(r) > max_len:
            return r[:max_len] + f"... [truncated {len(r)} bytes]"
        return r
    except Exception as e:
        return f"<Unrepresentable object: {e}>"


def _is_sensitive_key(k: str) -> bool:
    """Detect passwords, keys, and tokens to prevent leaking secrets in crash dumps."""
    norm = k.lower()
    return any(s in norm for s in ("password", "passwd", "secret", "token", "auth_key", "credential"))


def _extract_frame_locals(tb) -> List[Dict[str, Any]]:
    """Walk all frames in traceback and extract safe representation of local variables."""
    frames_data = []
    curr = tb
    while curr is not None:
        frame = curr.tb_frame
        code = frame.f_code
        locs: Dict[str, str] = {}
        for k, v in frame.f_locals.items():
            if _is_sensitive_key(k):
                locs[k] = "****** [REDACTED SECRET]"
            else:
                locs[k] = _sanitize_repr(v)

        frames_data.append({
            "filename": code.co_filename,
            "line_no": curr.tb_lineno,
            "function": code.co_name,
            "locals": locs,
        })
        curr = curr.tb_next
    return frames_data


def format_crash_report(
    exc_type: type,
    exc_value: BaseException,
    exc_tb,
    thread_name: str = "MainThread"
) -> Tuple[str, Dict[str, Any]]:
    """Assemble a comprehensive Markdown crash report and metadata dictionary."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    now_local = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    frames = _extract_frame_locals(exc_tb)

    # Telemetry at time of failure
    temp_c = "N/A"
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_c = f"{float(f.read().strip()) / 1000.0:.1f} °C"
    except Exception:
        pass

    load_avg = "N/A"
    try:
        with open("/proc/loadavg", "r") as f:
            load_avg = f.read().strip()
    except Exception:
        pass

    from nmb.netd.interfaces import find_preferred_measurement_interface
    pref_iface, pref_ip, is_wired = find_preferred_measurement_interface()

    meta = {
        "timestamp_utc": now_utc,
        "timestamp_local": now_local,
        "process_name": sys.argv[0],
        "pid": os.getpid(),
        "thread_name": thread_name,
        "exception_type": getattr(exc_type, "__name__", str(exc_type)),
        "exception_message": str(exc_value),
        "preferred_interface": pref_iface,
        "preferred_ip": pref_ip,
        "is_wired": is_wired,
        "frames": frames,
    }

    lines = [
        "# 💥 NetworkMeasureBox — Fatal Crash Incident Report",
        f"> **Generated at**: `{now_local}` (`{now_utc}`) | **PID**: `{os.getpid()}` | **Thread**: `{thread_name}`",
        f"> **Process**: `{sys.argv[0]}` | **Arguments**: `{' '.join(sys.argv[1:])}`",
        "",
        "## 🚨 Exception Summary",
        f"- **Type**: `{getattr(exc_type, '__name__', str(exc_type))}`",
        f"- **Message**: `{exc_value}`",
        f"- **CPU Temp**: `{temp_c}` | **Load Average**: `{load_avg}`",
        f"- **Egress Network**: `{pref_iface}` (IP: `{pref_ip}`, Wired: `{is_wired}`)",
        "",
        "## 📜 Standard Traceback",
        "```text",
        tb_str.strip(),
        "```",
        "",
        "## 🔬 Frame-by-Frame Local Variable Introspection",
    ]

    for idx, f in enumerate(frames, start=1):
        lines.append(f"### Frame {idx}: `{f['function']}` in `{f['filename']}:{f['line_no']}`")
        if f["locals"]:
            lines.append("| Variable | Value |")
            lines.append("| :--- | :--- |")
            for var_name, var_val in f["locals"].items():
                safe_val = var_val.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| `{var_name}` | `{safe_val}` |")
        else:
            lines.append("*(No local variables)*")
        lines.append("")

    lines.extend([
        "## 💡 AI Developer Recovery Steps",
        "1. Inspect the variable values above in the failing frame to identify invalid inputs or states.",
        "2. Review the latest invasive snapshot `/var/log/nmb/invasive_dev_snapshot.md` for contemporaneous system changes.",
        "3. Restart the failed service via `systemctl restart nmb-*` or `bin/nmb-helper`.",
    ])

    return "\n".join(lines), meta


def save_crash_report(md_content: str, meta: Dict[str, Any]) -> List[Path]:
    """Persist crash report to /var/log/nmb/crashes and mirror to FAT32 boot drive."""
    saved_paths: List[Path] = []
    ts_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    proc_slug = Path(sys.argv[0]).stem or "proc"
    fname = f"crash_{ts_slug}_{proc_slug}_{os.getpid()}.md"

    # 1. Primary path
    for d in (CRASH_DIR, FALLBACK_CRASH_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
            target = d / fname
            target.write_text(md_content, encoding="utf-8")
            saved_paths.append(target)
            _prune_old_reports(d)
            break
        except (PermissionError, OSError):
            continue

    # 2. Mirror to FAT32 Boot Partition
    try:
        boot_dir = get_boot_drive_crashes_target()
        if boot_dir:
            boot_target = boot_dir / fname
            boot_target.write_text(md_content, encoding="utf-8")
            saved_paths.append(boot_target)
            _prune_old_reports(boot_dir)
            log.info("mirrored fatal crash report to FAT32 boot partition: %s", boot_target)
    except Exception as e:
        log.debug("could not mirror crash report to boot drive: %s", e)

    # 3. Log to SQLite event table
    try:
        from nmb.db import database as db
        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'crit', 'crash', 'unhandled_exception', ?)",
                (db.now_ms(), f"Unhandled exception in {proc_slug}: {meta.get('exception_type')}: {meta.get('exception_message')}")
            )
        conn.close()
    except Exception:
        pass

    return saved_paths


def _prune_old_reports(directory: Path) -> None:
    """Keep only the latest MAX_CRASH_REPORTS files in directory."""
    try:
        files = sorted(directory.glob("crash_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[MAX_CRASH_REPORTS:]:
            try:
                old.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def handle_unhandled_exception(
    exc_type: type,
    exc_value: BaseException,
    exc_tb,
    thread_name: str = "MainThread"
) -> None:
    """Handler executed when an unhandled exception reaches top of stack."""
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return

    try:
        log.critical("UNHANDLED FATAL EXCEPTION: %s: %s", exc_type.__name__, exc_value)
        md, meta = format_crash_report(exc_type, exc_value, exc_tb, thread_name=thread_name)
        paths = save_crash_report(md, meta)
        log.critical("crash dump successfully persisted to: %s", ", ".join(str(p) for p in paths))
    except Exception as e:
        log.critical("error while generating emergency crash dump: %s", e)


def _sys_excepthook(exc_type, exc_value, exc_tb):
    handle_unhandled_exception(exc_type, exc_value, exc_tb, thread_name="MainThread")
    if _orig_sys_excepthook:
        _orig_sys_excepthook(exc_type, exc_value, exc_tb)


def _threading_excepthook(args):
    handle_unhandled_exception(args.exc_type, args.exc_value, args.exc_traceback, thread_name=getattr(args.thread, "name", "Thread"))
    if _orig_threading_excepthook:
        _orig_threading_excepthook(args)


def install_crash_trap() -> None:
    """Install global crash interceptor hooks across process and threads."""
    global _trap_installed
    with _trap_lock:
        if _trap_installed:
            return
        sys.excepthook = _sys_excepthook
        if hasattr(threading, "excepthook"):
            threading.excepthook = _threading_excepthook
        _trap_installed = True
        log.debug("invasive crash trap interceptor installed for process %s (PID %d)", sys.argv[0], os.getpid())


def list_crash_reports() -> List[Dict[str, Any]]:
    """List all available crash reports across local storage and boot drive."""
    reports: List[Dict[str, Any]] = []
    seen = set()

    search_dirs = [CRASH_DIR, FALLBACK_CRASH_DIR]
    boot_dir = get_boot_drive_crashes_target()
    if boot_dir:
        search_dirs.append(boot_dir)

    for d in search_dirs:
        if d.is_dir():
            for p in d.glob("crash_*.md"):
                if p.name in seen:
                    continue
                seen.add(p.name)
                try:
                    stat = p.stat()
                    reports.append({
                        "filename": p.name,
                        "path": str(p),
                        "size_bytes": stat.st_size,
                        "created_ts": stat.st_mtime,
                        "created_iso": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "location": "boot_drive" if "boot" in str(p) else "local_disk",
                    })
                except Exception:
                    pass

    reports.sort(key=lambda x: x["created_ts"], reverse=True)
    return reports


def read_crash_report(filename: str) -> Optional[str]:
    """Read specific crash report text by filename."""
    clean = Path(filename).name
    search_dirs = [CRASH_DIR, FALLBACK_CRASH_DIR]
    boot_dir = get_boot_drive_crashes_target()
    if boot_dir:
        search_dirs.append(boot_dir)

    for d in search_dirs:
        p = d / clean
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                pass
    return None


def clear_crash_reports() -> int:
    """Clear all crash reports across storage locations."""
    count = 0
    search_dirs = [CRASH_DIR, FALLBACK_CRASH_DIR]
    boot_dir = get_boot_drive_crashes_target()
    if boot_dir:
        search_dirs.append(boot_dir)

    for d in search_dirs:
        if d.is_dir():
            for p in d.glob("crash_*.md"):
                try:
                    p.unlink(missing_ok=True)
                    count += 1
                except Exception:
                    pass
    return count


def create_diagnostic_bundle() -> Path:
    """Package complete system state, logs, snapshots, and crashes into a single .tar.gz archive."""
    out_dir = Path("/var/log/nmb/bundles")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        out_dir = Path.home() / ".local/share/nmb/bundles"
        out_dir.mkdir(parents=True, exist_ok=True)

    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_path = out_dir / f"nmb_diagnostic_bundle_{ts_str}.tar.gz"

    with tarfile.open(bundle_path, mode="w:gz") as tar:
        # 1. Invasive Snapshots
        for snap_p in (
            Path("/var/log/nmb/invasive_dev_snapshot.md"),
            Path("/var/log/nmb/invasive_dev_snapshot.json"),
            Path.home() / ".local/share/nmb/invasive_dev_snapshot.md",
        ):
            if snap_p.is_file():
                tar.add(snap_p, arcname=f"diagnostics/{snap_p.name}")

        # 2. Crash Reports
        for cr_dir in (CRASH_DIR, FALLBACK_CRASH_DIR):
            if cr_dir.is_dir():
                for cr in cr_dir.glob("crash_*.md"):
                    tar.add(cr, arcname=f"crashes/{cr.name}")

        # 3. Configurations
        for conf_p in (Path("/etc/nmb/nmb.conf"), Path("/boot/firmware/nmb.conf"), Path("/boot/nmb.conf")):
            try:
                if conf_p.is_file():
                    tar.add(conf_p, arcname=f"config/{conf_p.name}")
            except (PermissionError, OSError):
                pass

        # 4. Standard Logs
        log_dir = Path("/var/log/nmb")
        if log_dir.is_dir():
            for l in log_dir.glob("*.log"):
                if l.stat().st_size < 10 * 1024 * 1024:  # under 10MB
                    tar.add(l, arcname=f"logs/{l.name}")

    log.info("assembled complete diagnostic bundle archive: %s (%d bytes)", bundle_path, bundle_path.stat().st_size)
    return bundle_path
