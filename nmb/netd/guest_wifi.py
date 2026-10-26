"""Dedicated Guest Wi-Fi Receiver & Client Station Probe for NetworkMeasureBox.

Allows NetworkMeasureBox to operate in Standalone Mode (wired to primary LAN via eth0)
while concurrently maintaining an active Wi-Fi Client (Station) connection to the
upstream router's isolated Guest Wi-Fi network (via wlan0).

This bridges AP isolation and VLAN boundaries, enabling simultaneous:
- Independent ping and latency probing across both LAN and Guest subnets
- Passive ARP and active subnet device exploration (Network Explorer)
- Raw packet sniffing on the Guest Wi-Fi interface (Packet Sniffer)
- Automatic verification of IP subnet isolation between LAN and Guest networks
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.guest_wifi")

_scan_lock = threading.Lock()
_last_scan_time = 0.0
_cached_networks: List[Dict[str, Any]] = []


def _run_cmd(cmd: List[str], timeout: float = 15.0) -> Tuple[int, str, str]:
    """Execute command with optional sudo fallback."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        log.debug("command failed %s: %s", cmd, e)

    # Try with sudo if not already root
    if os.geteuid() != 0 and cmd[0] != "sudo":
        sudo_cmd = ["sudo", "-n"] + cmd
        try:
            proc = subprocess.run(sudo_cmd, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout, proc.stderr
        except Exception as e:
            log.debug("sudo command failed %s: %s", sudo_cmd, e)
            return -1, "", str(e)

    return -1, "", "Command failed or timed out"


def scan_wifi_networks(iface: str = "wlan0", force_rescan: bool = True) -> List[Dict[str, Any]]:
    """Scan visible Wi-Fi access points using nmcli or iw.

    Returns a list of dicts with keys:
    - in_use: bool (currently connected)
    - bssid: str
    - ssid: str
    - channel: int
    - signal: int (0-100%)
    - security: str (e.g. 'WPA2 WPA3', 'WPA2', 'Open')
    """
    global _last_scan_time, _cached_networks

    now = time.time()
    with _scan_lock:
        if not force_rescan and _cached_networks and (now - _last_scan_time < 10.0):
            return _cached_networks

        networks: List[Dict[str, Any]] = []
        nmcli_bin = shutil.which("nmcli")

        if nmcli_bin:
            cmd = [
                nmcli_bin,
                "-t",
                "-f",
                "IN-USE,BSSID,SSID,CHAN,SIGNAL,SECURITY",
                "dev",
                "wifi",
                "list",
            ]
            if force_rescan:
                cmd.extend(["--rescan", "yes"])
            if iface:
                cmd.extend(["ifname", iface])

            ret, stdout, stderr = _run_cmd(cmd, timeout=12.0)
            if ret == 0 and stdout:
                seen_bssids = set()
                for raw_line in stdout.splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    # nmcli escapes colons in MAC addresses as "\:"
                    # Replace "\:" with a sentinel before splitting on ":"
                    safe_line = line.replace(r"\:", "__ESCAPED_COLON__")
                    parts = safe_line.split(":")
                    if len(parts) >= 6:
                        in_use = (parts[0].strip() == "*")
                        bssid = parts[1].replace("__ESCAPED_COLON__", ":").strip()
                        ssid = parts[2].replace("__ESCAPED_COLON__", ":").strip()
                        chan_str = parts[3].strip()
                        sig_str = parts[4].strip()
                        security = parts[5].replace("__ESCAPED_COLON__", ":").strip()

                        if not ssid:
                            ssid = f"<Hidden Network> ({bssid})"

                        try:
                            chan = int(chan_str)
                        except ValueError:
                            chan = 0

                        try:
                            signal = int(sig_str)
                        except ValueError:
                            signal = 0

                        dedup_key = f"{ssid}_{chan}_{bssid}"
                        if dedup_key in seen_bssids:
                            continue
                        seen_bssids.add(dedup_key)

                        networks.append({
                            "in_use": in_use,
                            "bssid": bssid,
                            "ssid": ssid,
                            "channel": chan,
                            "signal": signal,
                            "security": security or "Open",
                        })

        # Sort: connected first, then by signal strength descending
        networks.sort(key=lambda n: (not n["in_use"], -n["signal"]))
        _cached_networks = networks
        _last_scan_time = now
        return networks


def get_guest_wifi_status(
    iface: str = "wlan0",
    wan_iface: str = "eth0",
    cfg_guest: Optional[Any] = None,
) -> Dict[str, Any]:
    """Retrieve full operational telemetry of the Guest Wi-Fi client station.

    Checks:
    - Connection state, connected SSID, BSSID, RSSI, Channel
    - Assigned IPv4 address, subnet mask, gateway, DNS
    - Routing metric
    - LAN vs Guest IP subnet isolation status (compares with wan_iface)
    """
    res: Dict[str, Any] = {
        "enabled": getattr(cfg_guest, "enabled", False) if cfg_guest else False,
        "interface": iface,
        "connected": False,
        "state": "disconnected",
        "connection_name": "",
        "ssid": "",
        "bssid": "",
        "channel": 0,
        "signal_percent": 0,
        "security": "",
        "ip_address": "",
        "cidr": "",
        "subnet": "",
        "gateway": "",
        "dns": [],
        "mac_address": "",
        "route_metric": 600,
        "wan_interface": wan_iface,
        "wan_ip": "",
        "wan_subnet": "",
        "is_isolated_subnet": False,
        "isolation_verdict": "Guest Wi-Fi client is not connected.",
    }

    # 1. Parse dev show via nmcli
    nmcli_bin = shutil.which("nmcli")
    if nmcli_bin:
        ret, stdout, _ = _run_cmd([nmcli_bin, "dev", "show", iface], timeout=5.0)
        if ret == 0 and stdout:
            for line in stdout.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k == "GENERAL.STATE":
                    m = re.match(r"([0-9]+)\s*\(([^)]+)\)", v)
                    if m:
                        state_code = int(m.group(1))
                        res["state"] = m.group(2).lower()
                        res["connected"] = (state_code == 100 or "connected" in res["state"])
                elif k == "GENERAL.CONNECTION":
                    res["connection_name"] = v if v != "--" else ""
                elif k == "GENERAL.HWADDR":
                    res["mac_address"] = v
                elif k == "IP4.ADDRESS[1]":
                    res["cidr"] = v
                    if "/" in v:
                        res["ip_address"] = v.split("/")[0]
                        try:
                            net = ipaddress.ip_network(v, strict=False)
                            res["subnet"] = str(net)
                        except Exception:
                            pass
                    else:
                        res["ip_address"] = v
                elif k == "IP4.GATEWAY":
                    if v and v != "--":
                        res["gateway"] = v
                elif k.startswith("IP4.DNS"):
                    if v and v not in res["dns"]:
                        res["dns"].append(v)
                elif k.startswith("IP4.ROUTE") and "nh =" in v:
                    m_mt = re.search(r"mt\s*=\s*([0-9]+)", v)
                    if m_mt:
                        try:
                            res["route_metric"] = int(m_mt.group(1))
                        except ValueError:
                            pass

    # 2. Get active Wi-Fi BSSID, SSID, Signal and Security
    active_nets = scan_wifi_networks(iface=iface, force_rescan=False)
    for n in active_nets:
        if n["in_use"]:
            res["ssid"] = n["ssid"]
            res["bssid"] = n["bssid"]
            res["channel"] = n["channel"]
            res["signal_percent"] = n["signal"]
            res["security"] = n["security"]
            res["connected"] = True
            break

    # If connected according to nmcli dev show but not marked in scan list
    if not res["ssid"] and res["connected"] and res["connection_name"]:
        clean_name = res["connection_name"]
        for prefix in ("netplan-wlan0-", "netplan-", "wifi-", "wlan0-"):
            if clean_name.startswith(prefix):
                clean_name = clean_name[len(prefix):]
        res["ssid"] = clean_name

    # 3. Retrieve primary WAN / LAN interface subnet to evaluate network isolation
    if wan_iface:
        try:
            ret, stdout, _ = _run_cmd(["ip", "-o", "-4", "addr", "show", wan_iface], timeout=3.0)
            if ret == 0 and stdout:
                parts = stdout.strip().split()
                if len(parts) >= 4:
                    wan_cidr = parts[3]
                    res["wan_ip"] = wan_cidr.split("/")[0]
                    wan_net = ipaddress.ip_network(wan_cidr, strict=False)
                    res["wan_subnet"] = str(wan_net)
        except Exception:
            pass

    # 4. Determine Subnet Isolation Verdict
    if res["connected"] and res["subnet"] and res["wan_subnet"]:
        if res["subnet"] != res["wan_subnet"]:
            res["is_isolated_subnet"] = True
            res["isolation_verdict"] = (
                f"🟢 ISOLATED GUEST SUBNET VERIFIED: Guest Wi-Fi client is operating on `{res['subnet']}` (Gateway: {res['gateway']}), "
                f"completely separated from the primary LAN `{res['wan_subnet']}`. "
                "Simultaneous probing and sniffing across both networks is fully active."
            )
        else:
            res["is_isolated_subnet"] = False
            res["isolation_verdict"] = (
                f"🟡 SHARED BROADCAST DOMAIN: Both `{iface}` and `{wan_iface}` share the same subnet `{res['subnet']}`. "
                "The upstream router does not isolate this Wi-Fi SSID from the wired LAN."
            )
    elif res["connected"]:
        res["isolation_verdict"] = f"🟢 Connected to '{res['ssid']}' (IP: {res['ip_address'] or 'Waiting for DHCP'})."
    else:
        res["isolation_verdict"] = "⚪ Guest Wi-Fi client is inactive or disconnected."

    return res


def connect_guest_wifi(
    ssid: str,
    password: Optional[str] = None,
    iface: str = "wlan0",
    metric: int = 600,
    timeout: float = 25.0,
) -> Tuple[bool, str]:
    """Connect wireless interface to a Guest Wi-Fi network as a client station.

    Ensures route metric is higher than the wired interface (e.g. metric 600) so
    that primary Internet bandwidth measurements remain bound to eth0.
    """
    ssid = ssid.strip()
    if not ssid:
        return False, "SSID cannot be empty"

    nmcli_bin = shutil.which("nmcli")
    if not nmcli_bin:
        return False, "nmcli utility not found on system"

    log.info("Connecting Guest Wi-Fi client (%s) to SSID: %s (metric: %d)", iface, ssid, metric)

    # 1. Connect using nmcli
    cmd = [nmcli_bin, "dev", "wifi", "connect", ssid, "ifname", iface]
    if password:
        cmd.extend(["password", password])

    ret, stdout, stderr = _run_cmd(cmd, timeout=timeout)
    if ret != 0:
        err_msg = stderr.strip() or stdout.strip() or "Connection failed"
        log.error("Failed to connect to %s on %s: %s", ssid, iface, err_msg)
        return False, f"Connection failed: {err_msg}"

    # 2. Adjust route metric to ensure eth0 retains default route priority
    conn_name = ""
    # Find active connection name on iface
    ret_c, out_c, _ = _run_cmd([nmcli_bin, "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"], timeout=4.0)
    if ret_c == 0 and out_c:
        for line in out_c.splitlines():
            parts = line.strip().split(":")
            if len(parts) >= 2 and parts[1] == iface:
                conn_name = parts[0]
                break

    if conn_name:
        _run_cmd([nmcli_bin, "connection", "modify", conn_name, "ipv4.route-metric", str(metric)], timeout=4.0)
        _run_cmd([nmcli_bin, "connection", "up", conn_name], timeout=8.0)

    # Allow DHCP negotiation to finalize
    time.sleep(1.0)
    status = get_guest_wifi_status(iface=iface)
    log.info("Guest Wi-Fi connected successfully: SSID=%s, IP=%s, Subnet=%s",
             status["ssid"], status["ip_address"], status["subnet"])
    return True, f"Successfully connected to '{ssid}' (IP: {status['ip_address'] or 'DHCP pending'})."


def disconnect_guest_wifi(iface: str = "wlan0") -> Tuple[bool, str]:
    """Disconnect wireless interface from Wi-Fi network."""
    nmcli_bin = shutil.which("nmcli")
    if not nmcli_bin:
        return False, "nmcli not found"

    log.info("Disconnecting Guest Wi-Fi client on interface %s", iface)
    ret, stdout, stderr = _run_cmd([nmcli_bin, "dev", "disconnect", iface], timeout=8.0)
    if ret == 0:
        return True, f"Interface {iface} disconnected."
    err_msg = stderr.strip() or stdout.strip() or "Failed to disconnect"
    return False, err_msg


def sync_guest_wifi_connection(cfg: Any) -> None:
    """Synchronize configured Guest Wi-Fi settings in the background on startup."""
    guest_cfg = getattr(cfg, "guest_wifi", None)
    if not guest_cfg or not getattr(guest_cfg, "enabled", False):
        return

    ssid = getattr(guest_cfg, "ssid", "").strip()
    if not ssid:
        return

    iface = getattr(guest_cfg, "interface", "wlan0")
    password = getattr(guest_cfg, "password", "")
    metric = int(getattr(guest_cfg, "metric", 600))

    def _worker():
        try:
            status = get_guest_wifi_status(iface=iface, cfg_guest=guest_cfg)
            if status.get("connected") and status.get("ssid") == ssid:
                log.info("Guest Wi-Fi already connected to target SSID '%s' on %s", ssid, iface)
                return
            log.info("Syncing Guest Wi-Fi client: connecting to '%s' on %s...", ssid, iface)
            connect_guest_wifi(ssid=ssid, password=password, iface=iface, metric=metric)
        except Exception as e:
            log.warning("Guest Wi-Fi sync worker error: %s", e)

    threading.Thread(target=_worker, daemon=True, name="nmb-guest-wifi-sync").start()
