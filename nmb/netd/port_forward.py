"""Port forwarding in router mode (Mode A): rules the owner sets, and UPnP IGD / NAT-PMP / PCP for LAN devices.

Both can be switched on and off on their own (Web UI > Router > Port forwarding, or `[port_forward]` in
nmb.conf). They only act in router mode: in the other modes the box is not the LAN's router.

Rules: `[port_forward] rules` holds a JSON list, one object per rule:
    {"name": "nas", "proto": "tcp", "ext": "8443", "ip": "192.168.100.20", "port": 443, "on": true}
  proto  tcp, udp or both
  ext    the port on the WAN (internet) side, or a range "6881-6889" (then the LAN ports are the same)
  ip     the LAN device (inside the router's LAN subnet, not the box itself)
  port   the port on the device; 0 or missing means the same as ext
  on     a rule can be kept but switched off

UPnP / NAT-PMP / PCP (miniupnpd, nftables): only LAN devices may ask, only for themselves and only for
ports 1024-65535 (secure mode); everything it opens is removed when router mode stops. Off by default,
since any program on any LAN device can open a port with it.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.port_forward")

UPNP_TABLE = "nmb_upnp"
PROTOS = ("tcp", "udp", "both")
MAX_RULES = 64
MAX_RANGE = 1000
_NAME = re.compile(r"^[\w .:+-]{0,32}$")


class RuleError(ValueError):
    pass


def _ports(text: Any) -> Tuple[int, int]:
    s = str(text if text is not None else "").strip()
    m = re.fullmatch(r"(\d{1,5})(?:\s*-\s*(\d{1,5}))?", s)
    if not m:
        raise RuleError(f"port '{s}' is not a number or a range like 6881-6889")
    a = int(m.group(1))
    b = int(m.group(2) or a)
    if not (1 <= a <= 65535 and 1 <= b <= 65535) or b < a:
        raise RuleError(f"port '{s}' must be 1-65535 (a range low-high)")
    if b - a + 1 > MAX_RANGE:
        raise RuleError(f"range '{s}' is longer than {MAX_RANGE} ports")
    return a, b


def lan_network(gateway_ip: str, netmask: str) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(f"{gateway_ip}/{netmask or '255.255.255.0'}", strict=False)


def clean_rule(raw: Dict[str, Any], lan: ipaddress.IPv4Network, gateway_ip: str) -> Dict[str, Any]:
    """One rule checked and normalised; RuleError with a reason the owner understands."""
    if not isinstance(raw, dict):
        raise RuleError("a rule must be an object")
    name = str(raw.get("name", "") or "").strip()
    if not _NAME.match(name):
        raise RuleError(f"name '{name[:40]}': at most 32 letters, digits, spaces and . : + - _")
    proto = str(raw.get("proto", "tcp") or "tcp").strip().lower()
    if proto not in PROTOS:
        raise RuleError(f"protocol '{proto}': tcp, udp or both")
    a, b = _ports(raw.get("ext"))
    try:
        ip = ipaddress.IPv4Address(str(raw.get("ip", "")).strip())
    except ValueError:
        raise RuleError(f"LAN address '{raw.get('ip', '')}' is not an IPv4 address")
    if ip not in lan or ip in (lan.network_address, lan.broadcast_address) or str(ip) == gateway_ip:
        raise RuleError(f"LAN address {ip} must be a device in {lan} (not the box itself)")
    port_raw = raw.get("port", 0)
    port = 0 if port_raw in (None, "", 0, "0") else _ports(port_raw)[0]
    if a != b and port not in (0, a):
        raise RuleError("a port range keeps its port numbers: leave the device port empty")
    return {"name": name, "proto": proto, "ext": f"{a}" if a == b else f"{a}-{b}", "ip": str(ip),
            "port": 0 if port in (0, a) and a != b else (port or a), "on": bool(raw.get("on", True))}


def _protos(proto: str) -> List[str]:
    return ["tcp", "udp"] if proto == "both" else [proto]


def _span(rule: Dict[str, Any]) -> Tuple[int, int]:
    return _ports(rule["ext"])


def clean_rules(raws: List[Dict[str, Any]], lan: ipaddress.IPv4Network, gateway_ip: str,
                reserved: Optional[List[Tuple[str, int]]] = None) -> List[Dict[str, Any]]:
    """All rules checked; WAN ports may not overlap each other or the box's own open ports (VPNs)."""
    if not isinstance(raws, list):
        raise RuleError("the rules must be a list")
    if len(raws) > MAX_RULES:
        raise RuleError(f"at most {MAX_RULES} rules")
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(raws, 1):
        try:
            out.append(clean_rule(raw, lan, gateway_ip))
        except RuleError as e:
            raise RuleError(f"rule {i}: {e}")
    taken: Dict[str, List[Tuple[int, int, int]]] = {"tcp": [], "udp": []}
    for i, r in enumerate(out, 1):
        if not r["on"]:
            continue
        a, b = _span(r)
        for p in _protos(r["proto"]):
            for (x, y, j) in taken[p]:
                if a <= y and x <= b:
                    raise RuleError(f"rule {i}: {p.upper()} {r['ext']} overlaps rule {j}")
            for rp, rport in reserved or []:
                if rp == p and a <= rport <= b:
                    raise RuleError(f"rule {i}: {p.upper()} {rport} is used by the box itself (VPN)")
            taken[p].append((a, b, i))
    return out


def box_open_ports(cfg: Any) -> List[Tuple[str, int]]:
    """Ports the box itself keeps open on the WAN: Tailscale's direct connections and the VPN servers
    that are on. A forwarding rule may not take them."""
    ports = [("udp", 41641)]
    # On in the settings, or running anyway (its tunnel interface exists): the firewall must not cut off
    # a server that runs (2026-11-10 on the box: OpenVPN ran with enabled = false in nmb.conf).
    wg = getattr(cfg, "wireguard", None)
    if wg is not None and (getattr(wg, "enabled", False) or Path("/sys/class/net/wg0").exists()):
        ports.append(("udp", int(getattr(wg, "port", 51820) or 51820)))
    ov = getattr(cfg, "openvpn", None)
    if ov is not None and (getattr(ov, "enabled", False) or Path("/sys/class/net/tun0").exists()):
        proto = "tcp" if "tcp" in str(getattr(ov, "proto", "udp")).lower() else "udp"
        ports.append((proto, int(getattr(ov, "port", 1194) or 1194)))
    return ports


def parse_config_rules(text: str) -> List[Dict[str, Any]]:
    """The rules from nmb.conf (JSON); an unreadable value means no rules, never a crash."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        log.warning("port_forward rules in nmb.conf are not valid JSON; no rules applied")
        return []
    return data if isinstance(data, list) else []


def active_rules(cfg: Any) -> List[Dict[str, Any]]:
    """The rules to apply now: forwarding on, each rule valid and switched on."""
    pf = getattr(cfg, "port_forward", None)
    net = getattr(cfg, "network", None)
    if pf is None or net is None or not getattr(pf, "enabled", False):
        return []
    lan = lan_network(net.gateway_ip, getattr(net, "gateway_netmask", "255.255.255.0"))
    out = []
    for i, raw in enumerate(getattr(pf, "rules", []) or [], 1):
        try:
            r = clean_rule(raw, lan, net.gateway_ip)
        except RuleError as e:
            log.warning("port forwarding rule %d left out: %s", i, e)
            continue
        if r["on"]:
            out.append(r)
    return out


def nat_rules(wan_iface: str, lan_set: str, gateway_ip: str, lan: ipaddress.IPv4Network,
              rules: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """nftables lines for the prerouting (DNAT) and postrouting (hairpin) chains of nmb_nat.

    Hairpin: a LAN device that uses the line's public address (or a DynDNS name) for a forwarded port
    reaches the device too; the box masquerades those so the answers come back through it.
    """
    pre: List[str] = []
    for r in rules:
        a, b = _span(r)
        dport = str(a) if a == b else f"{a}-{b}"
        target = r["ip"] if a != b else f"{r['ip']}:{r['port'] or a}"
        match = "meta l4proto { tcp, udp } th" if r["proto"] == "both" else r["proto"]
        pre.append(f'iifname "{wan_iface}" {match} dport {dport} dnat ip to {target}')
        pre.append(f'iifname {lan_set} fib daddr type local ip daddr != {gateway_ip} {match} dport {dport} dnat ip to {target}')
    post = [f"oifname {lan_set} ip saddr {lan} ip daddr {lan} ct status dnat masquerade"] if rules else []
    return pre, post


# ---- UPnP IGD / NAT-PMP / PCP (miniupnpd) ----

def miniupnpd_bin() -> str:
    return shutil.which("miniupnpd") or ("/usr/sbin/miniupnpd" if Path("/usr/sbin/miniupnpd").exists() else "")


def upnp_table_ruleset() -> str:
    """The table miniupnpd fills: its forward chain is a plain chain (the router's own forward chain
    accepts DNAT-ed packets), its NAT chains hook prerouting and postrouting."""
    return f"""table inet {UPNP_TABLE}
delete table inet {UPNP_TABLE}
table inet {UPNP_TABLE} {{
    chain forward {{
    }}
    chain prerouting {{
        type nat hook prerouting priority dstnat; policy accept;
    }}
    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
    }}
}}
"""


def miniupnpd_conf(wan_iface: str, lan_iface: str, lan: ipaddress.IPv4Network, uuid: str, lease_file: str) -> str:
    return "\n".join([
        f"ext_ifname={wan_iface}",
        f"listening_ip={lan_iface}",
        "port=0",
        "enable_upnp=yes",
        "enable_natpmp=yes",
        "enable_pcp_pmp=yes",
        "secure_mode=yes",
        "system_uptime=yes",
        "notify_interval=60",
        "clean_ruleset_interval=600",
        "min_lifetime=120",
        "max_lifetime=86400",
        f"lease_file={lease_file}",
        f"uuid={uuid}",
        "friendly_name=NetworkMeasureBox",
        "model_name=NetworkMeasureBox",
        f"upnp_table_name={UPNP_TABLE}",
        f"upnp_nat_table_name={UPNP_TABLE}",
        "upnp_forward_chain=forward",
        "upnp_nat_chain=prerouting",
        "upnp_nat_postrouting_chain=postrouting",
        "upnp_nftables_family_split=no",   # one inet table (miniupnpd 2.3.9 has no upnp_nftables_family)
        f"allow 1024-65535 {lan} 1024-65535",
        "deny 0-65535 0.0.0.0/0 0-65535",
        "",
    ])


_L4 = {"0x6": "tcp", "0x06": "tcp", "0x11": "udp"}
_MAP_LINE = re.compile(r"(?:\b(tcp|udp)\b|@nh,72,8 (0x[0-9a-f]+)).*?\bdport (\d+) dnat ip to ([\d.]+):(\d+)")


def parse_upnp_chain(text: str, leases: str = "") -> List[Dict[str, Any]]:
    """Mappings from `nft list chain inet nmb_upnp prerouting`. miniupnpd 2.3.9 writes the protocol as a raw
    match (`@nh,72,8 0x6 th dport 38080 dnat ip to 192.168.100.251:8000`); the names come from its lease
    file (`TCP:38080:192.168.100.251:8000:<expiry>:<description>`)."""
    names = {}
    for line in leases.splitlines():
        parts = line.split(":", 5)
        if len(parts) == 6 and parts[1].isdigit():
            names[(parts[0].lower(), int(parts[1]))] = parts[5].strip()[:64]
    out = []
    for line in text.splitlines():
        m = _MAP_LINE.search(line)
        if not m:
            continue
        proto = m.group(1) or _L4.get(m.group(2) or "", "")
        if not proto:
            continue
        ext = int(m.group(3))
        out.append({"proto": proto, "ext": ext, "ip": m.group(4), "port": int(m.group(5)),
                    "name": names.get((proto, ext), "")})
    return out


def upnp_mappings(lease_file: str = "/run/nmb/upnp.leases") -> List[Dict[str, Any]]:
    """What LAN devices opened over UPnP / NAT-PMP right now (from miniupnpd's nftables chain)."""
    import subprocess
    nft = shutil.which("nft")
    if not nft:
        return []
    res = subprocess.run([nft, "list", "chain", "inet", UPNP_TABLE, "prerouting"], capture_output=True, text=True,
                         timeout=10, check=False)
    try:
        leases = Path(lease_file).read_text()
    except OSError:
        leases = ""
    return parse_upnp_chain(res.stdout, leases)
