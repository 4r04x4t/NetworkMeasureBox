"""Linux interface management and status querying via sysfs and iproute2.

Pure stdlib helpers for querying carrier status, MAC/IP addresses, and
manipulating links/bridges without external third-party dependencies.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.iface")

SYS_CLASS_NET = Path("/sys/class/net")


def run_cmd(cmd: List[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    log.debug("exec: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        check=check,
    )


def interface_exists(iface: str) -> bool:
    return (SYS_CLASS_NET / iface).exists()


def get_carrier(iface: str) -> bool:
    """Check physical link carrier status (/sys/class/net/<iface>/carrier)."""
    p = SYS_CLASS_NET / iface / "carrier"
    if not p.exists():
        return False
    try:
        return p.read_text().strip() == "1"
    except (OSError, ValueError):
        return False


def get_operstate(iface: str) -> str:
    p = SYS_CLASS_NET / iface / "operstate"
    if not p.exists():
        return "missing"
    try:
        return p.read_text().strip()
    except OSError:
        return "unknown"


def has_net_admin() -> bool:
    """True when the service holds CAP_NET_ADMIN, so network tools work without sudo."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("CapEff:"):
                return bool(int(line.split()[1], 16) & (1 << 12))
    except (OSError, ValueError, IndexError):
        pass
    return False


def _wrap_sudo(cmd: List[str]) -> List[str]:
    if os.geteuid() != 0 and not has_net_admin() and shutil.which("sudo"):
        return ["sudo", "-n"] + cmd
    return cmd


def get_mac_address(iface: str) -> str:
    p = SYS_CLASS_NET / iface / "address"
    if not p.exists():
        return ""
    try:
        return p.read_text().strip().lower()
    except OSError:
        return ""


def get_factory_mac_address(iface: str) -> str:
    """Retrieve permanent hardware/factory MAC address."""
    factory_file = Path(f"/etc/nmb/factory_mac_{iface}")
    if factory_file.exists():
        try:
            val = factory_file.read_text().strip().lower().replace("\\", "")
            if val:
                return val
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Try nmcli GENERAL.HWADDR
    nmcli_bin = shutil.which("nmcli")
    if nmcli_bin:
        try:
            res = run_cmd([nmcli_bin, "-g", "GENERAL.HWADDR", "dev", "show", iface], check=False)
            if res.returncode == 0 and res.stdout.strip():
                hw = res.stdout.strip().lower().replace("\\", "")
                try:
                    factory_file.parent.mkdir(parents=True, exist_ok=True)
                    factory_file.write_text(hw + "\n")
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
                return hw
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    curr = get_mac_address(iface).lower()
    if curr:
        try:
            factory_file.parent.mkdir(parents=True, exist_ok=True)
            factory_file.write_text(curr + "\n")
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    return curr


def set_mac_address(iface: str, mac: str) -> bool:
    """Set custom/cloned MAC address on interface (via NetworkManager and iproute2)."""
    import re
    cleaned = mac.strip().lower()
    if not re.match(r"^([0-9a-f]{2}[:-]){5}([0-9a-f]{2})$", cleaned):
        log.error("invalid MAC address format: %s", mac)
        return False
    normalized = cleaned.replace("-", ":")
    if not interface_exists(iface):
        log.error("interface %s does not exist", iface)
        return False

    # Ensure factory MAC is recorded before overwriting
    get_factory_mac_address(iface)

    if get_mac_address(iface).lower() == normalized:
        return True

    log.info("setting custom MAC on %s -> %s", iface, normalized)

    # 1. Update NetworkManager persistent connection property
    nmcli_bin = shutil.which("nmcli")
    con_name = ""
    if nmcli_bin:
        try:
            res = run_cmd(_wrap_sudo([nmcli_bin, "-g", "GENERAL.CONNECTION", "dev", "show", iface]), check=False)
            con_name = res.stdout.strip() if res.returncode == 0 else ""
            if con_name and con_name != "--":
                mod_cmd = _wrap_sudo([nmcli_bin, "con", "mod", con_name, "802-3-ethernet.cloned-mac-address", normalized])
                run_cmd(mod_cmd, check=False)
        except Exception as e:
            log.debug("nmcli cloned-mac exception: %s", e)

    # 2. Kernel immediate link update
    ip_bin = shutil.which("ip")
    if ip_bin:
        try:
            was_up = get_operstate(iface) == "up" or get_carrier(iface)
            if was_up:
                run_cmd(_wrap_sudo([ip_bin, "link", "set", "dev", iface, "down"]), check=False)
            run_cmd(_wrap_sudo([ip_bin, "link", "set", "dev", iface, "address", normalized]), check=False)
            if was_up:
                run_cmd(_wrap_sudo([ip_bin, "link", "set", "dev", iface, "up"]), check=False)
        except Exception as e:
            log.debug("ip link set address exception: %s", e)

    # 3. Verify and return
    return get_mac_address(iface).lower() == normalized


def reset_mac_to_factory(iface: str) -> bool:
    """Restore permanent hardware/factory MAC address."""
    factory = get_factory_mac_address(iface)
    if not factory:
        return False
    log.info("resetting %s MAC to factory hardware address %s", iface, factory)

    # 1. Clear NM cloned-mac-address
    nmcli_bin = shutil.which("nmcli")
    con_name = ""
    if nmcli_bin:
        try:
            res = run_cmd(_wrap_sudo([nmcli_bin, "-g", "GENERAL.CONNECTION", "dev", "show", iface]), check=False)
            con_name = res.stdout.strip() if res.returncode == 0 else ""
            if con_name and con_name != "--":
                mod_cmd = _wrap_sudo([nmcli_bin, "con", "mod", con_name, "802-3-ethernet.cloned-mac-address", ""])
                run_cmd(mod_cmd, check=False)
        except Exception as e:
            log.debug("nmcli reset cloned-mac exception: %s", e)

    # 2. Kernel immediate link update
    ip_bin = shutil.which("ip")
    if ip_bin:
        try:
            was_up = get_operstate(iface) == "up" or get_carrier(iface)
            if was_up:
                run_cmd(_wrap_sudo([ip_bin, "link", "set", "dev", iface, "down"]), check=False)
            run_cmd(_wrap_sudo([ip_bin, "link", "set", "dev", iface, "address", factory]), check=False)
            if was_up:
                run_cmd(_wrap_sudo([ip_bin, "link", "set", "dev", iface, "up"]), check=False)
        except Exception as e:
            log.debug("ip link set address exception: %s", e)

    # 3. Verify and return
    return get_mac_address(iface).lower() == factory.lower()


def get_ip_addresses(iface: str) -> List[str]:
    """Retrieve IPv4/IPv6 addresses assigned to an interface using ip --json."""
    if not interface_exists(iface):
        return []
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return []
    try:
        res = run_cmd([ip_bin, "-j", "addr", "show", "dev", iface], check=False)
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
        addrs = []
        for item in data:
            for addr_info in item.get("addr_info", []):
                local = addr_info.get("local")
                prefixlen = addr_info.get("prefixlen")
                if local and prefixlen:
                    addrs.append(f"{local}/{prefixlen}")
        return addrs
    except Exception as e:
        log.warning("error getting IP addresses for %s: %s", iface, e)
        return []


def set_link_up(iface: str) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin or not interface_exists(iface):
        return False
    res = run_cmd([ip_bin, "link", "set", "dev", iface, "up"], check=False)
    return res.returncode == 0


def set_link_down(iface: str) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin or not interface_exists(iface):
        return False
    res = run_cmd([ip_bin, "link", "set", "dev", iface, "down"], check=False)
    return res.returncode == 0


def flush_ip_addresses(iface: str) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin or not interface_exists(iface):
        return False
    res = run_cmd([ip_bin, "addr", "flush", "dev", iface], check=False)
    return res.returncode == 0


def add_ip_address(iface: str, ip_cidr: str) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin or not interface_exists(iface):
        return False
    res = run_cmd([ip_bin, "addr", "add", ip_cidr, "dev", iface], check=False)
    return res.returncode == 0


def setup_bridge(br_name: str, member_ifaces: List[str]) -> bool:
    """Create a passive transparent bridge between member interfaces.

    Configures:
      - stp 0 (disables spanning tree protocol to avoid upstream topology disruption)
      - forward_delay 0 (instant packet forwarding, no listening/learning delay)
      - ageing_time 30000 (standard 300s mac ageing)
    """
    ip_bin = shutil.which("ip")
    if not ip_bin:
        log.error("'ip' command not found")
        return False

    # Create bridge if not already existing
    if not interface_exists(br_name):
        log.info("creating bridge %s", br_name)
        res = run_cmd([
            ip_bin, "link", "add", "name", br_name, "type", "bridge",
            "forward_delay", "0",
            "stp_state", "0",
            "ageing_time", "30000"
        ], check=False)
        if res.returncode != 0:
            log.error("failed to create bridge %s: %s", br_name, res.stderr)
            return False

    # Bind member interfaces to bridge
    for iface in member_ifaces:
        if not interface_exists(iface):
            log.warning("member interface %s does not exist, skipping", iface)
            continue
        flush_ip_addresses(iface)
        set_link_up(iface)
        res = run_cmd([ip_bin, "link", "set", "dev", iface, "master", br_name], check=False)
        if res.returncode != 0:
            log.error("failed to attach %s to bridge %s: %s", iface, br_name, res.stderr)

    # Bring bridge up
    set_link_up(br_name)
    return True


def teardown_bridge(br_name: str, member_ifaces: List[str]) -> bool:
    """Tear down transparent bridge and release member interfaces."""
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return False

    for iface in member_ifaces:
        if interface_exists(iface):
            run_cmd([ip_bin, "link", "set", "dev", iface, "nomaster"], check=False)

    if interface_exists(br_name):
        set_link_down(br_name)
        res = run_cmd([ip_bin, "link", "delete", "dev", br_name, "type", "bridge"], check=False)
        return res.returncode == 0
    return True


def request_dhcp_lease(iface: str) -> bool:
    """Request a DHCP lease on iface using whichever client is installed."""
    for client, cmd in (
        ("dhclient", ["dhclient", "-1", "-v", iface]),
        ("udhcpc", ["udhcpc", "-i", iface, "-n", "-q"]),
        ("dhcpcd", ["dhcpcd", "-1", "-t", "10", iface]),
    ):
        if shutil.which(client):
            log.info("requesting DHCP lease on %s using %s", iface, client)
            res = run_cmd(cmd, check=False)
            if res.returncode == 0:
                return True
            log.debug("%s exited %d: %s", client, res.returncode, (res.stderr or "").strip())
    return False


def get_default_gateway_iface() -> Optional[str]:
    """Find the interface holding the default route."""
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return None
    res = run_cmd([ip_bin, "-j", "route", "show", "default"], check=False)
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            if data and len(data) > 0:
                return data[0].get("dev")
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    return None


# USB network functions of phones, mobile hotspots (e.g. Netgear Nighthawk) and cellular modems.
# They are named like Ethernet (usb0, enx<MAC>, eth1), so the name alone would let a 5G link be
# measured and stored as the wired line.
_ALWAYS_TETHER_DRIVERS = {"rndis_host", "ipheth", "qmi_wwan", "cdc_mbim", "huawei_cdc_ncm", "cdc_eem"}
_CDC_DRIVERS = {"cdc_ether", "cdc_ncm", "cdc_subset"}
# USB Ethernet dongle makers whose chips can fall back to the generic CDC drivers.
_DONGLE_VENDORS = {"0bda", "0b95", "0424", "2001", "13b1", "0fe6", "17ef"}


def usb_tether_kind(iface: str) -> Optional[str]:
    """'modem' or 'tether' for a phone, hotspot or modem on USB; None for anything else."""
    dev = SYS_CLASS_NET / iface / "device"
    try:
        uevent = (SYS_CLASS_NET / iface / "uevent").read_text()
    except OSError:
        uevent = ""
    if "DEVTYPE=wwan" in uevent:
        return "modem"
    try:
        driver = os.path.basename(os.path.realpath(dev / "driver"))
    except OSError:
        return None
    if driver in ("qmi_wwan", "cdc_mbim"):
        return "modem"
    if driver in _ALWAYS_TETHER_DRIVERS:
        return "tether"
    if driver in _CDC_DRIVERS:
        try:
            vendor = (dev.resolve().parent / "idVendor").read_text().strip().lower()
        except OSError:
            vendor = ""
        return None if vendor in _DONGLE_VENDORS else "tether"
    return None


def is_wired_interface(iface: str) -> bool:
    """Return True if interface is a wired Ethernet controller (not a USB phone, hotspot or modem)."""
    name = iface.lower()
    if name == "br-pass" or name.startswith("bond"):
        return True
    if not (name.startswith(("eth", "en", "end", "eno", "ens", "enp")) and not name.startswith(("wl", "ww", "br", "lo", "docker", "tun", "wg"))):
        return False
    return usb_tether_kind(iface) is None


def bridge_master(iface: str) -> Optional[str]:
    """Return the bridge an interface belongs to; its addresses live on the bridge."""
    master = SYS_CLASS_NET / iface / "master"
    return master.resolve().name if master.exists() and (SYS_CLASS_NET / iface / "brport").exists() else None


def find_active_wired_interface() -> Optional[Tuple[str, str]]:
    """Check if an Ethernet cable is physically connected with carrier and IP.

    Returns (interface_name, bound_ip) if active wired connection is found, else None.
    """
    if not SYS_CLASS_NET.exists():
        return None

    try:
        from nmb.netd.wifi_share import shared_lan_interface
        shared = shared_lan_interface()   # the box is the router there: no uplink
    except Exception:
        shared = None
    wired_candidates = []
    for ifp in SYS_CLASS_NET.iterdir():
        name = ifp.name
        if name == shared:
            continue
        if is_wired_interface(name) and get_carrier(name):
            oper = get_operstate(name)
            if oper != "down":
                if bridge_master(name):
                    continue
                addrs = [a for a in get_ip_addresses(name) if not a.lower().startswith("fe80:")]
                if addrs:
                    ip_only = addrs[0].split("/")[0]
                    wired_candidates.append((name, ip_only))

    if wired_candidates:
        wired_candidates.sort(key=lambda x: (0 if "0" in x[0] else 1, x[0]))
        return wired_candidates[0]
    return None


def _usable_address(iface: str) -> Optional[str]:
    """The address a test can bind to on iface: IPv4 first, else a global IPv6; never link-local."""
    addrs = [a.split("/")[0] for a in get_ip_addresses(iface)]
    v4 = [a for a in addrs if ":" not in a]
    v6 = [a for a in addrs if ":" in a and not a.lower().startswith("fe80")]
    return (v4 or v6 or [None])[0]


def router_wan_interface(state_file: Path = Path("/run/nmb/netd_state.json")) -> Optional[str]:
    """In router mode, the WAN nmb-netd routes through (from its state file); None in the other modes."""
    try:
        st = json.loads(state_file.read_text())
    except (OSError, ValueError):
        return None
    if st.get("active_mode") != "mode_a":
        return None
    # The name even while it is missing (ppp0 between two dials): callers must not fall back to another line.
    return (st.get("details") or {}).get("wan_interface") or None


def find_preferred_measurement_interface(cfg: Optional[Any] = None, target_iface: Optional[str] = None) -> Tuple[str, Optional[str], bool]:
    """Resolve optimal measurement interface, strictly prioritizing active wired Ethernet connections.

    Returns (interface_name, bound_ip, is_wired).
    """
    # 1. If explicit interface was requested by caller and exists
    if target_iface and interface_exists(target_iface):
        addrs = get_ip_addresses(target_iface)
        ip = addrs[0].split("/")[0] if addrs else None
        return target_iface, ip, is_wired_interface(target_iface)

    # 1b. [network] measurement_link: "ethernet" or "wifi" pins the link; "auto" goes on below.
    link = getattr(getattr(cfg, "network", None), "measurement_link", "auto") if cfg is not None else "auto"
    if link == "wifi":
        from nmb.netd.wifi_uplink import uplink_interface
        wl = uplink_interface(cfg)
        if wl and interface_exists(wl):
            addrs = get_ip_addresses(wl)
            ip = addrs[0].split("/")[0] if addrs else None
            log.info("measurement link set to Wi-Fi: using %s (ip=%s)", wl, ip)
            return wl, ip, False
        log.warning("measurement link set to Wi-Fi, but no wireless interface is up")
        return wl or "wlan0", None, False
    if link == "usb":
        from nmb.netd.usb_uplink import uplink_interface as usb_iface
        ui = usb_iface(cfg)
        if ui and interface_exists(ui):
            addrs = [a for a in get_ip_addresses(ui) if ":" not in a.split("/")[0]]
            ip = addrs[0].split("/")[0] if addrs else None
            log.info("measurement link set to USB: using %s (ip=%s)", ui, ip)
            return ui, ip, False
        log.warning("measurement link set to USB, but no phone, hotspot or modem is up on USB")
        return ui or "usb0", None, False
    if link == "ethernet":
        wired = find_active_wired_interface()
        if wired:
            return wired[0], wired[1], True
        wan = getattr(cfg.network, "wan_interface", "eth0") or "eth0"
        log.warning("measurement link set to Ethernet, but no cable with an address is connected")
        return wan, None, True

    # 1c. Router mode: the line is the router's WAN (ppp0 on PPPoE, the hotspot on USB), not the cable that
    # carries PPPoE. 2026-11-09: tests bound to eth0, which had only a link-local address, and failed.
    rw = router_wan_interface()
    if rw:
        ip = _usable_address(rw)
        if ip:
            return rw, ip, is_wired_interface(rw)

    # 2. STRICT WIRED PRIORITY: If a cable is plugged in with carrier & IP
    wired = find_active_wired_interface()
    if wired:
        w_iface, w_ip = wired
        log.info("physical Ethernet cable detected on %s (carrier=1, ip=%s); prioritizing wired connection for benchmark", w_iface, w_ip)
        return w_iface, w_ip, True

    # 3. Check configured measurement_interface or wan_interface
    if cfg is not None:
        meas_target = getattr(cfg.network, "measurement_interface", "wan")
        if meas_target in ("wan2", "secondary") and getattr(cfg.network, "wan2_interface", ""):
            cand = cfg.network.wan2_interface
            if interface_exists(cand):
                addrs = get_ip_addresses(cand)
                ip = addrs[0].split("/")[0] if addrs else None
                return cand, ip, is_wired_interface(cand)

        wan = getattr(cfg.network, "wan_interface", "eth0")
        wan = bridge_master(wan) or wan
        if wan and interface_exists(wan):
            ip = _usable_address(wan)   # a link-local IPv6 address cannot carry a test
            # Without an address the WAN port cannot carry a test; fall through to the link that has the
            # default route (Wi-Fi, or the USB tethering fallback), so "auto" really measures that link.
            if ip or not get_default_gateway_iface():
                return wan, ip, is_wired_interface(wan)

    # 4. Fallback to default gateway interface
    gw_iface = get_default_gateway_iface()
    if gw_iface and interface_exists(gw_iface):
        addrs = get_ip_addresses(gw_iface)
        ip = addrs[0].split("/")[0] if addrs else None
        return gw_iface, ip, is_wired_interface(gw_iface)

    return "eth0", None, True


WIRED_ROUTE_METRIC = "50"


def _wired_metric_via_network_manager(iface: str) -> Optional[bool]:
    """Metric 50 in the NetworkManager profile of iface (None when NetworkManager does not run iface).

    A route added with `ip route` outside NetworkManager stayed after the cable moved from the router to a laptop
    (2026-11-08) and beat Wi-Fi and USB; NetworkManager installs its own route and takes it away with the cable.
    An old route of ours (proto boot) is removed. True when something changed."""
    if not shutil.which("nmcli"):
        return None
    name = (subprocess.run(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", iface],
                           capture_output=True, text=True, check=False).stdout or "").strip()
    if not name or name == "--":
        return None
    changed = False
    cur = (subprocess.run(["nmcli", "-g", "ipv4.route-metric", "connection", "show", name],
                          capture_output=True, text=True, check=False).stdout or "").strip()
    if cur != WIRED_ROUTE_METRIC:
        res = subprocess.run(["nmcli", "connection", "modify", name, "ipv4.route-metric", WIRED_ROUTE_METRIC],
                             capture_output=True, text=True, check=False)
        if res.returncode == 0:
            subprocess.run(["nmcli", "device", "reapply", iface], capture_output=True, text=True, check=False)
            log.info("wired route priority: metric %s set in the NetworkManager profile %s", WIRED_ROUTE_METRIC, name)
            changed = True
        else:
            log.debug("nmcli could not set the route metric on %s: %s", name, res.stderr.strip())
    out = subprocess.run(["ip", "-4", "route", "show", "default", "dev", iface, "proto", "boot"],
                         capture_output=True, text=True, check=False).stdout or ""
    for line in out.splitlines():
        parts = line.split()          # "default via 192.168.8.1 metric 50" (dev left out by the filter)
        if "dev" not in parts:
            parts += ["dev", iface]
        subprocess.run(["ip", "-4", "route", "del"] + parts, capture_output=True, check=False)
        log.info("removed the old wired default route outside NetworkManager on %s", iface)
        changed = True
    return changed


def enforce_wired_default_route_priority() -> bool:
    """Ensure Linux kernel default route priority strictly favors wired Ethernet over Wi-Fi.

    If an active wired interface (carrier=1, operstate!=down) has an IP, lowers its
    route metric to 50 so all OS traffic and un-bound sockets naturally egress via cable.
    """
    wired = find_active_wired_interface()
    if not wired:
        return False

    w_iface, _ = wired
    nm = _wired_metric_via_network_manager(w_iface)
    if nm is not None:
        return nm
    try:
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, check=False)
        lines = res.stdout.strip().splitlines()
        wired_gw = None
        needs_metric_bump = False

        for line in lines:
            parts = line.split()
            if "dev" in parts and "via" in parts:
                dev_idx = parts.index("dev") + 1
                via_idx = parts.index("via") + 1
                if dev_idx < len(parts) and via_idx < len(parts):
                    dev_name = parts[dev_idx]
                    gw_ip = parts[via_idx]
                    metric = 0
                    if "metric" in parts:
                        m_idx = parts.index("metric") + 1
                        if m_idx < len(parts) and parts[m_idx].isdigit():
                            metric = int(parts[m_idx])

                    if dev_name == w_iface:
                        wired_gw = gw_ip
                        if metric > 50:
                            needs_metric_bump = True

        if wired_gw and needs_metric_bump:
            subprocess.run(
                ["ip", "route", "replace", "default", "via", wired_gw, "dev", w_iface, "metric", "50"],
                check=False,
                capture_output=True
            )
            log.info("adjusted wired route priority: dev %s default route metric set to 50", w_iface)
            return True
    except Exception as e:
        log.debug("enforce_wired_default_route_priority error: %s", e)
    return False


def get_interface_stats(iface: str) -> Dict[str, int]:
    """Query interface bytes/packets stats from sysfs."""
    stats_dir = SYS_CLASS_NET / iface / "statistics"
    if not stats_dir.exists():
        return {"rx_bytes": 0, "tx_bytes": 0, "rx_packets": 0, "tx_packets": 0}
    try:
        rx_b = int((stats_dir / "rx_bytes").read_text().strip())
        tx_b = int((stats_dir / "tx_bytes").read_text().strip())
        rx_p = int((stats_dir / "rx_packets").read_text().strip())
        tx_p = int((stats_dir / "tx_packets").read_text().strip())
        return {"rx_bytes": rx_b, "tx_bytes": tx_b, "rx_packets": rx_p, "tx_packets": tx_p}
    except Exception:
        log.debug("suppressed exception", exc_info=True)
        return {"rx_bytes": rx_b, "tx_bytes": tx_b, "rx_packets": rx_p, "tx_packets": tx_p}
    except Exception:
        log.debug("suppressed exception", exc_info=True)
        return {"rx_bytes": 0, "tx_bytes": 0, "rx_packets": 0, "tx_packets": 0}


_cached_dual_stack_ips: Dict[str, Optional[str]] = {}
_cached_dual_stack_ts: float = 0.0
_dual_stack_lock = threading.Lock()
_dual_stack_bg_thread: Optional[threading.Thread] = None


def _bg_resolve_external_ips(iface: Optional[str] = None) -> None:
    """Resolve external public IPv4/IPv6 asynchronously without blocking HTTP requests."""
    global _cached_dual_stack_ips, _cached_dual_stack_ts
    import ipaddress
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_endpoint(urls: tuple[str, ...]) -> Optional[str]:
        for u in urls:
            try:
                from nmb.common.user_agent import get_effective_user_agent
                req = urllib.request.Request(u, headers={"User-Agent": get_effective_user_agent()})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    val = resp.read().decode("utf-8").strip()
                    if val:
                        ipaddress.ip_address(val)
                        return val
            except Exception:
                log.debug("suppressed exception", exc_info=True)
                continue
        return None

    v4_urls = ("https://api4.ipify.org", "https://ipv4.icanhazip.com", "https://v4.ident.me")
    v6_urls = ("https://api6.ipify.org", "https://ipv6.icanhazip.com", "https://v6.ident.me")

    pub_v4 = None
    pub_v6 = None
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_v4 = executor.submit(_fetch_endpoint, v4_urls)
            fut_v6 = executor.submit(_fetch_endpoint, v6_urls)
            pub_v4 = fut_v4.result(timeout=3.0)
            pub_v6 = fut_v6.result(timeout=3.0)
    except Exception as e:
        log.debug("async dual-stack fetch exception: %s", e)

    with _dual_stack_lock:
        if _cached_dual_stack_ips:
            res = dict(_cached_dual_stack_ips)
            if pub_v4:
                res["public_ipv4"] = pub_v4
                res["ipv4"] = pub_v4
            if pub_v6:
                res["public_ipv6"] = pub_v6
                res["ipv6"] = pub_v6
            best_v4 = res.get("ipv4") or res.get("local_ipv4")
            best_v6 = res.get("ipv6") or res.get("local_ipv6")
            if best_v4 and best_v6:
                res["display"] = f"IPv4: {best_v4} | IPv6: {best_v6}"
            elif best_v4:
                res["display"] = f"IPv4: {best_v4}"
            elif best_v6:
                res["display"] = f"IPv6: {best_v6}"
            _cached_dual_stack_ips = res
            _cached_dual_stack_ts = time.time()


def get_dual_stack_ips(iface: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Optional[str]]:
    """Dynamically determine both IPv4 and IPv6 public and local addresses (non-blocking)."""
    global _cached_dual_stack_ips, _cached_dual_stack_ts, _dual_stack_bg_thread
    import ipaddress

    now = time.time()
    with _dual_stack_lock:
        if not force_refresh and _cached_dual_stack_ips:
            if now - _cached_dual_stack_ts > 180.0:
                if not (_dual_stack_bg_thread and _dual_stack_bg_thread.is_alive()):
                    _dual_stack_bg_thread = threading.Thread(
                        target=_bg_resolve_external_ips,
                        args=(iface,),
                        daemon=True,
                        name="nmb-dual-stack-bg"
                    )
                    _dual_stack_bg_thread.start()
            return dict(_cached_dual_stack_ips)

    local_ipv4: Optional[str] = None
    local_ipv6: Optional[str] = None

    target_iface = iface or get_default_gateway_iface() or "eth0"
    candidate_ifaces = [target_iface] if target_iface else []
    for extra in ("eth0", "wlan0", "eth1", "br0"):
        if extra not in candidate_ifaces and interface_exists(extra):
            candidate_ifaces.append(extra)

    for ifn in candidate_ifaces:
        for a in get_ip_addresses(ifn):
            raw_ip = a.split("/")[0].strip()
            try:
                ip_obj = ipaddress.ip_address(raw_ip)
                if ip_obj.version == 4 and not ip_obj.is_loopback:
                    if not local_ipv4 or (ip_obj.is_global and not ip_obj.is_private):
                        local_ipv4 = str(ip_obj)
                elif ip_obj.version == 6 and not ip_obj.is_loopback and not ip_obj.is_link_local:
                    if ip_obj.is_global and not ip_obj.is_private:
                        local_ipv6 = str(ip_obj)
            except ValueError:
                pass

    best_v4 = local_ipv4
    best_v6 = local_ipv6
    if best_v4 and best_v6:
        display = f"IPv4: {best_v4} | IPv6: {best_v6}"
    elif best_v4:
        display = f"IPv4: {best_v4}"
    elif best_v6:
        display = f"IPv6: {best_v6}"
    else:
        display = "--"

    res = {
        "ipv4": best_v4,
        "ipv6": best_v6,
        "public_ipv4": best_v4 if (best_v4 and not ipaddress.ip_address(best_v4).is_private) else None,
        "public_ipv6": best_v6 if (best_v6 and ipaddress.ip_address(best_v6).is_global) else None,
        "local_ipv4": local_ipv4,
        "local_ipv6": local_ipv6,
        "display": display,
    }

    with _dual_stack_lock:
        _cached_dual_stack_ips = res
        _cached_dual_stack_ts = now

    if not (_dual_stack_bg_thread and _dual_stack_bg_thread.is_alive()):
        _dual_stack_bg_thread = threading.Thread(
            target=_bg_resolve_external_ips,
            args=(iface,),
            daemon=True,
            name="nmb-dual-stack-bg"
        )
        _dual_stack_bg_thread.start()

    return res

    with _dual_stack_lock:
        _cached_dual_stack_ips = dict(res)
        _cached_dual_stack_ts = time.time()

    return res


def get_public_ip(iface: Optional[str] = None) -> Optional[str]:
    """Dynamically determine public IP address (returns dual-stack display or primary IP)."""
    ips = get_dual_stack_ips(iface)
    return ips.get("display") or ips.get("ipv4") or ips.get("ipv6")


def get_default_gateway(iface: Optional[str] = None) -> Optional[str]:
    """Find default gateway IP (via ip route show default)."""
    ip_bin = shutil.which("ip") or "/usr/bin/ip"
    if not os.path.exists(ip_bin):
        return None
    cmd = [ip_bin, "-j", "route", "show", "default"]
    if iface:
        cmd.extend(["dev", iface])
    res = run_cmd(cmd, check=False)
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            if data and isinstance(data, list):
                for entry in data:
                    gw = entry.get("gateway")
                    if gw:
                        return gw
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Fallback to text parsing: ip route show default
    cmd2 = [ip_bin, "route", "show", "default"]
    if iface:
        cmd2.extend(["dev", iface])
    res2 = run_cmd(cmd2, check=False)
    if res2.returncode == 0:
        for line in res2.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
                return parts[2]
    return None


def get_isp_first_hop(target: str = "1.1.1.1", timeout_sec: int = 4) -> Optional[str]:
    """Discover ISP first hop / WAN gateway via low-hop traceroute or MTR.
    
    If behind a NAT router, Hop 1 is the local router, and Hop 2 is the ISP gateway.
    If directly connected to WAN (PPPoE/direct IP), Hop 1 is the ISP gateway.
    """
    import ipaddress
    import re
    local_gw = get_default_gateway()

    tr_bin = shutil.which("traceroute")
    if tr_bin:
        try:
            r = subprocess.run(
                [tr_bin, "-n", "-m", "4", "-q", "1", "-w", "1", "--", target],
                capture_output=True, text=True, timeout=timeout_sec, check=False
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0].isdigit():
                        hop_num = int(parts[0])
                        hop_ip = parts[1]
                        if hop_ip == "*":
                            continue
                        try:
                            ipaddress.ip_address(hop_ip)
                        except ValueError:
                            continue
                        if hop_num == 1 and local_gw and hop_ip != local_gw:
                            return hop_ip
                        if hop_num == 2 and hop_ip != local_gw:
                            return hop_ip
                        if hop_num == 1 and not local_gw:
                            return hop_ip
        except Exception as e:
            log.debug("traceroute isp first hop exception: %s", e)

    mtr_bin = shutil.which("mtr") or "/usr/bin/mtr"
    if os.path.exists(mtr_bin):
        try:
            r = subprocess.run(
                [mtr_bin, "-r", "-n", "-c", "2", "-w", "--", target],
                capture_output=True, text=True, timeout=timeout_sec, check=False
            )
            for line in r.stdout.splitlines():
                m = re.search(r"^\s*([0-9]+)\.\|--\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", line)
                if m:
                    hop_idx = int(m.group(1))
                    ip_str = m.group(2)
                    if hop_idx == 1 and local_gw and ip_str != local_gw:
                        return ip_str
                    if hop_idx == 2 and ip_str != local_gw:
                        return ip_str
                    if hop_idx == 1 and not local_gw:
                        return ip_str
        except Exception as e:
            log.debug("mtr isp first hop exception: %s", e)

    return None


def ppp_peer_addresses() -> List[str]:
    """The peer addresses of PPP links ("peer 10.0.0.1/32"): an ISP's PPPoE concentrator often uses one
    placeholder for every customer and does not answer pings on it (DIGI, 2026-11-09)."""
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return []
    res = run_cmd([ip_bin, "-4", "-o", "addr", "show"], check=False)
    return re.findall(r"\bpeer ([0-9.]+)", getattr(res, "stdout", "") or "")


PPP_PEER_MEMORY_DAYS = 90
SILENT_HOP_MIN_SENT = 2000


def first_hop_never_answers(conn, addr: str, now_ms: Optional[int] = None) -> bool:
    """True when addr, pinged as a target, answered none of at least SILENT_HOP_MIN_SENT pings in 24 h."""
    try:
        import time as _time
        now = now_ms or int(_time.time() * 1000)
        row = conn.execute(
            "SELECT SUM(m.sent), SUM(m.sent - m.lost) FROM ping_minute m JOIN target t ON t.id = m.target_id "
            "WHERE t.addr = ? AND m.ts >= ?", (addr, now - 86_400_000)).fetchone()
        sent, answered = (row[0] or 0, row[1] or 0) if row else (0, 0)
        return sent >= SILENT_HOP_MIN_SENT and answered == 0
    except Exception:
        return False


def known_ppp_peers(conn=None) -> List[str]:
    """PPP peer addresses seen now, plus those remembered from when this box dialled PPPoE itself.

    Behind another router that dials (standalone mode), the same ISP placeholder (10.0.0.1 on one ISP)
    shows up as hop 2 in a traceroute; it is neither an ISP router that answers pings nor a sign of
    double NAT (2026-11-10: the diagnostic bundle said "Double NAT" and the probe pinged it at 100 % loss).
    """
    peers = set(ppp_peer_addresses())
    if conn is None:
        return sorted(peers)
    try:
        import json as _json
        import time as _time
        now = int(_time.time() * 1000)
        row = conn.execute("SELECT v FROM kv WHERE k = 'ppp_peers_seen'").fetchone()
        seen = _json.loads(row[0]) if row and row[0] else {}
        if not isinstance(seen, dict):
            seen = {}
        if peers:
            for p in peers:
                seen[p] = now
            try:
                conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('ppp_peers_seen', ?, ?)", (_json.dumps(seen), now))
            except Exception:
                log.debug("PPP peers not remembered (read-only connection)", exc_info=True)
        horizon = now - PPP_PEER_MEMORY_DAYS * 86_400_000
        peers |= {p for p, ts in seen.items() if isinstance(ts, (int, float)) and ts >= horizon}
    except Exception:
        log.debug("remembered PPP peers not available", exc_info=True)
    return sorted(peers)


def sync_gateway_ping_targets(conn, iface: Optional[str] = None, isp_first_hop: bool = True) -> None:
    """Enroll and maintain Local Gateway and ISP First Hop in the ping probe targets table.
    
    Dynamically identifies:
      1. Local Default Gateway (e.g. 192.168.1.1) -> Role: 'Local Gateway'
      2. ISP First Hop / WAN Gateway (e.g. 10.0.0.1) -> Role: 'ISP First Hop'

    A target that does not fit the line any more is switched off, not left to pile up lost pings: the Local
    Gateway when the box has none (PPPoE: the default route has no gateway), the ISP First Hop when it is the
    PPP peer placeholder or when `[probe] isp_first_hop = false`.
    """
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(target)")
        cols = {row[1] for row in cur.fetchall()}
        if "role" not in cols:
            cur.execute("ALTER TABLE target ADD COLUMN role TEXT DEFAULT 'Public DNS'")

        local_gw = get_default_gateway(iface)
        isp_hop = get_isp_first_hop() if isp_first_hop else None
        peers = set(known_ppp_peers(conn))
        if isp_hop in peers:
            isp_hop = None
        if isp_hop and first_hop_never_answers(conn, isp_hop):
            # Pinging a hop that has answered none of thousands of pings only adds made-up "loss"
            # (2026-11-10: 100 % loss to the ISP's placeholder for a whole day in the reports).
            log.info("ISP first hop %s answered no ping in 24 h; not pinged as a target", isp_hop)
            isp_hop = None
            silent_hop = True
        else:
            silent_hop = False
        if not isp_first_hop or (not isp_hop and (peers or silent_hop)):
            cur.execute("UPDATE target SET enabled = 0 WHERE role = 'ISP First Hop'")
        if not local_gw:
            cur.execute("UPDATE target SET enabled = 0 WHERE role = 'Local Gateway'")

        # Update existing null roles to 'Public DNS'
        cur.execute("UPDATE target SET role = 'Public DNS' WHERE role IS NULL")

        if local_gw:
            cur.execute("SELECT id, addr FROM target WHERE role = 'Local Gateway'")
            row = cur.fetchone()
            if row:
                if row["addr"] != local_gw:
                    log.info("updating Local Gateway target address: %s -> %s", row["addr"], local_gw)
                cur.execute("UPDATE target SET addr = ?, enabled = 1 WHERE id = ?", (local_gw, row["id"]))
            else:
                cur.execute("SELECT id FROM target WHERE addr = ?", (local_gw,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("UPDATE target SET label = 'Local Gateway', role = 'Local Gateway', enabled = 1 WHERE id = ?", (existing["id"],))
                else:
                    log.info("enrolling Local Gateway ping target: %s", local_gw)
                    cur.execute("INSERT INTO target (addr, label, enabled, role) VALUES (?, 'Local Gateway', 1, 'Local Gateway')", (local_gw,))

        if isp_hop:
            cur.execute("SELECT id, addr FROM target WHERE role = 'ISP First Hop'")
            row = cur.fetchone()
            if row:
                if row["addr"] != isp_hop:
                    log.info("updating ISP First Hop target address: %s -> %s", row["addr"], isp_hop)
                cur.execute("UPDATE target SET addr = ?, enabled = 1 WHERE id = ?", (isp_hop, row["id"]))
            else:
                cur.execute("SELECT id FROM target WHERE addr = ?", (isp_hop,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("UPDATE target SET label = 'ISP First Hop', role = 'ISP First Hop', enabled = 1 WHERE id = ?", (existing["id"],))
                else:
                    log.info("enrolling ISP First Hop ping target: %s", isp_hop)
                    cur.execute("INSERT INTO target (addr, label, enabled, role) VALUES (?, 'ISP First Hop', 1, 'ISP First Hop')", (isp_hop,))

    except Exception as e:
        log.warning("sync_gateway_ping_targets exception: %s", e)





def dead_default_routes(route_lines: str, has_ipv4: Callable[[str], bool]) -> List[List[str]]:
    """Default routes (with a gateway) through a link that is down or has no IPv4 address.

    2026-11-08: a static default route on eth0 (metric 50) stayed after the cable moved from the router to a
    laptop. eth0 had a carrier but no address, the gateway was gone, and the route still beat Wi-Fi and USB,
    so the box lost its internet and Tailscale.
    """
    dead = []
    for line in route_lines.splitlines():
        parts = line.split()
        if not parts or parts[0] != "default" or "via" not in parts or "dev" not in parts:
            continue
        dev = parts[parts.index("dev") + 1]
        if "linkdown" in parts or "dead" in parts or not has_ipv4(dev):
            dead.append(parts)
    return dead


def route_delete_args(parts: List[str]) -> List[str]:
    """The selector of a route for `ip route del`: flags such as `dead` or `linkdown` make it fail."""
    out = ["default"]
    for key in ("via", "dev", "proto", "metric", "table"):
        if key in parts and parts.index(key) + 1 < len(parts):
            out += [key, parts[parts.index(key) + 1]]
    return out


def reap_dead_default_routes() -> List[str]:
    """Remove dead default routes from the main table (root, nmb-netd loop). Returns the devices."""
    res = run_cmd(["ip", "-4", "route", "show", "default"], check=False)
    gone = []
    for parts in dead_default_routes(getattr(res, "stdout", "") or "",
                                     lambda d: any(":" not in a for a in get_ip_addresses(d))):
        res = run_cmd(["ip", "-4", "route", "del"] + route_delete_args(parts), check=False)
        dev = parts[parts.index("dev") + 1]
        if getattr(res, "returncode", 1) == 0:
            log.warning("removed a dead default route through %s (%s): no link or no address", dev, " ".join(parts))
            gone.append(dev)
        else:
            log.warning("could not remove the dead default route through %s (%s): %s", dev, " ".join(parts),
                        (getattr(res, "stderr", "") or "").strip()[:120])
    return gone


IPV4_DNS_PRIORITY = "50"


def prefer_ipv4_dns(run: Optional[Callable[..., Any]] = None) -> List[str]:
    """Put the IPv4 DNS servers before the IPv6 ones on the box's own wired and Wi-Fi profiles.

    NetworkManager writes at most three nameservers. 2026-11-09: the home router started to hand out three
    IPv6 DNS servers while the line had no IPv6 route; they pushed the router's IPv4 DNS out of
    resolv.conf and every lookup failed. Returns the profiles changed.
    """
    run = run or (lambda cmd: run_cmd(cmd, check=False))
    if not shutil.which("nmcli"):
        return []
    res = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    changed = []
    for line in (getattr(res, "stdout", "") or "").splitlines():
        parts = line.replace("\\:", "\x00").split(":")
        if len(parts) < 3:
            continue
        name, ctype, dev = (p.replace("\x00", ":") for p in parts[:3])
        if ctype not in ("802-3-ethernet", "802-11-wireless") or not dev:
            continue
        cur = (getattr(run(["nmcli", "-g", "ipv4.dns-priority", "connection", "show", name]), "stdout", "") or "").strip()
        if cur == IPV4_DNS_PRIORITY:
            continue
        run(["nmcli", "connection", "modify", name, "ipv4.dns-priority", IPV4_DNS_PRIORITY])
        run(["nmcli", "device", "reapply", dev])
        log.info("IPv4 DNS now before IPv6 DNS on %s (%s)", name, dev)
        changed.append(name)
    return changed


def accept_ra_with_forwarding(iface: str) -> bool:
    """Let iface learn its IPv6 address and default route from router adverts although the box forwards.

    With forwarding on (router mode, the VPN servers) the kernel ignores router adverts unless accept_ra
    is 2: on the first real PPPoE line (2026-11-09) ppp0 got no IPv6 although the ISP advertises it.
    True when the setting had to be changed.
    """
    path = Path(f"/proc/sys/net/ipv6/conf/{iface}/accept_ra")
    try:
        if path.read_text().strip() == "2":
            return False
        path.write_text("2")
        return True
    except OSError:
        return False


def send_router_solicitation(iface: str) -> bool:
    """Ask the routers on iface for an advert now (ICMPv6 type 133 to ff02::2), instead of waiting for one."""
    import socket
    import struct
    try:
        idx = socket.if_nametoindex(iface)
        s = socket.socket(socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6)
    except OSError:
        return False
    try:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, idx)
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 255)
        s.sendto(struct.pack("!BBHI", 133, 0, 0, 0), ("ff02::2", 0, 0, idx))   # the kernel fills the checksum
        return True
    except OSError:
        return False
    finally:
        s.close()
