"""
Multi-OS and Linux Distro Detection & System Package Updater for NetworkMeasureBox.
Supports Debian, Ubuntu, Fedora, RHEL, CentOS, Rocky, Alma, Arch Linux, Alpine, openSUSE.
Discovers hardware architectures, dynamic network interfaces, and package managers.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.netd.os_detector")

UPDATE_LOG_FILE = Path("/var/lib/nmb/live/system_update.log")
_update_lock = threading.Lock()
_update_in_progress = False


def detect_os_info() -> Dict[str, Any]:
    """Detect operating system distribution, release, architecture and package manager."""
    info: Dict[str, Any] = {
        "system": platform.system(),
        "node": platform.node(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "distro_id": "generic_linux",
        "distro_name": "Linux",
        "distro_version": "",
        "package_manager": None,
        "is_raspberry_pi": False,
        "hardware_model": "Generic Linux Device",
    }

    # 1. Parse /etc/os-release or /usr/lib/os-release
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    v = v.strip("\"'")
                    if k == "ID":
                        info["distro_id"] = v.lower()
                    elif k == "NAME":
                        info["distro_name"] = v
                    elif k == "VERSION_ID":
                        info["distro_version"] = v
                    elif k == "PRETTY_NAME" and not info.get("distro_name"):
                        info["distro_name"] = v
            except Exception as e:
                log.debug("could not parse %s: %s", path, e)
            break

    # 2. Check for Raspberry Pi model
    dt_model = Path("/proc/device-tree/model")
    if dt_model.exists():
        try:
            model_str = dt_model.read_text(encoding="utf-8", errors="replace").strip("\x00 \n")
            if model_str:
                info["hardware_model"] = model_str
                if "raspberry pi" in model_str.lower():
                    info["is_raspberry_pi"] = True
        except Exception:
            pass

    # 3. Detect available package manager
    if shutil.which("apt-get"):
        info["package_manager"] = "apt"
    elif shutil.which("dnf"):
        info["package_manager"] = "dnf"
    elif shutil.which("yum"):
        info["package_manager"] = "yum"
    elif shutil.which("pacman"):
        info["package_manager"] = "pacman"
    elif shutil.which("apk"):
        info["package_manager"] = "apk"
    elif shutil.which("zypper"):
        info["package_manager"] = "zypper"

    return info


def get_dynamic_interfaces() -> List[Dict[str, Any]]:
    """Scan and return all active network interfaces on the host dynamically."""
    interfaces: List[Dict[str, Any]] = []
    sys_net = Path("/sys/class/net")
    if not sys_net.exists():
        return interfaces

    for iface_dir in sorted(sys_net.iterdir()):
        name = iface_dir.name
        if name == "lo":
            continue

        iface_info: Dict[str, Any] = {
            "name": name,
            "type": "ethernet",
            "is_wireless": False,
            "is_bridge": False,
            "is_virtual": False,
            "operstate": "unknown",
            "mac": "",
            "mtu": 1500,
            "ipv4": [],
            "ipv6": [],
            "speed_mbps": None,
        }

        # Operational state
        oper_file = iface_dir / "operstate"
        if oper_file.exists():
            try:
                iface_info["operstate"] = oper_file.read_text().strip()
            except Exception:
                pass

        # MAC Address
        addr_file = iface_dir / "address"
        if addr_file.exists():
            try:
                iface_info["mac"] = addr_file.read_text().strip().lower()
            except Exception:
                pass

        # MTU
        mtu_file = iface_dir / "mtu"
        if mtu_file.exists():
            try:
                iface_info["mtu"] = int(mtu_file.read_text().strip())
            except Exception:
                pass

        # Interface type check
        if (iface_dir / "wireless").exists() or (iface_dir / "phy80211").exists():
            iface_info["type"] = "wireless"
            iface_info["is_wireless"] = True
        elif (iface_dir / "bridge").exists():
            iface_info["type"] = "bridge"
            iface_info["is_bridge"] = True
        elif name.startswith(("tun", "tap", "veth", "docker", "br-")):
            iface_info["type"] = "virtual"
            iface_info["is_virtual"] = True

        # Speed if available
        speed_file = iface_dir / "speed"
        if speed_file.exists():
            try:
                val = int(speed_file.read_text().strip())
                if val > 0:
                    iface_info["speed_mbps"] = val
            except Exception:
                pass

        interfaces.append(iface_info)

    # Enrich with IP addresses using ip addr or ifconfig
    try:
        res = subprocess.run(["ip", "-o", "addr", "show"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4:
                    iname = parts[1]
                    proto = parts[2]
                    ip_cidr = parts[3]
                    for ifc in interfaces:
                        if ifc["name"] == iname:
                            if proto == "inet":
                                ifc["ipv4"].append(ip_cidr)
                            elif proto == "inet6" and not ip_cidr.startswith("fe80"):
                                ifc["ipv6"].append(ip_cidr)
    except Exception as e:
        log.debug("ip addr show parse error: %s", e)

    return interfaces


def _run_privileged_cmd(cmd_str: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run command with root elevation and sandbox escape if needed."""
    if shutil.which("systemd-run") and os.geteuid() != 0:
        args = ["sudo", "systemd-run", "--pipe", "--wait", "--quiet", "/bin/sh", "-c", cmd_str]
    elif os.geteuid() != 0:
        args = ["sudo", "/bin/sh", "-c", cmd_str]
    else:
        args = ["/bin/sh", "-c", cmd_str]
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)


def check_updates_available() -> Dict[str, Any]:
    """Check for system packages that can be upgraded without installing."""
    os_info = detect_os_info()
    pm = os_info.get("package_manager")

    result: Dict[str, Any] = {
        "package_manager": pm,
        "distro": os_info.get("distro_name"),
        "upgradable_count": 0,
        "packages": [],
        "checked": True,
        "message": "",
    }

    if not pm:
        result["message"] = "No supported package manager detected on this system."
        return result

    try:
        if pm == "apt":
            # Refresh list first
            _run_privileged_cmd("apt-get update", timeout=45)
            res = _run_privileged_cmd("apt-get -s upgrade", timeout=30)
            if res.returncode == 0:
                pkgs = []
                for line in res.stdout.splitlines():
                    if line.startswith("Inst "):
                        parts = line.split()
                        if len(parts) > 1:
                            pkgs.append(parts[1])
                result["upgradable_count"] = len(pkgs)
                result["packages"] = pkgs[:50]
                result["message"] = f"{len(pkgs)} package(s) can be upgraded."
        elif pm in ("dnf", "yum"):
            res = _run_privileged_cmd(f"{pm} check-update -q", timeout=45)
            # exit code 100 means updates are available
            lines = [l.split()[0] for l in res.stdout.splitlines() if l.strip() and not l.startswith("Security")]
            result["upgradable_count"] = len(lines)
            result["packages"] = lines[:50]
            result["message"] = f"{len(lines)} package(s) can be upgraded."
        elif pm == "pacman":
            res = _run_privileged_cmd("pacman -Qu", timeout=30)
            lines = [l.split()[0] for l in res.stdout.splitlines() if l.strip()]
            result["upgradable_count"] = len(lines)
            result["packages"] = lines[:50]
            result["message"] = f"{len(lines)} package(s) can be upgraded."
        elif pm == "apk":
            _run_privileged_cmd("apk update", timeout=30)
            res = _run_privileged_cmd("apk version -u -l '<'", timeout=30)
            lines = [l.split()[0] for l in res.stdout.splitlines() if l.strip()]
            result["upgradable_count"] = len(lines)
            result["packages"] = lines[:50]
            result["message"] = f"{len(lines)} package(s) can be upgraded."
    except Exception as e:
        result["message"] = f"Error checking updates: {e}"

    return result


def trigger_system_upgrade() -> Dict[str, Any]:
    """Asynchronously execute system upgrade based on detected package manager."""
    global _update_in_progress
    if _update_in_progress:
        return {"status": "busy", "message": "System upgrade is already in progress."}

    os_info = detect_os_info()
    pm = os_info.get("package_manager")
    if not pm:
        return {"status": "error", "message": "No supported package manager detected."}

    UPDATE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _worker():
        global _update_in_progress
        with _update_lock:
            _update_in_progress = True
            try:
                with open(UPDATE_LOG_FILE, "w", encoding="utf-8") as f:
                    f.write(f"=== Starting System Update [{pm.upper()}] ===\n")
                    f.flush()

                    if pm == "apt":
                        raw_cmd = "export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get -y -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold' upgrade"
                    elif pm == "dnf":
                        raw_cmd = "dnf -y upgrade"
                    elif pm == "yum":
                        raw_cmd = "yum -y update"
                    elif pm == "pacman":
                        raw_cmd = "pacman -Syu --noconfirm"
                    elif pm == "apk":
                        raw_cmd = "apk update && apk upgrade"
                    elif pm == "zypper":
                        raw_cmd = "zypper -n update"
                    else:
                        raw_cmd = "echo 'Unsupported package manager'"

                    if shutil.which("systemd-run") and os.geteuid() != 0:
                        full_cmd = ["sudo", "systemd-run", "--pipe", "--wait", "--quiet", "/bin/sh", "-c", raw_cmd]
                    elif os.geteuid() != 0:
                        full_cmd = ["sudo", "/bin/sh", "-c", raw_cmd]
                    else:
                        full_cmd = ["/bin/sh", "-c", raw_cmd]

                    proc = subprocess.Popen(
                        full_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    if proc.stdout:
                        for line in proc.stdout:
                            f.write(line)
                            f.flush()
                    proc.wait()
                    f.write(f"\n=== System Update Completed (Exit Code: {proc.returncode}) ===\n")
            except Exception as e:
                with open(UPDATE_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"\nError executing update: {e}\n")
            finally:
                _update_in_progress = False

    t = threading.Thread(target=_worker, daemon=True, name="nmb-sys-updater")
    t.start()
    return {"status": "started", "package_manager": pm, "message": f"System upgrade started using {pm}."}


def get_upgrade_status() -> Dict[str, Any]:
    """Return the current progress and log of the system update."""
    log_text = ""
    if UPDATE_LOG_FILE.exists():
        try:
            log_text = UPDATE_LOG_FILE.read_text(encoding="utf-8", errors="replace")[-8000:]
        except Exception:
            pass

    return {
        "in_progress": _update_in_progress,
        "log": log_text,
    }
