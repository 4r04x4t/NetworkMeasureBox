"""Speedtest and net-neutrality runner with traffic gate idle enforcement.

Enforces that active client traffic is below threshold before executing heavy
bandwidth measurements. Records results directly to SQLite WAL tables.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from nmb.config import Config, load_config
from nmb.db import database as db
from nmb.probe.traffic_gate import TrafficGate
from nmb.speed.ookla import SpeedtestResult, execute_speedtest
from nmb.speed.cloudflare import execute_cloudflare_speedtest
from nmb.speed.rtr import execute_rtr_speedtest
from nmb.speed.port_checker import record_port_checks_to_db, run_port_neutrality_check

log = logging.getLogger("nmb.speed.runner")

_SPEEDTEST_RUNNING = False
_RUNNING_LOCK = threading.Lock()


def is_speedtest_running() -> bool:
    """Return True if a bandwidth or throughput measurement is actively running."""
    global _SPEEDTEST_RUNNING
    with _RUNNING_LOCK:
        return _SPEEDTEST_RUNNING


def set_speedtest_running(running: bool) -> None:
    global _SPEEDTEST_RUNNING
    with _RUNNING_LOCK:
        _SPEEDTEST_RUNNING = running


class CpuLoadSampler:
    """Samples per-core CPU and SoftIRQ utilization during a measurement run."""

    def __init__(self, interval_sec: float = 0.25):
        self.interval = interval_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.peak_cpu_pct: float = 0.0
        self.peak_single_core_pct: float = 0.0
        self.peak_single_core_name: str = "CPU0"
        self.peak_softirq_pct: float = 0.0
        self.peak_softirq_core: str = "CPU0"
        self.samples: int = 0

    def _sample_loop(self):
        last_stats = self._read_stats()
        while not self._stop.wait(self.interval):
            curr_stats = self._read_stats()
            if not last_stats or not curr_stats:
                last_stats = curr_stats
                continue

            for name, v2 in curr_stats.items():
                if name not in last_stats:
                    continue
                v1 = last_stats[name]
                dt = sum(v2) - sum(v1)
                if dt <= 0:
                    continue
                idle = v2[3] - v1[3]
                softirq = v2[6] - v1[6]
                usage = max(0.0, min(100.0, ((dt - idle) / dt) * 100.0))
                sirq = max(0.0, min(100.0, (softirq / dt) * 100.0))

                if name == "cpu":
                    if usage > self.peak_cpu_pct:
                        self.peak_cpu_pct = usage
                else:
                    if usage > self.peak_single_core_pct:
                        self.peak_single_core_pct = usage
                        self.peak_single_core_name = name.upper()
                    if sirq > self.peak_softirq_pct:
                        self.peak_softirq_pct = sirq
                        self.peak_softirq_core = name.upper()
            self.samples += 1
            last_stats = curr_stats

    def _read_stats(self) -> Dict[str, List[int]]:
        res = {}
        try:
            with open("/proc/stat", "r") as f:
                for line in f:
                    if line.startswith("cpu"):
                        parts = line.split()
                        res[parts[0]] = [int(x) for x in parts[1:]]
        except Exception:
            pass
        return res

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True, name="nmb-cpu-sampler")
        self._thread.start()

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        return {
            "peak_cpu_pct": round(self.peak_cpu_pct, 1),
            "single_core_max_pct": round(self.peak_single_core_pct, 1),
            "single_core_name": self.peak_single_core_name,
            "peak_softirq_pct": round(self.peak_softirq_pct, 1),
            "peak_softirq_core": self.peak_softirq_core,
            "samples": self.samples,
        }


def _run_single_engine(
    engine: str,
    cfg: Config,
    trigger: str,
    target_server_id: Optional[int],
    conn: db.sqlite3.Connection,
    now_ms: int,
    target_iface: Optional[str] = None,
) -> SpeedtestResult:
    """Execute a single measurement engine and persist results."""
    t_start = time.monotonic()
    log.info("launching speedtest engine=%s (target_server_id=%s, trigger=%s, target_iface=%s)", engine, target_server_id, trigger, target_iface)
    # Determine target interface (supports Multi-WAN selection)
    meas_target = getattr(cfg.network, "measurement_interface", "wan")
    if target_iface:
        chosen_iface = target_iface
    elif meas_target in ("wan2", "secondary") and getattr(cfg.network, "wan2_interface", ""):
        chosen_iface = cfg.network.wan2_interface
    else:
        chosen_iface = cfg.network.wan_interface or "eth0"

    wan_iface = chosen_iface
    from nmb.netd.interfaces import get_ip_addresses
    wan_addrs = get_ip_addresses(wan_iface)
    bound_ip = wan_addrs[0].split("/")[0] if wan_addrs else None
    bound_iface = wan_iface
    log.info("binding speedtest engine=%s to interface=%s (ip=%s)", engine, bound_iface, bound_ip)

    set_speedtest_running(True)
    sampler = CpuLoadSampler(interval_sec=0.25)
    sampler.start()
    try:
        if engine == "cloudflare":
            log.debug("starting Cloudflare Edge speedtest")
            res = execute_cloudflare_speedtest()
            if hasattr(res, "to_speedtest_result"):
                res = res.to_speedtest_result()
        elif engine == "rtr":
            log.debug("starting RTR-NetTest / Open-RMBT speedtest")
            res = execute_rtr_speedtest()
        elif engine == "iperf3":
            from nmb.speed.iperf import run_iperf_client_test
            target_host = cfg.iperf.target_host or "speedtest.init7.net"
            target_port = cfg.iperf.target_port or 5201
            duration = cfg.iperf.duration or 10
            protocol = (cfg.iperf.protocol or "tcp").lower()
            # Automata iPerf3: minimum 4 streams, download reverse mode default
            parallel = max(4, int(cfg.iperf.parallel or 4))
            bidir = getattr(cfg.iperf, "bidir", False)
            reverse = (True if cfg.iperf.reverse is None else cfg.iperf.reverse) and not bidir
            log.debug("starting iPerf3 test: target=%s:%s, proto=%s, streams=%s, duration=%ss, reverse=%s, bidir=%s, bind=%s",
                      target_host, target_port, protocol, parallel, duration, reverse, bidir, bound_ip or bound_iface)

            raw_res = run_iperf_client_test(
                host=target_host,
                port=target_port,
                duration=duration,
                protocol=protocol,
                parallel=parallel,
                reverse=reverse,
                bidir=bidir,
                bind_address=bound_ip or bound_iface,
            )

            status = raw_res.get("status", "error")
            bps = int(raw_res.get("bps", 0))
            rtt_ms = raw_res.get("rtt_ms")
            ping_us = int(rtt_ms * 1000) if rtt_ms is not None else None
            jitter_ms = raw_res.get("jitter_ms")
            jitter_us = int(jitter_ms * 1000) if jitter_ms is not None else None
            loss_pct = raw_res.get("lost_percent")
            retransmits = raw_res.get("retransmits")
            tcp_window = raw_res.get("tcp_window")

            # In iPerf, reverse=True indicates download stream; reverse=False indicates upload stream; bidir provides both
            if raw_res.get("is_bidirectional"):
                down_bps = int(raw_res.get("download_bps") or 0)
                up_bps = int(raw_res.get("upload_bps") or 0)
            else:
                down_bps = bps if reverse else None
                up_bps = bps if not reverse else None

            res = SpeedtestResult(
                status=status,
                down_bps=down_bps,
                up_bps=up_bps,
                ping_us=ping_us,
                jitter_us=jitter_us,
                loss_pct=loss_pct,
                server_name=f"iPerf3: {target_host}:{target_port}",
                server_host=target_host,
                server_location=f"{protocol.upper()} -P {parallel}",
                client_ip=raw_res.get("local_host"),
                raw_json=raw_res.get("raw_output"),
                error=raw_res.get("error"),
                engine="iperf3",
                colo=f"Port {target_port}",
                bound_iface=bound_iface,
                bound_ip=bound_ip,
                retransmits=retransmits,
                tcp_window=tcp_window,
            )
        else:
            res = execute_speedtest(server_id=target_server_id, interface=bound_iface, bind_ip=bound_ip)
    finally:
        set_speedtest_running(False)
        cpu_telemetry = sampler.stop()

    if not res.bound_iface:
        res.bound_iface = bound_iface
    if not res.bound_ip:
        res.bound_ip = bound_ip

    # Attach CPU telemetry to raw_json
    try:
        if res.raw_json:
            parsed_rj = json.loads(res.raw_json) if isinstance(res.raw_json, str) else dict(res.raw_json)
        else:
            parsed_rj = {}
        parsed_rj["measurement_cpu"] = cpu_telemetry
        res.raw_json = json.dumps(parsed_rj)
    except Exception:
        pass

    conn_type = getattr(cfg.isp, "connection_type", "fiber")
    with db.tx(conn):
        conn.execute(
            """INSERT INTO speedtest (
                ts, trigger, status, server_id, server_name,
                down_bps, up_bps, ping_us, jitter_us, loss_pct,
                result_url, raw_json, error,
                down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms,
                connection_type, client_ip, client_ipv6, server_host, server_location, engine, colo,
                bound_iface, bound_ip, retransmits, tcp_window
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_ms,
                trigger,
                res.status,
                res.server_id,
                res.server_name,
                res.down_bps,
                res.up_bps,
                res.ping_us,
                res.jitter_us,
                res.loss_pct,
                res.result_url,
                res.raw_json,
                res.error,
                res.down_loaded_lat_ms,
                res.up_loaded_lat_ms,
                res.bufferbloat_grade,
                res.bufferbloat_delta_ms,
                conn_type,
                res.client_ip,
                getattr(res, "client_ipv6", None),
                res.server_host,
                res.server_location,
                engine if engine in ("cloudflare", "rtr", "iperf3") else (getattr(res, "engine", None) or engine),
                getattr(res, "colo", None) or ("VIE" if engine == "rtr" else None),
                res.bound_iface,
                res.bound_ip,
                getattr(res, "retransmits", None),
                getattr(res, "tcp_window", None),
            )
        )
        down_mbps = (res.down_bps or 0) / 1_000_000.0
        up_mbps = (res.up_bps or 0) / 1_000_000.0
        bb_info = f" (Bufferbloat: {res.bufferbloat_grade}, +{res.bufferbloat_delta_ms}ms)" if res.bufferbloat_grade else ""
        from nmb.config import CONNECTION_TYPES
        type_label = CONNECTION_TYPES.get(conn_type, conn_type)

        contract_down = float(getattr(cfg.isp, "contract_down_mbps", 0.0) or 0.0)
        contract_up = float(getattr(cfg.isp, "contract_up_mbps", 0.0) or 0.0)
        down_pct = (down_mbps / contract_down * 100.0) if contract_down > 0 else None
        up_pct = (up_mbps / contract_up * 100.0) if contract_up > 0 else None
        down_pct_str = f" ({down_pct:.1f}% of offered {contract_down:.0f} Mbps)" if down_pct is not None else ""
        up_pct_str = f" ({up_pct:.1f}% of offered {contract_up:.0f} Mbps)" if up_pct is not None else ""
        down_contract_note = f" — ISP offered plan ({contract_down:.0f} Mbps): {down_pct:.1f}%" if down_pct is not None else ""
        up_contract_note = f" — ISP offered plan ({contract_up:.0f} Mbps): {up_pct:.1f}%" if up_pct is not None else ""

        engine_label = "Ookla" if engine == "ookla" else ("Cloudflare" if engine == "cloudflare" else ("RTR-NetTest" if engine == "rtr" else "iPerf3"))
        parts = [f"Speedtest [{engine_label}] {res.status}: Down: {down_mbps:.1f} Mbps{down_pct_str}, Up: {up_mbps:.1f} Mbps{up_pct_str}{bb_info} [{type_label}]"]
        client_ipv6_val = getattr(res, "client_ipv6", None)
        if res.client_ip and client_ipv6_val:
            parts.append(f"Public IP: IPv4: {res.client_ip} | IPv6: {client_ipv6_val}")
        elif res.client_ip:
            parts.append(f"Public IP (IPv4): {res.client_ip}")
        elif client_ipv6_val:
            parts.append(f"Public IP (IPv6): {client_ipv6_val}")
        if res.server_name or res.server_host:
            srv_parts = []
            if res.server_name:
                srv_parts.append(res.server_name)
            if res.server_host:
                srv_parts.append(res.server_host)
            if res.server_location:
                srv_parts.append(res.server_location)
            parts.append(f"Server: {' - '.join(srv_parts)}")
        if res.result_url:
            parts.append(f"Result URL: {res.result_url}")
        detail = " | ".join(parts)

        ping_ms_val = (res.ping_us / 1000.0) if res.ping_us else 0.0
        jitter_ms_val = (res.jitter_us / 1000.0) if res.jitter_us else 0.0
        log.info(
            "Speedtest [%s] %s: Down: %.2f Mbps%s, Up: %.2f Mbps%s (Ping: %.2f ms)%s",
            engine_label, res.status, down_mbps, down_pct_str, up_mbps, up_pct_str, ping_ms_val, bb_info
        )

        # Generate real executed command representation based on measurement engine
        import datetime
        dt_str = datetime.datetime.fromtimestamp(now_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")

        if engine == "cloudflare":
            meroscript = f"""#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime Cloudflare Edge Speedtest Execution
# Measurement Engine: Cloudflare Edge (speed.cloudflare.com)
# Timestamp: {dt_str} | Status: {res.status.upper()}
# ==============================================================================

# 1. Target PoP Datacenter & Endpoint:
# Datacenter (PoP): {getattr(res, 'colo', None) or 'Edge'} | Endpoint: https://speed.cloudflare.com
# Public Client IPv4: {res.client_ip or '--'}
# Public Client IPv6: {client_ipv6_val or '--'}

# 2. Executed HTTP/HTTPS Transfer Benchmark:
curl -s -X GET "https://speed.cloudflare.com/__down?bytes=25000000" -o /dev/null
curl -s -X POST "https://speed.cloudflare.com/__up" --data-binary @chunk_10mb.bin -o /dev/null

# 3. Measured Real Telemetry:
# Download Speed: {down_mbps:.2f} Mbps ({(down_mbps/8):.2f} MB/s){down_contract_note}
# Upload Speed: {up_mbps:.2f} Mbps ({(up_mbps/8):.2f} MB/s){up_contract_note}
# Latency (Ping): {ping_ms_val:.2f} ms | Bufferbloat: {res.bufferbloat_grade or '--'} (+{res.bufferbloat_delta_ms or 0} ms)
"""
        elif engine == "rtr":
            meroscript = f"""#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime RTR-NetTest Execution
# Measurement Engine: RTR-NetTest (netztest.at / Open-RMBT, BEREC Standard)
# Timestamp: {dt_str} | Status: {res.status.upper()}
# ==============================================================================

# 1. Control Server Handshake & Token Request:
# Public Client IPv4: {res.client_ip or '--'}
# Public Client IPv6: {client_ipv6_val or '--'}
curl -s -X POST "https://c01.netztest.at/RMBTControlServer/testRequest" \\
  -H "Content-Type: application/json" \\
  -d '{{"client_name":"RMBT","client_version":"1.3","language":"en"}}'

# 2. WebSocket Data Transfer Benchmark (Open-RMBT Protocol)

# 3. Measured Real Telemetry:
# Download Speed: {down_mbps:.2f} Mbps ({(down_mbps/8):.2f} MB/s){down_contract_note}
# Upload Speed: {up_mbps:.2f} Mbps ({(up_mbps/8):.2f} MB/s){up_contract_note}
# Latency (Ping): {ping_ms_val:.2f} ms | Bufferbloat: {res.bufferbloat_grade or '--'} (+{res.bufferbloat_delta_ms or 0} ms)
# Verified Sharing Link: {res.result_url or '--'}
"""
        elif engine == "iperf3":
            proto_flag = "-u" if (cfg.iperf.protocol or "").lower() == "udp" else ""
            rev_flag = "-R" if cfg.iperf.reverse else ""
            par_flag = f"-P {cfg.iperf.parallel or 1}"
            dur_flag = f"-t {cfg.iperf.duration or 10}"
            ipf_target = cfg.iperf.target_host or "speedtest.init7.net"
            ipf_port = cfg.iperf.target_port or 5201
            through_mbps = down_mbps if cfg.iperf.reverse else up_mbps
            meroscript = f"""#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime iPerf3 Benchmark Execution
# Measurement Engine: iPerf3 (RFC 2544 / RFC 6349 TCP & UDP Probing)
# Timestamp: {dt_str} | Status: {res.status.upper()}
# ==============================================================================

# 1. Target Endpoint & Parameters:
# Server: {ipf_target}:{ipf_port}
# Protocol: {(cfg.iperf.protocol or 'tcp').upper()} | Parallel Streams: {cfg.iperf.parallel or 1}
# Direction: {'Download (-R / Server->Client)' if cfg.iperf.reverse else 'Upload (Client->Server)'}
# Local Client IP: {res.client_ip or '--'}

# 2. Realtime CLI Invocation:
iperf3 -c {ipf_target} -p {ipf_port} {dur_flag} {par_flag} {proto_flag} {rev_flag} --connect-timeout 4000 -J

# 3. Measured Real Telemetry:
# Throughput: {through_mbps:.2f} Mbps ({(through_mbps/8):.2f} MB/s)
# Ping / RTT: {ping_ms_val:.2f} ms | Retransmits / Loss: {res.loss_pct or 0}%
"""
        else:
            # Ookla Speedtest CLI
            target_flag = f" --server-id {res.server_id}" if res.server_id else ""
            srv_desc = f"#{res.server_id} - {res.server_name}" if res.server_id else "Auto-selected closest"
            if res.server_location:
                srv_desc += f" ({res.server_location})"
            meroscript = f"""#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime Ookla Speedtest Execution
# Measurement Engine: Ookla Speedtest CLI (Official Binary)
# Timestamp: {dt_str} | Status: {res.status.upper()}
# ==============================================================================

# 1. Target Server Information:
# Server: {srv_desc}
# Host: {res.server_host or 'speedtest.net'}
# Public Client IPv4: {res.client_ip or '--'}
# Public Client IPv6: {client_ipv6_val or '--'}

# 2. Realtime CLI Invocation:
/usr/local/bin/speedtest --accept-license --accept-gdpr --format=json{target_flag}

# 3. Measured Real Telemetry:
# Download Speed: {down_mbps:.2f} Mbps ({(down_mbps/8):.2f} MB/s){down_contract_note}
# Upload Speed: {up_mbps:.2f} Mbps ({(up_mbps/8):.2f} MB/s){up_contract_note}
# Ping Latency: {ping_ms_val:.2f} ms | Jitter: {jitter_ms_val:.2f} ms | Packet Loss: {res.loss_pct:.1f}%
# Loaded Latency: Download: {res.down_loaded_lat_ms or '--'} ms | Upload: {res.up_loaded_lat_ms or '--'} ms
# Bufferbloat Grade: {res.bufferbloat_grade or '--'} (+{res.bufferbloat_delta_ms or 0} ms delta)
# Official Result URL: {res.result_url or '--'}
"""

        conn.execute(
            "INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('last_meroscript', ?, ?)",
            (meroscript.strip(), now_ms)
        )
        conn.execute(
            "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'speed', 'speedtest_completed', ?)",
            (now_ms, detail)
        )
    elapsed = time.monotonic() - t_start
    log.info("speedtest engine=%s completed in %.2fs (status=%s, down=%.1f Mbps, up=%.1f Mbps, ping=%.2f ms, error=%s)",
             engine, elapsed, res.status, down_mbps, up_mbps, ping_ms_val, res.error or "none")
    from nmb.common.memory import trim_process_memory
    trim_process_memory()
    return res


def run_measurement_cycle(
    cfg: Config,
    trigger: str = "schedule",
    force: bool = False,
    run_port_check: bool = True,
    custom_ports: Optional[List[int]] = None,
    server_id: Optional[int] = None,
    engine: Optional[str] = None,
    target_iface: Optional[str] = None,
) -> bool:
    """Execute complete measurement cycle (Traffic Gate -> Speedtest -> Port Checker)."""
    now_ms = db.now_ms()
    if not engine:
        engine = getattr(cfg.speedtest, "automated_engine", "ookla")
    log.info("starting measurement cycle (trigger=%s, force=%s, server_id=%s, engine=%s, iface=%s)", trigger, force, server_id, engine, target_iface)

    # 0. Check if automated scheduled measurements are disabled (manual mode)
    if trigger == "schedule" and getattr(cfg.speedtest, "schedule_mode", "scheduled") == "manual":
        log.info("automated measurement mode is set to 'manual'; skipping scheduled test")
        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                """INSERT INTO speedtest (ts, trigger, status, error, engine)
                   VALUES (?, 'schedule', 'skipped_busy', 'skipped: automated speedtest is set to manual mode', ?)""",
                (now_ms, engine)
            )
            conn.execute(
                "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'speed', 'speedtest_skipped', 'Időzített mérés kihagyva: a sebességmérés manuális üzemmódra van állítva')",
                (now_ms,)
            )
        conn.close()
        return True

    # 1. Enforce Traffic Gate (Idle check with < 2% network load condition)
    tg_mode = getattr(cfg.speedtest, "idle_threshold_mode", "percent")
    thresh_pct = getattr(cfg.speedtest, "idle_threshold_percent", 2.0)
    fixed_kbps = getattr(cfg.speedtest, "idle_threshold_kbps", 500)
    max_wait = cfg.raw_parser.getfloat("speedtest", "idle_wait_max_sec", fallback=1800.0)

    # For scheduled automated tests, cap wait time to 60s so test cycles don't overlap or hang
    wait_timeout = min(max_wait, 60.0) if trigger == "schedule" else min(max_wait, 30.0)

    check_gate_iface = target_iface or (cfg.network.wan2_interface if getattr(cfg.network, "measurement_interface", "wan") in ("wan2", "secondary") and getattr(cfg.network, "wan2_interface", "") else cfg.network.wan_interface)
    if not force:
        gate = TrafficGate(check_gate_iface)
        cap_mbps = gate.get_interface_capacity_mbps(check_gate_iface, contract_down_mbps=cfg.isp.contract_down_mbps)
        gate_res = gate.wait_for_idle(
            threshold_kbps=fixed_kbps,
            max_wait_sec=wait_timeout,
            consecutive_idle_sec=3.0,
            iface=check_gate_iface,
            capacity_mbps=cap_mbps,
            threshold_percent=thresh_pct,
            mode=tg_mode,
        )

        if not gate_res.cleared:
            reason = (
                f"deferred: network load {gate_res.load_percent:.2f}% ({gate_res.rate_kbps:.0f} kbps) exceeded {thresh_pct:.1f}% threshold "
                f"({gate_res.threshold_kbps:.0f} kbps / {cap_mbps:.0f} Mbps capacity) to preserve test accuracy and protect active user traffic"
            )
            reason_hu = (
                f"Időzített sebességmérés elhalasztva: a hálózati terhelés {gate_res.load_percent:.2f}% ({gate_res.rate_kbps:.0f} Kbps) "
                f"meghaladta a megengedett < {thresh_pct:.1f}% küszöböt ({gate_res.threshold_kbps/1000.0:.1f} Mbps / {cap_mbps:.0f} Mbps kapacitás) "
                f"a mérés pontosságának és az ügyfélforgalom zavartalanságának megőrzése érdekében."
            )
            log.warning("network busy: %s", reason)
            conn = db.connect()
            with db.tx(conn):
                conn.execute(
                    """INSERT INTO speedtest (ts, trigger, status, error, engine)
                       VALUES (?, ?, 'skipped_busy', ?, ?)""",
                    (now_ms, trigger, reason, engine)
                )
                conn.execute(
                    "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warn', 'speed', 'speedtest_skipped', ?)",
                    (now_ms, reason_hu)
                )
            conn.close()
            return False

    # 2. Ensure DNS resolution is healthy (fallback if needed)
    if getattr(cfg.network, "dns_fallback_enabled", True):
        try:
            from nmb.netd import dns as net_dns
            net_dns.ensure_dns_fallback(
                servers=getattr(cfg.network, "dns_fallback_servers", None),
                force=False,
                iface=check_gate_iface,
            )
        except Exception as e:
            log.debug("dns fallback check exception: %s", e)

    # 3. Execute Speedtest Engine(s)
    target_server_id = server_id if server_id is not None else getattr(cfg.speedtest, "server_id", None)
    conn = db.connect()
    engines_to_run = ["ookla", "cloudflare", "rtr"] if engine == "all" else [engine or "ookla"]

    all_ok = True
    last_res = None
    for eng in engines_to_run:
        res = _run_single_engine(eng, cfg, trigger, target_server_id, conn, now_ms, target_iface=target_iface)
        last_res = res
        if res.status != "ok":
            all_ok = False

    # 4. Execute Net-Neutrality Port Throttling Check
    if run_port_check:
        log.info("launching net-neutrality port-throttling verification")
        port_results = run_port_neutrality_check(ports=custom_ports)
        record_port_checks_to_db(conn, port_results)

    conn.close()
    log.info("measurement cycle complete successfully")
    from nmb.common.memory import trim_process_memory
    trim_process_memory()
    return all_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-speed", description="NetworkMeasureBox speedtest & net-neutrality runner")
    parser.add_argument("--config", "-c", help="Path to nmb.conf")
    parser.add_argument("--trigger", choices=["schedule", "manual", "telegram", "web"], default="manual")
    parser.add_argument("--interface", "-i", help="Target network interface (WAN1, WAN2, or specific NIC)")
    parser.add_argument("--server-id", "-s", type=int, help="Target Ookla Speedtest server ID")
    parser.add_argument("--force", "-f", action="store_true", help="Bypass traffic gate idle check")
    parser.add_argument("--no-port-check", action="store_true", help="Skip port throttling tests")
    parser.add_argument("--ports", help="Comma-separated list of ports to test for throttling")
    parser.add_argument("--engine", "-e", choices=["ookla", "cloudflare", "rtr", "iperf3", "all"], help="Measurement engine")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose debug output")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    from nmb.devlog import setup_dev_logging
    log_level = "DEBUG" if args.verbose else getattr(cfg.logging, "level", "DEBUG")
    setup_dev_logging(
        cfg=cfg,
        level=log_level,
        log_file=getattr(cfg.logging, "file_path", None),
        max_bytes=getattr(cfg.logging, "max_bytes", 10485760),
        backup_count=getattr(cfg.logging, "backup_count", 5),
        console=getattr(cfg.logging, "console_enabled", True),
    )

    ports = [int(p.strip()) for p in args.ports.split(",") if p.strip()] if args.ports else None

    ok = run_measurement_cycle(
        cfg=cfg,
        trigger=args.trigger,
        force=args.force,
        run_port_check=not args.no_port_check,
        custom_ports=ports,
        server_id=args.server_id,
        engine=args.engine,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
