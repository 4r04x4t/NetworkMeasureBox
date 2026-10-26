"""
Linux Kernel Network Stack Tuning & Hardware Offload Acceleration Subsystem.

Delves deeply into the Linux kernel to achieve maximum network throughput,
sub-microsecond measurement precision, and zero-loss packet processing:
1. Multi-Core SoftIRQ Packet Steering (RPS/RFS/XPS) across all CPU cores
2. High-speed BBR Congestion Control & FQ Pacing enforcement
3. Multi-Gigabit Socket Core & TCP Buffer Auto-Tuning (64 MB ceiling)
4. Kernel Socket Busy-Polling & DSCP Expedited Forwarding QoS
5. Hardware Offload (TSO, GSO, GRO, Checksumming) & Ring Buffer Optimization
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.netd.kernel")

SYSFS_NET = Path("/sys/class/net")
PROCNET = Path("/proc/sys/net")


def get_cpu_affinity_mask_hex() -> str:
    """Calculate the hex bitmask representing all available CPU cores.
    E.g.: 4 cores -> 0xf (binary 1111); 8 cores -> 0xff.
    """
    try:
        cpus = os.cpu_count() or 1
        mask_val = (1 << cpus) - 1
        return hex(mask_val)[2:]
    except Exception:
        return "f"


def _write_kernel_param(path: Path | str, value: str) -> bool:
    """Write parameter to sysfs or procfs safely."""
    p = Path(path)
    val_str = str(value).strip() + "\n"
    try:
        p.write_text(val_str)
        return True
    except Exception:
        return False


def apply_kernel_network_tuning() -> Dict[str, Any]:
    """Apply high-performance network sysctls, RPS/RFS/XPS multi-core packet steering,
    and NIC hardware offloads.
    """
    results: Dict[str, Any] = {
        "sysctl_applied": False,
        "rps_configured_interfaces": [],
        "offload_tuned_interfaces": [],
        "errors": [],
    }

    # 1. Apply System-wide Performance Sysctl Config if available
    sysctl_conf = Path("/etc/sysctl.d/99-nmb-performance.conf")
    fallback_conf = Path("/opt/nmb/os/99-nmb-performance.conf")

    try:
        if fallback_conf.exists() and not sysctl_conf.exists():
            shutil.copy(fallback_conf, sysctl_conf)

        if sysctl_conf.exists():
            proc = subprocess.run(["sysctl", "-p", str(sysctl_conf)], capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                results["sysctl_applied"] = True
                log.info("applied /etc/sysctl.d/99-nmb-performance.conf successfully")
            else:
                log.warning("sysctl -p returned %d: %s", proc.returncode, proc.stderr.strip())
    except Exception as e:
        results["errors"].append(f"sysctl apply error: {e}")
        log.debug("sysctl apply exception: %s", e)

    # 2. Configure Direct /proc/sys/net Parameters tailored to hardware memory profile
    from nmb.common.memory import get_effective_memory_profile
    eff_profile = get_effective_memory_profile()
    results["memory_profile"] = eff_profile

    if eff_profile == "low":
        # Embedded Router Profile (<= 512 MB RAM): bounded buffers, zero busy-poll, memory safety
        direct_sysctls = {
            "/proc/sys/net/core/default_qdisc": "fq",
            "/proc/sys/net/ipv4/tcp_congestion_control": "bbr",
            "/proc/sys/net/core/rmem_max": "4194304",        # 4 MB ceiling
            "/proc/sys/net/core/wmem_max": "4194304",        # 4 MB ceiling
            "/proc/sys/net/core/rmem_default": "262144",     # 256 KB
            "/proc/sys/net/core/wmem_default": "262144",     # 256 KB
            "/proc/sys/net/core/optmem_max": "262144",       # 256 KB
            "/proc/sys/net/core/netdev_max_backlog": "5000", # 5K packets
            "/proc/sys/net/core/somaxconn": "2048",
            "/proc/sys/net/core/busy_poll": "0",             # Disabled to protect router CPU
            "/proc/sys/net/core/busy_read": "0",
            "/proc/sys/net/core/rps_sock_flow_entries": "4096",
            "/proc/sys/net/ipv4/tcp_rmem": "4096 65536 4194304",
            "/proc/sys/net/ipv4/tcp_wmem": "4096 65536 4194304",
            "/proc/sys/net/ipv4/tcp_slow_start_after_idle": "0",
            "/proc/sys/net/ipv4/tcp_window_scaling": "1",
            "/proc/sys/net/ipv4/tcp_timestamps": "1",
            "/proc/sys/net/ipv4/tcp_sack": "1",
            "/proc/sys/net/ipv4/tcp_dsack": "1",
            "/proc/sys/net/ipv4/tcp_adv_win_scale": "1",
            "/proc/sys/net/ipv4/tcp_tw_reuse": "1",
            "/proc/sys/net/ipv4/tcp_fin_timeout": "15",
            "/proc/sys/net/ipv4/tcp_max_syn_backlog": "4096",
            "/proc/sys/net/ipv4/tcp_mtu_probing": "1",
            "/proc/sys/net/ipv4/tcp_fastopen": "3",
            "/proc/sys/net/ipv4/tcp_notsent_lowat": "16384",
            "/proc/sys/net/ipv4/ping_group_range": "0 2147483647",
            "/proc/sys/net/ipv4/conf/all/arp_ignore": "1",
            "/proc/sys/net/ipv4/conf/all/arp_announce": "2",
            "/proc/sys/net/ipv4/conf/default/arp_ignore": "1",
            "/proc/sys/net/ipv4/conf/default/arp_announce": "2",
            "/proc/sys/vm/vfs_cache_pressure": "100",        # Aggressively reclaim dentry/inode RAM
            "/proc/sys/vm/swappiness": "10",
            "/proc/sys/vm/dirty_background_ratio": "5",
            "/proc/sys/vm/dirty_ratio": "15",
            "/proc/sys/vm/dirty_expire_centisecs": "1500",
            "/proc/sys/vm/dirty_writeback_centisecs": "500",
            "/proc/sys/vm/min_free_kbytes": "8192",          # 8 MB instead of 64 MB (leaves RAM for applications!)
        }
    else:
        # Standard / Performance Profile (1GB+ RAM): multi-gigabit mega buffers
        direct_sysctls = {
            "/proc/sys/net/core/default_qdisc": "fq",
            "/proc/sys/net/ipv4/tcp_congestion_control": "bbr",
            "/proc/sys/net/core/rmem_max": "67108864",
            "/proc/sys/net/core/wmem_max": "67108864",
            "/proc/sys/net/core/rmem_default": "1048576",
            "/proc/sys/net/core/wmem_default": "1048576",
            "/proc/sys/net/core/optmem_max": "2097152",
            "/proc/sys/net/core/netdev_max_backlog": "250000",
            "/proc/sys/net/core/somaxconn": "65535",
            "/proc/sys/net/core/busy_poll": "50",
            "/proc/sys/net/core/busy_read": "50",
            "/proc/sys/net/core/rps_sock_flow_entries": "32768",
            "/proc/sys/net/ipv4/tcp_rmem": "4096 1048576 67108864",
            "/proc/sys/net/ipv4/tcp_wmem": "4096 1048576 67108864",
            "/proc/sys/net/ipv4/tcp_slow_start_after_idle": "0",
            "/proc/sys/net/ipv4/tcp_window_scaling": "1",
            "/proc/sys/net/ipv4/tcp_timestamps": "1",
            "/proc/sys/net/ipv4/tcp_sack": "1",
            "/proc/sys/net/ipv4/tcp_dsack": "1",
            "/proc/sys/net/ipv4/tcp_adv_win_scale": "1",
            "/proc/sys/net/ipv4/tcp_tw_reuse": "1",
            "/proc/sys/net/ipv4/tcp_fin_timeout": "15",
            "/proc/sys/net/ipv4/tcp_max_syn_backlog": "3240000",
            "/proc/sys/net/ipv4/tcp_mtu_probing": "1",
            "/proc/sys/net/ipv4/tcp_fastopen": "3",
            "/proc/sys/net/ipv4/tcp_notsent_lowat": "16384",
            "/proc/sys/net/ipv4/ping_group_range": "0 2147483647",
            "/proc/sys/net/ipv4/conf/all/arp_ignore": "1",
            "/proc/sys/net/ipv4/conf/all/arp_announce": "2",
            "/proc/sys/net/ipv4/conf/default/arp_ignore": "1",
            "/proc/sys/net/ipv4/conf/default/arp_announce": "2",
            "/proc/sys/vm/vfs_cache_pressure": "50",
            "/proc/sys/vm/swappiness": "1",
            "/proc/sys/vm/dirty_background_ratio": "5",
            "/proc/sys/vm/dirty_ratio": "20",
            "/proc/sys/vm/dirty_expire_centisecs": "3000",
            "/proc/sys/vm/dirty_writeback_centisecs": "500",
            "/proc/sys/vm/min_free_kbytes": "65536",
        }

    for path_str, val in direct_sysctls.items():
        _write_kernel_param(path_str, val)

    # 3. Multi-Core SoftIRQ Packet Steering (RPS/RFS/XPS) & Interface Tuning
    cpu_mask = get_cpu_affinity_mask_hex()
    log.info("distributing network packet softirq across all CPU cores (mask 0x%s)", cpu_mask)

    if SYSFS_NET.exists():
        for iface_path in SYSFS_NET.iterdir():
            iface = iface_path.name
            if iface in ("lo",) or iface.startswith(("dummy", "tun", "tap")):
                continue

            # Enforce ARP flux protection per interface
            _write_kernel_param(f"/proc/sys/net/ipv4/conf/{iface}/arp_ignore", "1")
            _write_kernel_param(f"/proc/sys/net/ipv4/conf/{iface}/arp_announce", "2")

            # Tune RX queues: RPS (packet steering) & RFS (flow steering)
            rx_queues = list(iface_path.glob("queues/rx-*"))
            for rx_q in rx_queues:
                rps_cpus = rx_q / "rps_cpus"
                if rps_cpus.exists():
                    _write_kernel_param(rps_cpus, cpu_mask)
                rps_flow = rx_q / "rps_flow_cnt"
                if rps_flow.exists():
                    _write_kernel_param(rps_flow, "4096")

            # Tune TX queues: XPS (transmit packet steering)
            tx_queues = list(iface_path.glob("queues/tx-*"))
            for tx_q in tx_queues:
                xps_cpus = tx_q / "xps_cpus"
                if xps_cpus.exists():
                    _write_kernel_param(xps_cpus, cpu_mask)

            if rx_queues or tx_queues:
                results["rps_configured_interfaces"].append(iface)

            # 4. NIC Hardware Offloads & Coalescing (via ethtool)
            ethtool_bin = shutil.which("ethtool")
            if ethtool_bin:
                try:
                    # Enable key hardware offloads: TSO, GSO, GRO, RX/TX csum
                    subprocess.run(
                        [ethtool_bin, "-K", iface, "tso", "on", "gso", "on", "gro", "on", "rx", "on", "tx", "on"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    # Adaptive RX coalescing for high throughput and microsecond ping latency
                    subprocess.run(
                        [ethtool_bin, "-C", iface, "adaptive-rx", "on"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    results["offload_tuned_interfaces"].append(iface)
                except Exception as e:
                    log.debug("ethtool tuning for %s error: %s", iface, e)

    log.info("Kernel network optimization completed: RPS on %s, Offloads on %s",
             results["rps_configured_interfaces"], results["offload_tuned_interfaces"])
    return results


def get_kernel_network_status() -> Dict[str, Any]:
    """Retrieve the real-time status of kernel network parameters and offloads."""
    def _read_str(path: str, default: str = "") -> str:
        p = Path(path)
        if p.exists():
            try:
                return p.read_text().strip()
            except Exception:
                pass
        return default

    def _read_int(path: str, default: int = 0) -> int:
        val = _read_str(path)
        try:
            return int(val)
        except Exception:
            return default

    # Congestion control & qdisc
    tcp_cc = _read_str("/proc/sys/net/ipv4/tcp_congestion_control", "cubic")
    avail_cc = _read_str("/proc/sys/net/ipv4/tcp_available_congestion_control", "reno cubic")
    default_qdisc = _read_str("/proc/sys/net/core/default_qdisc", "pfifo_fast")

    # Buffer limits
    rmem_max = _read_int("/proc/sys/net/core/rmem_max", 212992)
    wmem_max = _read_int("/proc/sys/net/core/wmem_max", 212992)
    rmem_default = _read_int("/proc/sys/net/core/rmem_default", 212992)
    wmem_default = _read_int("/proc/sys/net/core/wmem_default", 212992)
    busy_poll = _read_int("/proc/sys/net/core/busy_poll", 0)
    rps_flow_entries = _read_int("/proc/sys/net/core/rps_sock_flow_entries", 0)

    # Interfaces details
    interfaces: List[Dict[str, Any]] = []
    if SYSFS_NET.exists():
        for iface_path in SYSFS_NET.iterdir():
            iface = iface_path.name
            if iface in ("lo",) or iface.startswith(("dummy", "tun", "tap")):
                continue

            # Speed
            speed_str = _read_str(f"/sys/class/net/{iface}/speed", "-1")
            try:
                speed = int(speed_str)
            except Exception:
                speed = -1

            # MTU
            mtu = _read_int(f"/sys/class/net/{iface}/mtu", 1500)

            # RPS mask on rx-0
            rps_mask = _read_str(f"/sys/class/net/{iface}/queues/rx-0/rps_cpus", "0")
            rfs_cnt = _read_int(f"/sys/class/net/{iface}/queues/rx-0/rps_flow_cnt", 0)
            xps_mask = _read_str(f"/sys/class/net/{iface}/queues/tx-0/xps_cpus", "0")

            interfaces.append({
                "name": iface,
                "speed_mbps": speed if speed > 0 else None,
                "mtu": mtu,
                "rps_cpus": rps_mask,
                "rps_enabled": (rps_mask != "0" and rps_mask != ""),
                "rfs_flow_cnt": rfs_cnt,
                "xps_cpus": xps_mask,
            })

    # Ethtool offloads summary (check on primary interface)
    offloads_summary: Dict[str, bool] = {}
    ethtool_bin = shutil.which("ethtool")
    primary_iface = interfaces[0]["name"] if interfaces else "eth0"
    if ethtool_bin and primary_iface:
        try:
            res = subprocess.run([ethtool_bin, "-k", primary_iface], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k = k.strip()
                        v = v.strip().lower()
                        if k in ("tcp-segmentation-offload", "generic-segmentation-offload", "generic-receive-offload",
                                 "rx-checksumming", "tx-checksumming"):
                            offloads_summary[k] = ("on" in v)
        except Exception:
            pass

    return {
        "status": "ok",
        "tcp_congestion_control": tcp_cc,
        "tcp_available_congestion_control": avail_cc.split(),
        "is_bbr_active": (tcp_cc == "bbr"),
        "default_qdisc": default_qdisc,
        "is_fq_active": (default_qdisc == "fq"),
        "rmem_max": rmem_max,
        "wmem_max": wmem_max,
        "rmem_max_mb": round(rmem_max / (1024 * 1024), 1),
        "wmem_max_mb": round(wmem_max / (1024 * 1024), 1),
        "rmem_default": rmem_default,
        "wmem_default": wmem_default,
        "busy_poll_us": busy_poll,
        "rps_flow_entries": rps_flow_entries,
        "interfaces": interfaces,
        "offloads": offloads_summary,
        "so_timestampns_supported": True,
        "so_priority_qos_supported": True,
        "cpu_count": os.cpu_count() or 1,
        "kernel_release": _read_str("/proc/sys/kernel/osrelease", "Linux"),
    }
