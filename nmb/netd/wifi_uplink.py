"""The box on a Wi-Fi network as a measuring client (not the guest network feature).

``[wifi_uplink]`` connects a wireless interface to the owner's own Wi-Fi with its own
NetworkManager profile (``nmb-uplink``), separate from the guest Wi-Fi client, which
exists for packet capture on another network.

``[network] measurement_link`` chooses where speed tests run:

* ``auto`` (default): over Ethernet when a cable is connected, otherwise over Wi-Fi;
* ``ethernet``: only over Ethernet;
* ``wifi``: only over the Wi-Fi uplink.

With a cable and Wi-Fi both up, the default route stays on Ethernet (the Wi-Fi
profile gets a higher route metric). So that a test bound to the Wi-Fi address
really leaves over Wi-Fi, ``nmb-netd`` (root) keeps a source rule
``from <wifi address> lookup 150`` with a default route via the Wi-Fi gateway in
table 150 (``sync_source_routing``).
"""
from __future__ import annotations

import ipaddress
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.wifi_uplink")

PROFILE = "nmb-uplink"
TABLE = 150
RULE_PRIORITY = 150
METRIC = 700
LINKS = ("auto", "ethernet", "wifi")
SYS_CLASS_NET = Path("/sys/class/net")


def _run(cmd: List[str], timeout: float = 15.0) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def wireless_interfaces() -> List[str]:
    if not SYS_CLASS_NET.exists():
        return []
    return sorted(p.name for p in SYS_CLASS_NET.iterdir() if (p / "wireless").exists() or (p / "phy80211").exists())


def uplink_interface(cfg: Any) -> Optional[str]:
    """The configured Wi-Fi interface, or the first wireless one."""
    up = getattr(cfg, "wifi_uplink", None)
    name = str(getattr(up, "interface", "") or "").strip()
    if name and name != "auto":
        return name
    found = wireless_interfaces()
    return found[0] if found else None


def _ipv4_and_gateway(iface: str) -> Tuple[Optional[str], Optional[str]]:
    rc, out, _ = _run(["ip", "-4", "-o", "addr", "show", "dev", iface, "scope", "global"], timeout=4)
    ip = None
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                ip = parts[parts.index("inet") + 1].split("/")[0]
                break
    gw = None
    rc, out, _ = _run(["ip", "-4", "route", "show", "default", "dev", iface], timeout=4)
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if "via" in parts:
                gw = parts[parts.index("via") + 1]
                break
    return ip, gw


def status(cfg: Any) -> Dict[str, Any]:
    up = getattr(cfg, "wifi_uplink", None)
    iface = uplink_interface(cfg)
    res: Dict[str, Any] = {
        "enabled": bool(getattr(up, "enabled", False)),
        "ssid_configured": str(getattr(up, "ssid", "") or ""),
        "password_set": bool(getattr(up, "password", "")),
        "hidden": bool(getattr(up, "hidden", False)),
        "interface": iface,
        "interfaces": wireless_interfaces(),
        "measurement_link": getattr(getattr(cfg, "network", None), "measurement_link", "auto"),
        "connected": False, "ssid": None, "ip": None, "gateway": None,
        "signal_dbm": None, "bitrate": None, "frequency_mhz": None,
    }
    if not iface:
        return res
    ip, gw = _ipv4_and_gateway(iface)
    res.update(ip=ip, gateway=gw)
    iw = shutil.which("iw")
    if iw:
        rc, out, _ = _run([iw, "dev", iface, "link"], timeout=4)
        if rc == 0 and out.startswith("Connected"):
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("SSID:"):
                    res["ssid"] = line[5:].strip()
                elif line.startswith("signal:"):
                    try:
                        res["signal_dbm"] = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass
                elif line.startswith("tx bitrate:"):
                    res["bitrate"] = line.split(":", 1)[1].strip()
                elif line.startswith("freq:"):
                    try:
                        res["frequency_mhz"] = int(float(line.split()[1]))
                    except (IndexError, ValueError):
                        pass
    res["connected"] = bool(ip and (res["ssid"] or not iw))
    return res


def connect(cfg: Any, password: Optional[str] = None) -> Tuple[bool, str]:
    """Join the configured Wi-Fi with the box's own profile; the password is not logged."""
    up = cfg.wifi_uplink
    ssid = str(up.ssid or "").strip()
    if not ssid:
        return False, "Set the Wi-Fi network name (SSID) first."
    iface = uplink_interface(cfg)
    if not iface:
        return False, "No wireless interface found."
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return False, "NetworkManager (nmcli) is needed for the Wi-Fi uplink."
    psk = password if password is not None else str(up.password or "")
    _run([nmcli, "connection", "delete", "id", PROFILE], timeout=8)
    cmd = [nmcli, "connection", "add", "type", "wifi", "con-name", PROFILE, "ifname", iface, "ssid", ssid,
           "connection.autoconnect", "yes", "ipv4.route-metric", str(METRIC), "ipv6.route-metric", str(METRIC)]
    if getattr(up, "hidden", False):
        cmd += ["802-11-wireless.hidden", "yes"]
    if psk:
        cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk]
    rc, out, err = _run(cmd, timeout=15)
    if rc != 0:
        return False, f"Could not create the Wi-Fi profile: {(err or out).strip()}"
    rc, out, err = _run([nmcli, "connection", "up", PROFILE], timeout=45)
    if rc != 0:
        return False, f"Could not join '{ssid}': {(err or out).strip()}"
    st = status(cfg)
    log.info("Wi-Fi uplink connected to %s on %s (ip %s)", ssid, iface, st.get("ip"))
    return True, f"Connected to '{ssid}' on {iface} (IP {st.get('ip') or 'pending'})."


def disconnect(cfg: Any) -> Tuple[bool, str]:
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return False, "nmcli not found"
    rc, out, err = _run([nmcli, "connection", "down", PROFILE], timeout=15)
    if rc != 0 and "not an active" not in (err + out):
        return False, (err or out).strip()
    return True, "Wi-Fi uplink disconnected."


def measurement_target(cfg: Any) -> Tuple[str, Optional[str]]:
    """Which link the next test must use: ("ethernet"|"wifi"|"any", wifi interface)."""
    link = getattr(getattr(cfg, "network", None), "measurement_link", "auto")
    return (link if link in ("ethernet", "wifi") else "any"), uplink_interface(cfg)


def sync_source_routing(cfg: Any) -> bool:
    """Keep "from <wifi ip> lookup 150" and table 150's default route via the Wi-Fi gateway (root)."""
    iface = uplink_interface(cfg)
    if not iface or not getattr(getattr(cfg, "wifi_uplink", None), "enabled", False):
        _run(["ip", "-4", "rule", "del", "priority", str(RULE_PRIORITY)], timeout=4)
        return False
    ip, gw = _ipv4_and_gateway(iface)
    if not ip or not gw:
        return False
    try:
        ipaddress.ip_address(ip)
        ipaddress.ip_address(gw)
    except ValueError:
        return False
    _run(["ip", "-4", "route", "replace", "default", "via", gw, "dev", iface, "table", str(TABLE)], timeout=4)
    rc, out, _ = _run(["ip", "-4", "rule", "show", "priority", str(RULE_PRIORITY)], timeout=4)
    if f"from {ip} " not in out + " ":
        _run(["ip", "-4", "rule", "del", "priority", str(RULE_PRIORITY)], timeout=4)
        _run(["ip", "-4", "rule", "add", "priority", str(RULE_PRIORITY), "from", ip, "lookup", str(TABLE)], timeout=4)
        log.info("Wi-Fi uplink source routing: from %s via %s dev %s (table %d)", ip, gw, iface, TABLE)
    return True
