"""A phone, mobile hotspot or modem on USB as a measuring link ("USB tethering").

Phones (Android: ``rndis_host``/``cdc_ncm``, iPhone: ``ipheth``), mobile hotspots such as the
Netgear Nighthawk (``rndis_host``) and cellular modems (``qmi_wwan``, ``cdc_mbim``) appear as
network interfaces named like Ethernet. ``nmb.netd.interfaces.usb_tether_kind`` recognises them by
their driver, so they are never taken for the wired line.

``[usb_uplink] enabled`` gives such an interface the box's own NetworkManager profile
(``nmb-usb-uplink``): an address by DHCP, but **never the default route**, so the box's own
traffic, the outage probe and every test on another link stay where they were. With
``[network] measurement_link = usb`` speed tests are bound to its address; ``nmb-netd`` (root)
keeps ``from <usb address> lookup 152`` with a default route via the hotspot in table 152 so those
tests really leave over USB (``sync_source_routing``).

Mobile data costs money: tests over USB stop for the day after ``daily_limit_mb``, counted on the
USB interface's own byte counters (``data_budget``, key ``speedtest_data_used_usb``).
"""
from __future__ import annotations

import ipaddress
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.usb_uplink")

PROFILE = "nmb-usb-uplink"
TABLE = 152
RULE_PRIORITY = 152
METRIC = 750
SYS_CLASS_NET = Path("/sys/class/net")
USAGE_KEY = "speedtest_data_used_usb"


def _run(cmd: List[str], timeout: float = 15.0) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def tether_interfaces() -> List[str]:
    """USB phones, hotspots and modems present now."""
    from nmb.netd.interfaces import usb_tether_kind
    if not SYS_CLASS_NET.exists():
        return []
    return sorted(p.name for p in SYS_CLASS_NET.iterdir() if usb_tether_kind(p.name))


def uplink_interface(cfg: Any) -> Optional[str]:
    want = str(getattr(getattr(cfg, "usb_uplink", None), "interface", "auto") or "auto")
    present = tether_interfaces()
    if want != "auto":
        return want if want in present else None
    return present[0] if present else None


def _device_info(iface: str) -> Dict[str, Any]:
    from nmb.netd.interfaces import usb_tether_kind
    import os
    dev = SYS_CLASS_NET / iface / "device"
    info: Dict[str, Any] = {"kind": usb_tether_kind(iface), "driver": None, "vendor_id": None,
                            "product_id": None, "product": None, "manufacturer": None}
    try:
        info["driver"] = os.path.basename(os.path.realpath(dev / "driver"))
        usb = dev.resolve().parent
        for key, name in (("vendor_id", "idVendor"), ("product_id", "idProduct"),
                          ("product", "product"), ("manufacturer", "manufacturer")):
            try:
                info[key] = (usb / name).read_text().strip()
            except OSError:
                pass
    except OSError:
        pass
    return info


def _address_and_gateway(iface: str) -> Tuple[Optional[str], Optional[str]]:
    """IPv4 address of the interface, and the gateway the hotspot handed out by DHCP.

    The profile never takes the default route, so the gateway is read from the DHCP lease
    (NetworkManager's DHCP4 options), not from the routing table.
    """
    ip = None
    rc, out, _ = _run(["ip", "-4", "-o", "addr", "show", "dev", iface, "scope", "global"], timeout=4)
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                ip = parts[parts.index("inet") + 1].split("/")[0]
                break
    gw = None
    nmcli = shutil.which("nmcli")
    if nmcli:
        rc, out, _ = _run([nmcli, "-t", "-f", "DHCP4.OPTION,IP4.GATEWAY", "device", "show", iface], timeout=6)
        if rc == 0:
            for line in out.splitlines():
                key, _, val = line.partition(":")
                val = val.strip()
                if key.startswith("IP4.GATEWAY") and val:
                    gw = val
                elif key.startswith("DHCP4.OPTION") and val.replace(" ", "").startswith("routers="):
                    gw = gw or val.split("=", 1)[1].strip().split()[0]
    for cand in (gw,):
        try:
            if cand:
                ipaddress.ip_address(cand)
        except ValueError:
            gw = None
    return ip, gw


def usage_today_mb() -> float:
    try:
        from nmb.db import database as db
        from nmb.speed import data_budget
        conn = db.connect()
        try:
            return data_budget.used_today_mb(conn, key=USAGE_KEY)
        finally:
            conn.close()
    except Exception:
        return 0.0


def status(cfg: Any) -> Dict[str, Any]:
    uu = getattr(cfg, "usb_uplink", None)
    iface = uplink_interface(cfg)
    res: Dict[str, Any] = {
        "enabled": bool(getattr(uu, "enabled", False)),
        "interface_setting": str(getattr(uu, "interface", "auto") or "auto"),
        "interface": iface,
        "interfaces": tether_interfaces(),
        "measurement_link": getattr(getattr(cfg, "network", None), "measurement_link", "auto"),
        "daily_limit_mb": int(getattr(uu, "daily_limit_mb", 1024) or 0),
        "used_today_mb": round(usage_today_mb(), 1),
        "connected": False, "ip": None, "gateway": None,
    }
    if iface:
        res.update(_device_info(iface))
        ip, gw = _address_and_gateway(iface)
        res.update(ip=ip, gateway=gw, connected=bool(ip))
    return res


def connect(cfg: Any) -> Tuple[bool, str]:
    """Give the USB interface the box's own DHCP profile, without the default route."""
    iface = uplink_interface(cfg)
    if not iface:
        return False, "No phone, hotspot or modem found on USB. Plug it in and turn on USB tethering on it."
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return False, "NetworkManager (nmcli) is needed for the USB uplink."
    _run([nmcli, "connection", "delete", "id", PROFILE], timeout=8)
    rc, out, err = _run([nmcli, "connection", "add", "type", "ethernet", "con-name", PROFILE, "ifname", iface,
                         "connection.autoconnect", "yes", "ipv4.method", "auto", "ipv4.never-default", "yes",
                         "ipv4.route-metric", str(METRIC), "ipv6.method", "ignore"], timeout=15)
    if rc != 0:
        return False, f"Could not create the USB profile: {(err or out).strip()}"
    rc, out, err = _run([nmcli, "connection", "up", PROFILE], timeout=45)
    if rc != 0:
        return False, f"Could not bring up {iface}: {(err or out).strip()}"
    ip, gw = _address_and_gateway(iface)
    log.info("USB uplink up on %s (ip %s, gateway %s)", iface, ip, gw)
    return True, f"USB uplink up on {iface} (IP {ip or 'pending'}, gateway {gw or 'pending'})."


def disconnect(cfg: Any = None) -> Tuple[bool, str]:
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return False, "nmcli not found"
    _run([nmcli, "connection", "down", PROFILE], timeout=15)
    _run([nmcli, "connection", "delete", "id", PROFILE], timeout=8)
    _run(["ip", "-4", "rule", "del", "priority", str(RULE_PRIORITY)], timeout=4)
    _run(["ip", "-4", "route", "flush", "table", str(TABLE)], timeout=4)
    return True, "USB uplink off."


def sync_source_routing(cfg: Any) -> bool:
    """Keep "from <usb ip> lookup 152" with a default route via the hotspot (root). Off: remove both."""
    enabled = bool(getattr(getattr(cfg, "usb_uplink", None), "enabled", False))
    iface = uplink_interface(cfg) if enabled else None
    ip, gw = _address_and_gateway(iface) if iface else (None, None)
    if not (iface and ip and gw):
        rc, out, _ = _run(["ip", "-4", "rule", "show", "priority", str(RULE_PRIORITY)], timeout=4)
        if out.strip():
            _run(["ip", "-4", "rule", "del", "priority", str(RULE_PRIORITY)], timeout=4)
            _run(["ip", "-4", "route", "flush", "table", str(TABLE)], timeout=4)
        return False
    _run(["ip", "-4", "route", "replace", "default", "via", gw, "dev", iface, "table", str(TABLE)], timeout=4)
    rc, out, _ = _run(["ip", "-4", "rule", "show", "priority", str(RULE_PRIORITY)], timeout=4)
    if f"from {ip} " not in out + " ":
        _run(["ip", "-4", "rule", "del", "priority", str(RULE_PRIORITY)], timeout=4)
        _run(["ip", "-4", "rule", "add", "priority", str(RULE_PRIORITY), "from", ip, "lookup", str(TABLE)], timeout=4)
        log.info("USB uplink source routing: from %s via %s dev %s (table %d)", ip, gw, iface, TABLE)
    return True


def keep_up(cfg: Any) -> None:
    """While enabled, bring the profile up when the device is plugged in again (root, nmb-netd)."""
    if not getattr(getattr(cfg, "usb_uplink", None), "enabled", False):
        return
    iface = uplink_interface(cfg)
    if not iface:
        return
    ip, _ = _address_and_gateway(iface)
    if ip:
        return
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return
    rc, out, _ = _run([nmcli, "-t", "-f", "NAME,DEVICE", "connection", "show"], timeout=6)
    if f"{PROFILE}:" not in out:
        connect(cfg)
    else:
        _run([nmcli, "connection", "up", PROFILE, "ifname", iface], timeout=45)


FALLBACK_METRIC = 900
_fallback_active: Optional[bool] = None


def _other_default_route(iface: str) -> bool:
    """A default route in the main table through anything but the USB interface."""
    rc, out, _ = _run(["ip", "-4", "route", "show", "default"], timeout=4)
    for line in out.splitlines() if rc == 0 else []:
        parts = line.split()
        if "dev" in parts and parts[parts.index("dev") + 1] != iface:
            return True
    return False


def _log_event(kind: str, detail: str) -> None:
    try:
        from nmb.db import database as db
        conn = db.connect()
        try:
            with db.tx(conn):
                conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warning', 'netd', ?, ?)",
                             (db.now_ms(), kind, detail))
        finally:
            conn.close()
    except Exception:
        log.debug("usb fallback event not written", exc_info=True)


def sync_default_fallback(cfg: Any) -> bool:
    """The USB link becomes the box's internet only when nothing else is (root, nmb-netd).

    No default route through Ethernet or Wi-Fi, USB up: a default route via the hotspot with metric 900.
    As soon as another default route is back it is removed, so the cable or Wi-Fi wins again.
    Every switch is written as an event, so reports show when the box ran on the mobile link.
    """
    global _fallback_active
    enabled = bool(getattr(getattr(cfg, "usb_uplink", None), "enabled", False))
    iface = uplink_interface(cfg) if enabled else None
    ip, gw = _address_and_gateway(iface) if iface else (None, None)
    want = bool(iface and ip and gw and not _other_default_route(iface))
    rc, out, _ = _run(["ip", "-4", "route", "show", "default", "metric", str(FALLBACK_METRIC)], timeout=4)
    have = rc == 0 and "default" in out
    if want:
        if not have or f"dev {iface}" not in out:
            _run(["ip", "-4", "route", "replace", "default", "via", gw, "dev", iface, "metric", str(FALLBACK_METRIC)], timeout=4)
    elif have:
        _run(["ip", "-4", "route", "del", "default", "metric", str(FALLBACK_METRIC)], timeout=4)
    if want != _fallback_active:
        if want:
            log.warning("no wired or Wi-Fi internet: the box now uses USB tethering on %s", iface)
            _log_event("uplink_usb_fallback", f"No wired or Wi-Fi internet: using USB tethering on {iface}")
        elif _fallback_active:
            log.info("wired or Wi-Fi internet is back: USB fallback route removed")
            _log_event("uplink_usb_fallback_end", "Wired or Wi-Fi internet is back: USB tethering is no longer the box's internet")
        _fallback_active = want
    return want


def fallback_active() -> bool:
    return bool(_fallback_active)
