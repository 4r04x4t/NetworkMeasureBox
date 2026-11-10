"""NetworkMeasureBox Automated Self-Healing, Multi-Tier Component Correction,
and Safe Stable Updates Engine with Automatic Rollback Protection.

Provides:
- Comprehensive health audit across binaries, symlinks, SQLite databases,
  system configs, filesystem permissions, systemd services, and network stack.
- Multi-tier escalation state tracking stored in
  /var/lib/nmb/self_heal_state.json:
  - Tier 1: Permissions/dirs, symlinks, soft service reset, config mirror restore.
  - Tier 2: Component recompilation (Open-RMBT C engine), binary downloads (Ookla
    speedtest, OONI miniooni), package manager reinstallation (iperf3, dnsmasq, etc.).
  - Tier 3: Aggressive system repair (dpkg --configure -a, apt-get install -f,
    database recovery from backup archive, systemd target restart).
- Safe Stable Update Engine:
  - Upstream stable tag/commit verification (avoiding pre-releases).
  - Atomic pre-update safety backup checkpoint creation with SHA-256 verification.
  - Code update, component recompilation, symlink refresh.
  - Automated test suite execution (python3 -m unittest discover tests) & health check.
  - Immediate automated rollback to checkpoint if tests fail.
"""
from __future__ import annotations

import configparser
import datetime
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nmb.common import backup

log = logging.getLogger("nmb.common.heal")

STATE_FILE = Path(os.environ.get("NMB_HEAL_STATE", "/var/lib/nmb/self_heal_state.json"))
INSTALL_DIR = Path(os.environ.get("NMB_INSTALL_DIR", "/opt/nmb"))
CONFIG_PATH = Path(os.environ.get("NMB_CONFIG", "/etc/nmb/nmb.conf"))
LIVE_DB_PATH = Path(os.environ.get("NMB_LIVE_DB", "/var/lib/nmb/live/nmb.db"))
PERSIST_DB_PATH = Path(os.environ.get("NMB_PERSIST_DB", "/var/lib/nmb/persist/nmb.db"))
NMB_USER = os.environ.get("NMB_USER", "nmb")

# Required NMB binaries / symlinks in /usr/local/bin
CORE_SYMLINKS = [
    "nmb-netd",
    "nmb-probe",
    "nmb-speed",
    "nmb-report",
    "nmb-telegram",
    "nmb-web",
    "nmb-helper",
    "nmb-vpn",
    "nmb-wifi",
    "nmb-iperf",
    "nmb-ooni",
    "nmb-invasive-log",
    "nmb-factory-reset",
    "nmb-cli",
    "nmb-driver",
    "nmb-adblock",
    "pivpn",
    "pihole",
    "nmb-heal",
]

# Required external & compiled binaries
CORE_BINARIES = {
    "rmbt-client": {
        "label": "Open-RMBT C Regulatory Speedtest Engine",
        "cmd": ["rmbt-client", "--version"],
        "alt_paths": ["/usr/local/bin/rmbt-client", "/opt/nmb/components/open-rmbt/build/rmbt-client"],
        "pkg": "open-rmbt-source",
    },
    "speedtest": {
        "label": "Ookla Speedtest CLI",
        "cmd": ["speedtest", "--version"],
        "alt_paths": ["/usr/local/bin/speedtest", "/usr/bin/speedtest"],
        "pkg": "speedtest",
    },
    "iperf3": {
        "label": "iPerf3 Network Bandwidth Engine",
        "cmd": ["iperf3", "--version"],
        "alt_paths": ["/usr/bin/iperf3", "/usr/local/bin/iperf3"],
        "pkg": "iperf3",
    },
    "ooniprobe": {
        "label": "OONI Probe Freedom Diagnostic Suite",
        "cmd": ["ooniprobe", "version"],
        "alt_paths": ["/usr/bin/ooniprobe", "/usr/local/bin/ooniprobe", "/usr/bin/ooniprobe-cli"],
        "pkg": "ooniprobe-cli",
    },
    "mtr": {
        "label": "MTR / My Traceroute Diagnostic Utility",
        "cmd": ["mtr", "--version"],
        "alt_paths": ["/usr/bin/mtr", "/usr/sbin/mtr"],
        "pkg": "mtr-tiny",
    },
    "traceroute": {
        "label": "Traceroute IP Path Hop Diagnostic",
        "cmd": ["traceroute", "--version"],
        "alt_paths": ["/usr/bin/traceroute", "/bin/traceroute", "/usr/bin/tracepath"],
        "pkg": "traceroute",
    },
    "dnsmasq": {
        "label": "Dnsmasq Lightweight DHCP & DNS Server",
        "cmd": ["dnsmasq", "--version"],
        "alt_paths": ["/usr/sbin/dnsmasq", "/usr/bin/dnsmasq"],
        "pkg": "dnsmasq",
    },
    "hostapd": {
        "label": "Hostapd Wireless Access Point Daemon",
        "cmd": ["hostapd", "-v"],
        "alt_paths": ["/usr/sbin/hostapd", "/usr/bin/hostapd"],
        "pkg": "hostapd",
    },
    "wg": {
        "label": "WireGuard Kernel / Userspace Tools",
        "cmd": ["wg", "--version"],
        "alt_paths": ["/usr/bin/wg", "/usr/sbin/wg"],
        "pkg": "wireguard-tools",
    },
    "openvpn": {
        "label": "OpenVPN Secure Tunneling Daemon",
        "cmd": ["openvpn", "--version"],
        "alt_paths": ["/usr/sbin/openvpn", "/usr/bin/openvpn"],
        "pkg": "openvpn",
    },
    "sqlite3": {
        "label": "SQLite3 Database Engine CLI",
        "cmd": ["sqlite3", "--version"],
        "alt_paths": ["/usr/bin/sqlite3", "/bin/sqlite3"],
        "pkg": "sqlite3",
    },
    "ethtool": {
        "label": "Ethtool Network Interface Controller Tool",
        "cmd": ["ethtool", "--version"],
        "alt_paths": ["/usr/sbin/ethtool", "/sbin/ethtool"],
        "pkg": "ethtool",
    },
}

# Required directory hierarchy
CORE_DIRECTORIES = [
    Path("/etc/nmb"),
    Path("/var/lib/nmb"),
    Path("/var/lib/nmb/live"),
    Path("/var/lib/nmb/persist"),
    Path("/var/lib/nmb/persist/reports"),
    Path("/var/lib/nmb/adblock"),
    Path("/var/lib/nmb/backups"),
    Path("/var/log/nmb"),
    Path("/run/nmb"),
]

# Required systemd units
CORE_SERVICES = [
    "nmb-db.service",
    "nmb-tune.service",
    "nmb-netd.service",
    "nmb-probe.service",
    "nmb-web.service",
    "nmb-iperf3.service",
    "nmb-adblock.service",
]

CORE_TIMERS = [
    "nmb-maintain.timer",
    "nmb-snapshot.timer",
    "nmb-report.timer",
    "nmb-invasive-log.timer",
    "nmb-ooni.timer",
    "nmb-adblock-update.timer",
    "nmb-heal.timer",
]

# Expected database tables in nmb.db
REQUIRED_DB_TABLES = ["kv", "target", "ping_sample", "ping_minute", "speedtest"]


DEFAULT_HEAL_STATE: Dict[str, Any] = {
    "version": 1,
    "last_audit_ts": 0,
    "overall_health": "unknown",
    "consecutive_clean_audits": 0,
    "components": {},
    "history": [],
    "updates": {
        "last_check_ts": 0,
        "last_applied_version": backup.APP_VERSION,
        "last_applied_ts": 0,
        "last_checkpoint": "",
    },
}


def _get_state_path() -> Path:
    """Return an accessible path for the self-heal state file."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Test writability
        if not STATE_FILE.exists():
            STATE_FILE.write_text(json.dumps(DEFAULT_HEAL_STATE, indent=2), encoding="utf-8")
        return STATE_FILE
    except (PermissionError, OSError):
        user_state = Path.home() / ".local" / "share" / "nmb" / "self_heal_state.json"
        try:
            user_state.parent.mkdir(parents=True, exist_ok=True)
            return user_state
        except (PermissionError, OSError):
            return Path("/tmp/nmb_self_heal_state.json")


def load_heal_state() -> Dict[str, Any]:
    """Load persistent self-healing and escalation state from disk."""
    base_state = dict(DEFAULT_HEAL_STATE)
    base_state["components"] = {}
    base_state["history"] = []
    base_state["updates"] = dict(DEFAULT_HEAL_STATE["updates"])

    path = _get_state_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    base_state.update(data)
                    if not isinstance(base_state.get("components"), dict):
                        base_state["components"] = {}
                    if not isinstance(base_state.get("history"), list):
                        base_state["history"] = []
                    if not isinstance(base_state.get("updates"), dict):
                        base_state["updates"] = dict(DEFAULT_HEAL_STATE["updates"])
                    return base_state
        except Exception as e:
            log.warning("Could not read self-heal state (%s); initializing fresh state: %s", path, e)
    return base_state


def save_heal_state(state: Dict[str, Any]) -> None:
    """Safely persist self-healing state atomically."""
    path = _get_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
        try:
            os.chmod(path, 0o664)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    except Exception as e:
        log.warning("Failed to save self-healing state to %s: %s", path, e)


def _run_cmd(cmd: List[str], timeout: int = 15, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    """Execute command safely and capture exit code, stdout, and stderr."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
            env=env,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return 1, "", str(e)


def _run_helper_or_sudo(action: str, args: Optional[List[str]] = None, timeout: int = 30) -> Tuple[int, str]:
    """Run privileged action via nmb-helper or sudo."""
    helper = None
    for p in ["/usr/local/bin/nmb-helper", "/opt/nmb/bin/nmb-helper"]:
        if os.path.exists(p) and os.access(p, os.X_OK):
            helper = p
            break
    if not helper:
        helper = "nmb-helper"

    cmd = ["sudo", "-n", helper, action] + (args or [])
    rc, out, err = _run_cmd(cmd, timeout=timeout)
    return rc, (out + "\n" + err).strip()


# ------------------------------------------------------------------------------
# AUDIT ENGINE: Comprehensive System & Component Health Check
# ------------------------------------------------------------------------------

def audit_system_health() -> Dict[str, Any]:
    """Audit all components, binaries, symlinks, databases, configurations,
    directories, permissions, systemd units, and network stacks.

    Returns structured health report with issue classification.
    """
    ts_now = int(time.time())
    report: Dict[str, Any] = {
        "timestamp": ts_now,
        "datetime": datetime.datetime.fromtimestamp(ts_now, datetime.timezone.utc).isoformat(),
        "overall_status": "healthy",
        "issues_count": 0,
        "critical_count": 0,
        "warning_count": 0,
        "components": {
            "binaries": {"status": "ok", "items": []},
            "symlinks": {"status": "ok", "items": []},
            "database": {"status": "ok", "items": []},
            "config": {"status": "ok", "items": []},
            "filesystem": {"status": "ok", "items": []},
            "services": {"status": "ok", "items": []},
            "network": {"status": "ok", "items": []},
        },
    }

    def add_issue(category: str, item_id: str, label: str, severity: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
        report["issues_count"] += 1
        if severity == "critical":
            report["critical_count"] += 1
        else:
            report["warning_count"] += 1

        entry = {
            "id": item_id,
            "label": label,
            "severity": severity,
            "status": "error" if severity == "critical" else "warning",
            "message": message,
            "meta": meta or {},
        }
        report["components"][category]["items"].append(entry)
        if severity == "critical" or report["components"][category]["status"] != "error":
            report["components"][category]["status"] = "error" if severity == "critical" else "degraded"

    def add_ok(category: str, item_id: str, label: str, details: str = "Operational", meta: Optional[Dict[str, Any]] = None) -> None:
        report["components"][category]["items"].append({
            "id": item_id,
            "label": label,
            "severity": "info",
            "status": "ok",
            "message": details,
            "meta": meta or {},
        })

    # 1. External & Compiled Binaries Check
    for bin_name, meta in CORE_BINARIES.items():
        found = False
        resolved_path = shutil.which(bin_name)
        if not resolved_path:
            for alt in meta["alt_paths"]:
                if os.path.exists(alt) and os.access(alt, os.X_OK):
                    resolved_path = alt
                    break

        if resolved_path:
            # Check executable execution
            rc, out, _ = _run_cmd([resolved_path] + meta["cmd"][1:], timeout=5)
            # Some binaries return non-zero or require args, but if rc in (0, 1, 2) or returns version text, it is present
            if rc in (0, 1, 2) or "version" in out.lower() or "client" in out.lower() or "speedtest" in out.lower():
                ver_snippet = out.split("\n")[0][:80] if out else "Ready"
                add_ok("binaries", f"bin:{bin_name}", meta["label"], f"Binary operational ({resolved_path}): {ver_snippet}", {"path": resolved_path})
                found = True

        if not found:
            severity = "critical" if bin_name in ("rmbt-client", "speedtest", "iperf3", "sqlite3") else "warning"
            add_issue(
                "binaries",
                f"bin:{bin_name}",
                meta["label"],
                severity,
                f"Binary '{bin_name}' is missing or not executable in PATH.",
                {"package": meta["pkg"], "alt_paths": meta["alt_paths"]},
            )

    # 2. CLI Symlinks in /usr/local/bin Check
    for link_name in CORE_SYMLINKS:
        link_path = Path(f"/usr/local/bin/{link_name}")
        target_in_opt = INSTALL_DIR / "bin" / link_name
        if link_path.exists():
            if link_path.is_symlink():
                target = os.readlink(link_path)
                if os.path.exists(link_path) and os.access(link_path, os.X_OK):
                    add_ok("symlinks", f"link:{link_name}", f"CLI Symlink {link_name}", f"Symlinked to {target}")
                else:
                    add_issue("symlinks", f"link:{link_name}", f"CLI Symlink {link_name}", "warning", f"Broken symlink pointing to non-existent target: {target}")
            elif os.access(link_path, os.X_OK):
                add_ok("symlinks", f"link:{link_name}", f"CLI Binary {link_name}", "Direct executable in /usr/local/bin")
            else:
                add_issue("symlinks", f"link:{link_name}", f"CLI {link_name}", "warning", f"File exists in /usr/local/bin/{link_name} but is not executable")
        else:
            add_issue("symlinks", f"link:{link_name}", f"CLI Symlink {link_name}", "warning", f"Missing symlink /usr/local/bin/{link_name}")

    # 3. SQLite Database Integrity & Table Checks
    for db_desc, db_p in [("Live tmpfs DB", LIVE_DB_PATH), ("Persistent SD DB", PERSIST_DB_PATH)]:
        db_id = f"db:{db_p.name}_{db_desc.split()[0].lower()}"
        if not db_p.exists():
            # If live DB doesn't exist yet, it might be before first boot hydrate
            severity = "critical" if db_p == PERSIST_DB_PATH else "warning"
            add_issue("database", db_id, db_desc, severity, f"Database file does not exist at {db_p}")
            continue

        try:
            conn = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True, timeout=5)
            cursor = conn.cursor()
            # PRAGMA quick_check
            cursor.execute("PRAGMA quick_check;")
            row = cursor.fetchone()
            check_res = row[0] if row else "unknown"

            if check_res != "ok":
                add_issue("database", db_id, db_desc, "critical", f"Database corrupted: PRAGMA quick_check returned '{check_res}'")
                conn.close()
                continue

            # Verify core table existence
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            existing_tables = {r[0] for r in cursor.fetchall()}
            missing_tables = [t for t in REQUIRED_DB_TABLES if t not in existing_tables]

            if missing_tables:
                add_issue("database", db_id, db_desc, "critical", f"Missing required tables: {', '.join(missing_tables)}")
            else:
                cursor.execute("SELECT COUNT(*) FROM speedtest;")
                st_count = cursor.fetchone()[0]
                add_ok("database", db_id, db_desc, f"Integrity verified (ok). Tables complete ({len(existing_tables)} tables, {st_count} speedtest records).")

            conn.close()
        except sqlite3.DatabaseError as e:
            add_issue("database", db_id, db_desc, "critical", f"SQLite database query error: {e}")
        except Exception as e:
            add_issue("database", db_id, db_desc, "warning", f"Database check warning: {e}")

    # 4. Configuration File Check
    if not CONFIG_PATH.exists():
        # Check if boot mirror exists
        boot_mirror = Path("/boot/firmware/nmb.conf")
        if not boot_mirror.exists():
            boot_mirror = Path("/boot/nmb.conf")
        if boot_mirror.exists():
            add_issue("config", "cfg:nmb.conf", "Main Configuration", "warning", f"Configuration file {CONFIG_PATH} is missing, but boot mirror exists at {boot_mirror}")
        else:
            add_issue("config", "cfg:nmb.conf", "Main Configuration", "critical", f"Configuration file {CONFIG_PATH} is missing and no boot mirror found")
    else:
        try:
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(CONFIG_PATH, encoding="utf-8")
            if not cfg.sections():
                add_issue("config", "cfg:nmb.conf", "Main Configuration", "warning", "Configuration file is empty or contains no valid INI sections")
            else:
                add_ok("config", "cfg:nmb.conf", "Main Configuration", f"Valid INI configuration with {len(cfg.sections())} sections")
        except Exception as e:
            add_issue("config", "cfg:nmb.conf", "Main Configuration", "critical", f"Configuration file syntax error: {e}")

    # 5. Filesystem Hierarchy & Permissions Check
    for dir_path in CORE_DIRECTORIES:
        dir_id = f"fs:{str(dir_path).replace('/', '_')}"
        if not dir_path.exists():
            add_issue("filesystem", dir_id, str(dir_path), "warning", f"Directory {dir_path} does not exist")
        else:
            # Check permissions & writability
            is_writable = os.access(dir_path, os.W_OK)
            st = dir_path.stat()
            mode = oct(st.st_mode)[-4:]
            if not is_writable and os.getuid() == 0:
                add_issue("filesystem", dir_id, str(dir_path), "warning", f"Directory {dir_path} is not writable (mode {mode})")
            else:
                add_ok("filesystem", dir_id, str(dir_path), f"Directory exists with mode {mode}")

    # 6. Systemd Units Check (if systemd is init system)
    is_systemd = Path("/run/systemd/system").exists() or shutil.which("systemctl") is not None
    if is_systemd:
        for srv in CORE_SERVICES:
            srv_id = f"srv:{srv}"
            rc_act, out_act, _ = _run_cmd(["systemctl", "is-active", srv], timeout=5)
            rc_fail, out_fail, _ = _run_cmd(["systemctl", "is-failed", srv], timeout=5)

            if out_fail == "failed":
                add_issue("services", srv_id, srv, "critical", f"Service is in failed state (failed)")
            elif out_act == "active":
                add_ok("services", srv_id, srv, "Service is active and running")
            elif out_act in ("inactive", "deactivating"):
                # nmb-tune and nmb-db are oneshot services that finish with success
                if srv in ("nmb-tune.service", "nmb-db.service"):
                    add_ok("services", srv_id, srv, "Oneshot service completed successfully")
                else:
                    add_issue("services", srv_id, srv, "warning", f"Service is currently {out_act}")
            else:
                add_issue("services", srv_id, srv, "warning", f"Service status: {out_act or 'unknown'}")

        for tmr in CORE_TIMERS:
            tmr_id = f"tmr:{tmr}"
            rc_act, out_act, _ = _run_cmd(["systemctl", "is-active", tmr], timeout=5)
            if out_act == "active":
                add_ok("services", tmr_id, tmr, "Timer is active and scheduled")
            else:
                add_issue("services", tmr_id, tmr, "warning", f"Timer is {out_act or 'inactive'}")
    else:
        add_ok("services", "srv:init", "Init System", "Non-systemd environment (OpenRC or Docker container)")

    # 7. Network Stack & DNS Health Check
    # Loopback
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.close()
        add_ok("network", "net:loopback", "Loopback Socket", "Loopback network stack operational")
    except Exception as e:
        add_issue("network", "net:loopback", "Loopback Socket", "critical", f"Socket creation failed: {e}")

    # DNS Resolution
    dns_ok = False
    try:
        # Test resolution of common domains
        socket.getaddrinfo("dns.google", 53, socket.AF_INET, socket.SOCK_STREAM)
        dns_ok = True
        add_ok("network", "net:dns", "DNS Resolver", "Host DNS resolution functional (dns.google resolved)")
    except Exception as e:
        # Try local sinkhole resolver 127.0.0.1:53
        try:
            s_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s_dns.settimeout(2.0)
            s_dns.connect(("127.0.0.1", 53))
            s_dns.close()
            add_ok("network", "net:dns", "Local DNS Sinkhole", "Local DNS resolver listening on 127.0.0.1:53")
            dns_ok = True
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    if not dns_ok:
        add_issue("network", "net:dns", "DNS Resolver", "warning", "DNS resolution failed to resolve upstream domains")

    # Set overall status
    if report["critical_count"] > 0:
        report["overall_status"] = "critical"
    elif report["warning_count"] > 0:
        report["overall_status"] = "warning"
    else:
        report["overall_status"] = "healthy"

    return report


# ------------------------------------------------------------------------------
# MULTI-TIER SELF-HEALING ENGINE
# ------------------------------------------------------------------------------

def _repair_symlinks() -> List[str]:
    """Tier 1: Re-create any missing or broken CLI symlinks in /usr/local/bin."""
    actions = []
    usr_bin = Path("/usr/local/bin")
    try:
        usr_bin.mkdir(parents=True, exist_ok=True)
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    for link_name in CORE_SYMLINKS:
        link_path = usr_bin / link_name
        # Determine source executable
        if link_name == "pivpn":
            target = INSTALL_DIR / "bin" / "nmb-vpn"
        elif link_name == "pihole":
            target = INSTALL_DIR / "bin" / "nmb-adblock"
        else:
            target = INSTALL_DIR / "bin" / link_name

        if not target.exists():
            # Fallback to local dev repo bin/
            dev_target = Path(__file__).resolve().parent.parent.parent / "bin" / link_name
            if dev_target.exists():
                target = dev_target

        if not link_path.exists() or (link_path.is_symlink() and not os.path.exists(link_path)):
            try:
                if link_path.is_symlink() or link_path.exists():
                    link_path.unlink()
                if target.exists():
                    link_path.symlink_to(target)
                    try:
                        os.chmod(target, 0o755)
                    except Exception:
                        log.debug("suppressed exception", exc_info=True)
                    actions.append(f"Restored symlink /usr/local/bin/{link_name} -> {target}")
            except Exception as e:
                # Try via sudo
                rc, msg = _run_helper_or_sudo("heal-symlink", [link_name, str(target)])
                if rc == 0:
                    actions.append(f"Restored symlink via helper: {link_name}")
                else:
                    log.warning("Could not restore symlink %s: %s", link_name, e)
    return actions


def _repair_filesystem_permissions() -> List[str]:
    """Tier 1: Fix directory ownership and permissions across /var/lib/nmb and /run/nmb."""
    actions = []
    for dir_path in CORE_DIRECTORIES:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            # Set SGID and read/write permissions (2775)
            try:
                os.chmod(dir_path, 0o2775)
            except Exception:
                log.debug("suppressed exception", exc_info=True)
            actions.append(f"Ensured directory and permissions for {dir_path}")
        except PermissionError:
            rc, _ = _run_helper_or_sudo("heal-permissions", [str(dir_path)])
            if rc == 0:
                actions.append(f"Restored directory permissions via helper for {dir_path}")
    return actions


def _repair_config_file() -> List[str]:
    """Tier 1/2: Recover configuration from boot partition mirror or default template."""
    actions = []
    if not CONFIG_PATH.exists() or CONFIG_PATH.stat().st_size == 0:
        boot_mirrors = [
            Path("/boot/firmware/nmb.conf"),
            Path("/boot/nmb.conf"),
            INSTALL_DIR / "config" / "nmb.conf.example",
            Path(__file__).resolve().parent.parent.parent / "config" / "nmb.conf.example",
        ]
        restored = False
        for mirror in boot_mirrors:
            if mirror.exists() and mirror.stat().st_size > 0:
                try:
                    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                    # The boot copy has marks instead of secrets; never copy them in as values.
                    from nmb.config import merge_drive_config
                    CONFIG_PATH.write_text(merge_drive_config(mirror.read_text(encoding="utf-8"), ""), encoding="utf-8")
                    os.chmod(CONFIG_PATH, 0o640)
                    actions.append(f"Recovered configuration file from mirror: {mirror}")
                    restored = True
                    break
                except Exception as e:
                    rc, _ = _run_helper_or_sudo("heal-restore-config", [str(mirror)])
                    if rc == 0:
                        actions.append(f"Recovered configuration file via helper from: {mirror}")
                        restored = True
                        break
        if not restored:
            actions.append("Warning: Could not locate a valid configuration mirror.")
    return actions


def _repair_service(service_name: str, tier: int) -> List[str]:
    """Tier 1/2/3: Reset and recover failed systemd services."""
    actions = []
    if shutil.which("systemctl") is None:
        return actions

    if tier == 1:
        # Soft reset and restart
        _run_cmd(["systemctl", "reset-failed", service_name], timeout=5)
        rc, out, err = _run_cmd(["systemctl", "restart", service_name], timeout=10)
        if rc == 0:
            actions.append(f"Reset and restarted service: {service_name}")
        else:
            actions.append(f"Service restart attempted for {service_name} (rc={rc}): {err or out}")
    elif tier >= 2:
        # Full reload, enable, and restart
        _run_cmd(["systemctl", "daemon-reload"], timeout=10)
        _run_cmd(["systemctl", "enable", service_name], timeout=5)
        rc, out, err = _run_cmd(["systemctl", "restart", service_name], timeout=15)
        actions.append(f"Tier {tier} service daemon-reload and re-enable performed for {service_name} (rc={rc})")

    return actions


def _repair_database(tier: int) -> List[str]:
    """Tier 1/2/3: Recover corrupted SQLite database."""
    actions = []
    # 1. Check live DB vs persistent DB
    if not PERSIST_DB_PATH.exists() and LIVE_DB_PATH.exists():
        try:
            PERSIST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(LIVE_DB_PATH, PERSIST_DB_PATH)
            actions.append("Mirrored live DB to persistent SD DB location")
        except Exception as e:
            actions.append(f"Failed to copy live DB to persist: {e}")

    if not LIVE_DB_PATH.exists() and PERSIST_DB_PATH.exists():
        try:
            LIVE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PERSIST_DB_PATH, LIVE_DB_PATH)
            actions.append("Hydrated live tmpfs DB from persistent SD DB")
        except Exception as e:
            actions.append(f"Failed to hydrate live DB: {e}")

    # Tier 2: Checkpoint & schema dump recovery
    if tier == 2:
        for db_p in [LIVE_DB_PATH, PERSIST_DB_PATH]:
            if db_p.exists():
                try:
                    conn = sqlite3.connect(str(db_p), timeout=5)
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    conn.close()
                    actions.append(f"Executed PRAGMA wal_checkpoint(TRUNCATE) on {db_p.name}")
                except Exception as e:
                    actions.append(f"WAL truncate checkpoint error on {db_p.name}: {e}")

    # Tier 3: Aggressive disaster recovery from latest backup archive
    if tier >= 3:
        backups_list = backup.list_backups()
        if backups_list:
            latest = backups_list[0]
            archive_path = Path(latest["path"])
            ok, msg = backup.restore_backup(archive_path, restore_db=True, restore_vpn=False, create_safety_snapshot=True)
            if ok:
                actions.append(f"Disaster Recovery: Restored database from backup snapshot '{latest['filename']}'")
            else:
                actions.append(f"Backup restore attempt failed: {msg}")
        else:
            # Re-bootstrap fresh database schema using module
            rc, out, _ = _run_cmd(["python3", "-m", "nmb.db.database", "restore"], timeout=10)
            actions.append(f"Bootstrapped clean database schema via nmb.db.database (rc={rc})")

    return actions


def _repair_missing_binary(bin_name: str, tier: int) -> List[str]:
    """Tier 2/3: Recompile or download missing or corrupted binaries.

    - rmbt-client: recompile native C source from components/open-rmbt
    - speedtest: download official standalone Ookla CLI binary
    - ooniprobe: download standalone miniooni binary
    - system packages: invoke package manager reinstall
    """
    actions = []
    arch = platform.machine().lower()

    if bin_name == "rmbt-client":
        # Look for source directory
        src_dirs = [
            INSTALL_DIR / "components" / "open-rmbt",
            Path(__file__).resolve().parent.parent.parent / "components" / "open-rmbt",
        ]
        src_dir = None
        for d in src_dirs:
            if (d / "Makefile").exists() and (d / "src" / "main.c").exists():
                src_dir = d
                break

        if src_dir:
            actions.append(f"Recompiling native Open-RMBT C engine from {src_dir}...")
            # Run make clean && make
            rc1, _, err1 = _run_cmd(["make", "-C", str(src_dir), "clean"], timeout=15)
            rc2, out2, err2 = _run_cmd(["make", "-C", str(src_dir)], timeout=60)
            built_bin = src_dir / "build" / "rmbt-client"
            if built_bin.exists() and os.access(built_bin, os.X_OK):
                # Install to /usr/local/bin/rmbt-client
                try:
                    dest = Path("/usr/local/bin/rmbt-client")
                    shutil.copy2(built_bin, dest)
                    os.chmod(dest, 0o755)
                    actions.append("Successfully compiled and installed /usr/local/bin/rmbt-client")
                except Exception:
                    rc_inst, _ = _run_helper_or_sudo("heal-install-file", [str(built_bin), "/usr/local/bin/rmbt-client"])
                    if rc_inst == 0:
                        actions.append("Installed /usr/local/bin/rmbt-client via helper")
                    else:
                        actions.append(f"Failed to install compiled rmbt-client: {err2}")
            else:
                actions.append(f"Open-RMBT compilation failed (rc={rc2}): {err2 or out2}")
        else:
            actions.append("Warning: Open-RMBT C source directory not found for recompilation.")

    elif bin_name == "speedtest":
        # Map CPU architecture to Ookla archive naming
        ookla_arch = ""
        if arch in ("x86_64", "amd64"):
            ookla_arch = "x86_64"
        elif arch in ("aarch64", "arm64"):
            ookla_arch = "aarch64"
        elif "arm" in arch:
            ookla_arch = "armhf"

        if ookla_arch:
            url = f"https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-{ookla_arch}.tgz"
            actions.append(f"Downloading official Ookla Speedtest standalone CLI from {url}...")
            tmp_dir = Path(tempfile.mkdtemp(prefix="nmb-heal-speedtest-"))
            try:
                # Use curl
                rc, _, err = _run_cmd(["curl", "-sSL", url, "-o", str(tmp_dir / "speedtest.tgz")], timeout=30)
                from nmb.speed.ookla import OOKLA_SHA256
                archive = tmp_dir / "speedtest.tgz"
                if rc == 0 and archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest() != OOKLA_SHA256.get(ookla_arch):
                    actions.append("Ookla download failed its checksum; not installing it")
                    archive.unlink()
                if rc == 0 and archive.exists():
                    _run_cmd(["tar", "-xzf", str(archive), "-C", str(tmp_dir)], timeout=10)
                    extracted = tmp_dir / "speedtest"
                    if extracted.exists():
                        os.chmod(extracted, 0o755)
                        try:
                            shutil.copy2(extracted, "/usr/local/bin/speedtest")
                            actions.append("Successfully installed /usr/local/bin/speedtest")
                        except Exception:
                            _run_helper_or_sudo("heal-install-file", [str(extracted), "/usr/local/bin/speedtest"])
                            actions.append("Installed /usr/local/bin/speedtest via helper")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    elif bin_name == "ooniprobe":
        ooni_arch = ""
        if arch in ("x86_64", "amd64"):
            ooni_arch = "amd64"
        elif arch in ("aarch64", "arm64"):
            ooni_arch = "arm64"
        elif "arm" in arch:
            ooni_arch = "armv7"

        if ooni_arch:
            url = f"https://github.com/ooni/probe-cli/releases/download/v3.31.1/miniooni-linux-{ooni_arch}"
            actions.append(f"Downloading standalone miniooni binary from {url}...")
            tmp_bin = Path(tempfile.mktemp(prefix="miniooni-"))
            try:
                rc, _, _ = _run_cmd(["curl", "-sSL", url, "-o", str(tmp_bin)], timeout=45)
                if rc == 0 and tmp_bin.exists() and tmp_bin.stat().st_size > 100000:
                    os.chmod(tmp_bin, 0o755)
                    try:
                        shutil.copy2(tmp_bin, "/usr/local/bin/ooniprobe")
                        actions.append("Successfully installed /usr/local/bin/ooniprobe")
                    except Exception:
                        _run_helper_or_sudo("heal-install-file", [str(tmp_bin), "/usr/local/bin/ooniprobe"])
                        actions.append("Installed /usr/local/bin/ooniprobe via helper")
                    # Onboard
                    _run_cmd(["/usr/local/bin/ooniprobe", "onboard", "--yes"], timeout=15)
            finally:
                if tmp_bin.exists():
                    tmp_bin.unlink()

    else:
        # Standard system package
        pkg = CORE_BINARIES.get(bin_name, {}).get("pkg", bin_name)
        if tier >= 3:
            # Aggressive package manager repair first
            actions.append("Tier 3 Aggressive package subsystem repair: dpkg --configure -a...")
            _run_helper_or_sudo("heal-dpkg-repair", timeout=60)

        actions.append(f"Reinstalling system package '{pkg}' via package manager...")
        rc, out = _run_helper_or_sudo("heal-pkg-install", [pkg], timeout=90)
        if rc == 0:
            actions.append(f"Package manager successfully installed '{pkg}'")
        else:
            actions.append(f"Package installation attempted for '{pkg}' (rc={rc})")

    return actions


def auto_heal_all(force_tier: Optional[int] = None) -> Dict[str, Any]:
    """Execute automated self-healing across all detected issues with
    multi-attempt escalation tracking.

    Args:
        force_tier: Optional override to force Tier 1, 2, or 3.

    Returns:
        Structured self-healing execution summary.
    """
    ts_now = int(time.time())
    state = load_heal_state()
    audit_pre = audit_system_health()

    summary: Dict[str, Any] = {
        "timestamp": ts_now,
        "pre_status": audit_pre["overall_status"],
        "issues_detected": audit_pre["issues_count"],
        "repairs_executed": [],
        "post_status": "unknown",
        "post_issues_count": 0,
        "success": False,
    }

    if audit_pre["issues_count"] == 0:
        state["consecutive_clean_audits"] = state.get("consecutive_clean_audits", 0) + 1
        state["overall_health"] = "healthy"
        state["last_audit_ts"] = ts_now
        save_heal_state(state)
        summary["post_status"] = "healthy"
        summary["success"] = True
        return summary

    # Reset clean audit streak
    state["consecutive_clean_audits"] = 0

    # Process all detected issues
    all_actions: List[str] = []

    for cat_name, cat_data in audit_pre["components"].items():
        for item in cat_data["items"]:
            if item.get("status") in ("error", "warning"):
                item_id = item["id"]
                comp_state = state["components"].get(item_id, {
                    "id": item_id,
                    "label": item["label"],
                    "category": cat_name,
                    "consecutive_failures": 0,
                    "total_failures": 0,
                    "first_detected": ts_now,
                    "last_detected": ts_now,
                    "last_tier_attempted": 0,
                    "last_action_ts": 0,
                    "resolved": False,
                })

                comp_state["consecutive_failures"] = comp_state.get("consecutive_failures", 0) + 1
                comp_state["total_failures"] = comp_state.get("total_failures", 0) + 1
                comp_state["last_detected"] = ts_now

                # Determine escalation tier:
                # 1st failure -> Tier 1 (Soft fix: symlinks, permissions, service restart)
                # 2nd failure -> Tier 2 (Reinstall / recompile / DB truncate)
                # 3rd+ failure -> Tier 3 (Aggressive dpkg repair / backup restore / target restart)
                if force_tier:
                    tier = force_tier
                elif comp_state["consecutive_failures"] <= 1:
                    tier = 1
                elif comp_state["consecutive_failures"] == 2:
                    tier = 2
                else:
                    tier = 3

                comp_state["last_tier_attempted"] = tier
                comp_state["last_action_ts"] = ts_now

                # Execute repair by category
                actions_taken: List[str] = []
                if cat_name == "symlinks":
                    actions_taken = _repair_symlinks()
                elif cat_name == "filesystem":
                    actions_taken = _repair_filesystem_permissions()
                elif cat_name == "config":
                    actions_taken = _repair_config_file()
                elif cat_name == "services":
                    srv_name = item_id.replace("srv:", "").replace("tmr:", "")
                    actions_taken = _repair_service(srv_name, tier)
                elif cat_name == "database":
                    actions_taken = _repair_database(tier)
                elif cat_name == "binaries":
                    bin_name = item_id.replace("bin:", "")
                    actions_taken = _repair_missing_binary(bin_name, tier)

                comp_state["last_actions"] = actions_taken
                state["components"][item_id] = comp_state
                all_actions.extend(actions_taken)

                # Record in history
                state["history"].append({
                    "timestamp": ts_now,
                    "item_id": item_id,
                    "tier": tier,
                    "actions": actions_taken,
                })

    # Trim history to last 50 entries
    state["history"] = state["history"][-50:]

    # Post-repair audit verification
    audit_post = audit_system_health()
    summary["repairs_executed"] = all_actions
    summary["post_status"] = audit_post["overall_status"]
    summary["post_issues_count"] = audit_post["issues_count"]
    summary["success"] = (audit_post["issues_count"] < audit_pre["issues_count"]) or (audit_post["critical_count"] == 0)

    # For any issues that are now resolved, reset consecutive_failures
    remaining_issue_ids = {
        item["id"]
        for cdata in audit_post["components"].values()
        for item in cdata["items"]
        if item.get("status") in ("error", "warning")
    }

    for item_id, cstate in state["components"].items():
        if item_id not in remaining_issue_ids:
            cstate["consecutive_failures"] = 0
            cstate["resolved"] = True
        else:
            cstate["resolved"] = False

    state["overall_health"] = audit_post["overall_status"]
    state["last_audit_ts"] = ts_now
    save_heal_state(state)

    return summary


# ------------------------------------------------------------------------------
# STABLE UPDATES ENGINE WITH AUTOMATED SAFETY ROLLBACK
# ------------------------------------------------------------------------------

def _find_repo_dir() -> Optional[Path]:
    """Find the root Git repository directory."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent,
        INSTALL_DIR,
    ]
    for c in candidates:
        if (c / ".git").exists():
            return c
    return None


def is_version_stable(version_str: str) -> bool:
    """Check if a version string is considered a stable release.

    Stable versions:
    - Match standard semver: v1.2.3, 2.4.0, v3.0
    - Do NOT contain pre-release markers (-rc, -beta, -alpha, -dev, -preview, dirty)
    """
    cleaned = version_str.strip().lower()
    if any(marker in cleaned for marker in ("-rc", "rc.", "-beta", "beta.", "-alpha", "alpha.", "-dev", "dev.", "preview", "dirty")):
        return False
    return bool(re.match(r"^v?[0-9]+(\.[0-9]+)+$", cleaned))


def check_stable_updates() -> Dict[str, Any]:
    """Check for upstream stable updates via Git tags/commits and OS package manager.

    Returns structured update check status.
    """
    ts_now = int(time.time())
    repo_dir = _find_repo_dir()

    result: Dict[str, Any] = {
        "timestamp": ts_now,
        "current_version": backup.APP_VERSION,
        "available_version": backup.APP_VERSION,
        "update_available": False,
        "is_stable": True,
        "target_ref": "",
        "git_branch": "main",
        "current_commit": "",
        "upstream_commit": "",
        "os_updates_count": 0,
        "changelog": [],
        "message": "System software is up to date.",
    }

    # 1. Check Git updates if in git repo
    if repo_dir:
        rc, branch, _ = _run_cmd(["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
        if rc == 0:
            result["git_branch"] = branch

        rc, commit, _ = _run_cmd(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], timeout=5)
        if rc == 0:
            result["current_commit"] = commit[:8]

        # Fetch remote tags and commits with a short timeout
        rc_fetch, _, _ = _run_cmd(["git", "-C", str(repo_dir), "fetch", "--tags", "--quiet", "origin"], timeout=15)
        if rc_fetch == 0:
            # Check available release tags
            rc_tags, tags_out, _ = _run_cmd(["git", "-C", str(repo_dir), "tag", "--list", "v*"], timeout=5)
            stable_tags = []
            if rc_tags == 0 and tags_out:
                for t in tags_out.splitlines():
                    t = t.strip()
                    if is_version_stable(t):
                        stable_tags.append(t)

            if stable_tags:
                # Get latest stable tag
                latest_tag = stable_tags[-1]
                result["available_version"] = latest_tag
                if latest_tag.lstrip("v") != backup.APP_VERSION.lstrip("v"):
                    result["update_available"] = True
                    result["target_ref"] = latest_tag
                    result["is_stable"] = True
                    result["message"] = f"Stable release {latest_tag} is available for upgrade."

            # If no tags, check commit difference on main
            if not result["update_available"]:
                rc_up, up_commit, _ = _run_cmd(["git", "-C", str(repo_dir), "rev-parse", f"origin/{result['git_branch']}"], timeout=5)
                if rc_up == 0 and up_commit and up_commit != commit:
                    result["upstream_commit"] = up_commit[:8]
                    # Get commit log
                    rc_log, log_out, _ = _run_cmd(
                        ["git", "-C", str(repo_dir), "log", f"HEAD..origin/{result['git_branch']}", "--oneline", "-n", "5"],
                        timeout=5,
                    )
                    changelog = log_out.splitlines() if rc_log == 0 and log_out else []
                    result["update_available"] = True
                    result["target_ref"] = f"origin/{result['git_branch']}"
                    result["is_stable"] = True
                    result["changelog"] = changelog
                    result["message"] = f"Stable update available: {len(changelog)} new commit(s) on {result['git_branch']}."

    else:
        # Installed by setup.sh without git: compare with the newest commit on GitHub.
        from nmb.common import updater
        result.update(updater.check())
        if result["update_available"]:
            result["available_version"] = result["upstream_commit"]

    # 2. Check system OS package upgrades
    rc_os, os_out = _run_helper_or_sudo("check-updates", timeout=20)
    if rc_os == 0 and os_out:
        # Count upgradable lines
        upg_lines = [line for line in os_out.splitlines() if "Inst " in line or "upgraded" in line.lower()]
        result["os_updates_count"] = len(upg_lines)

    return result


def start_github_update(target_ref: Optional[str] = None, background: bool = True) -> Dict[str, Any]:
    """Update from GitHub through nmb-helper (a box installed without git).

    In the background (web server) the result says the update started, and its progress is in
    ``updater.read_status()``. In the foreground (CLI) it waits and returns the final status.
    """
    ref = target_ref if target_ref and re.fullmatch(r"[0-9a-f]{40}", str(target_ref)) else None
    args = ["start" if background else "run"] + ([ref] if ref else [])
    rc, out = _run_helper_or_sudo("self-update", args, timeout=120 if background else 4000)
    try:
        status = json.loads(out[out.index("{"):])
    except ValueError:
        status = {"state": "failed", "message": out or "nmb-helper self-update did not answer."}
    state = status.get("state")
    return {
        "success": state in ("started", "success"),
        "started": state == "started",
        "rolled_back": state == "rolled_back",
        "state": state,
        "message": status.get("message", "Update started." if state == "started" else ""),
        "error": "" if state in ("started", "success") else status.get("message", ""),
        "checkpoint": status.get("checkpoint", ""),
        "new_version": status.get("commit", ""),
    }


def apply_stable_update(target_ref: Optional[str] = None, background: bool = True) -> Dict[str, Any]:
    """Safely apply a verified stable update with AUTOMATED ROLLBACK PROTECTION.

    Sequence:
    1. Verify update availability and stability.
    2. Create atomic pre-update backup checkpoint via nmb.common.backup.
    3. Pull/checkout update.
    4. Recompile native components and refresh symlinks.
    5. Run automated test suite (python3 -m unittest discover tests) & health audit.
    6. IF verification fails: execute automated rollback to checkpoint.
    7. IF verification succeeds: reload systemd and restart services.
    """
    ts_now = int(time.time())
    repo_dir = _find_repo_dir()
    if not repo_dir:
        if not target_ref:
            # Only when GitHub really is newer: a box ahead of GitHub must not be "updated" back (2026-11-10).
            from nmb.common import updater
            chk = updater.check()
            if not chk.get("update_available"):
                return {"success": False, "up_to_date": True, "rolled_back": False,
                        "message": chk.get("message", "System software is up to date."),
                        "version": backup.APP_VERSION}
            target_ref = chk.get("target_ref") or None
        return start_github_update(target_ref, background=background)

    # 1. Update verification
    check = check_stable_updates()
    if not check["update_available"] and not target_ref:
        return {
            "success": True,
            "rolled_back": False,
            "message": "System is already running the latest version.",
            "version": backup.APP_VERSION,
        }

    # A value starting with "-" would be read by git as an option.
    if target_ref and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", str(target_ref)):
        return {"status": "error", "message": "Invalid update reference."}
    ref_to_apply = target_ref or check["target_ref"]

    # 2. Pre-Update Safety Checkpoint
    checkpoint_name = f"nmb-auto-pre-update-{ts_now}.tar.gz"
    log.info("Creating pre-update safety checkpoint: %s", checkpoint_name)
    ok_b, b_path, b_manifest = backup.create_backup(
        backup_type="full",
        comment="Automatic pre-update safety checkpoint",
        custom_filename=checkpoint_name,
    )
    if not ok_b:
        return {
            "success": False,
            "rolled_back": False,
            "error": "Safety checkpoint creation failed. Aborting update to protect system integrity.",
        }

    # Verify checkpoint
    valid_b, msg_b, _ = backup.verify_backup(b_path)
    if not valid_b:
        return {
            "success": False,
            "rolled_back": False,
            "error": f"Safety checkpoint verification failed ({msg_b}). Aborting update.",
        }

    # Record previous commit for rollback
    _, prev_commit, _ = _run_cmd(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], timeout=5)

    # 3. Apply the update
    log.info("Pulling update ref %s in %s...", ref_to_apply, repo_dir)
    pull_cmd = ["git", "-C", str(repo_dir), "pull", "--ff-only", "origin", check["git_branch"]]
    if ref_to_apply and ref_to_apply.startswith("v"):
        pull_cmd = ["git", "-C", str(repo_dir), "checkout", ref_to_apply]

    rc_pull, out_pull, err_pull = _run_cmd(pull_cmd, timeout=30)
    if rc_pull != 0:
        return {
            "success": False,
            "rolled_back": False,
            "error": f"Failed to pull git update: {err_pull or out_pull}",
        }

    # Synchronize updated files to /opt/nmb if repo is different from INSTALL_DIR
    if repo_dir != INSTALL_DIR and INSTALL_DIR.exists():
        try:
            for item in ["nmb", "bin", "components", "os", "config"]:
                src = repo_dir / item
                dst = INSTALL_DIR / item
                if src.exists():
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
        except Exception as e:
            log.warning("Could not sync to /opt/nmb: %s", e)

    # Recompile native components (Open-RMBT)
    open_rmbt_dir = repo_dir / "components" / "open-rmbt"
    if (open_rmbt_dir / "Makefile").exists():
        _run_cmd(["make", "-C", str(open_rmbt_dir), "clean"], timeout=15)
        _run_cmd(["make", "-C", str(open_rmbt_dir)], timeout=60)
        built = open_rmbt_dir / "build" / "rmbt-client"
        if built.exists():
            try:
                shutil.copy2(built, "/usr/local/bin/rmbt-client")
                os.chmod("/usr/local/bin/rmbt-client", 0o755)
            except Exception:
                _run_helper_or_sudo("heal-install-file", [str(built), "/usr/local/bin/rmbt-client"])

    # Refresh symlinks
    _repair_symlinks()

    # 4. Automated Test Suite & Health Verification
    log.info("Running automated verification test suite...")
    # Tests must never write to the live database.
    with tempfile.TemporaryDirectory(prefix="nmb-verify-") as verify_dir:
        rc_tests, out_tests, err_tests = _run_cmd(
            ["python3", "-m", "unittest", "discover", "tests"],
            timeout=300,
            cwd=str(repo_dir),
            env=dict(os.environ, NMB_LIVE_DB=f"{verify_dir}/live.db", NMB_PERSIST_DB=f"{verify_dir}/persist.db",
                     NMB_OOKLA_COOLDOWN_FILE=f"{verify_dir}/ookla_cooldown.json"),
        )
    health_check = audit_system_health()

    test_passed = (rc_tests == 0) and (health_check["critical_count"] == 0)

    # 5. Rollback on Failure
    if not test_passed:
        log.error("Update verification failed (tests rc=%s, critical_issues=%s). Initiating automatic safety rollback!", rc_tests, health_check["critical_count"])
        # Restore git commit
        if prev_commit:
            _run_cmd(["git", "-C", str(repo_dir), "reset", "--hard", prev_commit], timeout=15)

        # Restore system state and DB from checkpoint
        ok_r, msg_r = backup.restore_backup(b_path, restore_db=True, restore_vpn=True, create_safety_snapshot=False)

        # Restart systemd target
        _run_cmd(["systemctl", "daemon-reload"], timeout=10)
        _run_cmd(["systemctl", "restart", "nmb.target"], timeout=15)

        return {
            "success": False,
            "rolled_back": True,
            "error": f"Update failed verification tests: {err_tests or out_tests}. System was automatically rolled back to checkpoint {checkpoint_name}.",
            "checkpoint": str(b_path),
            "current_version": backup.APP_VERSION,
        }

    # 6. Success: Reload and finalize
    _run_cmd(["systemctl", "daemon-reload"], timeout=10)
    _run_cmd(["systemctl", "restart", "nmb.target"], timeout=15)

    state = load_heal_state()
    state["updates"]["last_applied_version"] = check["available_version"]
    state["updates"]["last_applied_ts"] = ts_now
    state["updates"]["last_checkpoint"] = str(b_path)
    save_heal_state(state)

    return {
        "success": True,
        "rolled_back": False,
        "new_version": check["available_version"],
        "checkpoint": str(b_path),
        "message": f"Successfully upgraded and verified stable version {check['available_version']}.",
    }
