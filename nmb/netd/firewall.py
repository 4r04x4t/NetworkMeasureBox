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
    by_proto: Dict[str, List[int]] = {}
    for proto, port in open_ports or []:
        if proto in ("udp", "tcp") and 0 < int(port) < 65536 and int(port) not in by_proto.setdefault(proto, []):
            by_proto[proto].append(int(port))
    for proto, ports in sorted(by_proto.items()):
        rules.append(f"{w} {proto} dport {{ {', '.join(str(x) for x in sorted(ports))} }} accept")
    rules.append(f"{w} drop")
    return rules


def enable_nat_mode_a(wan_iface: str, lan_ifaces: List[str], block_public_wan: bool = True, dmz_iface: str = "",
                      open_ports: Optional[List[Tuple[str, int]]] = None) -> bool:
    """Setup NAT and forwarding rules for Mode A (Active Gateway).

    block_public_wan: the internet reaches the box on the WAN only for answers to its own traffic, ICMP and
    open_ports (the VPN servers: Tailscale, WireGuard, OpenVPN). Private sources (a home router or hotspot
    in front of the WAN) reach everything, as before.
    """
    _set_sysctl_forward(True)
    nft_bin = shutil.which("nft")
    ipt_bin = shutil.which("iptables")

    wan_drop_rule = ""
    if block_public_wan:
        wan_drop_rule = "\n        ".join(wan_input_rules(wan_iface, open_ports))

    if nft_bin:
        log.info("applying Mode A NAT and WAN protection via nftables on WAN iface %s", wan_iface)
        lan_set = "{" + ", ".join(f'"{i}"' for i in lan_ifaces) + "}" if lan_ifaces else '""'
        # A DMZ host may reach the internet, but neither the LAN nor the box beyond DHCP and DNS.
        dmz_input = dmz_forward = ""
        if dmz_iface:
            dmz_input = (f'iifname "{dmz_iface}" udp dport {{ 53, 67 }} accept\n'
                         f'        iifname "{dmz_iface}" tcp dport 53 accept\n'
                         f'        iifname "{dmz_iface}" ct state established,related accept\n'
                         f'        iifname "{dmz_iface}" drop')
            dmz_forward = (f'iifname "{dmz_iface}" oifname "{wan_iface}" accept\n'
                           f'        iifname "{dmz_iface}" drop')
        nft_rules = f"""
table inet {NFT_TABLE} {{
    chain input {{
        type filter hook input priority filter; policy accept;
        {wan_drop_rule}
        {dmz_input}
    }}
    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        oifname "{wan_iface}" masquerade
    }}
    chain forward {{
        type filter hook forward priority filter; policy accept;
        # PPPoE (MTU 1492) and tunnels: clients send 1500-byte segments, so clamp the MSS to the path MTU,
        # or some sites hang for them (2026-11-09).
        tcp flags syn tcp option maxseg size set rt mtu
        ct state established,related accept
        {dmz_forward}
        iifname {lan_set} oifname "{wan_iface}" accept
    }}
}}
"""
        cmd = [nft_bin, "-f", "-"]
        res = subprocess.run(cmd, input=nft_rules, text=True, capture_output=True)
        if res.returncode == 0:
            log.info("nftables NAT and WAN port protection rules applied successfully")
            return True
        log.warning("nftables failed (%s), attempting iptables fallback", res.stderr.strip())

    if ipt_bin:
        log.info("applying Mode A NAT and WAN protection via iptables fallback on WAN iface %s", wan_iface)
        try:
            subprocess.run([ipt_bin, "-t", "nat", "-D", "POSTROUTING", "-o", wan_iface, "-j", "MASQUERADE"],
                           check=False, stderr=subprocess.DEVNULL)
            subprocess.run([ipt_bin, "-t", "nat", "-A", "POSTROUTING", "-o", wan_iface, "-j", "MASQUERADE"],
                           check=True)
            for lan in lan_ifaces:
                subprocess.run([ipt_bin, "-A", "FORWARD", "-i", lan, "-o", wan_iface, "-j", "ACCEPT"],
                               check=False)
            subprocess.run([ipt_bin, "-A", "FORWARD", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
                           check=False)
            subprocess.run([ipt_bin, "-t", "mangle", "-A", "FORWARD", "-p", "tcp", "--tcp-flags", "SYN,RST", "SYN",
                            "-j", "TCPMSS", "--clamp-mss-to-pmtu"], check=False)
            if block_public_wan:
                # Same policy as the nftables rules (wan_input_rules), IPv4 only.
                rules = [["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"]]
                rules += [["-s", priv, "-j", "ACCEPT"] for priv in PRIVATE_V4.split(", ")]
                rules += [["-p", "icmp", "-j", "ACCEPT"], ["-p", "udp", "--sport", "67", "--dport", "68", "-j", "ACCEPT"]]
                rules += [["-p", proto, "--dport", str(port), "-j", "ACCEPT"] for proto, port in (open_ports or [])
                          if proto in ("udp", "tcp")]
                rules.append(["-j", "DROP"])
                for r in rules:
                    subprocess.run([ipt_bin, "-A", "INPUT", "-i", wan_iface] + r, check=False)
            return True
        except Exception as e:
            log.error("failed applying iptables rules: %s", e)
            return False

    log.error("neither nftables nor iptables found on system")
    return False


def enable_nat_simple(out_iface: str, in_ifaces: List[str]) -> bool:
    """Setup transparent masquerade for standalone / AP mode without any input filtering."""
    return enable_nat_mode_a(wan_iface=out_iface, lan_ifaces=in_ifaces, block_public_wan=False)


def enable_nat_for_wan2(wan2_iface: str, lan_ifaces: List[str]) -> bool:
    """Add NAT masquerade and forwarding rules for secondary WAN2 interface."""
    if not wan2_iface:
        return False
    ipt_bin = shutil.which("iptables")
    if ipt_bin:
        try:
            subprocess.run([ipt_bin, "-t", "nat", "-A", "POSTROUTING", "-o", wan2_iface, "-j", "MASQUERADE"],
                           check=False)
            for lan in lan_ifaces:
                subprocess.run([ipt_bin, "-A", "FORWARD", "-i", lan, "-o", wan2_iface, "-j", "ACCEPT"],
                               check=False)
            subprocess.run([ipt_bin, "-I", "INPUT", "-i", wan2_iface, "-p", "tcp", "--dport", "80", "-j", "DROP"],
                           check=False)
            subprocess.run([ipt_bin, "-I", "INPUT", "-i", wan2_iface, "-p", "tcp", "--dport", "8080", "-j", "DROP"],
                           check=False)
            log.info("NAT masquerading enabled for secondary WAN interface: %s", wan2_iface)
            return True
        except Exception as e:
            log.warning("enable_nat_for_wan2 error: %s", e)
    return False


def disable_nat() -> bool:
    """Flush and tear down all NMB NAT and forwarding rules."""
    success = True
    nft_bin = shutil.which("nft")
    if nft_bin:
        res = subprocess.run([nft_bin, "delete", "table", "inet", NFT_TABLE],
                             capture_output=True, check=False)
        if res.returncode == 0:
            log.info("nftables table inet %s deleted", NFT_TABLE)

    ipt_bin = shutil.which("iptables")
    if ipt_bin:
        # Flush any stray iptables nat entries created
        try:
            subprocess.run([ipt_bin, "-t", "nat", "-F"], check=False)
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    return success
