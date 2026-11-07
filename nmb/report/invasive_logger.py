"""NetworkMeasureBox Invasive Background Developer Logger & System Tracer.

Continuously captures deep, low-level telemetry, kernel states, socket audits,
network interfaces, routing, firewall rules, hardware throttling, SQLite integrity,
recent benchmark results, and developer tracebacks into a discoverable, self-documenting
snapshot (both locally and on the FAT32 boot drive) so developers / AI assistants
can immediately analyze, debug, and continue development without physical device access.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nmb.config import (
    Config,
    load_config,
    find_drive_config_path,
    get_writable_drive_config_target,
    DEFAULT_CONFIG_PATH,
)
from nmb.common.user_agent import get_effective_user_agent
from nmb.db import database as db
from nmb.netd.os_detector import detect_os_info, get_dynamic_interfaces
from nmb.netd.interfaces import get_dual_stack_ips

log = logging.getLogger("nmb.report.invasive")

BOOT_MIRROR_MIN_SEC = 3600.0

PRIMARY_SNAPSHOT_PATH = Path("/var/log/nmb/invasive_dev_snapshot.md")
PRIMARY_JSON_PATH = Path("/var/log/nmb/invasive_dev_snapshot.json")
RUN_SNAPSHOT_PATH = Path("/run/nmb/invasive_dev_snapshot.md")
FALLBACK_SNAPSHOT_PATH = Path.home() / ".local/share/nmb/invasive_dev_snapshot.md"

_cached_markdown: str = ""
_cached_metadata: Dict[str, Any] = {}
_cached_timestamp: float = 0.0
_cache_lock = threading.Lock()

_worker_thread: Optional[threading.Thread] = None
_worker_stop_event = threading.Event()


def get_boot_drive_snapshot_target() -> Optional[Path]:
    """Find appropriate location on FAT32 boot partition or removable media for persistent debug log."""
    candidates = [
        Path("/boot/firmware/nmb_invasive_dev_snapshot.md"),
        Path("/boot/nmb_invasive_dev_snapshot.md"),
        Path("/mnt/boot/nmb_invasive_dev_snapshot.md"),
    ]
    for c in candidates:
        parent = c.parent
        if parent.is_dir():
            try:
                test_file = parent / ".nmb_invasive_write_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink(missing_ok=True)
                return c
            except (PermissionError, OSError):
                continue

    # Check mounted removable media
    for mount_root in (Path("/media"), Path("/mnt")):
        if mount_root.is_dir():
            try:
                for sub in mount_root.glob("*/*"):
                    if sub.is_dir() and "boot" in sub.name.lower():
                        target = sub / "nmb_invasive_dev_snapshot.md"
                        try:
                            t = sub / ".nmb_test"
                            t.write_text("ok")
                            t.unlink(missing_ok=True)
                            return target
                        except Exception:
                            pass
            except Exception:
                pass
    return None


def _run_cmd(cmd: List[str], timeout: float = 4.0) -> str:
    """Run shell command safely without throwing exceptions."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        out = res.stdout.strip()
        if res.stderr.strip() and not out:
            out = f"(stderr: {res.stderr.strip()})"
        return out if out else "N/A"
    except Exception as e:
        return f"(Error executing {' '.join(cmd)}: {e})"


def _collect_hardware_telemetry() -> Dict[str, Any]:
    """Collect invasive thermal, throttling, CPU, and RAM metrics."""
    temp_c = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_c = round(float(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass

    load_avg = "N/A"
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
            load_avg = f"1m: {parts[0]}, 5m: {parts[1]}, 15m: {parts[2]}"
    except Exception:
        pass

    freq_mhz = None
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "r") as f:
            freq_mhz = int(int(f.read().strip()) / 1000)
    except Exception:
        pass

    throttled_hex = None
    throttled_flags: List[str] = []
    try:
        res = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2, check=False)
        m = re.search(r"throttled=(0x[0-9a-fA-F]+)", res.stdout)
        if m:
            throttled_hex = m.group(1)
            val = int(throttled_hex, 16)
            flags_map = {
                0: "Under-voltage currently detected",
                1: "Arm frequency currently capped",
                2: "Currently throttled (thermal)",
                3: "Soft temperature limit currently active",
                16: "Under-voltage has occurred previously",
                17: "Arm frequency capping has occurred previously",
                18: "Throttling has occurred previously",
                19: "Soft temperature limit has occurred previously",
            }
            for bit, desc in flags_map.items():
                if val & (1 << bit):
                    throttled_flags.append(desc)
    except Exception:
        pass

    mem_info: Dict[str, str] = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = parts[1].strip()
                    if k in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SwapTotal", "SwapFree"):
                        mem_info[k] = v
    except Exception:
        pass

    uptime_str = "unknown"
    try:
        with open("/proc/uptime", "r") as f:
            up_sec = float(f.read().split()[0])
            uptime_str = f"{int(up_sec // 3600)}h {int((up_sec % 3600) // 60)}m {int(up_sec % 60)}s"
    except Exception:
        pass

    return {
        "temp_c": temp_c,
        "load_avg": load_avg,
        "freq_mhz": freq_mhz,
        "throttled_hex": throttled_hex,
        "throttled_flags": throttled_flags,
        "mem": mem_info,
        "uptime": uptime_str,
    }


def _collect_network_interfaces() -> List[Dict[str, Any]]:
    """Collect deep per-interface statistics, link speeds, MTU, and error drops."""
    ifaces: List[Dict[str, Any]] = []
    net_dir = Path("/sys/class/net")
    if not net_dir.exists():
        return ifaces

    for ifp in sorted(net_dir.iterdir()):
        name = ifp.name
        operstate = "unknown"
        try:
            operstate = (ifp / "operstate").read_text().strip()
        except Exception:
            pass

        carrier = "0"
        try:
            carrier = (ifp / "carrier").read_text().strip()
        except Exception:
            pass

        mtu = "1500"
        try:
            mtu = (ifp / "mtu").read_text().strip()
        except Exception:
            pass

        speed = "N/A"
        try:
            s = (ifp / "speed").read_text().strip()
            if s and s != "-1":
                speed = f"{s} Mbps"
        except Exception:
            pass

        duplex = "N/A"
        try:
            duplex = (ifp / "duplex").read_text().strip()
        except Exception:
            pass

        stats: Dict[str, int] = {}
        s_dir = ifp / "statistics"
        if s_dir.exists():
            for k in ("rx_packets", "rx_bytes", "rx_errors", "rx_dropped", "tx_packets", "tx_bytes", "tx_errors", "tx_dropped"):
                try:
                    stats[k] = int((s_dir / k).read_text().strip())
                except Exception:
                    stats[k] = 0

        ifaces.append({
            "name": name,
            "operstate": operstate,
            "carrier": carrier == "1",
            "mtu": mtu,
            "speed": speed,
            "duplex": duplex,
            "stats": stats,
        })
    return ifaces


def _collect_systemd_status() -> Dict[str, str]:
    """Collect systemd active/sub state for all relevant daemons."""
    services = [
        "nmb-netd",
        "nmb-probe",
        "nmb-web",
        "nmb-speed.service",
        "hostapd",
        "dnsmasq",
        "openvpn",
        "wg-quick@wg0",
    ]
    status: Dict[str, str] = {}
    for s in services:
        out = _run_cmd(["systemctl", "is-active", s], timeout=1.5)
        status[s] = out
    return status


def _collect_database_health() -> Dict[str, Any]:
    """Inspect SQLite database files, WAL sizes, table row counts, and integrity."""
    live_db = db.get_live_db()
    persist_db = db.get_persist_db()

    health = {
        "live_path": str(live_db),
        "live_exists": live_db.exists(),
        "live_size_bytes": live_db.stat().st_size if live_db.exists() else 0,
        "persist_path": str(persist_db),
        "persist_exists": persist_db.exists(),
        "persist_size_bytes": persist_db.stat().st_size if persist_db.exists() else 0,
        "integrity": "unknown",
        "table_counts": {},
        "latest_speedtests": [],
        "probes": [],
        "events": [],
    }

    try:
        conn = db.connect(readonly=True)
        # Integrity check
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            health["integrity"] = row[0] if row else "unknown"
        except Exception as e:
            health["integrity"] = f"Error: {e}"

        # Table row counts
        tables = ["speedtest", "ping_sample", "ping_minute", "event", "outage", "alert", "target"]
        for t in tables:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                health["table_counts"][t] = cnt
            except Exception:
                health["table_counts"][t] = 0

        # Latest speedtests
        try:
            rows = conn.execute("SELECT * FROM speedtest ORDER BY ts DESC LIMIT 10").fetchall()
            health["latest_speedtests"] = [dict(r) for r in rows]
        except Exception as e:
            log.debug("error querying speedtests for snapshot: %s", e)

        # Probes summary
        day_ago = db.now_ms() - (24 * 3600 * 1000)
        try:
            p_rows = conn.execute(
                """SELECT t.id, t.addr, t.label, t.role,
                          COUNT(p.ts) as sent,
                          SUM(CASE WHEN p.rtt_us IS NULL THEN 1 ELSE 0 END) as lost,
                          AVG(p.rtt_us) as avg_rtt,
                          MIN(p.rtt_us) as min_rtt,
                          MAX(p.rtt_us) as max_rtt
                   FROM target t
                   LEFT JOIN ping_sample p ON p.target_id = t.id AND p.ts >= ?
                   WHERE t.enabled = 1
                   GROUP BY t.id, t.addr, t.label, t.role
                   ORDER BY t.id""",
                (day_ago,)
            ).fetchall()
            health["probes"] = [dict(r) for r in p_rows]
        except Exception as e:
            log.debug("error querying probes for snapshot: %s", e)

        # Recent events
        try:
            e_rows = conn.execute("SELECT ts, severity, source, kind, detail FROM event ORDER BY ts DESC LIMIT 15").fetchall()
            health["events"] = [dict(r) for r in e_rows]
        except Exception as e:
            log.debug("error querying events for snapshot: %s", e)

        conn.close()
    except Exception as e:
        health["integrity"] = f"DB Connection Failed: {e}"

    return health


def _read_recent_dev_logs(limit_lines: int = 200) -> str:
    """Extract the tail of the developer log with full trace details."""
    candidates = [
        Path("/var/log/nmb/nmb_developer.log"),
        Path.home() / ".local/share/nmb/nmb_developer.log",
        Path("/tmp/nmb/nmb_developer.log"),
    ]
    for c in candidates:
        if c.is_file():
            try:
                lines = c.read_text(encoding="utf-8", errors="replace").splitlines()
                return "\n".join(lines[-limit_lines:])
            except Exception as e:
                return f"(Error reading {c}: {e})"
    return "(No nmb_developer.log file found yet)"


def _read_systemd_journal(lines: int = 60) -> str:
    """Read recent systemd journal logs for all nmb units."""
    if not shutil.which("journalctl"):
        return "(journalctl binary not available on system)"
    return _run_cmd(["journalctl", "-u", "nmb-*", "-n", str(lines), "--no-pager"], timeout=3.0)


def _collect_live_threads() -> str:
    """Format stack traces of all active Python threads in the current process."""
    lines = []
    thread_map = {t.ident: t for t in threading.enumerate()}
    for ident, frame in sys._current_frames().items():
        th = thread_map.get(ident)
        th_name = th.name if th else f"Thread-{ident}"
        is_daemon = getattr(th, "daemon", False)
        lines.append(f"Thread: '{th_name}' (ident={ident}, daemon={is_daemon}):")
        formatted = "".join(traceback.format_stack(frame))
        lines.append(formatted.strip())
        lines.append("")
    return "\n".join(lines) if lines else "(No threads recorded)"


def _collect_dns_health() -> Dict[str, Any]:
    """Test DNS resolution latency and parse nameservers."""
    res: Dict[str, Any] = {
        "nameservers": [],
        "resolve_1111_ms": None,
        "resolve_speedtest_ms": None,
        "error": None,
    }
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    res["nameservers"].append(parts[1])
    except Exception as e:
        res["error"] = str(e)

    for host, key in (("1.1.1.1", "resolve_1111_ms"), ("speedtest.net", "resolve_speedtest_ms")):
        try:
            t0 = time.monotonic()
            socket.gethostbyname(host)
            res[key] = round((time.monotonic() - t0) * 1000.0, 1)
        except Exception:
            res[key] = -1.0
    return res


def _collect_disk_and_mounts() -> Dict[str, Any]:
    """Collect block device hierarchy and detect read-only filesystem alerts."""
    res = {
        "lsblk": _run_cmd(["lsblk", "-o", "NAME,FSTYPE,SIZE,MOUNTPOINT,RO,RM,MODEL"]),
        "ro_mounts": [],
    }
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    mountpoint = parts[1]
                    opts = parts[3].split(",")
                    if "ro" in opts and mountpoint in ("/", "/boot", "/boot/firmware"):
                        res["ro_mounts"].append(f"{mountpoint} (filesystem is mounted READ-ONLY!)")
    except Exception:
        pass
    return res


def _collect_dmesg_events() -> str:
    """Extract recent kernel errors and hardware warnings from dmesg."""
    cmd = ["dmesg", "-T", "--level=emerg,alert,crit,err,warn"] if shutil.which("dmesg") else None
    if not cmd:
        return "(dmesg not available)"
    out = _run_cmd(cmd, timeout=3.0)
    if not out or "(Error" in out or "(stderr:" in out:
        out = _run_cmd(["dmesg"], timeout=3.0)
        lines = [l for l in out.splitlines() if any(k in l.lower() for k in ("error", "fail", "warn", "oom", "drop", "carrier", "throttl"))]
        return "\n".join(lines[-40:]) if lines else "(No critical kernel events detected)"
    return "\n".join(out.splitlines()[-40:])


def generate_invasive_snapshot(cfg: Optional[Config] = None, force_write: bool = True) -> Tuple[str, Dict[str, Any]]:
    """Assemble the comprehensive, deeply invasive diagnostic Markdown report and metadata."""
    global _cached_markdown, _cached_metadata, _cached_timestamp

    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            from nmb.config import Config
            cfg = Config()

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    now_local = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Hardware & System
    hw = _collect_hardware_telemetry()
    os_info = detect_os_info()
    ifaces = _collect_network_interfaces()
    services = _collect_systemd_status()
    db_health = _collect_database_health()
    journal_text = _read_systemd_journal(60)
    dev_log_text = _read_recent_dev_logs(200)

    # 2. Network state
    wan_iface = cfg.network.wan_interface or "eth0"
    dual_ips = get_dual_stack_ips(wan_iface)
    routes_v4 = _run_cmd(["ip", "route", "show"])
    routes_v6 = _run_cmd(["ip", "-6", "route", "show"])
    sockets = _run_cmd(["ss", "-tulpn"])
    arp_neigh = _run_cmd(["ip", "neigh", "show"])
    dns_health = _collect_dns_health()
    disk_mounts = _collect_disk_and_mounts()
    dmesg_events = _collect_dmesg_events()
    live_threads = _collect_live_threads()

    try:
        from nmb.report.crash_trap import list_crash_reports
        crash_reports = list_crash_reports()
    except Exception:
        crash_reports = []
    rfkill_state = _run_cmd(["rfkill", "list"])
    iw_state = _run_cmd(["iw", "dev"])
    qdisc_stats = _run_cmd(["tc", "-s", "qdisc", "show"])
    iptables_nat = _run_cmd(["iptables", "-t", "nat", "-S"])
    disk_df = _run_cmd(["df", "-h"])

    # 3. Drive config status
    drive_cfg_path = find_drive_config_path()
    writable_drive_target = get_writable_drive_config_target()
    drive_match = False
    if drive_cfg_path and DEFAULT_CONFIG_PATH.exists():
        try:
            drive_match = drive_cfg_path.read_text() == DEFAULT_CONFIG_PATH.read_text()
        except Exception:
            pass

    # 4. Red Flag Alert Assessment
    red_flags: List[Tuple[str, str, str]] = []  # (Subsystem, Severity, Message)

    # Check under-voltage / throttling
    if hw["throttled_flags"]:
        for flag in hw["throttled_flags"]:
            sev = "CRITICAL" if "currently" in flag else "WARNING"
            red_flags.append(("Hardware Power/Thermal", sev, flag))

    if hw["temp_c"] and hw["temp_c"] > 75.0:
        red_flags.append(("CPU Temperature", "WARNING", f"High core temperature: {hw['temp_c']}°C"))

    # Check read-only mounts
    if disk_mounts.get("ro_mounts"):
        for ro_m in disk_mounts["ro_mounts"]:
            red_flags.append(("Storage Filesystem", "CRITICAL", ro_m))

    # Check fatal crashes
    if crash_reports:
        red_flags.append(("Crash Reports", "CRITICAL", f"{len(crash_reports)} fatal Python incident report(s) captured!"))

    # Check DB integrity
    if db_health["integrity"] != "ok":
        red_flags.append(("SQLite Database", "CRITICAL", f"Integrity check returned: {db_health['integrity']}"))

    # Check systemd services
    for s_name, s_state in services.items():
        if s_state in ("failed", "inactive") and s_name.startswith("nmb-"):
            sev = "WARNING" if "timer" in s_name else "CRITICAL"
            red_flags.append(("System Service", sev, f"Daemon {s_name} is {s_state}"))

    # Check WAN IP
    if not dual_ips.get("ipv4") and not dual_ips.get("ipv6"):
        red_flags.append(("Network Connectivity", "WARNING", f"No public IPv4 or IPv6 detected on {wan_iface}"))

    # Check speedtest failures
    if db_health["latest_speedtests"]:
        latest_st = db_health["latest_speedtests"][0]
        if latest_st.get("download_bps", 0) == 0:
            red_flags.append(("Speedtest Benchmark", "WARNING", f"Most recent speedtest (ID: {latest_st.get('id')}) reported 0 Mbps"))

    # 5. Build Comprehensive Markdown
    md_lines: List[str] = []
    md_lines.append("# 🕵️ NetworkMeasureBox — Invasive Developer Diagnostic Snapshot")
    md_lines.append(f"> Generated automatically at **{now_utc}** (Local: `{now_local}`).")
    md_lines.append(f"> **Purpose**: Complete, low-level technical state dump enabling headless debugging and AI development continuation.")
    md_lines.append("")

    # Section 1: Executive Red Flags
    md_lines.append("## 🚨 Executive Health & Red Flags")
    if not red_flags:
        md_lines.append("✅ **No critical hardware or daemon alerts detected.** System is operating within normal parameters.")
    else:
        md_lines.append("| Subsystem | Severity | Alert Details |")
        md_lines.append("| :--- | :--- | :--- |")
        for sub, sev, msg in red_flags:
            badge = "🔴 **CRITICAL**" if sev == "CRITICAL" else "🟡 **WARNING**"
            md_lines.append(f"| {sub} | {badge} | {msg} |")
    md_lines.append("")

    # Section 2: System & Hardware Telemetry
    md_lines.append("## 🖥️ System & Hardware Telemetry")
    md_lines.append(f"- **Box ID**: `{cfg.system.box_id}`")
    md_lines.append(f"- **OS**: {os_info.get('distro', 'Linux')} ({os_info.get('kernel', platform.release())})")
    md_lines.append(f"- **Architecture / Machine**: `{platform.machine()}` (CPU: `{hw.get('freq_mhz', 'N/A')} MHz`)")
    md_lines.append(f"- **System Uptime**: `{hw.get('uptime', 'N/A')}`")
    md_lines.append(f"- **Load Average**: `{hw.get('load_avg', 'N/A')}`")
    md_lines.append(f"- **CPU Temperature**: `{hw.get('temp_c', 'N/A')} °C`")
    md_lines.append(f"- **Throttling Code**: `{hw.get('throttled_hex', '0x0')}`")
    if hw["mem"]:
        md_lines.append(f"- **Memory**: Total: `{hw['mem'].get('MemTotal', 'N/A')}`, Free: `{hw['mem'].get('MemFree', 'N/A')}`, Available: `{hw['mem'].get('MemAvailable', 'N/A')}`")
    md_lines.append("")

    # Section 3: Configuration & Drive Sync Status
    conf_exists = False
    try:
        conf_exists = DEFAULT_CONFIG_PATH.exists()
    except (PermissionError, OSError):
        conf_exists = False

    md_lines.append("## ⚙️ Configuration & Storage Sync Status")
    md_lines.append(f"- **Internal Config Path**: `{DEFAULT_CONFIG_PATH}` (Exists: `{conf_exists}`)")
    md_lines.append(f"- **FAT32 Boot Drive Config**: `{drive_cfg_path or 'Not Detected'}` (Writable: `{writable_drive_target is not None}`)")
    md_lines.append(f"- **Drive Mirror Match**: `{'✅ Synced (Identical)' if drive_match else '⚠️ Diverged or Not Synced'}`")
    md_lines.append(f"- **Network Mode**: `{cfg.network.mode}`")
    md_lines.append(f"- **Active Benchmark Engine**: `{getattr(cfg.speedtest, 'automated_engine', 'ookla')}`")
    md_lines.append(f"- **User-Agent Mode**: `{getattr(cfg.speedtest, 'user_agent_mode', 'auto_fresh')}`")
    md_lines.append(f"- **Effective User-Agent**: `{get_effective_user_agent(cfg)}`")
    md_lines.append(f"- **Designated Speedtest Server ID**: `{getattr(cfg.speedtest, 'server_id', 'Auto')}`")
    md_lines.append("")

    # Section 4: Systemd Daemons Status
    md_lines.append("## 🛠️ Systemd Daemons State")
    md_lines.append("| Daemon / Unit | Status |")
    md_lines.append("| :--- | :--- |")
    for s_name, s_state in services.items():
        st_icon = "🟢" if s_state == "active" else ("🟡" if s_state == "inactive" else "🔴")
        md_lines.append(f"| `{s_name}` | {st_icon} **{s_state}** |")
    md_lines.append("")

    # Section 5: Network Interfaces Dump
    md_lines.append("## 🌐 Network Interfaces & Statistics")
    md_lines.append("| Interface | Carrier | State | Speed | MTU | RX Bytes / Errors | TX Bytes / Errors |")
    md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for ifc in ifaces:
        c_icon = "🟢 UP" if ifc["carrier"] else "⚪ DOWN"
        rx_str = f"{ifc['stats'].get('rx_bytes', 0):,} B (err: {ifc['stats'].get('rx_errors', 0)})"
        tx_str = f"{ifc['stats'].get('tx_bytes', 0):,} B (err: {ifc['stats'].get('tx_errors', 0)})"
        md_lines.append(f"| `{ifc['name']}` | {c_icon} | {ifc['operstate']} | {ifc['speed']} ({ifc['duplex']}) | {ifc['mtu']} | {rx_str} | {tx_str} |")
    md_lines.append("")

    # Section 6: Sockets & Listening Ports
    md_lines.append("## 🔌 Active Sockets & Listening Ports (`ss -tulpn`)")
    md_lines.append("```text")
    md_lines.append(sockets if sockets else "No open listening sockets detected.")
    md_lines.append("```")
    md_lines.append("")

    # Section 7: Kernel Routing & NAT
    md_lines.append("## 🗺️ Kernel Routing Tables")
    md_lines.append("**IPv4 Routing Table (`ip route`):**")
    md_lines.append("```text")
    md_lines.append(routes_v4 if routes_v4 else "No IPv4 routes.")
    md_lines.append("```")
    md_lines.append("**IPv6 Routing Table (`ip -6 route`):**")
    md_lines.append("```text")
    md_lines.append(routes_v6 if routes_v6 else "No IPv6 routes.")
    md_lines.append("```")
    md_lines.append("")

    # Section 8: Database & Recent Measurements
    md_lines.append("## 🗄️ SQLite Database Health & Benchmark History")
    md_lines.append(f"- **Live DB Path**: `{db_health['live_path']}` (Size: `{db_health['live_size_bytes']:,} bytes`)")
    md_lines.append(f"- **Persistent DB Path**: `{db_health['persist_path']}` (Size: `{db_health['persist_size_bytes']:,} bytes`)")
    md_lines.append(f"- **SQLite PRAGMA Integrity Check**: `{'✅ ' + db_health['integrity'] if db_health['integrity'] == 'ok' else '❌ ' + db_health['integrity']}`")
    md_lines.append(f"- **Table Row Counts**: `{json.dumps(db_health['table_counts'])}`")
    md_lines.append("")

    if db_health["latest_speedtests"]:
        md_lines.append("### ⚡ Latest 10 Speedtest Benchmark Results")
        md_lines.append("| ID | Timestamp (UTC) | Engine | Down (Mbps) | Up (Mbps) | Ping (ms) | Bufferbloat | Grade | Server | Client IP |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for st in db_health["latest_speedtests"]:
            st_dt = datetime.datetime.fromtimestamp(st["ts"] / 1000.0, datetime.timezone.utc).strftime("%m-%d %H:%M")
            down_mbps = round(st.get("download_bps", 0) / 1_000_000.0, 1)
            up_mbps = round(st.get("upload_bps", 0) / 1_000_000.0, 1)
            ping_ms = round(st.get("latency_ms", 0.0), 1)
            bb_delta = round(st.get("bufferbloat_delta_ms", 0.0), 1) if st.get("bufferbloat_delta_ms") is not None else "-"
            bb_grade = st.get("bufferbloat_grade", "-")
            srv = f"{st.get('server_name', '')} (#{st.get('server_id', '')})"
            md_lines.append(f"| {st.get('id')} | {st_dt} | `{st.get('engine', 'ookla')}` | **{down_mbps}** | **{up_mbps}** | {ping_ms} | +{bb_delta} ms | `{bb_grade}` | {srv} | {st.get('client_ip', '')} |")
        md_lines.append("")

    # Section 9: Crash Incident Reports (if any)
    if crash_reports:
        md_lines.append("## 💥 Unhandled Fatal Crash Reports")
        md_lines.append("| Incident File | Created | Location | Size |")
        md_lines.append("| :--- | :--- | :--- | :--- |")
        for cr in crash_reports[:5]:
            md_lines.append(f"| `{cr['filename']}` | {cr['created_iso']} | {cr['location']} | {cr['size_bytes']:,} B |")
        md_lines.append("")

    # Section 10: DNS & ARP Neighbors
    md_lines.append("## 🌐 DNS Name Resolution & Neighbors (`ip neigh`)")
    ns_str = ", ".join(dns_health["nameservers"]) if dns_health["nameservers"] else "None"
    md_lines.append(f"- **Configured Nameservers**: `{ns_str}`")
    md_lines.append(f"- **DNS Query Latency (1.1.1.1)**: `{dns_health['resolve_1111_ms']} ms` | **(speedtest.net)**: `{dns_health['resolve_speedtest_ms']} ms`")
    md_lines.append("**ARP / Neighbor Table (`ip neigh`):**")
    md_lines.append("```text")
    md_lines.append(arp_neigh if arp_neigh else "No neighbor entries.")
    md_lines.append("```")
    md_lines.append("")

    # Section 11: Block Devices & Mount Health
    md_lines.append("## 💾 Block Devices & Filesystem Mount State (`lsblk`)")
    md_lines.append("```text")
    md_lines.append(disk_mounts["lsblk"])
    md_lines.append("```")
    if disk_mounts["ro_mounts"]:
        md_lines.append("> ⚠️ **CRITICAL WARNING**: Read-only mount detected: " + ", ".join(disk_mounts["ro_mounts"]))
    md_lines.append("")

    # Section 12: Kernel Ring Buffer Alert Filter (dmesg)
    md_lines.append("## ⚠️ Kernel Ring Buffer Alert Filter (`dmesg`)")
    md_lines.append("```text")
    md_lines.append(dmesg_events)
    md_lines.append("```")
    md_lines.append("")

    # Section 13: Live Python Threads
    md_lines.append("## 🧵 Active Python Process Threads & Call Stacks")
    md_lines.append("```text")
    md_lines.append(live_threads)
    md_lines.append("```")
    md_lines.append("")

    # Section 14: Systemd Journal Logs
    md_lines.append("## 📜 Systemd Journal Tail (`journalctl -u nmb-* -n 60`)")
    md_lines.append("```text")
    md_lines.append(journal_text)
    md_lines.append("```")
    md_lines.append("")

    # Section 15: Deep Developer Trace Log Tail
    md_lines.append("## 🔎 Developer High-Resolution Trace Log (`/var/log/nmb/nmb_developer.log`)")
    md_lines.append("```text")
    md_lines.append(dev_log_text)
    md_lines.append("```")
    md_lines.append("")

    # Section 16: Developer Continuation Instructions
    md_lines.append("## 💡 Developer & AI Continuation Guide")
    md_lines.append("This snapshot captures the live system state of NetworkMeasureBox. When continuing development:")
    md_lines.append("1. **Configuration**: Edit `/etc/nmb/nmb.conf` or the FAT32 boot drive `/boot/firmware/nmb.conf`. Call `nmb-helper sync-drive-config` to synchronize.")
    md_lines.append("2. **Daemons**: Control services using `systemctl restart nmb-netd nmb-probe nmb-web` or `nmb-helper`.")
    md_lines.append("3. **Speedtest Runner**: Tested via `python3 -m nmb.speed.runner --engine [ookla|cloudflare|rtr]` or `nmb-speed`.")
    md_lines.append("4. **Database**: Direct SQLite access on `/var/lib/nmb/live/nmb.db` or `/tmp/nmb/live/nmb.db`.")
    md_lines.append("")

    full_markdown = "\n".join(md_lines)

    metadata: Dict[str, Any] = {
        "timestamp_utc": now_utc,
        "timestamp_local": now_local,
        "red_flags": red_flags,
        "box_id": cfg.system.box_id,
        "hardware": hw,
        "services": services,
        "interfaces": ifaces,
        "crashes_count": len(crash_reports),
        "dns": dns_health,
        "database": {
            "integrity": db_health["integrity"],
            "counts": db_health["table_counts"],
            "latest_speedtests_count": len(db_health["latest_speedtests"]),
        },
        "drive_sync": {
            "drive_config_path": str(drive_cfg_path) if drive_cfg_path else None,
            "is_synced": drive_match,
        },
    }

    with _cache_lock:
        _cached_markdown = full_markdown
        _cached_metadata = metadata
        _cached_timestamp = time.monotonic()

    if force_write:
        _persist_snapshot(full_markdown, metadata)

    return full_markdown, metadata


def _persist_snapshot(markdown_content: str, metadata: Dict[str, Any]) -> None:
    """Safely persist snapshot to all predictable primary and backup locations with rolling history."""
    # 1. Primary log path (/var/log/nmb/invasive_dev_snapshot.md) with rolling previous copy
    try:
        PRIMARY_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        prev_p = PRIMARY_SNAPSHOT_PATH.with_name("invasive_dev_snapshot_prev.md")
        if PRIMARY_SNAPSHOT_PATH.is_file():
            try:
                shutil.copy2(PRIMARY_SNAPSHOT_PATH, prev_p)
            except Exception:
                pass

        tmp = PRIMARY_SNAPSHOT_PATH.with_suffix(".tmp")
        tmp.write_text(markdown_content, encoding="utf-8")
        tmp.replace(PRIMARY_SNAPSHOT_PATH)

        # Write JSON version
        tmp_json = PRIMARY_JSON_PATH.with_suffix(".tmp")
        tmp_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        tmp_json.replace(PRIMARY_JSON_PATH)
    except (PermissionError, OSError):
        # Fallback to local share or /tmp
        try:
            FALLBACK_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            FALLBACK_SNAPSHOT_PATH.write_text(markdown_content, encoding="utf-8")
        except Exception:
            pass

    # 2. Live tmpfs run dir (/run/nmb/invasive_dev_snapshot.md)
    try:
        RUN_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUN_SNAPSHOT_PATH.write_text(markdown_content, encoding="utf-8")
    except Exception:
        pass

    # 3. FAT32 Boot Partition / Removable Drive (The crucial physical recovery channel)
    try:
        boot_target = get_boot_drive_snapshot_target()
        # The timer runs every 3 minutes, and the SD card should not be written that often.
        if boot_target and boot_target.is_file() and time.time() - boot_target.stat().st_mtime < BOOT_MIRROR_MIN_SEC:
            boot_target = None
        if boot_target:
            if boot_target.is_file():
                try:
                    shutil.copy2(boot_target, boot_target.with_name("nmb_invasive_dev_snapshot_prev.md"))
                except Exception:
                    pass
            boot_target.write_text(markdown_content, encoding="utf-8")
            log.debug("invasive dev snapshot mirrored to FAT32 boot drive: %s", boot_target)
    except Exception as e:
        log.debug("could not mirror invasive snapshot to boot drive: %s", e)


def get_cached_invasive_snapshot() -> Tuple[str, Dict[str, Any]]:
    """Return memory-cached snapshot or generate immediately if empty."""
    with _cache_lock:
        if _cached_markdown:
            return _cached_markdown, _cached_metadata
    return generate_invasive_snapshot(force_write=False)


def _background_logger_worker(cfg: Config, interval_sec: int) -> None:
    """Continuous background worker maintaining fresh invasive diagnostic snapshots."""
    log.info("invasive background diagnostic logger started (interval: %ds)", interval_sec)
    # Generate initial snapshot immediately on startup
    try:
        generate_invasive_snapshot(cfg, force_write=True)
    except Exception as e:
        log.warning("initial invasive snapshot generation error: %s", e)

    while not _worker_stop_event.is_set():
        # Sleep with 1s wake-up checks
        for _ in range(interval_sec):
            if _worker_stop_event.is_set():
                break
            time.sleep(1.0)

        if not _worker_stop_event.is_set():
            try:
                generate_invasive_snapshot(cfg, force_write=True)
            except Exception as e:
                log.debug("periodic invasive snapshot generation exception: %s", e)

    log.info("invasive background diagnostic logger stopped")


def start_invasive_background_logger(cfg: Config, interval_sec: int = 180) -> None:
    """Launch the continuous background diagnostic thread."""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return

    _worker_stop_event.clear()
    _worker_thread = threading.Thread(
        target=_background_logger_worker,
        args=(cfg, interval_sec),
        daemon=True,
        name="nmb-invasive-logger",
    )
    _worker_thread.start()


def stop_invasive_background_logger() -> None:
    """Stop the continuous background diagnostic thread."""
    _worker_stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3.0)


def read_latest_invasive_snapshot_file() -> Optional[str]:
    """Read the latest persisted invasive markdown snapshot from any known location."""
    for p in (PRIMARY_SNAPSHOT_PATH, RUN_SNAPSHOT_PATH, FALLBACK_SNAPSHOT_PATH, get_boot_drive_snapshot_target()):
        if p and isinstance(p, Path) and p.is_file():
            try:
                content = p.read_text(encoding="utf-8")
                if content:
                    return content
            except Exception:
                continue
    return None

