"""Firewall & NAT rules management for Mode A and Mode B.

Uses modern nftables with scoped tables (table inet nmb_nat), with transparent
fallback to iptables if nft is unavailable. Enables and disables ip_forwarding safely.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import List

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


def enable_nat_mode_a(wan_iface: str, lan_ifaces: List[str], block_public_wan: bool = True, dmz_iface: str = "") -> bool:
    """Setup NAT and forwarding rules for Mode A (Active Gateway).
    If block_public_wan is True, drops incoming web UI access from non-private public Internet IPs only.
    Local RFC1918 subnets (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) are always allowed.
    """
    _set_sysctl_forward(True)
    nft_bin = shutil.which("nft")
    ipt_bin = shutil.which("iptables")

    # Protection rule: only drop public Internet traffic on WAN (never block private LAN/management subnets)
    wan_drop_rule = ""
    if block_public_wan:
        wan_drop_rule = f'iifname "{wan_iface}" ip saddr != {{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 127.0.0.0/8 }} tcp dport {{ 80, 8080 }} drop'

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
            if block_public_wan:
                # Only drop on WAN if source is NOT a private RFC1918 subnet
                for priv in ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]:
                    subprocess.run([ipt_bin, "-I", "INPUT", "-i", wan_iface, "-s", priv, "-p", "tcp", "-m", "multiport", "--dports", "80,8080", "-j", "ACCEPT"],
                                   check=False)
                subprocess.run([ipt_bin, "-A", "INPUT", "-i", wan_iface, "-p", "tcp", "-m", "multiport", "--dports", "80,8080", "-j", "DROP"],
                               check=False)
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
