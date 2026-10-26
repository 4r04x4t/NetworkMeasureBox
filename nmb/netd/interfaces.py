"""Linux interface management and status querying via sysfs and iproute2.

Pure stdlib helpers for querying carrier status, MAC/IP addresses, and
manipulating links/bridges without external third-party dependencies.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

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


def _wrap_sudo(cmd: List[str]) -> List[str]:
    if os.geteuid() != 0 and shutil.which("sudo"):
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
            pass

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
                    pass
                return hw
        except Exception:
            pass

    curr = get_mac_address(iface).lower()
    if curr:
        try:
            factory_file.parent.mkdir(parents=True, exist_ok=True)
            factory_file.write_text(curr + "\n")
        except Exception:
            pass
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
            pass
    return None


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
        return {"rx_bytes": rx_b, "tx_bytes": tx_b, "rx_packets": rx_p, "tx_packets": tx_p}
    except Exception:
        return {"rx_bytes": 0, "tx_bytes": 0, "rx_packets": 0, "tx_packets": 0}


_cached_dual_stack_ips: Dict[str, Optional[str]] = {}
_cached_dual_stack_ts: float = 0.0
_dual_stack_lock = threading.Lock()


def get_dual_stack_ips(iface: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Optional[str]]:
    """Dynamically determine both IPv4 and IPv6 public and local addresses.

    Returns dict with keys:
      - 'ipv4': best public/WAN IPv4 address
      - 'ipv6': best public/global IPv6 address
      - 'public_ipv4': externally resolved public IPv4
      - 'public_ipv6': externally resolved or global IPv6
      - 'local_ipv4': interface IPv4 (e.g. LAN/DHCP WAN)
      - 'local_ipv6': interface global IPv6
      - 'display': human-readable dual-stack string (e.g. 'IPv4: 203.0.113.195 | IPv6: 2001:db8::1')
    """
    global _cached_dual_stack_ips, _cached_dual_stack_ts
    import ipaddress
    import urllib.request

    now = time.time()
    with _dual_stack_lock:
        if not force_refresh and _cached_dual_stack_ips and (now - _cached_dual_stack_ts < 60.0):
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

    def _fetch_endpoint(urls: tuple[str, ...]) -> Optional[str]:
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "NetworkMeasureBox/1.0"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    val = resp.read().decode("utf-8").strip()
                    if val:
                        ipaddress.ip_address(val)
                        return val
            except Exception:
                continue
        return None

    public_ipv4: Optional[str] = None
    public_ipv6: Optional[str] = None

    v4_urls = ("https://api4.ipify.org", "https://ipv4.icanhazip.com", "https://v4.ident.me")
    v6_urls = ("https://api6.ipify.org", "https://ipv6.icanhazip.com", "https://v6.ident.me")

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_v4 = executor.submit(_fetch_endpoint, v4_urls)
            fut_v6 = executor.submit(_fetch_endpoint, v6_urls)
            public_ipv4 = fut_v4.result(timeout=2.5)
            public_ipv6 = fut_v6.result(timeout=2.5)
    except Exception as e:
        log.debug("dual-stack fetch exception: %s", e)

    # Global IPv6 on an interface is public and globally routable
    if not public_ipv6 and local_ipv6:
        try:
            if ipaddress.ip_address(local_ipv6).is_global:
                public_ipv6 = local_ipv6
        except Exception:
            pass

    # Public IPv4 fallback if interface has a direct global IP (e.g. PPPoE or static)
    if not public_ipv4 and local_ipv4:
        try:
            if ipaddress.ip_address(local_ipv4).is_global and not ipaddress.ip_address(local_ipv4).is_private:
                public_ipv4 = local_ipv4
        except Exception:
            pass

    best_v4 = public_ipv4 or local_ipv4
    best_v6 = public_ipv6 or local_ipv6

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
        "public_ipv4": public_ipv4,
        "public_ipv6": public_ipv6,
        "local_ipv4": local_ipv4,
        "local_ipv6": local_ipv6,
        "display": display,
    }

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
            pass

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


def sync_gateway_ping_targets(conn, iface: Optional[str] = None) -> None:
    """Enroll and maintain Local Gateway and ISP First Hop in the ping probe targets table.
    
    Dynamically identifies:
      1. Local Default Gateway (e.g. 192.168.1.1) -> Role: 'Local Gateway'
      2. ISP First Hop / WAN Gateway (e.g. 10.0.0.1) -> Role: 'ISP First Hop'
    """
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(target)")
        cols = {row[1] for row in cur.fetchall()}
        if "role" not in cols:
            cur.execute("ALTER TABLE target ADD COLUMN role TEXT DEFAULT 'Public DNS'")

        local_gw = get_default_gateway(iface)
        isp_hop = get_isp_first_hop()

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



