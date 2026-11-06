"""NetworkMeasureBox Real-Time System Task Manager & Resource Monitor Engine.

Provides htop-grade real-time system introspection for the Web UI:
- Per-core CPU utilization (Core 0, Core 1, ...) with user/kernel breakdown.
- Detailed memory and swap telemetry (Total, Used, Free, Buffers, Cached).
- Load averages, uptime, task states (Running, Sleeping, Stopped, Zombie).
- Process table with PID, PPID, User, Priority, Nice, VIRT, RES, SHR, State, CPU%, MEM%, Run time, and Command.
- Process search, filtering, and safe termination (SIGTERM / SIGKILL).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.common.tasks")

# Cache for CPU delta calculation between consecutive samples
_PREV_CPU_STATS: Dict[str, Dict[str, float]] = {}
_LAST_SAMPLE_TS: float = 0.0


def _format_bytes(bytes_count: float) -> str:
    """Format bytes count into human-readable binary prefix string."""
    if bytes_count <= 0:
        return "0 B"
    sizes = ["B", "KB", "MB", "GB", "TB"]
    k = 1024.0
    i = 0
    val = float(bytes_count)
    while val >= k and i < len(sizes) - 1:
        val /= k
        i += 1
    return f"{val:.1f} {sizes[i]}" if i > 0 else f"{int(val)} B"


def _format_kb(kb: float) -> str:
    """Format kilobytes into human-readable string."""
    return _format_bytes(kb * 1024.0)


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into a clean human readable string (e.g. 3d 04:12:35)."""
    s = int(seconds)
    days = s // 86400
    rem = s % 86400
    hours = rem // 3600
    rem = rem % 3600
    mins = rem // 60
    secs = rem % 60
    if days > 0:
        return f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _read_cpu_stats() -> Dict[str, Dict[str, float]]:
    """Read CPU time counters from /proc/stat."""
    stats = {}
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("cpu"):
                    parts = line.split()
                    cname = parts[0]
                    vals = [float(x) for x in parts[1:]]
                    user = vals[0]
                    nice = vals[1] if len(vals) > 1 else 0.0
                    system = vals[2] if len(vals) > 2 else 0.0
                    idle = vals[3] if len(vals) > 3 else 0.0
                    iowait = vals[4] if len(vals) > 4 else 0.0
                    irq = vals[5] if len(vals) > 5 else 0.0
                    softirq = vals[6] if len(vals) > 6 else 0.0
                    steal = vals[7] if len(vals) > 7 else 0.0

                    idle_all = idle + iowait
                    system_all = system + irq + softirq
                    user_all = user + nice
                    total = sum(vals)
                    busy = total - idle_all

                    stats[cname] = {
                        "user": user_all,
                        "system": system_all,
                        "idle": idle_all,
                        "total": total,
                        "busy": busy,
                    }
    except Exception as e:
        log.warning("Could not read /proc/stat: %s", e)
    return stats


def get_cpu_telemetry() -> Dict[str, Any]:
    """Calculate real-time overall and per-core CPU utilization."""
    global _PREV_CPU_STATS, _LAST_SAMPLE_TS

    curr_stats = _read_cpu_stats()
    now = time.monotonic()

    # If first reading or elapsed time too long (> 10s), sample twice with a 50ms pause
    if not _PREV_CPU_STATS or (now - _LAST_SAMPLE_TS) > 10.0:
        time.sleep(0.05)
        _PREV_CPU_STATS = curr_stats
        curr_stats = _read_cpu_stats()

    cores_list: List[Dict[str, Any]] = []
    total_cpu_pct = 0.0

    # Calculate percentages
    for cname, curr in curr_stats.items():
        prev = _PREV_CPU_STATS.get(cname, curr)
        diff_total = curr["total"] - prev["total"]
        diff_busy = curr["busy"] - prev["busy"]
        diff_user = curr["user"] - prev["user"]
        diff_sys = curr["system"] - prev["system"]

        if diff_total > 0:
            usage_pct = min(100.0, max(0.0, round((diff_busy / diff_total) * 100.0, 1)))
            user_pct = min(100.0, max(0.0, round((diff_user / diff_total) * 100.0, 1)))
            sys_pct = min(100.0, max(0.0, round((diff_sys / diff_total) * 100.0, 1)))
        else:
            usage_pct = user_pct = sys_pct = 0.0

        if cname == "cpu":
            total_cpu_pct = usage_pct
        elif cname.startswith("cpu"):
            try:
                core_idx = int(cname.replace("cpu", ""))
            except ValueError:
                core_idx = len(cores_list)
            cores_list.append({
                "core": core_idx,
                "label": f"Core {core_idx}",
                "usage_pct": usage_pct,
                "percent": usage_pct,
                "user_pct": user_pct,
                "sys_pct": sys_pct,
            })

    # Sort cores by index
    cores_list.sort(key=lambda x: x["core"])

    # Update cache
    _PREV_CPU_STATS = curr_stats
    _LAST_SAMPLE_TS = now

    # CPU Temperature
    cpu_temp_c = None
    thermal_paths = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
    ]
    for tp in thermal_paths:
        if tp.exists():
            try:
                val = float(tp.read_text().strip()) / 1000.0
                if 0.0 < val < 125.0:
                    cpu_temp_c = round(val, 1)
                    break
            except Exception:
                log.debug("suppressed exception", exc_info=True)

    # CPU Frequency
    freq_mhz = None
    freq_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    if freq_path.exists():
        try:
            freq_mhz = round(float(freq_path.read_text().strip()) / 1000.0, 0)
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    return {
        "total_usage_pct": total_cpu_pct,
        "total_percent": total_cpu_pct,
        "cores": cores_list,
        "cores_count": len(cores_list) if cores_list else os.cpu_count() or 1,
        "cpu_temp_c": cpu_temp_c,
        "temp_c": cpu_temp_c,
        "cpu_freq_mhz": freq_mhz,
    }


def get_memory_telemetry() -> Dict[str, Any]:
    """Parse /proc/meminfo to retrieve RAM and swap metrics."""
    info: Dict[str, float] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    val_parts = parts[1].strip().split()
                    if val_parts:
                        info[k] = float(val_parts[0])  # in kB
    except Exception as e:
        log.warning("Could not read /proc/meminfo: %s", e)

    mem_total_kb = info.get("MemTotal", 1048576.0)
    mem_free_kb = info.get("MemFree", 0.0)
    mem_avail_kb = info.get("MemAvailable", mem_free_kb)
    buffers_kb = info.get("Buffers", 0.0)
    cached_kb = info.get("Cached", 0.0)
    sreclaimable_kb = info.get("SReclaimable", 0.0)

    # htop-style calculation
    mem_used_kb = max(0.0, mem_total_kb - mem_avail_kb)
    mem_used_pct = round((mem_used_kb / mem_total_kb) * 100.0, 1) if mem_total_kb > 0 else 0.0

    swap_total_kb = info.get("SwapTotal", 0.0)
    swap_free_kb = info.get("SwapFree", 0.0)
    swap_used_kb = max(0.0, swap_total_kb - swap_free_kb)
    swap_used_pct = round((swap_used_kb / swap_total_kb) * 100.0, 1) if swap_total_kb > 0 else 0.0

    return {
        "total_bytes": int(mem_total_kb * 1024),
        "used_bytes": int(mem_used_kb * 1024),
        "available_bytes": int(mem_avail_kb * 1024),
        "free_bytes": int(mem_free_kb * 1024),
        "buffers_bytes": int(buffers_kb * 1024),
        "cached_bytes": int(cached_kb * 1024),
        "used_pct": mem_used_pct,
        "used_percent": mem_used_pct,
        "used_mb": round(mem_used_kb / 1024.0, 1),
        "total_mb": round(mem_total_kb / 1024.0, 1),
        "buffers_mb": round(buffers_kb / 1024.0, 1),
        "cached_mb": round(cached_kb / 1024.0, 1),
        "used_human": _format_kb(mem_used_kb),
        "total_human": _format_kb(mem_total_kb),
        "available_human": _format_kb(mem_avail_kb),
        "buffers_human": _format_kb(buffers_kb),
        "cached_human": _format_kb(cached_kb),
        "swap_total_bytes": int(swap_total_kb * 1024),
        "swap_used_bytes": int(swap_used_kb * 1024),
        "swap_used_pct": swap_used_pct,
        "swap_used_percent": swap_used_pct,
        "swap_used_mb": round(swap_used_kb / 1024.0, 1),
        "swap_total_mb": round(swap_total_kb / 1024.0, 1),
        "swap_used_human": _format_kb(swap_used_kb),
        "swap_total_human": _format_kb(swap_total_kb),
    }


def get_system_summary() -> Dict[str, Any]:
    """Retrieve load average, uptime, and system execution counters."""
    # Load averages
    load1, load5, load15 = 0.0, 0.0, 0.0
    running_entities, total_entities = 0, 0
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as f:
            parts = f.read().strip().split()
            if len(parts) >= 4:
                load1 = float(parts[0])
                load5 = float(parts[1])
                load15 = float(parts[2])
                ent_parts = parts[3].split("/")
                if len(ent_parts) == 2:
                    running_entities = int(ent_parts[0])
                    total_entities = int(ent_parts[1])
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    # Uptime
    uptime_sec = 0.0
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            parts = f.read().strip().split()
            if parts:
                uptime_sec = float(parts[0])
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    return {
        "loadavg_1m": load1,
        "loadavg_5m": load5,
        "loadavg_15m": load15,
        "loadavg_human": f"{load1:.2f}, {load5:.2f}, {load15:.2f}",
        "uptime_seconds": int(uptime_sec),
        "uptime_human": _format_uptime(uptime_sec),
        "running_entities": running_entities,
        "total_entities": total_entities,
    }


def get_processes_list(limit: int = 150) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Execute high-speed ps command to retrieve and parse running processes.

    Returns:
        (processes_list, process_stats)
    """
    cmd = ["ps", "-eo", "pid,ppid,user,pri,ni,vsz,rss,stat,%cpu,%mem,time,comm,args"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as e:
        log.error("Failed to run ps: %s", e)
        return [], {"total": 0, "running": 0, "sleeping": 0, "zombie": 0}

    lines = proc.stdout.strip().splitlines()
    if not lines or len(lines) <= 1:
        return [], {"total": 0, "running": 0, "sleeping": 0, "zombie": 0}

    processes: List[Dict[str, Any]] = []
    stats = {"total": 0, "running": 0, "sleeping": 0, "zombie": 0}

    for line in lines[1:]:
        parts = line.split(None, 12)
        if len(parts) < 12:
            continue

        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            user = parts[2]
            pri = int(parts[3])
            ni = int(parts[4])
            vsz_kb = float(parts[5])
            rss_kb = float(parts[6])
            state_raw = parts[7]
            cpu_pct = float(parts[8])
            mem_pct = float(parts[9])
            time_str = parts[10]
            comm = parts[11]
            args = parts[12] if len(parts) > 12 else comm
        except (ValueError, IndexError):
            continue

        stats["total"] += 1
        primary_state = state_raw[0] if state_raw else "S"
        if primary_state == "R":
            stats["running"] += 1
        elif primary_state == "Z":
            stats["zombie"] += 1
        else:
            stats["sleeping"] += 1

        # Check if process is part of NetworkMeasureBox
        is_nmb = bool(
            "nmb" in comm.lower()
            or "nmb" in args.lower()
            or "rmbt" in comm.lower()
            or "ooni" in comm.lower()
            or "speedtest" in comm.lower()
            or "wireguard" in comm.lower()
            or "openvpn" in comm.lower()
            or "adblock" in comm.lower()
        )

        # Compatibility and alias keys
        processes.append({
            "pid": pid,
            "ppid": ppid,
            "user": user,
            "priority": pri,
            "pri": pri,
            "nice": ni,
            "ni": ni,
            "vsz_kb": vsz_kb,
            "vsz_human": _format_kb(vsz_kb),
            "virt_h": _format_kb(vsz_kb),
            "rss_kb": rss_kb,
            "rss_human": _format_kb(rss_kb),
            "res_h": _format_kb(rss_kb),
            "shr_h": "-",
            "state": state_raw,
            "stat": state_raw,
            "cpu_pct": cpu_pct,
            "cpu_percent": cpu_pct,
            "mem_pct": mem_pct,
            "mem_percent": mem_pct,
            "time": time_str,
            "command": comm,
            "args": args,
            "is_nmb": is_nmb,
        })

    # Sort descending by CPU% by default
    processes.sort(key=lambda p: (p["cpu_pct"], p["mem_pct"]), reverse=True)

    if limit > 0:
        processes = processes[:limit]

    return processes, stats


def get_full_task_manager_payload(limit: int = 150) -> Dict[str, Any]:
    """Generate comprehensive real-time Task Manager payload."""
    cpu_data = get_cpu_telemetry()
    mem_data = get_memory_telemetry()
    sys_summary = get_system_summary()
    procs, proc_stats = get_processes_list(limit=limit)

    # Convenience swap object
    swap_data = {
        "total_bytes": mem_data.get("swap_total_bytes", 0),
        "used_bytes": mem_data.get("swap_used_bytes", 0),
        "used_percent": mem_data.get("swap_used_pct", 0.0),
        "used_mb": mem_data.get("swap_used_mb", 0.0),
        "total_mb": mem_data.get("swap_total_mb", 0.0),
        "used_human": mem_data.get("swap_used_human", "0 B"),
        "total_human": mem_data.get("swap_total_human", "0 B"),
    }

    # Convenience summary object
    summary_data = {
        "uptime_formatted": sys_summary.get("uptime_human", "--"),
        "uptime_seconds": sys_summary.get("uptime_seconds", 0),
        "load_avg": {
            "1m": sys_summary.get("loadavg_1m", 0.0),
            "5m": sys_summary.get("loadavg_5m", 0.0),
            "15m": sys_summary.get("loadavg_15m", 0.0),
        },
        "tasks_total": proc_stats.get("total", len(procs)),
        "tasks_running": proc_stats.get("running", 0),
        "tasks_sleeping": proc_stats.get("sleeping", 0),
        "tasks_zombie": proc_stats.get("zombie", 0),
    }

    return {
        "status": "ok",
        "timestamp": int(time.time()),
        "server_pid": os.getpid(),
        "cpu": cpu_data,
        "memory": mem_data,
        "swap": swap_data,
        "system": sys_summary,
        "summary": summary_data,
        "stats": proc_stats,
        "processes_count": len(procs),
        "processes": procs,
    }


def kill_process(pid: int, sig_num: int = 15) -> Dict[str, Any]:
    """Safely terminate a target process with protective constraints."""
    if pid <= 1:
        return {"status": "error", "message": "Cannot kill init process (PID 1). Protected system resource."}

    if pid == os.getpid():
        return {"status": "error", "message": "Cannot terminate self (NetworkMeasureBox Management Server)."}

    # Signal mapping
    allowed_signals = {
        15: signal.SIGTERM,
        9: signal.SIGKILL,
        1: signal.SIGHUP,
        2: signal.SIGINT,
    }

    target_sig = allowed_signals.get(sig_num, signal.SIGTERM)

    # Try direct kill
    try:
        os.kill(pid, target_sig)
        return {"status": "ok", "message": f"Signal {target_sig.name} ({sig_num}) delivered to PID {pid} successfully."}
    except PermissionError:
        # Try privileged kill via sudo
        try:
            res = subprocess.run(["sudo", "-n", "kill", f"-{sig_num}", str(pid)], capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0:
                return {"status": "ok", "message": f"Privileged signal {sig_num} sent to PID {pid}."}
            return {"status": "error", "message": f"Failed to kill PID {pid}: {res.stderr or res.stdout}"}
        except Exception as e:
            return {"status": "error", "message": f"Privileged termination failed: {e}"}
    except ProcessLookupError:
        return {"status": "error", "message": f"Process PID {pid} no longer exists."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to signal PID {pid}: {e}"}

