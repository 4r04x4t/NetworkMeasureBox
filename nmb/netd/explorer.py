"""
Local Network Device Explorer & Discovery for NetworkMeasureBox.
Scans active LAN and Guest Wi-Fi subnets via ARP, IP neighbour tables and ICMP sweeps.
Identifies device vendors by MAC OUI prefix and resolves hostnames.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import logging
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.netd.explorer")

# Common OUI Vendor Database (Prefix -> Vendor Name)
OUI_VENDORS = {
    "b8:27:eb": "Raspberry Pi Foundation",
    "dc:a6:32": "Raspberry Pi Trading",
    "e4:5f:01": "Raspberry Pi Trading",
    "28:cd:c1": "Raspberry Pi (RPi 4/5)",
    "00:1a:11": "Google Inc.",
    "f4:f5:e8": "Google Inc.",
    "3c:5a:37": "Google Inc. (Nest/Chromecast)",
    "00:17:88": "Philips Lighting (Hue)",
    "ac:bc:32": "Apple, Inc.",
    "f0:18:98": "Apple, Inc.",
    "3c:22:fb": "Apple, Inc.",
    "bc:d0:74": "Apple, Inc.",
    "a4:83:e7": "Apple, Inc.",
    "18:65:90": "Apple, Inc.",
    "f4:34:f0": "Apple, Inc.",
    "50:bc:c6": "Apple, Inc.",
    "d0:81:7a": "Apple, Inc.",
    "00:16:3e": "Xen / Virtual Machine",
    "52:54:00": "QEMU / KVM Virtual Machine",
    "00:50:56": "VMware, Inc.",
    "08:00:27": "Oracle VirtualBox",
    "00:0c:29": "VMware, Inc.",
    "00:24:8c": "ASUSTeK Computer",
    "04:d9:f5": "ASUSTeK Computer",
    "24:4b:fe": "ASUSTeK Computer",
    "c8:7f:54": "ASUSTeK Computer",
    "b4:8c:9d": "Intel Corporate",
    "70:4d:7b": "Samsung Electronics",
    "88:36:5f": "Samsung Electronics",
    "cc:07:ab": "Samsung Electronics",
    "e4:7c:f3": "Samsung Electronics",
    "50:c7:bf": "TP-Link Corporation",
    "60:32:b1": "TP-Link Corporation",
    "98:48:27": "TP-Link Corporation",
    "e8:48:b8": "TP-Link Corporation",
    "74:da:88": "TP-Link Corporation",
    "00:1d:aa": "Intel Corporate",
    "34:13:e8": "Intel Corporate",
    "84:fd:d1": "Intel Corporate",
    "a0:af:bd": "Intel Corporate",
    "00:26:86": "Cisco Systems",
    "70:69:79": "Cisco Systems",
    "cc:d5:39": "Cisco Systems",
    "48:8d:36": "Ubiquiti Networks",
    "80:2a:a8": "Ubiquiti Networks",
    "f0:9f:c2": "Ubiquiti Networks",
    "b4:fb:e4": "MikroTik",
    "48:8f:5a": "MikroTik",
    "64:d1:54": "Xiaomi Communications",
    "78:11:dc": "Xiaomi Communications",
    "d8:0d:17": "Xiaomi Communications",
    "00:e0:4c": "Realtek Semiconductor",
    "54:ef:44": "Realtek Semiconductor",
}

_scan_lock = threading.Lock()
_discovered_devices: Dict[str, Dict[str, Any]] = {}


def lookup_vendor(mac: str) -> str:
    """Lookup manufacturer name by MAC address OUI prefix."""
    mac_clean = mac.lower().replace("-", ":")
    prefix_8 = mac_clean[:8]
    if prefix_8 in OUI_VENDORS:
        return OUI_VENDORS[prefix_8]
    if mac_clean.startswith("52:54:00") or mac_clean.startswith("08:00:27"):
        return "Virtual Machine / Hypervisor"
    return "Unknown Vendor"


def _tag_device_network(dev: Dict[str, Any], guest_iface: str = "wlan0") -> None:
    """Enrich device dictionary with network classification (Primary LAN vs Guest Wi-Fi)."""
    iface = dev.get("interface", "")
    if iface == guest_iface or (iface.startswith("wlan") and not iface.startswith("eth")):
        dev["is_guest"] = True
        dev["network_type"] = "guest"
        dev["network_label"] = "Guest Wi-Fi"
    elif iface.startswith("eth"):
        dev["is_guest"] = False
        dev["network_type"] = "lan"
        dev["network_label"] = "Primary LAN"
    else:
        dev["is_guest"] = False
        dev["network_type"] = "local"
        dev["network_label"] = "Local Interface"


def _read_passive_neighbors() -> None:
    """Populate discovered devices from kernel ARP table and ip neigh show."""
    global _discovered_devices
    now_ts = int(time.time() * 1000)
    # 1. Read existing ARP cache from kernel (/proc/net/arp)
    try:
        arp_file = Path("/proc/net/arp")
        if arp_file.exists():
            for line in arp_file.read_text().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 6:
                    ip = parts[0]
                    mac = parts[3].lower()
                    iface = parts[5]
                    if mac != "00:00:00:00:00:00" and not ip.startswith("127."):
                        if ip not in _discovered_devices:
                            dev_item = {
                                "ip": ip,
                                "mac": mac,
                                "vendor": lookup_vendor(mac),
                                "hostname": "",
                                "interface": iface,
                                "first_seen": now_ts,
                                "last_seen": now_ts,
                                "status": "active",
                            }
                            _tag_device_network(dev_item)
                            _discovered_devices[ip] = dev_item
                        else:
                            _discovered_devices[ip]["last_seen"] = now_ts
                            _discovered_devices[ip]["mac"] = mac
                            _discovered_devices[ip]["interface"] = iface
                            _tag_device_network(_discovered_devices[ip])
    except Exception as e:
        log.debug("error reading /proc/net/arp: %s", e)

    # 2. Read `ip neigh show`
    try:
        res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "lladdr" in parts:
                    ip = parts[0]
                    dev_idx = parts.index("dev") + 1 if "dev" in parts else -1
                    ll_idx = parts.index("lladdr") + 1
                    if dev_idx > 0 and ll_idx < len(parts):
                        iface = parts[dev_idx]
                        mac = parts[ll_idx].lower()
                        if mac != "00:00:00:00:00:00":
                            if ip not in _discovered_devices:
                                dev_item = {
                                    "ip": ip,
                                    "mac": mac,
                                    "vendor": lookup_vendor(mac),
                                    "hostname": "",
                                    "interface": iface,
                                    "first_seen": now_ts,
                                    "last_seen": now_ts,
                                    "status": "active",
                                }
                                _tag_device_network(dev_item)
                                _discovered_devices[ip] = dev_item
                            else:
                                _discovered_devices[ip]["mac"] = mac
                                _discovered_devices[ip]["last_seen"] = now_ts
                                _discovered_devices[ip]["interface"] = iface
                                _tag_device_network(_discovered_devices[ip])
    except Exception as e:
        log.debug("error running ip neigh show: %s", e)


def scan_network_devices(iface: Optional[str] = None, timeout_sec: float = 8.0) -> List[Dict[str, Any]]:
    """
    Scan connected LAN and Guest subnets to discover all connected devices.
    """
    global _discovered_devices
    with _scan_lock:
        now_ts = int(time.time() * 1000)
        _read_passive_neighbors()

        # 3. Active ping sweep on connected subnets (fast parallel ping)
        subnets_to_sweep = set()
        try:
            res = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and parts[1] != "lo":
                        ip_cidr = parts[3]
                        try:
                            net = ipaddress.ip_network(ip_cidr, strict=False)
                            # Only sweep private /24 or smaller networks to prevent flooding
                            if net.is_private and net.prefixlen >= 24:
                                subnets_to_sweep.add(net)
                        except Exception:
                            pass
        except Exception:
            pass

        ips_to_sweep = []
        for net in subnets_to_sweep:
            for host_ip in list(net.hosts())[:80]:
                ips_to_sweep.append(str(host_ip))

        if ips_to_sweep:
            _sweep_sock = None
            try:
                _sweep_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
                _sweep_sock.setblocking(False)
            except OSError:
                try:
                    _sweep_sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
                    _sweep_sock.setblocking(False)
                except OSError:
                    _sweep_sock = None

            if _sweep_sock:
                try:
                    from nmb.probe.icmp import build_echo_request
                    ident = os.getpid() & 0xFFFF
                    for ip in ips_to_sweep:
                        try:
                            pkt = build_echo_request(ident, 1, payload_size=32)
                            _sweep_sock.sendto(pkt, (ip, 0))
                        except Exception:
                            pass
                    time.sleep(0.4)
                finally:
                    _sweep_sock.close()
            else:
                def _ping_ip(target_ip: str):
                    try:
                        subprocess.run(
                            ["ping", "-c", "1", "-W", "1", target_ip],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    except Exception:
                        pass

                with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
                    futures = [executor.submit(_ping_ip, str(ip)) for ip in ips_to_sweep[:40]]
                    concurrent.futures.wait(futures, timeout=timeout_sec)

        # 4. Resolve hostnames for discovered devices
        def _resolve_name(dev: Dict[str, Any]):
            ip = dev["ip"]
            if not dev.get("hostname"):
                try:
                    name, _, _ = socket.gethostbyaddr(ip)
                    dev["hostname"] = name
                except Exception:
                    dev["hostname"] = ""

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            for dev in _discovered_devices.values():
                executor.submit(_resolve_name, dev)

        # Format and sort by IP address
        result_list = list(_discovered_devices.values())
        if iface and iface != "any":
            result_list = [d for d in result_list if d.get("interface") == iface]
        try:
            result_list.sort(key=lambda d: socket.inet_aton(d["ip"]) if "." in d["ip"] else d["ip"])
        except Exception:
            result_list.sort(key=lambda d: d["ip"])

        return result_list


def get_cached_devices(iface: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return discovered devices without re-triggering full active ping sweep."""
    global _discovered_devices
    if not _discovered_devices:
        _read_passive_neighbors()
    res = list(_discovered_devices.values())
    if iface and iface != "any":
        res = [d for d in res if d.get("interface") == iface]
    try:
        res.sort(key=lambda d: socket.inet_aton(d["ip"]) if "." in d["ip"] else d["ip"])
    except Exception:
        pass
    return res


def get_explorer_summary() -> Dict[str, Any]:
    """Return device catalog with aggregated LAN and Guest Wi-Fi statistics."""
    devs = get_cached_devices()
    lan_c = sum(1 for d in devs if not d.get("is_guest"))
    guest_c = sum(1 for d in devs if d.get("is_guest"))
    return {
        "total": len(devs),
        "lan_count": lan_c,
        "guest_count": guest_c,
        "devices": devs,
    }
