"""Firewall & NAT rules management for Mode A and Mode B.

Uses modern nftables with scoped tables (table inet nmb_nat), with transparent
fallback to iptables if nft is unavailable. Enables and disables ip_forwarding safely.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.firewall")

NFT_TABLE = "nmb_nat"


def _set_sysctl_forward(enable: bool) -> bool:
    val = "1" if enable else "0"
    try:
        Path("/proc/sys/net/ipv4/ip_forward").write_text(f"{val}\n")
        log.info("set net.ipv4.ip_forward = %s", val)
        return True
    except OSError as e:
        log.warning("could not set ip_forward directly via /proc: %s; trying sysctl", e)
        res = subprocess.run(["sysctl", "-w", f"net.ipv4.ip_forward={val}"], check=False)
        return res.returncode == 0


# Sources that are never "the internet": a WAN behind a home router or hotspot stays fully reachable
# for the owner and the developer (SSH, Web UI, everything), as before.
PRIVATE_V4 = "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16"
PRIVATE_V6 = "fe80::/10, fc00::/7"


def wan_input_rules(wan_iface: str, open_ports: Optional[List[Tuple[str, int]]] = None) -> List[str]:
    """nftables input rules for the WAN: only answers, private sources, needed ICMP and the VPN ports.

    2026-11-09, first real PPPoE line: the box had a public IPv4 and IPv6 address on ppp0 and only the Web
    UI was closed to the internet; SSH (password login), DNS (an open resolver), iperf3, mDNS and the rest
    were open. Everything not listed here is dropped on the WAN now.
    """
    w = f'iifname "{wan_iface}"'
    rules = [
        f"{w} ct state established,related accept",
        f"{w} ct state invalid drop",
        f"{w} ip saddr {{ {PRIVATE_V4} }} accept",
        f"{w} ip6 saddr {{ {PRIVATE_V6} }} accept",
        f"{w} icmp type echo-request limit rate 10/second accept",
        f"{w} icmp type {{ destination-unreachable, time-exceeded, parameter-problem }} accept",
        f"{w} meta l4proto ipv6-icmp accept",   # neighbour discovery, router adverts, path MTU
        f"{w} udp sport 67 udp dport 68 accept",   # DHCP renewals from an ISP's public DHCP server
    ]
    rules += _port_rules(f"{w} ", open_ports)
    rules.append(f"{w} drop")
    return rules


GUARD_TABLE = "nmb_host"   # nmb_guard is the static boot-time table (os/nmb-guard.nft)
# Interfaces whose traffic is already authenticated or local: loopback, Tailscale, WireGuard, OpenVPN.
TRUSTED_IFACES = ("lo", "tailscale0", "wg0", "tun0")


def host_guard_rules(open_ports: Optional[List[Tuple[str, int]]] = None) -> List[str]:
    """Input rules for standalone and transparent mode, on every interface: the internet reaches the box
    only with answers, ICMP, DHCP and the VPN ports, as on the router's WAN. Private sources, the box's own
    on-link IPv6 prefixes (set onlink6, a home LAN with public IPv6) and the trusted interfaces reach
    everything. Before, these modes had no host firewall at all, and mode = auto picks standalone on a
    public ISP DHCP line, so SSH, DNS, iperf3 and the Web UI were open to the internet (audit netd H1)."""
    trusted = ", ".join(f'"{i}"' for i in TRUSTED_IFACES)
    rules = [
        f"iifname {{ {trusted} }} accept",
        "ct state established,related accept",
        "ct state invalid drop",
        f"ip saddr {{ {PRIVATE_V4} }} accept",
        f"ip6 saddr {{ {PRIVATE_V6} }} accept",
        "ip6 saddr @onlink6 accept",
        "icmp type echo-request limit rate 10/second accept",
        "icmp type { destination-unreachable, time-exceeded, parameter-problem } accept",
        "meta l4proto ipv6-icmp accept",
        "udp sport 67 udp dport 68 accept",
        "udp sport 547 udp dport 546 accept",
        # DHCP requests to the box's own server (the Wi-Fi share for a cable-plugged device) come from 0.0.0.0
        "ip saddr 0.0.0.0 udp sport 68 udp dport 67 accept",
    ]
    rules += _port_rules("", open_ports)
    rules.append("drop")
    return rules


def _port_rules(prefix: str, open_ports: Optional[List[Tuple[str, int]]]) -> List[str]:
    by_proto: Dict[str, List[int]] = {}
    for proto, port in open_ports or []:
        try:
            port = int(port)
        except (TypeError, ValueError):
            continue
        if proto in ("udp", "tcp") and 0 < port < 65536 and port not in by_proto.setdefault(proto, []):
            by_proto[proto].append(port)
    return [f"{prefix}{proto} dport {{ {', '.join(str(x) for x in sorted(ports))} }} accept"
            for proto, ports in sorted(by_proto.items()) if ports]


def onlink_ipv6_prefixes() -> List[str]:
    """Global IPv6 prefixes the box is directly on (routes without a gateway), e.g. a home LAN's /64."""
    import ipaddress
    try:
        res = subprocess.run(["ip", "-6", "route", "show", "table", "main"], capture_output=True, text=True,
                             timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in (res.stdout or "").splitlines():
        parts = line.split()
        if not parts or "via" in parts or parts[0] in ("default", "unreachable", "blackhole", "prohibit"):
            continue
        if "dev" in parts and parts[parts.index("dev") + 1] in TRUSTED_IFACES:
            continue
        try:
            net = ipaddress.ip_network(parts[0], strict=False)
        except ValueError:
            continue
        if net.version == 6 and net.is_global and 32 <= net.prefixlen <= 128 and str(net) not in out:
            out.append(str(net))
    return out


def guard_ruleset(input_rules: List[str], onlink6: Optional[List[str]] = None) -> str:
    elems = ""
    if onlink6:
        elems = f"\n        elements = {{ {', '.join(onlink6)} }}"
    body = "\n        ".join(input_rules)
    return f"""
table inet {GUARD_TABLE}
delete table inet {GUARD_TABLE}
table inet {GUARD_TABLE} {{
    set onlink6 {{
        type ipv6_addr; flags interval;{elems}
    }}
    chain input {{
        type filter hook input priority filter - 5; policy accept;
        {body}
    }}
}}
"""


_guard_state: Dict[str, object] = {"rules": None, "onlink6": None}


def apply_guard(input_rules: List[str], onlink6: Optional[List[str]] = None) -> bool:
    """Replace the guard table in one nft transaction (no moment without rules). Without nft, the same
    policy goes into iptables/ip6tables chains of our own (NMB-HOST), never touching other rules."""
    onlink6 = list(onlink6 or [])
    nft_bin = shutil.which("nft")
    if nft_bin:
        res = subprocess.run([nft_bin, "-f", "-"], input=guard_ruleset(input_rules, onlink6), text=True,
                             capture_output=True, check=False)
        if res.returncode == 0:
            _guard_state.update(rules=list(input_rules), onlink6=onlink6)
            return True
        log.error("host guard: nft refused the rules: %s", (res.stderr or "").strip()[:300])
        return False
    return _apply_guard_iptables(input_rules, onlink6)


def refresh_host_guard(open_ports: Optional[List[Tuple[str, int]]] = None) -> None:
    """Every netd loop outside router mode: follow a changed home IPv6 prefix and a VPN server that was
    switched on or off (its port), only when something changed."""
    rules = _guard_state.get("rules")
    if not rules or not any("@onlink6" in r for r in rules):
        return
    want = host_guard_rules(open_ports) if open_ports is not None else rules
    now = onlink_ipv6_prefixes()
    if now != _guard_state.get("onlink6") or want != rules:
        log.info("host guard: refreshed (on-link IPv6 prefixes: %s)", ", ".join(now) or "none")
        apply_guard(want, now)


refresh_onlink6 = refresh_host_guard


def apply_host_guard(open_ports: Optional[List[Tuple[str, int]]] = None) -> bool:
    """Standalone and transparent mode."""
    ok = apply_guard(host_guard_rules(open_ports), onlink_ipv6_prefixes())
    if ok:
        log.info("host guard on: the internet reaches the box only with answers, ICMP, DHCP and the VPN ports")
    return ok


def apply_wan_guard(wan_ifaces: List[str], open_ports: Optional[List[Tuple[str, int]]] = None) -> bool:
    """Router mode: the WAN rules on each WAN interface (also before pppd has created ppp0: nft matches
    the name when the packet arrives), set up before the line is dialled (audit netd H3)."""
    rules: List[str] = []
    for w in dict.fromkeys(i for i in wan_ifaces if i):
        rules += wan_input_rules(w, open_ports)
    return apply_guard(rules)


def _ipt_guard_rule(rule: str) -> Optional[Tuple[str, List[str]]]:
    """The iptables form of one guard rule, or None when it has no plain-iptables equivalent."""
    import re
    m = re.match(r'(?:iifname "([^"]+)" )?(.*)$', rule)
    iface, rest = m.group(1), m.group(2)
    pre = ["-i", iface] if iface else []
    fam = "4"
    if rest.startswith("iifname {"):
        return None
    if rest == "ct state established,related accept":
        args = ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"]; fam = "46"
    elif rest == "ct state invalid drop":
        args = ["-m", "conntrack", "--ctstate", "INVALID", "-j", "DROP"]; fam = "46"
    elif rest.startswith("ip saddr"):
        return ("4", pre + ["-s", ",".join(x.strip() for x in PRIVATE_V4.split(",")), "-j", "ACCEPT"])
    elif rest.startswith("ip6 saddr {"):
        return ("6", pre + ["-s", ",".join(x.strip() for x in PRIVATE_V6.split(",")), "-j", "ACCEPT"])
    elif rest.startswith("icmp type echo-request"):
        args = ["-p", "icmp", "--icmp-type", "echo-request", "-m", "limit", "--limit", "10/second", "-j", "ACCEPT"]
    elif rest.startswith("icmp type {"):
        return ("4", pre + ["-p", "icmp", "-m", "icmp", "!", "--icmp-type", "echo-request", "-j", "ACCEPT"])
    elif rest == "meta l4proto ipv6-icmp accept":
        return ("6", pre + ["-p", "ipv6-icmp", "-j", "ACCEPT"])
    elif rest == "udp sport 67 udp dport 68 accept":
        args = ["-p", "udp", "--sport", "67", "--dport", "68", "-j", "ACCEPT"]
    elif rest == "ip saddr 0.0.0.0 udp sport 68 udp dport 67 accept":
        return ("4", pre + ["-s", "0.0.0.0", "-p", "udp", "--sport", "68", "--dport", "67", "-j", "ACCEPT"])
    elif rest == "udp sport 547 udp dport 546 accept":
        return ("6", pre + ["-p", "udp", "--sport", "547", "--dport", "546", "-j", "ACCEPT"])
    elif re.match(r"(udp|tcp) dport \{", rest):
        proto = rest.split()[0]
        ports = ",".join(re.findall(r"\d+", rest.split("{")[1]))
        return ("46", pre + ["-p", proto, "-m", "multiport", "--dports", ports, "-j", "ACCEPT"])
    elif rest == "drop":
        return ("46", pre + ["-j", "DROP"])
    else:
        return None
    return (fam, pre + args)


def _apply_guard_iptables(input_rules: List[str], onlink6: Optional[List[str]] = None) -> bool:
    ok = False
    for fam, binary in (("4", "iptables"), ("6", "ip6tables")):
        b = shutil.which(binary)
        if not b:
            if fam == "6":
                log.warning("host guard: ip6tables missing; IPv6 forwarding off so nothing passes unfiltered")
                _set_ipv6_forward(False)
            continue
        subprocess.run([b, "-N", "NMB-HOST"], capture_output=True, check=False)
        subprocess.run([b, "-F", "NMB-HOST"], capture_output=True, check=False)
        trusted = [["-i", i, "-j", "ACCEPT"] for i in TRUSTED_IFACES] if any(r.startswith("iifname {") for r in input_rules) else []
        for args in trusted:
            subprocess.run([b, "-A", "NMB-HOST"] + args, capture_output=True, check=False)
        for r in input_rules:
            if r == "ip6 saddr @onlink6 accept":
                if fam == "6":
                    for net in onlink6 or []:
                        subprocess.run([b, "-A", "NMB-HOST", "-s", net, "-j", "ACCEPT"], capture_output=True, check=False)
                continue
            conv = _ipt_guard_rule(r)
            if conv and fam in conv[0]:
                subprocess.run([b, "-A", "NMB-HOST"] + conv[1], capture_output=True, check=False)
        if subprocess.run([b, "-C", "INPUT", "-j", "NMB-HOST"], capture_output=True, check=False).returncode != 0:
            subprocess.run([b, "-I", "INPUT", "1", "-j", "NMB-HOST"], capture_output=True, check=False)
        ok = ok or fam == "4"
    if ok:
        _guard_state.update(rules=list(input_rules), onlink6=list(onlink6 or []))
    return ok


def _set_ipv6_forward(enable: bool) -> None:
    try:
        Path("/proc/sys/net/ipv6/conf/all/forwarding").write_text("1\n" if enable else "0\n")
    except OSError as e:
        log.warning("could not set IPv6 forwarding: %s", e)


def enable_nat_mode_a(wan_iface: str, lan_ifaces: List[str], block_public_wan: bool = True, dmz_iface: str = "",
                      open_ports: Optional[List[Tuple[str, int]]] = None, forwards: Optional[List[dict]] = None,
                      gateway_ip: str = "", gateway_netmask: str = "255.255.255.0",
                      extra_wans: Optional[List[str]] = None) -> bool:
    """Setup NAT and forwarding rules for Mode A (Active Gateway).

    block_public_wan: the internet reaches the box on the WAN only for answers to its own traffic, ICMP and
    open_ports (the VPN servers: Tailscale, WireGuard, OpenVPN). Private sources (a home router or hotspot
    in front of the WAN) reach everything, as before.
    forwards: port forwarding rules (nmb/netd/port_forward.py), already checked; DNAT from the WAN, and
    hairpin NAT so LAN devices can use the public address too.
    extra_wans: a second WAN (WAN2) with the same NAT and the same protection; it had only two dropped
    TCP ports and nothing for IPv6 before (audit netd H2).
    The table is replaced in one nft transaction, so this can be called again when the rules change.
    IP forwarding is switched on only once the rules are in place, and a failure returns False (the
    caller then keeps forwarding off): before, forwarding came first and a failure was ignored (H3).
    """
    nft_bin = shutil.which("nft")
    ipt_bin = shutil.which("iptables")
    wans = list(dict.fromkeys([wan_iface] + [w for w in (extra_wans or []) if w and w != wan_iface]))

    wan_drop_rule = ""
    if block_public_wan:
        wan_drop_rule = "\n        ".join(r for w in wans for r in wan_input_rules(w, open_ports))

    if nft_bin:
        log.info("applying Mode A NAT and WAN protection via nftables on WAN iface %s", ", ".join(wans))
        lan_set = "{" + ", ".join(f'"{i}"' for i in lan_ifaces) + "}" if lan_ifaces else '""'
        wan_set = f'"{wans[0]}"' if len(wans) == 1 else "{" + ", ".join(f'"{w}"' for w in wans) + "}"
        # A DMZ host may reach the internet, but neither the LAN nor the box beyond DHCP and DNS.
        dmz_input = dmz_forward = ""
        if dmz_iface:
            dmz_input = (f'iifname "{dmz_iface}" udp dport {{ 53, 67 }} accept\n'
                         f'        iifname "{dmz_iface}" tcp dport 53 accept\n'
                         f'        iifname "{dmz_iface}" ct state established,related accept\n'
                         f'        iifname "{dmz_iface}" drop')
            dmz_forward = (f'iifname "{dmz_iface}" oifname {wan_set} accept\n'
                           f'        iifname "{dmz_iface}" drop')
        pre_rules, post_rules = [], []
        if forwards and gateway_ip:
            from nmb.netd.port_forward import lan_network, nat_rules
            pre_rules, post_rules = nat_rules(wan_iface, lan_set, gateway_ip, lan_network(gateway_ip, gateway_netmask), forwards)
        prerouting = ""
        if pre_rules:
            prerouting = ("    chain prerouting {\n        type nat hook prerouting priority dstnat; policy accept;\n        "
                          + "\n        ".join(pre_rules) + "\n    }\n")
        wan_forward = ""
        if block_public_wan:
            # From the WAN only answers, forwarded ports and private sources (a home LAN in front) reach the LAN.
            wan_forward = "\n        ".join(r for w in wans for r in (
                f'iifname "{w}" ct status dnat accept',
                f'iifname "{w}" ip saddr {{ {PRIVATE_V4} }} accept',
                f'iifname "{w}" ip6 saddr {{ {PRIVATE_V6} }} accept',
                f'iifname "{w}" drop',
            ))
        nft_rules = f"""
table inet {NFT_TABLE}
delete table inet {NFT_TABLE}
table inet {NFT_TABLE} {{
{prerouting}    chain input {{
        type filter hook input priority filter; policy accept;
        {wan_drop_rule}
        {dmz_input}
    }}
    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        {chr(10).join(post_rules)}
        oifname {wan_set} masquerade
    }}
    chain forward {{
        type filter hook forward priority filter; policy accept;
        # PPPoE (MTU 1492) and tunnels: clients send 1500-byte segments, so clamp the MSS to the path MTU,
        # or some sites hang for them (2026-11-09).
        tcp flags syn tcp option maxseg size set rt mtu
        ct state established,related accept
        {dmz_forward}
        iifname {lan_set} oifname {wan_set} accept
        {wan_forward}
    }}
}}
"""
        cmd = [nft_bin, "-f", "-"]
        res = subprocess.run(cmd, input=nft_rules, text=True, capture_output=True)
        if res.returncode == 0:
            log.info("nftables NAT and WAN port protection rules applied successfully")
            _set_sysctl_forward(True)
            return True
        log.warning("nftables failed (%s), attempting iptables fallback", res.stderr.strip())

    if ipt_bin:
        log.info("applying Mode A NAT and WAN protection via iptables fallback on WAN iface %s", ", ".join(wans))
        try:
            for w in wans:
                _ipt_add(ipt_bin, ["-t", "nat", "-A", "POSTROUTING", "-o", w, "-j", "MASQUERADE"], required=True)
                for lan in lan_ifaces:
                    _ipt_add(ipt_bin, ["-A", "FORWARD", "-i", lan, "-o", w, "-j", "ACCEPT"])
            _ipt_add(ipt_bin, ["-A", "FORWARD", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"])
            _ipt_add(ipt_bin, ["-t", "mangle", "-A", "FORWARD", "-p", "tcp", "--tcp-flags", "SYN,RST", "SYN",
                               "-j", "TCPMSS", "--clamp-mss-to-pmtu"])
            if block_public_wan:
                # The WAN input policy (wan_input_rules) for IPv4 and IPv6 in our own chain, and nothing new
                # from the WAN into the LAN; IPv6 off when ip6tables is missing, so nothing passes unfiltered.
                _apply_guard_iptables([r for w in wans for r in wan_input_rules(w, open_ports)])
                ip6 = shutil.which("ip6tables")
                for w in wans:
                    for b in [x for x in (ipt_bin, ip6) if x]:
                        _ipt_add(b, ["-A", "FORWARD", "-i", w, "-m", "conntrack", "!", "--ctstate",
                                     "ESTABLISHED,RELATED,DNAT", "-j", "DROP"])
                if not ip6:
                    _set_ipv6_forward(False)
            _set_sysctl_forward(True)
            return True
        except Exception as e:
            log.error("failed applying iptables rules: %s", e)
            return False

    log.error("neither nftables nor iptables found on system")
    return False


# iptables rules this module added (binary, rule), so teardown removes exactly these and never flushes
# a whole table: `iptables -t nat -F` also deleted Docker's, Tailscale's and the VPNs' NAT (audit netd M9).
_IPT_ADDED: List[Tuple[str, List[str]]] = []


def _ipt_add(binary: str, rule: List[str], required: bool = False) -> None:
    """Append a rule once: a repeated call no longer piles up copies."""
    check = [("-C" if x == "-A" else x) for x in rule]
    if subprocess.run([binary] + check, capture_output=True, check=False).returncode == 0:
        if (binary, rule) not in _IPT_ADDED:
            _IPT_ADDED.append((binary, rule))
        return
    subprocess.run([binary] + rule, capture_output=True, check=required)
    _IPT_ADDED.append((binary, rule))


def enable_nat_simple(out_iface: str, in_ifaces: List[str]) -> bool:
    """Setup transparent masquerade for standalone / AP mode without any input filtering."""
    return enable_nat_mode_a(wan_iface=out_iface, lan_ifaces=in_ifaces, block_public_wan=False)


def enable_nat_for_wan2(wan2_iface: str, lan_ifaces: List[str]) -> bool:
    """WAN2 without nftables: NAT plus the same WAN protection as the main WAN. With nftables, WAN2 is
    part of the router table (enable_nat_mode_a extra_wans) and this does nothing."""
    if not wan2_iface:
        return False
    if shutil.which("nft"):
        return True
    ipt_bin = shutil.which("iptables")
    if not ipt_bin:
        return False
    try:
        _ipt_add(ipt_bin, ["-t", "nat", "-A", "POSTROUTING", "-o", wan2_iface, "-j", "MASQUERADE"])
        for lan in lan_ifaces:
            _ipt_add(ipt_bin, ["-A", "FORWARD", "-i", lan, "-o", wan2_iface, "-j", "ACCEPT"])
        rules = list(_guard_state.get("rules") or []) + wan_input_rules(wan2_iface, [])
        _apply_guard_iptables(rules)
        for b in [x for x in (ipt_bin, shutil.which("ip6tables")) if x]:
            _ipt_add(b, ["-A", "FORWARD", "-i", wan2_iface, "-m", "conntrack", "!", "--ctstate",
                         "ESTABLISHED,RELATED,DNAT", "-j", "DROP"])
        log.info("NAT masquerading enabled for secondary WAN interface: %s", wan2_iface)
        return True
    except Exception as e:
        log.warning("enable_nat_for_wan2 error: %s", e)
    return False


def disable_nat() -> bool:
    """Tear down the router's NAT and forwarding rules (only ours). The host guard stays: the next mode
    replaces it, so the box is never without protection between modes."""
    nft_bin = shutil.which("nft")
    if nft_bin:
        res = subprocess.run([nft_bin, "delete", "table", "inet", NFT_TABLE],
                             capture_output=True, check=False)
        if res.returncode == 0:
            log.info("nftables table inet %s deleted", NFT_TABLE)
    while _IPT_ADDED:
        binary, rule = _IPT_ADDED.pop()
        delete = [("-D" if x == "-A" else x) for x in rule]
        subprocess.run([binary] + delete, capture_output=True, check=False)
    return True
