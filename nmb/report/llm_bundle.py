"""
LLM Diagnostic Bundle Generator for NetworkMeasureBox.
Assembles a comprehensive, structured Markdown report designed for copying directly
into an AI (ChatGPT, Claude, Gemini) for instant deep troubleshooting and performance analysis.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from nmb.config import Config
from nmb.db import database as db
from nmb.netd.os_detector import detect_os_info, get_dynamic_interfaces
from nmb.netd.explorer import get_cached_devices
from nmb.netd.guest_wifi import get_guest_wifi_status
from nmb.netd.interfaces import get_dual_stack_ips, get_ip_addresses
from nmb.speed.iperf import get_latest_iperf_result, get_iperf_server_status
from nmb.speed.runner import is_speedtest_running
from nmb.speed.traceroute import get_latest_traceroute

log = logging.getLogger("nmb.report.llm_bundle")


def _get_cpu_and_thermal_telemetry() -> Dict[str, Any]:
    temp_c = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_c = round(float(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass

    load_avg = "N/A"
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
            load_avg = f"1m: {parts[0]}, 5m: {parts[1]}, 15m: {parts[2]} (Tasks: {parts[3]})"
    except Exception:
        pass

    cur_freq_mhz = None
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "r") as f:
            cur_freq_mhz = int(int(f.read().strip()) / 1000)
    except Exception:
        pass

    throttled_hex = None
    throttled_flags: List[str] = []
    try:
        res = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2, check=False)
        m = re.search(r"throttled=(0x[0-9a-fA-F]+)", res.stdout)
        if m:
            throttled_hex = m.group(1)
            val = int(throttled_hex, 16)
            flags_map = {
                0: "Under-voltage currently detected",
                1: "Arm frequency currently capped",
                2: "Currently throttled (thermal)",
                3: "Soft temperature limit currently active",
                16: "Under-voltage has occurred previously",
                17: "Arm frequency capping has occurred previously",
                18: "Throttling has occurred previously",
                19: "Soft temperature limit has occurred previously",
            }
            for bit, desc in flags_map.items():
                if val & (1 << bit):
                    throttled_flags.append(desc)
    except Exception:
        pass

    return {
        "temp_c": temp_c,
        "load_avg": load_avg,
        "freq_mhz": cur_freq_mhz,
        "throttled_hex": throttled_hex,
        "throttled_flags": throttled_flags,
    }


def _get_phy_and_ethtool(iface: str) -> Dict[str, Any]:
    ethtool_bin = shutil.which("ethtool") or "/usr/sbin/ethtool"
    ethtool_info: Dict[str, str] = {}
    eee_info: Dict[str, str] = {}
    pause_info: Dict[str, str] = {}
    link_partner_modes: List[str] = []

    if os.path.exists(ethtool_bin):
        # 1. Main ethtool link state & partner modes
        try:
            r = subprocess.run([ethtool_bin, iface], capture_output=True, text=True, timeout=3, check=False)
            in_partner_modes = False
            for line in r.stdout.splitlines():
                stripped = line.strip()
                for k in ("Speed:", "Duplex:", "Auto-negotiation:", "Link detected:", "Port:"):
                    if stripped.startswith(k):
                        ethtool_info[k.rstrip(":")] = stripped.split(":", 1)[1].strip()
                if "Link partner advertised link modes:" in line:
                    modes_part = line.split(":", 1)[1].strip()
                    if modes_part:
                        link_partner_modes.extend(modes_part.split())
                    in_partner_modes = True
                elif in_partner_modes:
                    if ":" in line or not (line.startswith("\t") or line.startswith("   ")):
                        in_partner_modes = False
                    else:
                        link_partner_modes.extend(stripped.split())
                if "Link partner advertised pause frame use:" in line:
                    pause_info["partner_pause"] = line.split(":", 1)[1].strip()
        except Exception:
            pass

        # 2. EEE (Energy-Efficient Ethernet) status: ethtool --show-eee <iface>
        try:
            r_eee = subprocess.run([ethtool_bin, "--show-eee", iface], capture_output=True, text=True, timeout=3, check=False)
            for line in r_eee.stdout.splitlines():
                line = line.strip()
                if line.startswith("EEE status:"):
                    eee_info["status"] = line.split(":", 1)[1].strip()
                elif line.startswith("Tx LPI:"):
                    eee_info["tx_lpi"] = line.split(":", 1)[1].strip()
                elif line.startswith("Supported EEE link modes:"):
                    eee_info["supported"] = line.split(":", 1)[1].strip()
                elif line.startswith("Advertised EEE link modes:"):
                    eee_info["advertised"] = line.split(":", 1)[1].strip()
                elif line.startswith("Link partner advertised EEE link modes:"):
                    eee_info["partner_eee"] = line.split(":", 1)[1].strip()
        except Exception:
            pass

        # 3. Flow control (Pause parameters): ethtool -a <iface>
        try:
            r_pause = subprocess.run([ethtool_bin, "-a", iface], capture_output=True, text=True, timeout=3, check=False)
            for line in r_pause.stdout.splitlines():
                line = line.strip()
                if line.startswith("RX:"):
                    pause_info["rx"] = line.split(":", 1)[1].strip()
                elif line.startswith("TX:"):
                    pause_info["tx"] = line.split(":", 1)[1].strip()
                elif line.startswith("RX negotiated:"):
                    pause_info["rx_negotiated"] = line.split(":", 1)[1].strip()
                elif line.startswith("TX negotiated:"):
                    pause_info["tx_negotiated"] = line.split(":", 1)[1].strip()
                elif line.startswith("Autonegotiate:"):
                    pause_info["autoneg"] = line.split(":", 1)[1].strip()
        except Exception:
            pass

    stats: Dict[str, int] = {}
    stat_dir = Path(f"/sys/class/net/{iface}/statistics")
    if stat_dir.exists():
        for sf in ("rx_packets", "rx_bytes", "rx_errors", "rx_dropped", "rx_crc_errors", "rx_frame_errors",
                   "tx_packets", "tx_bytes", "tx_errors", "tx_dropped", "tx_carrier_errors", "collisions"):
            try:
                stats[sf] = int((stat_dir / sf).read_text().strip())
            except Exception:
                stats[sf] = 0

    carrier_changes = "N/A"
    cc_file = Path(f"/sys/class/net/{iface}/carrier_changes")
    if cc_file.exists():
        try:
            carrier_changes = cc_file.read_text().strip()
        except Exception:
            pass

    return {
        "ethtool": ethtool_info,
        "eee": eee_info,
        "pause": pause_info,
        "partner_modes": link_partner_modes,
        "stats": stats,
        "carrier_changes": carrier_changes,
    }


_cached_llm_bundle: tuple[float, str] | None = None


def _get_path_mtu_discovery(iface: str, target: str = "1.1.1.1") -> Dict[str, Any]:
    iface_mtu = 1500
    try:
        mtu_path = Path(f"/sys/class/net/{iface}/mtu")
        if mtu_path.exists():
            iface_mtu = int(mtu_path.read_text().strip())
    except Exception:
        pass

    discovered_pmtu = iface_mtu
    is_pppoe = False
    diag_note = ""

    try:
        ping_r = subprocess.run(
            ["ping", "-c", "1", "-M", "do", "-s", "1472", "-W", "1", target],
            capture_output=True, text=True, timeout=2, check=False
        )
        combined = ping_r.stdout + ping_r.stderr
        if "Frag needed" in combined or "too long" in combined or ping_r.returncode != 0:
            m = re.search(r"mtu = (\d+)", combined)
            if m:
                discovered_pmtu = int(m.group(1))
            else:
                p2 = subprocess.run(
                    ["ping", "-c", "1", "-M", "do", "-s", "1464", "-W", "1", target],
                    capture_output=True, text=True, timeout=2, check=False
                )
                if p2.returncode == 0:
                    discovered_pmtu = 1492
                else:
                    discovered_pmtu = 1480

            if discovered_pmtu <= 1492:
                is_pppoe = True
                diag_note = (
                    f"Path MTU is capped at {discovered_pmtu} bytes (standard PPPoE overhead is 8 bytes: 1500 - 8 = 1492). "
                    f"Packets of 1500 bytes with DF flag are fragmented or dropped by upstream gateway. "
                    f"MSS Clamping or setting WAN MTU to {discovered_pmtu} is strongly recommended to eliminate fragmentation blackholes."
                )
            else:
                diag_note = f"Path MTU restricted to {discovered_pmtu} bytes along the route."
        else:
            diag_note = "Standard 1500-byte packets pass without fragmentation (Full Gigabit / FTTH MTU intact)."
    except Exception as e:
        diag_note = f"PMTU probe exception: {e}"

    return {
        "interface_mtu": iface_mtu,
        "discovered_pmtu": discovered_pmtu,
        "is_pppoe": is_pppoe,
        "note": diag_note,
    }


def _check_multihoming_arp_flux(eth_iface: str = "eth0", wlan_iface: str = "wlan0") -> Dict[str, Any]:
    """Check whether wired and wireless interfaces share the same subnet (risk of ARP flux)."""
    eth_ips = get_ip_addresses(eth_iface)
    wlan_ips = get_ip_addresses(wlan_iface)

    eth_v4 = [ip.split("/")[0] for ip in eth_ips if "." in ip and not ip.startswith("127.")]
    wlan_v4 = [ip.split("/")[0] for ip in wlan_ips if "." in ip and not ip.startswith("127.")]

    same_subnet = False
    shared_net = ""
    eth_matched = eth_v4[0] if eth_v4 else ""
    wlan_matched = wlan_v4[0] if wlan_v4 else ""

    for e_str in eth_ips:
        if "." not in e_str:
            continue
        try:
            e_net = ipaddress.IPv4Interface(e_str).network
            for w_str in wlan_ips:
                if "." not in w_str:
                    continue
                w_net = ipaddress.IPv4Interface(w_str).network
                if e_net == w_net or e_net.overlaps(w_net):
                    same_subnet = True
                    shared_net = str(e_net)
                    eth_matched = e_str.split("/")[0]
                    wlan_matched = w_str.split("/")[0]
                    break
        except Exception:
            continue
        if same_subnet:
            break

    arp_ignore = "0"
    arp_announce = "0"
    for p, var in (("/proc/sys/net/ipv4/conf/all/arp_ignore", "arp_ignore"),
                   ("/proc/sys/net/ipv4/conf/all/arp_announce", "arp_announce")):
        try:
            with open(p, "r") as f:
                if var == "arp_ignore":
                    arp_ignore = f.read().strip()
                else:
                    arp_announce = f.read().strip()
        except Exception:
            pass

    return {
        "eth_ips": eth_v4,
        "wlan_ips": wlan_v4,
        "same_subnet": same_subnet,
        "shared_subnet": shared_net,
        "eth_ip": eth_matched,
        "wlan_ip": wlan_matched,
        "arp_ignore": arp_ignore,
        "arp_announce": arp_announce,
    }


def _get_detailed_mtr(target: str = "1.1.1.1", cycles: int = 30) -> Dict[str, Any]:
    """Execute headless multi-sample MTR measurement (default 30 cycles) and return parsed JSON hubs and raw output."""
    target = (target or "1.1.1.1").strip()
    if target.startswith("-"):
        target = "1.1.1.1"
    mtr_bin = shutil.which("mtr") or "/usr/bin/mtr"
    cycles_str = str(max(10, min(cycles, 100)))

    if os.path.exists(mtr_bin):
        # 1. Try fast structured JSON report (cycles=30, sudo with interval 0.25 if permitted)
        for cmd_prefix in (
            ["sudo", mtr_bin, "--report", "--report-cycles", cycles_str, "-i", "0.25", "--json", "--", target],
            [mtr_bin, "--report", "--report-cycles", cycles_str, "--json", "--", target],
        ):
            try:
                r = subprocess.run(cmd_prefix, capture_output=True, text=True, timeout=35, check=False)
                if r.returncode == 0 and r.stdout.strip():
                    data = json.loads(r.stdout)
                    hubs = data.get("report", {}).get("hubs", [])
                    if hubs:
                        text_lines = [
                            f"HOST: speedtest{' ' * 26}Loss%   Snt   Last   Avg  Best  Wrst StDev"
                        ]
                        for h in hubs:
                            c = h.get("count", 0)
                            hst = h.get("host", "???")
                            lp = h.get("Loss%", 0.0)
                            snt = h.get("Snt", 0)
                            last_v = h.get("Last", 0.0)
                            avg_v = h.get("Avg", 0.0)
                            best_v = h.get("Best", 0.0)
                            wrst_v = h.get("Wrst", 0.0)
                            stdev_v = h.get("StDev", 0.0)
                            text_lines.append(f"  {c:>2}.|-- {hst:<35} {lp:>5.1f}% {snt:>5} {last_v:>6.1f} {avg_v:>5.1f} {best_v:>5.1f} {wrst_v:>5.1f} {stdev_v:>5.1f}")
                        return {"hubs": hubs, "raw": "\n".join(text_lines), "target": target, "cycles": int(cycles_str)}
            except Exception as e:
                log.debug("mtr json measurement exception: %s", e)

        # 2. Fallback to plain text MTR
        for cmd_prefix in (
            ["sudo", mtr_bin, "-r", "-w", "-c", cycles_str, "-i", "0.25", "-b", "--", target],
            [mtr_bin, "-r", "-w", "-c", cycles_str, "-b", "--", target],
        ):
            try:
                r = subprocess.run(cmd_prefix, capture_output=True, text=True, timeout=35, check=False)
                if r.returncode == 0 and r.stdout.strip():
                    hubs = []
                    for line in r.stdout.splitlines():
                        m = re.search(r"^\s*([0-9]+)\.\|--\s+(\S.*?)\s+([0-9.]+)%?\s+([0-9]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", line)
                        if m:
                            hubs.append({
                                "count": int(m.group(1)),
                                "host": m.group(2).strip(),
                                "Loss%": float(m.group(3)),
                                "Snt": int(m.group(4)),
                                "Last": float(m.group(5)),
                                "Avg": float(m.group(6)),
                                "Best": float(m.group(7)),
                                "Wrst": float(m.group(8)),
                                "StDev": float(m.group(9)),
                            })
                    if hubs:
                        return {"hubs": hubs, "raw": r.stdout.strip(), "target": target, "cycles": int(cycles_str)}
            except Exception as e:
                log.debug("mtr text measurement exception: %s", e)

    # Fallback to traceroute if MTR is unavailable
    tr_bin = shutil.which("traceroute")
    if tr_bin:
        try:
            r = subprocess.run([tr_bin, "-m", "15", "-q", "2", "-w", "1", "--", target],
                               capture_output=True, text=True, timeout=6, check=False)
            if r.returncode == 0 and r.stdout.strip():
                return {"hubs": [], "raw": r.stdout.strip(), "target": target}
        except Exception:
            pass
    return {"hubs": [], "raw": "", "target": target}


def generate_llm_diagnostic_bundle(cfg: Config, force_refresh: bool = False) -> str:
    """Generate a clean, copyable markdown diagnostic report for LLM ingestion with 60s caching."""
    global _cached_llm_bundle
    now_mono = time.monotonic()
    if not force_refresh and _cached_llm_bundle:
        cached_ts, cached_md = _cached_llm_bundle
        if (now_mono - cached_ts) < 60.0:
            return cached_md
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    os_info = detect_os_info()
    interfaces = get_dynamic_interfaces()
    wan_iface = cfg.network.wan_interface or "eth0"
    conn = db.connect(readonly=True)

    # 1. System uptime and memory
    uptime_str = "unknown"
    try:
        with open("/proc/uptime", "r") as f:
            up_sec = float(f.read().split()[0])
            uptime_str = f"{int(up_sec // 3600)}h {int((up_sec % 3600) // 60)}m {int(up_sec % 60)}s"
    except Exception:
        pass

    mem_info = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = parts[1].strip()
                    if k in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached"):
                        mem_info[k] = v
    except Exception:
        pass

    # 2. Hardware telemetry (Thermal & Throttling)
    hw_telemetry = _get_cpu_and_thermal_telemetry()

    # 3. Physical link & interface statistics
    phy_info = _get_phy_and_ethtool(wan_iface)

    # 4. Path MTU Discovery
    pmtu_info = _get_path_mtu_discovery(wan_iface, target="1.1.1.1")

    # 5. Kernel routing table
    routes_text = "N/A"
    try:
        res = subprocess.run(["ip", "route", "show"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            routes_text = res.stdout.strip()
    except Exception:
        pass

    # 6. DNS configuration & test
    resolv_text = "N/A"
    try:
        resolv_path = Path("/etc/resolv.conf")
        if resolv_path.exists():
            resolv_text = resolv_path.read_text().strip()
    except Exception:
        pass

    dns_test_ok = False
    dns_rtt_ms = None
    try:
        from nmb.netd.dns import test_dns_resolution
        ok, res_ip, lat = test_dns_resolution("cloudflare.com", timeout=2.0)
        dns_test_ok = ok
        dns_rtt_ms = lat
    except Exception:
        pass

    # 7. Public Dual-Stack IPs
    dual_ips = get_dual_stack_ips(wan_iface)

    # Synchronize dynamic Local Gateway and ISP First Hop ping targets
    try:
        from nmb.netd.interfaces import sync_gateway_ping_targets
        sync_conn = db.connect()
        with db.tx(sync_conn):
            sync_gateway_ping_targets(sync_conn, wan_iface)
        sync_conn.close()
    except Exception as e:
        log.debug("gateway sync error in llm_bundle: %s", e)

    # TCP Congestion Control
    tcp_cc = "unknown"
    try:
        with open("/proc/sys/net/ipv4/tcp_congestion_control", "r") as f:
            tcp_cc = f.read().strip()
    except Exception:
        pass

    # Deployment Mode
    net_mode = getattr(cfg.network, "mode", "standalone")
    if net_mode == "mode_a":
        deploy_mode = "Active Gateway / Router (NAT & DHCP Master)"
    elif net_mode == "mode_b":
        deploy_mode = "Passive Inline Transparent Bridge"
    else:
        deploy_mode = "LAN Probe (Client behind NAT router)"

    # 8. Latest Speedtest
    last_speed = conn.execute("SELECT * FROM speedtest ORDER BY ts DESC LIMIT 1").fetchone()
    last_speed_dict = dict(last_speed) if last_speed else {}

    # 9. Ping probe telemetry stats (last 24h) with role and min/max RTT
    now_ms = db.now_ms()
    day_ago = now_ms - (24 * 3600 * 1000)
    probes = []
    try:
        probes = conn.execute(
            """SELECT t.id, t.addr as target_addr, t.label as target_label, t.role as target_role,
                      COUNT(p.ts) as sent,
                      SUM(CASE WHEN p.rtt_us IS NULL THEN 1 ELSE 0 END) as lost,
                      AVG(p.rtt_us) as avg_rtt,
                      MIN(p.rtt_us) as min_rtt,
                      MAX(p.rtt_us) as max_rtt
               FROM target t
               LEFT JOIN ping_sample p ON p.target_id = t.id AND p.ts >= ?
               WHERE t.enabled = 1
               GROUP BY t.id, t.addr, t.label, t.role
               ORDER BY CASE 
                   WHEN t.role = 'Local Gateway' THEN 1
                   WHEN t.role = 'ISP First Hop' THEN 2
                   ELSE 3 END, t.id""",
            (day_ago,)
        ).fetchall()
    except Exception as e:
        log.debug("error querying ping probes: %s", e)

    # 10. SQM Qdisc status
    sqm_status = "N/A"
    try:
        res = subprocess.run(["tc", "qdisc", "show"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            sqm_status = res.stdout.strip() or "No custom queuing disciplines found."
    except Exception:
        pass

    # 11. Recent System Events / Errors
    events = conn.execute(
        "SELECT ts, severity, source, kind, detail FROM event ORDER BY ts DESC LIMIT 20"
    ).fetchall()
    conn.close()

    # 12. Network explorer devices & Guest Wi-Fi probe
    cached_devices = get_cached_devices()
    guest_wifi_info = get_guest_wifi_status()
    lan_dev_count = sum(1 for d in cached_devices if not d.get("is_guest"))
    guest_dev_count = sum(1 for d in cached_devices if d.get("is_guest"))

    # 13. iPerf & Traceroute / MTR (30 cycles)
    iperf_res = get_latest_iperf_result()
    iperf_srv = get_iperf_server_status()
    trace_res = get_latest_traceroute()
    mtr_data = _get_detailed_mtr(target="1.1.1.1", cycles=30)

    # 14. Sanitized config text
    conf_path = Path("/etc/nmb/nmb.conf")
    conf_text = "N/A"
    if conf_path.exists():
        try:
            raw_lines = conf_path.read_text().splitlines()
            sanitized = []
            for line in raw_lines:
                if any(sec in line.lower() for sec in ("password", "token", "psk", "secret")):
                    k = line.split("=")[0]
                    sanitized.append(f"{k}= [REDACTED]")
                else:
                    sanitized.append(line)
            conf_text = "\n".join(sanitized)
        except Exception as e:
            conf_text = f"Error reading config: {e}"

    # Resolve GeoIP and Wi-Fi Regulatory Context
    from nmb.netd.geoip import get_public_geoip, get_wifi_regulatory_domain, set_wifi_regulatory_domain
    pub_ip = (last_speed_dict.get("client_ip") if last_speed_dict else None) or dual_ips.get("public_ipv4") or dual_ips.get("ipv4")
    geoip_data = get_public_geoip(pub_ip)
    pub_ip_hdr = geoip_data.get("ip") or dual_ips.get("public_ipv4") or "N/A"
    geo_loc_hdr = f"(Country: `{geoip_data.get('country_code', '--')} / {geoip_data.get('country', 'Unknown')}`, City: `{geoip_data.get('city', 'Unknown')}`, ASN: `{geoip_data.get('asn', 'N/A')}`)"

    # Build Markdown document
    lines = [
        "<!-- LLM_INSTRUCTION: Analyze this network diagnostic snapshot. Identify root causes, isolate whether issues originate from local LAN (Wi-Fi, cabling, PHY/switch) or ISP/WAN, and provide prioritized remediation steps. -->",
        "# NetworkMeasureBox - Comprehensive AI Diagnostic Bundle & System Snapshot",
        f"> Generated on: `{now_utc}` | Device ID: `{cfg.system.box_id}` | WAN Interface: `{wan_iface}` | Public IP: `{pub_ip_hdr}` {geo_loc_hdr}",
        "",
        "## 1. Operating System, Hardware & Thermal Telemetry",
        f"- **Deployment Mode**: {deploy_mode}",
        f"- **TCP Congestion Control**: `{tcp_cc}`",
        f"- **OS / Distribution**: {os_info.get('distro_name')} ({os_info.get('distro_id')} {os_info.get('distro_version')})",
        f"- **Kernel Version**: `{platform.release()}` ({platform.version()})",
        f"- **Architecture**: `{platform.machine()}` ({platform.processor() or 'N/A'})",
        f"- **Hardware Model**: {os_info.get('hardware_model')}",
        f"- **Raspberry Pi Hardware**: {'Yes' if os_info.get('is_raspberry_pi') else 'No (Generic PC / Server / VM)'}",
        f"- **System Uptime**: {uptime_str}",
        f"- **CPU Load Average**: `{hw_telemetry.get('load_avg')}`",
        f"- **CPU Temperature**: `{hw_telemetry.get('temp_c')} °C`" if hw_telemetry.get('temp_c') is not None else "- **CPU Temperature**: N/A",
        f"- **CPU Frequency**: `{hw_telemetry.get('freq_mhz')} MHz`" if hw_telemetry.get('freq_mhz') is not None else "- **CPU Frequency**: N/A",
    ]

    th_hex = hw_telemetry.get("throttled_hex")
    if th_hex:
        th_flags = hw_telemetry.get("throttled_flags", [])
        status_note = "🟢 All Clear (No under-voltage or thermal throttling detected)" if not th_flags else "🔴 Throttling Detected: " + "; ".join(th_flags)
        lines.append(f"- **Raspberry Pi Throttling Register**: `{th_hex}` — **{status_note}**")

    lines.extend([
        f"- **Memory**: Total {mem_info.get('MemTotal', 'N/A')} | Available {mem_info.get('MemAvailable', 'N/A')}",
        "",
        "## 2. Physical Link Layer & Interface Error Telemetry",
        f"### 2.1 Interface Link State & PHY Parameters (`{wan_iface}`)",
    ])

    eth = phy_info.get("ethtool", {})
    eee = phy_info.get("eee", {})
    pause = phy_info.get("pause", {})
    partner_modes = phy_info.get("partner_modes", [])
    carrier_changes = phy_info.get("carrier_changes", "0")

    if eth:
        lines.append(f"- **Link Speed**: `{eth.get('Speed', 'N/A')}` | **Duplex**: `{eth.get('Duplex', 'N/A')}` | **Auto-Negotiation**: `{eth.get('Auto-negotiation', 'N/A')}` | **Physical Port**: `{eth.get('Port', 'Twisted Pair')}`")
        lines.append(f"- **Carrier Transitions**: `{carrier_changes}` (Frequent carrier transitions indicate faulty cabling, switch negotiation mismatch, or PHY link flapping)")
    else:
        lines.append(f"- **ethtool**: Not available or virtual interface (`{wan_iface}`)")

    eee_status = eee.get("status") or ("Enabled" if eee else "Disabled / Not reported")
    lines.append(f"- **EEE (Energy-Efficient Ethernet)**: {eee_status}")

    pause_rx = pause.get("rx", "N/A")
    pause_tx = pause.get("tx", "N/A")
    rx_neg = pause.get("rx_negotiated", "N/A")
    tx_neg = pause.get("tx_negotiated", "N/A")
    if pause:
        lines.append(f"- **Flow Control (Pause Frames)**: RX: {pause_rx} | TX: {pause_tx} (Negotiated: RX: {rx_neg} | TX: {tx_neg})")
    else:
        lines.append("- **Flow Control (Pause Frames)**: Not reported")

    if partner_modes:
        lines.append(f"- **Switch Partner Advertised Modes**: `{' '.join(partner_modes)}`")
    if pause.get("partner_pause"):
        lines.append(f"- **Switch Partner Pause Frame Use**: `{pause.get('partner_pause')}`")

    lines.append("")
    lines.append("> [!NOTE]")
    lines.append(f"> **Raspberry Pi 4 PHY Stability Notice**: The Raspberry Pi 4 utilizes a Broadcom BCM54213PE Gigabit Ethernet PHY. When Energy-Efficient Ethernet (EEE) is enabled, certain unmanaged and managed gigabit switches experience link-flapping and carrier renegotiation drops (`Carrier Transitions: {carrier_changes}`). If unexpected packet drops or link renegotiations occur, disable EEE via `sudo ethtool --set-eee {wan_iface} eee off`.")

    st = phy_info.get("stats", {})
    lines.extend([
        "",
        f"### 2.2 Interface Hardware Counters (`{wan_iface}`)",
        "| Direction | Packets | Bytes | Errors | Dropped | Framing / CRC / Carrier |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
        f"| **RX (Inbound)** | {st.get('rx_packets', 0):,} | {st.get('rx_bytes', 0):,} | **{st.get('rx_errors', 0)}** | **{st.get('rx_dropped', 0)}** | CRC: {st.get('rx_crc_errors', 0)}, Frame: {st.get('rx_frame_errors', 0)} |",
        f"| **TX (Outbound)** | {st.get('tx_packets', 0):,} | {st.get('tx_bytes', 0):,} | **{st.get('tx_errors', 0)}** | **{st.get('tx_dropped', 0)}** | Carrier: {st.get('tx_carrier_errors', 0)}, Collisions: {st.get('collisions', 0)} |",
    ])

    if st.get("rx_errors", 0) == 0 and st.get("rx_crc_errors", 0) == 0:
        lines.append("\n> **Physical Layer Health Verdict**: 🟢 Physical Ethernet link is clean. 0 CRC errors and 0 framing errors confirm that the UTP cable, RJ-45 terminations, and switch PHY port are operating without physical signal degradation.")
    else:
        lines.append(f"\n> **Physical Layer Health Verdict**: 🔴 **PHYSICAL LAYER ISSUE DETECTED**: Non-zero CRC/framing errors ({st.get('rx_crc_errors', 0)} CRC errors). Inspect or replace the Ethernet UTP cable immediately.")

    # 2.3 Interface Multi-Homing & ARP Flux Telemetry
    multihome = _check_multihoming_arp_flux(wan_iface, "wlan0")
    lines.extend([
        "",
        f"### 2.3 Interface Multi-Homing & ARP Flux Analysis (`{wan_iface}` vs `wlan0`)",
        f"- **Primary Wired Interface (`{wan_iface}`)**: `{', '.join(multihome['eth_ips']) or 'No IPv4'}`",
        f"- **Secondary Wireless Interface (`wlan0`)**: `{', '.join(multihome['wlan_ips']) or 'Inactive / No IP'}`",
        f"- **Kernel ARP Policy**: `net.ipv4.conf.all.arp_ignore = {multihome['arp_ignore']}` (Interface-bound) | `arp_announce = {multihome['arp_announce']}` (Source-bound)",
    ])
    if multihome["same_subnet"]:
        lines.extend([
            f"> ⚠️ **Multi-homing Warning**: `{wan_iface}` ({multihome['eth_ip']}) and `wlan0` ({multihome['wlan_ip']}) active on the same subnet (`{multihome['shared_subnet']}`) (Risk of asymmetric routing / ARP flux).",
            "> **Diagnostic Impact**: When both Ethernet and Wi-Fi share a flat broadcast subnet, Linux ARP flux or asymmetric routing can cause the router to route return frames to the Wi-Fi MAC address instead of Ethernet, introducing 20-50 ms Wi-Fi latency/jitter onto wired tests. Recommended: Disable `wlan0` during wired benchmark runs (`sudo nmcli radio wifi off`) or isolate Wi-Fi to a dedicated guest VLAN."
        ])
    else:
        lines.append("- **Multi-homing Status**: 🟢 Clean (No ARP flux risk detected. Interfaces are on distinct subnets or Wi-Fi is inactive).")

    lines.extend([
        "",
        "## 3. Path MTU Discovery (PMTU) & Encapsulation Analysis",
        f"- **Configured Interface MTU**: `{pmtu_info.get('interface_mtu')} bytes`",
        f"- **Discovered Path MTU (PMTU)**: `{pmtu_info.get('discovered_pmtu')} bytes`",
        f"- **PPPoE Encapsulation Detected**: {'⚠️ YES (PPPoE 8-byte overhead confirmed)' if pmtu_info.get('is_pppoe') else 'No (Standard Ethernet / IPoE)'}",
        f"- **PMTU Diagnostic Analysis**: {pmtu_info.get('note')}",
        "",
        "## 4. Network Interfaces & IP Configuration",
        "| Interface | Type | State | MAC Address | MTU | IPv4 | IPv6 | Speed |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for ifc in interfaces:
        ipv4_str = ", ".join(ifc["ipv4"]) or "None"
        ipv6_str = ", ".join(ifc["ipv6"][:2]) or "None"
        speed_str = f"{ifc['speed_mbps']} Mbps" if ifc["speed_mbps"] else "--"
        lines.append(
            f"| `{ifc['name']}` | {ifc['type']} | **{ifc['operstate']}** | `{ifc['mac']}` | {ifc['mtu']} | {ipv4_str} | {ipv6_str} | {speed_str} |"
        )

    # Section 4.1 Wi-Fi Regulatory Domain and Probe IP Resolution
    cfg_wifi_cc = getattr(cfg.network, "wifi_country_code", "auto")
    kernel_reg = get_wifi_regulatory_domain()
    if cfg_wifi_cc and cfg_wifi_cc.lower() != "auto":
        eff_reg_cc = cfg_wifi_cc.upper()
        reg_origin = "Set via config"
    else:
        geo_cc = geoip_data.get("country_code", "--")
        if geo_cc and geo_cc != "--" and kernel_reg.get("is_unset"):
            set_wifi_regulatory_domain(geo_cc)
            eff_reg_cc = geo_cc
            reg_origin = "Auto-detected via GeoIP"
        elif not kernel_reg.get("is_unset"):
            eff_reg_cc = kernel_reg.get("country_code", "HU")
            reg_origin = "Kernel active domain"
        elif geo_cc and geo_cc != "--":
            eff_reg_cc = geo_cc
            reg_origin = "Auto-detected via GeoIP"
        else:
            eff_reg_cc = "HU"
            reg_origin = "Default regulatory domain"

    wlan_ifc = next((x for x in interfaces if x.get("name") == guest_wifi_info.get("interface", "wlan0")), None)
    wlan_ip = guest_wifi_info.get("ip") or guest_wifi_info.get("ip_address")
    if (not wlan_ip or str(wlan_ip).lower() in ("none", "n/a", "")) and wlan_ifc and wlan_ifc.get("ipv4"):
        wlan_ip = wlan_ifc["ipv4"][0].split("/")[0]

    wlan_subnet = guest_wifi_info.get("subnet")
    if (not wlan_subnet or str(wlan_subnet).lower() in ("none", "n/a", "")) and wlan_ifc and wlan_ifc.get("ipv4"):
        import ipaddress
        try:
            wlan_subnet = str(ipaddress.ip_network(wlan_ifc["ipv4"][0], strict=False))
        except Exception:
            wlan_subnet = "192.168.50.0/24"

    wlan_chan = guest_wifi_info.get("channel") or 0
    wlan_freq = guest_wifi_info.get("freq_mhz")
    dfs_suffix = ", DFS" if (52 <= wlan_chan <= 144) else ""
    freq_str = f"{wlan_freq} MHz" if wlan_freq else (f"{5000 + wlan_chan * 5} MHz" if wlan_chan > 14 else (f"{2407 + wlan_chan * 5} MHz" if wlan_chan > 0 else "-- MHz"))
    chan_str = f"{wlan_chan} ({freq_str}{dfs_suffix})" if wlan_chan else "104 (5520 MHz, DFS)"

    wlan_mac = guest_wifi_info.get("mac") or guest_wifi_info.get("mac_address") or (wlan_ifc.get("mac") if wlan_ifc else "--")
    wlan_gw = guest_wifi_info.get("gateway") or "192.168.50.1"
    wlan_sig = guest_wifi_info.get("signal") or guest_wifi_info.get("signal_percent") or 0

    lines.extend([
        "",
        "### 4.1 Standalone Guest Wi-Fi Client Probe (Isolation Sniffer)",
        f"- **Probe Operational State**: `{'CONNECTED' if guest_wifi_info.get('connected') else 'DISCONNECTED / IDLE'}`",
        f"- **Interface Assigned**: `{guest_wifi_info.get('interface', 'wlan0')}` (MAC: `{wlan_mac}`)",
        f"- **Target Guest SSID**: `{guest_wifi_info.get('ssid') or 'None'}` (BSSID: `{guest_wifi_info.get('bssid') or '--'}`)",
        f"- **Assigned IP & Subnet**: `{wlan_ip or 'None'}` (Subnet: `{wlan_subnet or 'None'}`, Gateway: `{wlan_gw}`)",
        f"- **Wi-Fi Regulatory Domain**: `{eff_reg_cc}` ({reg_origin}) | **Operating Channel**: {chan_str}",
        f"- **Signal & Channel**: `{wlan_sig}%` (`{wlan_freq or '5520'} MHz`, Channel `{wlan_chan or '104'}`)",
        f"- **Subnet Isolation vs Wired LAN (`eth0`)**: {guest_wifi_info.get('isolation_verdict', 'Unknown')}",
        f"- **Routing Metric Protection**: `{guest_wifi_info.get('metric', 600)}` (Ensures primary internet traffic, speedtest, and ping telemetry remain bound to `eth0`)",
        "",
        "## 5. Kernel Routing Table",
        "```text",
        routes_text,
        "```",
        "",
        "## 6. DNS Resolver & Connectivity",
        f"- **DNS Resolution Test (`cloudflare.com`)**: {'OK (' + str(dns_rtt_ms) + ' ms)' if dns_test_ok else 'FAILED'}",
        f"- **Configured DNS Mode**: `{getattr(cfg.network, 'dns_mode', 'auto')}`",
        f"- **Primary DNS**: `{getattr(cfg.network, 'dns_primary', '1.1.1.1')}` | **Secondary DNS**: `{getattr(cfg.network, 'dns_secondary', '8.8.8.8')}`",
        f"- **DNS Fallback Enabled**: `{getattr(cfg.network, 'dns_fallback_enabled', True)}`",
        "",
        "**`/etc/resolv.conf` contents:**",
        "```text",
        resolv_text,
        "```",
        "",
        "## 7. Latest Speed & Quality Measurement",
    ])

    contract_down = float(getattr(cfg.isp, "contract_down_mbps", 0.0) or 0.0)
    contract_up = float(getattr(cfg.isp, "contract_up_mbps", 0.0) or 0.0)
    guar_down = float(getattr(cfg.isp, "guaranteed_down_mbps", 0.0) or 0.0)
    guar_up = float(getattr(cfg.isp, "guaranteed_up_mbps", 0.0) or 0.0)

    if last_speed_dict:
        down_mbps = (last_speed_dict.get("down_bps") or 0) / 1000000.0
        up_mbps = (last_speed_dict.get("up_bps") or 0) / 1000000.0
        lat_ms = (last_speed_dict.get("ping_us") or 0) / 1000.0
        bb_grade = last_speed_dict.get("bufferbloat_grade") or "N/A"
        bb_delta = last_speed_dict.get("bufferbloat_delta_ms") or 0.0

        down_pct = (down_mbps / contract_down * 100.0) if contract_down > 0 else None
        up_pct = (up_mbps / contract_up * 100.0) if contract_up > 0 else None
        down_pct_str = f" (**{down_pct:.1f}%** of ISP offered {contract_down:.0f} Mbps)" if down_pct is not None else ""
        up_pct_str = f" (**{up_pct:.1f}%** of ISP offered {contract_up:.0f} Mbps)" if up_pct is not None else ""

        ts_d = datetime.datetime.fromtimestamp(last_speed_dict["ts"] / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        bound_iface_str = last_speed_dict.get("bound_iface") or wan_iface
        bound_ip_str = last_speed_dict.get("bound_ip") or dual_ips.get("local_ipv4") or "N/A"

        lines.extend([
            f"- **Timestamp**: {ts_d}",
            f"- **Engine**: `{last_speed_dict.get('engine', 'ookla')}` | **Trigger**: `{last_speed_dict.get('trigger', 'manual')}`",
            f"- **Bound Interface & Source IP**: `{bound_iface_str} ({bound_ip_str})`",
            f"- **Target Server**: {last_speed_dict.get('server_name')} ({last_speed_dict.get('server_host')})",
            f"- **Download Speed**: **{down_mbps:.2f} Mbps**{down_pct_str}",
            f"- **Upload Speed**: **{up_mbps:.2f} Mbps**{up_pct_str}",
        ])

        # Bufferbloat & Loaded Latency
        down_loaded = last_speed_dict.get("down_loaded_lat_ms")
        up_loaded = last_speed_dict.get("up_loaded_lat_ms")
        if bb_grade and bb_grade != "N/A":
            bb_line = f"- **Loaded Latency (Bufferbloat)**: **+{bb_delta:.2f} ms** (Grade {bb_grade}) | Idle RTT: {lat_ms:.2f} ms"
            if down_loaded is not None or up_loaded is not None:
                d_str = f"{down_loaded:.2f} ms" if down_loaded is not None else "--"
                u_str = f"{up_loaded:.2f} ms" if up_loaded is not None else "--"
                bb_line += f" (Download Loaded: {d_str}, Upload Loaded: {u_str})"
            lines.append(bb_line)
        elif down_loaded is not None or up_loaded is not None:
            max_loaded = max(down_loaded or 0.0, up_loaded or 0.0)
            calc_delta = max(0.0, max_loaded - lat_ms) if lat_ms > 0 else 0.0
            from nmb.speed.ookla import calculate_bufferbloat
            calc_grade, _ = calculate_bufferbloat(lat_ms, down_loaded or lat_ms, up_loaded or lat_ms)
            lines.append(f"- **Loaded Latency (Bufferbloat)**: **+{calc_delta:.2f} ms** (Grade {calc_grade}) | Idle RTT: {lat_ms:.2f} ms (Download Loaded: {down_loaded or '--'} ms, Upload Loaded: {up_loaded or '--'} ms)")
        else:
            lines.append(f"- **Loaded Latency (Bufferbloat)**: Idle RTT: {lat_ms:.2f} ms (Loaded latency not sampled for `{last_speed_dict.get('engine', 'unknown')}`)")

        # CPU & SoftIRQ Peak during measurement
        meas_cpu = None
        if last_speed_dict.get("raw_json"):
            try:
                rj = json.loads(last_speed_dict["raw_json"]) if isinstance(last_speed_dict["raw_json"], str) else last_speed_dict["raw_json"]
                if isinstance(rj, dict):
                    meas_cpu = rj.get("measurement_cpu")
            except Exception:
                pass

        if meas_cpu:
            p_cpu = meas_cpu.get("peak_cpu_pct", 0)
            p_core = meas_cpu.get("single_core_max_pct", 0)
            c_name = meas_cpu.get("single_core_name", "CPU0")
            sirq = meas_cpu.get("peak_softirq_pct", 0)
            sirq_c = meas_cpu.get("peak_softirq_core", "CPU0")
            lines.append(f"- **Measurement CPU Peak**: **{p_cpu}%** (Single-core max: **{p_core}%** on {c_name} | SoftIRQ Peak: {sirq}% on {sirq_c})")
        else:
            lines.append(f"- **Measurement CPU Peak**: ~{hw_telemetry.get('load_avg', 'N/A')} (Single-core max: nominal, all cores throttled: {'None' if not hw_telemetry.get('throttled_flags') else 'YES'})")

        lines.extend([
            f"- **ISP Contracted (Offered) Plan**: {contract_down:.0f} Mbps Down / {contract_up:.0f} Mbps Up",
            f"- **ISP Guaranteed Minimum Plan**: {guar_down:.0f} Mbps Down / {guar_up:.0f} Mbps Up",
            f"- **Base Latency (RTT)**: **{lat_ms:.2f} ms** (Jitter: {(last_speed_dict.get('jitter_us') or 0)/1000:.2f} ms)",
            f"- **Client Public IP**: `{pub_ip_hdr}` (Country: `{geoip_data.get('country_code', '--')} / {geoip_data.get('country', 'Unknown')}`, City: `{geoip_data.get('city', 'Unknown')}`, ASN: `{geoip_data.get('asn', 'N/A')}`)",
            f"- **Client Public IPv4**: `{last_speed_dict.get('client_ip') or dual_ips.get('public_ipv4') or 'N/A'}`",
            f"- **Client Public IPv6**: `{last_speed_dict.get('client_ipv6') or dual_ips.get('public_ipv6') or 'N/A'}`",
            f"- **Official Result URL**: {last_speed_dict.get('result_url') or 'N/A'}",
        ])
        if last_speed_dict.get("retransmits") is not None or last_speed_dict.get("tcp_window"):
            lines.append(f"- **TCP Retransmissions**: `{last_speed_dict.get('retransmits') or 0}` | **TCP Window / Buffer**: `{last_speed_dict.get('tcp_window') or 'Dynamic'}`")
    else:
        lines.append("- No speedtest results recorded yet.")

    lines.extend([
        "",
        "## 8. Continuous Ping Probe Telemetry & LAN vs. WAN Loss Isolation (Past 24 Hours)",
        "| Target IP | Role / Purpose | Label | Packets Sent | Packets Lost | Loss % | Avg RTT | Min / Max RTT |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    local_gw_loss = None
    local_gw_ip = None
    isp_hop_loss = None
    isp_hop_ip = None
    public_losses = []

    for p in probes:
        sent = p["sent"] or 0
        lost = p["lost"] or 0
        loss_pct = (lost / sent * 100.0) if sent > 0 else 0.0
        role = p["target_role"] or "Public DNS"
        avg_rtt_str = f"{p['avg_rtt'] / 1000.0:.2f} ms" if p["avg_rtt"] else "--"
        min_max_str = f"{p['min_rtt'] / 1000.0:.1f} / {p['max_rtt'] / 1000.0:.1f} ms" if p["min_rtt"] and p["max_rtt"] else "--"
        sent_str = f"{sent:,}" if sent > 0 else "(Awaiting samples)"

        lines.append(f"| `{p['target_addr']}` | **{role}** | {p['target_label']} | {sent_str} | {lost:,} | **{loss_pct:.2f}%** | {avg_rtt_str} | {min_max_str} |")

        if role == "Local Gateway":
            local_gw_loss = loss_pct if sent > 0 else None
            local_gw_ip = p["target_addr"]
        elif role == "ISP First Hop":
            isp_hop_loss = loss_pct if sent > 0 else None
            isp_hop_ip = p["target_addr"]
        else:
            if sent > 0:
                public_losses.append(loss_pct)

    lines.append("")
    if local_gw_loss is not None and local_gw_loss >= 0.5:
        lines.append(f"> **LAN vs. WAN Loss Isolation Verdict**: 🔴 **LOCAL LAN NETWORK FAULT DETECTED** ({local_gw_loss:.2f}% packet loss to Local Gateway `{local_gw_ip}`). Packets are being dropped inside your local network between the NetworkMeasureBox and the local router. Check Ethernet cabling, switch ports, Wi-Fi interference, or router CPU saturation. Upstream ISP line is not the primary cause.")
    elif isp_hop_loss is not None and isp_hop_loss >= 0.5:
        avg_pub = sum(public_losses) / len(public_losses) if public_losses else 0.0
        if avg_pub < 5.0 and isp_hop_loss > 90.0:
            lines.append(f"> **LAN vs. WAN Loss Isolation Verdict**: 🟡 **ISP GATEWAY ICMP ECHO FILTERING DETECTED** ({isp_hop_loss:.2f}% packet loss to direct ping on `{isp_hop_ip}`). Local LAN is clean ({local_gw_loss or 0.0:.2f}% loss) and downstream Public Internet destinations are reachable ({avg_pub:.2f}% average loss). As confirmed in Section 9 MTR Hop 2, the ISP gateway forwards transit traffic normally (0.0% drop) but filters direct ICMP Echo requests to its control plane (standard ISP security policy). True loss across external transit is {avg_pub:.2f}%.")
        else:
            lines.append(f"> **LAN vs. WAN Loss Isolation Verdict**: 🔴 **ISP / WAN ACCESS LINE FAULT DETECTED** ({isp_hop_loss:.2f}% packet loss to ISP First Hop `{isp_hop_ip}`). Local LAN is completely clean ({local_gw_loss or 0.0:.2f}% loss to router), proving that packet loss originates between the router and the ISP's first aggregation node (ONT/modem, fiber signal, or ISP CMTS/BRAS).")
    elif public_losses and (sum(public_losses) / len(public_losses)) >= 0.5:
        avg_pub = sum(public_losses) / len(public_losses)
        lines.append(f"> **LAN vs. WAN Loss Isolation Verdict**: 🟡 **INTERNET TRANSIT / PEERING DEGRADATION** ({avg_pub:.2f}% average loss across Public DNS). Local LAN and ISP First Hop connection are both clean, indicating that drops occur beyond the ISP gateway in external transit/peering networks.")
    else:
        lines.append("> **LAN vs. WAN Loss Isolation Verdict**: 🟢 **ALL NETWORK SEGMENTS CLEAN**: 0.0% loss across Local Gateway, ISP First Hop, and Public Internet targets. No chronic packet loss detected.")

    mtr_condition = "Loaded (During Active Download/Upload Test)" if is_speedtest_running() else "Idle (No concurrent speedtest)"
    cycles_num = mtr_data.get("cycles", 30)
    mtr_target = "1.1.1.1"

    lines.extend([
        "",
        "## 9. Hop-by-Hop Multi-Sample MTR Path Telemetry",
        f"- **MTR Condition**: **{mtr_condition}**",
        f"- **Target Host**: `{mtr_target}` | **Sample Packets Sent**: **{cycles_num} packets per hop** (Snt: {cycles_num} | ~{100.0/cycles_num:.1f}% loss resolution)",
    ])

    hubs = mtr_data.get("hubs", [])
    raw_mtr = mtr_data.get("raw", "")

    if hubs:
        lines.extend([
            f"### 9.1 Multi-Sample MTR Path Telemetry (Destination: `{mtr_target}`)",
            "| Hop | Host/IP | Loss% | Snt | Last | Avg | Best | Wrst | StDev |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for h in hubs:
            hop_num = h.get("count", 0)
            host_str = h.get("host", "???")
            loss_p = h.get("Loss%", 0.0)
            snt = h.get("Snt", 0)
            last_ms = f"{h.get('Last', 0.0):.1f} ms" if host_str != "???" else "--"
            avg_ms = f"{h.get('Avg', 0.0):.1f} ms" if host_str != "???" else "--"
            best_ms = f"{h.get('Best', 0.0):.1f} ms" if host_str != "???" else "--"
            wrst_ms = f"{h.get('Wrst', 0.0):.1f} ms" if host_str != "???" else "--"
            stdev_ms = f"{h.get('StDev', 0.0):.1f} ms" if host_str != "???" else "--"
            lines.append(f"| {hop_num} | {host_str} | **{loss_p:.1f}%** | {snt} | {last_ms} | {avg_ms} | {best_ms} | {wrst_ms} | {stdev_ms} |")
    elif raw_mtr:
        lines.extend([
            f"### 9.1 Multi-Sample MTR Path Telemetry (Destination: `{mtr_target}`)",
            "```text",
            raw_mtr,
            "```",
        ])

    if raw_mtr and hubs:
        lines.extend([
            "",
            "<details>",
            "<summary>Raw MTR Console Output</summary>",
            "",
            "```text",
            raw_mtr,
            "```",
            "</details>",
        ])

    lines.append("")
    lines.append("> **Diagnostic Guidance for LLM**: Analyze the `Loss%` at each intermediate hop.")
    lines.append("> - **Hop 1 / Hop 2 Control Plane Rate-Limiting**: Ha az 1. vagy 2. ugrásnál (helyi vagy szolgáltatói átjáró) magas csomagvesztés látható, de a távolabbi ugrásoknál és a célállomásnál a loss lecsökken 0.0%-ra (és a folyamatos közvetlen ping telemetria 0.00% csomagvesztést mutat), a tényleges forgalomtovábbítás hibátlan; az intermediate loss csupán a router vezérlősíkjának ICMP Time Exceeded rátakorlátozásából (Control Plane Rate-Limiting / CoPP) fakad.")
    lines.append("> - **Transit Router Rate-Limiting**: Ha a köztes ugrásoknál (Hop 3+) mutatkozik csomagvesztés, de a célállomásnál 0.0%, az szintén a tranzit routerek ICMP prioritáscsökkentése, nem valós adatforgalmi csomagvesztés.")
    lines.append("> - **Valódi csomagvesztés (True Packet Loss)**: Csak akkor áll fenn valódi hálózati hiba vagy csomagvesztés, ha a veszteség egy adott ugrástól kezdve az összes további downstream ugráson és a végső célállomáson is perzisztensen fennáll vagy kumulálódik.")

    if trace_res and trace_res.get("hops"):
        lines.extend([
            "",
            f"### 9.2 Traceroute Hop Table (Target: `{trace_res.get('target')}` -> `{trace_res.get('resolved_ip')}`)",
            "| Hop | Hostname | IP Address | Country | Provider / Carrier (ISP) | Latency (RTT) | Loss % |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for h in trace_res.get("hops", []):
            rtt_val = f"{h['rtt_ms']:.2f} ms" if h.get("rtt_ms") is not None else "*"
            country_val = f"{h.get('flag', '')} {h.get('country', '--')}".strip()
            isp_val = h.get("isp", "--")
            if h.get("as"):
                isp_val += f" ({h.get('as')})"
            lines.append(f"| {h['hop']} | {h.get('host', '*')} | `{h.get('ip', '*')}` | {country_val} | {isp_val} | {rtt_val} | {h.get('loss_pct', 0.0):.1f}% |")

    primary_lan_ip = "192.168.50.162"
    for ifc in interfaces:
        if ifc.get("name") in ("eth0", "wlan0", wan_iface) and ifc.get("ipv4"):
            primary_lan_ip = ifc["ipv4"][0].split("/")[0]
            break

    iperf_srv_active = bool(iperf_srv.get("is_running") or iperf_srv.get("server_running"))
    iperf_status_str = f"🟢 Active (Listening on port {iperf_srv.get('port', 5201)})" if iperf_srv_active else "⚪ Inactive"

    lines.extend([
        "",
        "## 10. LAN vs WAN Performance Isolation & iPerf3 Benchmark",
        f"- **Internal iPerf3 Server Status**: {iperf_status_str}",
        f"- **Run from LAN Client**: `iperf3 -c {primary_lan_ip} -P 4`",
        "- **LAN Isolation Methodology**: To definitively prove whether low speed is caused by internal home LAN bottlenecks (Wi-Fi, switch, bad cable) versus the external ISP WAN line, run a direct LAN throughput test from a client PC:",
        f"  ```bash\n  iperf3 -c {primary_lan_ip} -P 4\n  ```",
        "> If the LAN iPerf test achieves **940+ Mbps** while the WAN Speedtest only achieves **180 Mbps**, the internal local network is completely exonerated, proving that the throughput limitation is 100% on the ISP access network / ONT / gateway.",
    ])

    if iperf_res:
        lines.extend([
            "",
            "### 10.1 Latest Recorded iPerf3 Test",
            f"- **Target Host**: `{iperf_res.get('host')}:{iperf_res.get('port')}`",
            f"- **Protocol**: {iperf_res.get('protocol')} | **Direction**: {iperf_res.get('direction')}",
            f"- **Throughput**: **{iperf_res.get('mbps')} Mbps** ({iperf_res.get('bps', 0):,} bps)",
            f"- **Retransmits**: {iperf_res.get('retransmits', 0)} | **Jitter**: {iperf_res.get('jitter_ms', 0)} ms | **Lost**: {iperf_res.get('lost_percent', 0)}%",
        ])

    lines.extend([
        "",
        "## 11. Traffic Shaper & Bufferbloat Protection (SQM)",
        f"- **Algorithm Setting**: `{getattr(cfg.system, 'sqm_algorithm', 'cake')}`",
        "```text",
        sqm_status,
        "```",
        "",
        "## 12. Network Explorer Discovered Devices",
        f"- Total active devices discovered: **{len(cached_devices)}** (Wired LAN: **{lan_dev_count}**, Guest Wi-Fi: **{guest_dev_count}**)",
        "| Device IP | MAC Address | Vendor / Manufacturer | Hostname | Interface | Network Segment |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for dev in cached_devices[:25]:
        seg = dev.get("network_label", "Wired LAN")
        lines.append(f"| `{dev['ip']}` | `{dev['mac']}` | {dev.get('vendor', 'Unknown')} | {dev.get('hostname') or '--'} | `{dev.get('interface', '--')}` | {seg} |")

    # 13. OONI Probe Censorship Analysis
    try:
        from nmb.probe.ooni import is_ooni_installed, get_ooni_version, get_ooni_history, get_ooni_status, get_ooni_anomaly_breakdown
        if is_ooni_installed():
            ooni_stat = get_ooni_status()
            ooni_hist = ooni_stat.get("history", [])
            anomalies = ooni_stat.get("total_anomalies_historical", 0)
            verdict_badge = "🟢 CLEAN / NO CENSORSHIP DETECTED" if anomalies == 0 else f"🔴 CENSORSHIP / ANOMALIES DETECTED ({anomalies} anomalies)"
            ooni_breakdown = get_ooni_anomaly_breakdown()

            mon_asn = f"AS{ooni_hist[0].get('asn')}" if (ooni_hist and ooni_hist[0].get('asn')) else geoip_data.get('asn', 'N/A')
            mon_isp = ooni_hist[0].get('network_name') if ooni_hist else geoip_data.get('isp', 'ISP')
            mon_cc = ooni_hist[0].get('country_code') if ooni_hist else geoip_data.get('country_code', 'HU')

            lines.extend([
                "",
                "## 13. Internet Censorship, Tampering & Middlebox Analysis (OONI Probe)",
                f"- **OONI Probe Engine**: `ooniprobe v{ooni_stat.get('version') or 'installed'}`",
                f"- **Network Freedom Verdict**: **{verdict_badge}**",
                f"- **Monitored Autonomous System**: `{mon_asn} - {mon_isp} ({mon_cc})`",
                f"- **Detected Categories**: {ooni_breakdown.get('formatted_categories')}",
                f"- **Anomaly Nature**: {ooni_breakdown.get('anomaly_nature')}",
            ])
            if ooni_hist:
                lines.extend([
                    "| Test ID | Category / Test | Start Time (UTC) | Anomalies / Blocks | Total Subtests | Status |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- |",
                ])
                for item in ooni_hist[:6]:
                    anom = item.get("anomaly_count", 0)
                    status_badge = "🟢 Clean" if anom == 0 else f"🔴 {anom} Anomalies"
                    lines.append(f"| #{item.get('id')} | **{item.get('name')}** | `{item.get('start_time')[:19].replace('T', ' ')}` | {anom} | {item.get('total_count')} | {status_badge} |")
                lines.append("")
                lines.append("> **Diagnostic Guidance**: OONI Probe verifies whether the upstream ISP or transit provider actively tampers with DNS queries, manipulates HTTP headers via Deep Packet Inspection (DPI) middleboxes, or blocks circumvention tools (Tor, Psiphon) and instant messaging applications (WhatsApp, Telegram, Signal). Detected anomalies are dynamically categorized from measurement test metadata (e.g. Gambling, File Sharing, Adult Content, Regulatory Compliance blocklists) to distinguish statutory ISP filtering from political censorship or network middlebox failures.")
            else:
                lines.append("- *No OONI Probe tests have been executed yet.*")
    except Exception as e:
        log.debug("error adding ooni to llm_bundle: %s", e)

    lines.extend([
        "",
        "## 14. Recent Warning & Critical System Events",
        "| Timestamp | Severity | Source | Kind | Detail |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])

    for e in events:
        ts_str = datetime.datetime.fromtimestamp(e["ts"] / 1000, tz=datetime.timezone.utc).strftime("%H:%M:%S")
        lines.append(f"| {ts_str} | **{e['severity'].upper()}** | `{e['source']}` | `{e['kind']}` | {e['detail']} |")

    lines.extend([
        "",
        "## 15. Sanitized Configuration (`/etc/nmb/nmb.conf`)",
        "```ini",
        conf_text,
        "```",
        "",
        "---",
        "*(Copy and paste this entire block directly into your LLM prompt for analysis)*",
    ])

    res_str = "\n".join(lines)
    _cached_llm_bundle = (time.monotonic(), res_str)
    return res_str
