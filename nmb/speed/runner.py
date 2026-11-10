"""Speedtest and net-neutrality runner with traffic gate idle enforcement.

Enforces that active client traffic is below threshold before executing heavy
bandwidth measurements. Records results directly to SQLite WAL tables.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from nmb.common.netaddr import global_ip
from nmb.config import Config, load_config
from nmb.db import database as db
from nmb.probe import cross_traffic
from nmb.probe.traffic_gate import TrafficGate
from nmb.speed import cancel, data_budget
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
            log.debug("suppressed exception", exc_info=True)
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
    """Execute a single measurement engine and persist results.

    The row's ts is when THIS engine started; now_ms is the run's start, stored as cycle_ts (all engines
    of a mixed run shared one ts until 2026-11-10, so it was not known when each one ran)."""
    t_start = time.monotonic()
    started_ms = db.now_ms()
    log.info("launching speedtest engine=%s (target_server_id=%s, trigger=%s, target_iface=%s)", engine, target_server_id, trigger, target_iface)

    # Determine target interface (strictly prioritizing active wired Ethernet cable)
    from nmb.netd.interfaces import find_preferred_measurement_interface
    chosen_iface, bound_ip, is_wired = find_preferred_measurement_interface(cfg, target_iface=target_iface)
    wan_iface = chosen_iface
    bound_iface = chosen_iface
    if is_wired:
        log.info("wired Ethernet cable active on %s (carrier=1, ip=%s) — STRICT WIRED PRIORITY applied for %s", bound_iface, bound_ip, engine)
    else:
        log.info("binding speedtest engine=%s to interface=%s (ip=%s)", engine, bound_iface, bound_ip)

    set_speedtest_running(True)
    sampler = CpuLoadSampler(interval_sec=0.25)
    ookla_paused = False
    sampler.start()
    try:
        if engine == "cloudflare":
            log.debug("starting Cloudflare Edge speedtest (bound_iface=%s, bound_ip=%s)", bound_iface, bound_ip)
            res = execute_cloudflare_speedtest(interface=bound_iface, bind_ip=bound_ip)
            if hasattr(res, "to_speedtest_result"):
                res = res.to_speedtest_result(bound_iface=bound_iface, bound_ip=bound_ip)
        elif engine == "fastcom":
            from nmb.speed.fastcom import execute_fastcom_speedtest
            res = execute_fastcom_speedtest(interface=bound_iface, bind_ip=bound_ip)
        elif engine == "rtr":
            log.debug("starting RTR-NetTest / Open-RMBT speedtest (bound_iface=%s, bound_ip=%s)", bound_iface, bound_ip)
            res = execute_rtr_speedtest(interface=bound_iface, bind_ip=bound_ip)
        elif engine == "iperf3":
            from nmb.speed.iperf import run_iperf_client_test
            target_host = cfg.iperf.target_host or "speedtest.init7.net"
            target_port = cfg.iperf.target_port or 5201
            duration = cfg.iperf.duration or 10
            protocol = (cfg.iperf.protocol or "tcp").lower()
            parallel = max(1, int(cfg.iperf.parallel or 4))
            bidir = bool(getattr(cfg.iperf, "bidir", False))
            direction = getattr(cfg.iperf, "auto_direction", "both")
            log.debug("starting iPerf3 test: target=%s:%s, proto=%s, streams=%s, duration=%ss, direction=%s, bidir=%s, bind=%s",
                      target_host, target_port, protocol, parallel, duration, direction, bidir, bound_ip or bound_iface)

            def _one(rev: bool, both: bool = False) -> dict:
                return run_iperf_client_test(
                    host=target_host, port=target_port, duration=duration, protocol=protocol,
                    parallel=parallel, reverse=rev, bidir=both, bind_address=bound_ip or bound_iface,
                )

            if bidir:
                raw_res = _one(False, True)
                reverse = False
            elif direction == "both":
                # Download (-R) and then upload, one after the other, so they do not compete.
                down_raw = _one(True)
                if down_raw.get("status") == "ok":
                    # Many public servers take one client at a time and need a moment to free it.
                    up_raw = {}
                    for wait in (3, 8):
                        time.sleep(wait)
                        up_raw = _one(False)
                        if up_raw.get("status") == "ok":
                            break
                    raw_res = dict(up_raw)
                    raw_res.update({
                        "is_bidirectional": True,
                        "download_bps": down_raw.get("bps"),
                        "upload_bps": up_raw.get("bps") if up_raw.get("status") == "ok" else None,
                        "rtt_ms": down_raw.get("rtt_ms") if down_raw.get("rtt_ms") is not None else up_raw.get("rtt_ms"),
                        "status": "ok",
                        "error": None if up_raw.get("status") == "ok" else f"upload not measured: {up_raw.get('error') or 'no answer'}",
                        "raw_output": json.dumps({"download": down_raw.get("raw_output"), "upload": up_raw.get("raw_output")}),
                    })
                else:
                    raw_res = down_raw
                reverse = True
            else:
                reverse = direction == "download"
                raw_res = _one(reverse)

            status = raw_res.get("status", "error")
            bps = int(raw_res.get("bps", 0))
            # iPerf3's RTT is the sending stream's mean TCP RTT while it saturates the upload: latency
            # under load, not the idle ping, so it goes into the loaded-latency column (2026-11-10).
            rtt_ms = raw_res.get("rtt_ms") if protocol == "tcp" else None
            ping_us = None
            jitter_ms = raw_res.get("jitter_ms")
            jitter_us = int(jitter_ms * 1000) if jitter_ms is not None else None
            loss_pct = raw_res.get("lost_percent")
            retransmits = raw_res.get("retransmits")
            tcp_window = raw_res.get("tcp_window")

            # In iPerf, reverse=True indicates download stream; reverse=False indicates upload stream; bidir provides both
            if raw_res.get("is_bidirectional"):
                down_bps = int(raw_res["download_bps"]) if raw_res.get("download_bps") else None
                up_bps = int(raw_res["upload_bps"]) if raw_res.get("upload_bps") else None
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
                server_name=_iperf_label(target_host, target_port),
                server_host=target_host,
                server_location=_iperf_location(target_host, target_port, protocol, parallel),
                # The local socket address is the box's own (usually a LAN) address: it is the client
                # IP only when it is a public one; otherwise it stays in bound_ip.
                client_ip=global_ip(raw_res.get("local_host")) if ":" not in str(raw_res.get("local_host") or "") else None,
                client_ipv6=global_ip(raw_res.get("local_host")) if ":" in str(raw_res.get("local_host") or "") else None,
                raw_json=raw_res.get("raw_output"),
                error=raw_res.get("error"),
                engine="iperf3",
                colo=None,
                up_loaded_lat_ms=rtt_ms if (up_bps and rtt_ms is not None) else None,
                bound_iface=bound_iface,
                bound_ip=bound_ip or raw_res.get("local_host"),
                retransmits=retransmits,
                tcp_window=tcp_window,
            )
        else:
            from nmb.speed.anti_ban import (
                client_cooldown_remaining,
                is_client_rate_limit,
                mark_client_ok,
                mark_client_rate_limited,
                record_client_attempt,
                scheduled_wait_remaining,
            )
            is_ban = False
            wait_sec = client_cooldown_remaining()
            hourly_wait = (scheduled_wait_remaining(60 * getattr(getattr(cfg, "speedtest", None), "ookla_interval_min", 60))
                           if trigger == "schedule" else 0.0)
            if not getattr(getattr(cfg, "speedtest", None), "ookla_terms_accepted", False):
                # Ookla's CLI is proprietary: its licence and privacy terms are the owner's to accept (Web UI,
                # speed test engines). Until then Ookla is not run and nothing stands in for it.
                log.info("Ookla skipped: its licence and privacy terms are not accepted yet")
                res = SpeedtestResult(status="skipped_busy",
                                      error="Ookla not run: accept Ookla's licence and privacy terms in the Web UI first",
                                      bound_iface=bound_iface, bound_ip=bound_ip)
                ookla_paused = True
            elif wait_sec <= 0 and hourly_wait > 0:
                # Scheduled Ookla runs at most hourly, however often the schedule runs.
                log.info("Ookla skipped: its own interval is not over yet (next in %d min)", int(hourly_wait // 60) + 1)
                res = SpeedtestResult(status="skipped_busy", error="Ookla interval not over yet",
                                      bound_iface=bound_iface, bound_ip=bound_ip)
                ookla_paused = True
            elif wait_sec > 0:
                # Asking again while limited only extends Ookla's block. No test ran, so this is a skip,
                # not a failed test (2026-11-08: 28 such rows counted as Ookla errors).
                res = SpeedtestResult(
                    status="skipped_busy",
                    error=f"Ookla rate limit: paused for another {int(wait_sec // 60) + 1} min",
                    bound_iface=bound_iface, bound_ip=bound_ip,
                )
                is_ban = True
                ookla_paused = True
            else:
                log.info("executing Ookla engine with server_id=%s (iface=%s, ip=%s)",
                         target_server_id or "auto", bound_iface, bound_ip)
                record_client_attempt()
                res = execute_speedtest(server_id=target_server_id, interface=bound_iface, bind_ip=bound_ip)
                if res.status == "ok":
                    mark_client_ok()
                    _flag_server_mismatch(res, target_server_id)
                elif is_client_rate_limit(res.error):
                    minutes = mark_client_rate_limited() // 60
                    res.error = f"Ookla rate limit (too many tests from this box): paused for {minutes} min"
                    is_ban = True

            # No silent substitute: the user chose Ookla (and a chosen server), so an Ookla
            # failure or pause is recorded as such instead of an RTR or Cloudflare result.
            if is_ban:
                log.warning("Ookla not run: %s", res.error)
    except cancel.MeasurementCancelled:
        res = None
    except Exception as e:
        # An engine that raises (no route, the bound address gone, a control server down) is a failed
        # measurement of that engine, stored as such. Before 2026-11-09 the exception left the cycle: the
        # other engines did not run and no row showed the failure (seen with RTR while the box was offline).
        expected = isinstance(e, (OSError, RuntimeError, ValueError, TimeoutError))
        log.warning("%s speed test failed: %s", engine, e, exc_info=not expected)
        res = SpeedtestResult(status="error", error=f"{type(e).__name__}: {str(e)[:200]}", engine=engine,
                              bound_iface=bound_iface, bound_ip=bound_ip)
    finally:
        set_speedtest_running(False)
        cpu_telemetry = sampler.stop()

    if res is None or cancel.is_requested():
        return _record_aborted(conn, trigger, engine, now_ms, cancel.current_reason())
    if (engine == "iperf3" and trigger == "schedule" and res.status != "ok"
            and any(m in (res.error or "").lower() for m in ("busy", "unable to connect", "connection refused", "timed out"))):
        # A busy or unreachable iPerf3 server is no measurement; the next run tries again.
        log.info("scheduled iPerf3 test not stored: %s", res.error)
        return res
    if ookla_paused:
        # Ookla was not asked, so there is no measurement to store. The refusal that started
        # the pause is stored once, and the pause is shown on the schedule and the home page.
        res.engine = "ookla"
        return res

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
        log.debug("suppressed exception", exc_info=True)

    conn_type = getattr(cfg.isp, "connection_type", "fiber")
    try:
        from nmb.netd.interfaces import usb_tether_kind
        if bound_iface and usb_tether_kind(bound_iface):
            conn_type = "fwa"   # measured over a phone, hotspot or modem on USB: mobile, whatever the home line is
    except Exception:
        log.debug("connection type check failed", exc_info=True)
    with db.tx(conn):
        conn.execute(
            """INSERT INTO speedtest (
                ts, trigger, status, server_id, server_name,
                down_bps, up_bps, ping_us, jitter_us, loss_pct,
                result_url, raw_json, error,
                down_loaded_lat_ms, up_loaded_lat_ms, bufferbloat_grade, bufferbloat_delta_ms,
                connection_type, client_ip, client_ipv6, server_host, server_location, engine, colo,
                bound_iface, bound_ip, retransmits, tcp_window,
                cycle_ts, duration_ms, nmb_version, box_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                started_ms,
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
                engine if engine in ("cloudflare", "fastcom", "rtr", "iperf3") else (getattr(res, "engine", None) or engine),
                getattr(res, "colo", None),
                res.bound_iface,
                res.bound_ip,
                getattr(res, "retransmits", None),
                getattr(res, "tcp_window", None),
                now_ms,
                int((time.monotonic() - t_start) * 1000),
                _nmb_version(),
                _box_mode(conn),
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

        used_engine = getattr(res, "engine", None) or engine
        engine_label = {"ookla": "Ookla", "cloudflare": "Cloudflare", "fastcom": "Fast.com", "rtr": "RTR-NetTest"}.get(used_engine, "iPerf3")
        if used_engine != engine:
            engine_label += f" (fallback for {engine})"
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
        elif engine == "fastcom":
            meroscript = f"""#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Fast.com (Netflix) Speedtest Execution
# Measurement Engine: Fast.com API, Netflix Open Connect servers
# Timestamp: {dt_str} | Status: {res.status.upper()}
# ==============================================================================

# 1. Servers chosen by Fast.com for this client:
curl -s "https://api.fast.com/netflix/speedtest/v2?https=false&token=<token>&urlCount=5"
# Closest server: {res.server_host or '--'} ({res.server_location or '--'})
# Public Client IP: {res.client_ip or client_ipv6_val or '--'}

# 2. Transfers over plain HTTP (16 parallel streams over the servers, 15 s each way, first 3 s left out):
curl -s "http://<server>/speedtest/range/0-0?<query>" -o /dev/null          # latency
curl -s "http://<server>/speedtest/range/0-26214400?<query>" -o /dev/null   # download
curl -s -X POST --data-binary @10mb.bin "http://<server>/speedtest/range/0-10000000?<query>"  # upload

# 3. Measured:
# Download Speed: {down_mbps:.2f} Mbps ({(down_mbps/8):.2f} MB/s){down_contract_note}
# Upload Speed: {up_mbps:.2f} Mbps ({(up_mbps/8):.2f} MB/s){up_contract_note}
# Unloaded latency: {ping_ms_val:.2f} ms | Jitter: {jitter_ms_val:.2f} ms
# Loaded latency: down {res.down_loaded_lat_ms or '--'} ms, up {res.up_loaded_lat_ms or '--'} ms | Bufferbloat: {res.bufferbloat_grade or '--'} (+{res.bufferbloat_delta_ms or 0} ms)
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
            loss_pct_str = f"{res.loss_pct:.1f}%" if res.loss_pct is not None else "--"
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
# Ping Latency: {ping_ms_val:.2f} ms | Jitter: {jitter_ms_val:.2f} ms | Packet Loss: {loss_pct_str}
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
             getattr(res, "engine", None) or engine, elapsed, res.status, down_mbps, up_mbps, ping_ms_val, res.error or "none")
    from nmb.common.memory import trim_process_memory
    trim_process_memory()
    return res


def _nmb_version() -> str:
    try:
        from nmb.common.version import installed_version
        return installed_version()
    except Exception:
        return "unknown"


def _box_mode(conn) -> Optional[str]:
    """The network mode netd last switched to (kv active_mode), or None when unknown."""
    try:
        row = conn.execute("SELECT v FROM kv WHERE k = 'active_mode'").fetchone()
        return (row[0] or None) if row else None
    except Exception:
        return None


def _iperf_label(host: str, port: int) -> str:
    """ "iPerf3: Vienna • DATAPACKET (185.180.12.40:5201)", or the address alone when nothing is known."""
    try:
        from nmb.speed.iperf_directory import describe_server
        name = describe_server(host, port).get("name")
    except Exception:
        name = ""
    return f"iPerf3: {name} ({host}:{port})" if name else f"iPerf3: {host}:{port}"


def _iperf_location(host: str, port: int, protocol: str, parallel: int) -> str:
    try:
        from nmb.speed.iperf_directory import describe_server
        d = describe_server(host, port)
    except Exception:
        d = {}
    where = " · ".join(x for x in (d.get("country"), d.get("isp")) if x)
    base = f"{protocol.upper()} -P {parallel}"
    return f"{where} · {base}" if where else base


def iperf3_servers(cfg: Config) -> List[tuple]:
    """The iPerf3 servers of automatic tests: the main one, then the extra ones, without repeats."""
    ip = getattr(cfg, "iperf", None)
    out: List[tuple] = []
    main = str(getattr(ip, "target_host", "") or "").strip()
    if main:
        out.append((main, int(getattr(ip, "target_port", 5201) or 5201)))
    for item in str(getattr(ip, "extra_servers", "") or "").replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.rpartition(":") if item.count(":") == 1 else (item, "", "")
        host = host or item
        try:
            p = int(port) if port else 5201
        except ValueError:
            continue
        if re.match(r"^[A-Za-z0-9.\-_]+$", host) and not host.startswith("-") and 0 < p < 65536 and (host, p) not in out:
            out.append((host, p))
    return out[:8]


def _answers(host: str, port: int) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError as e:
        log.info("iPerf3 server %s:%d left out: it does not answer (%s)", host, port, e)
        return False


IPERF3_FAIL_STREAK = 5
IPERF3_REST_SEC = 6 * 3600
_IPERF3_REST_LOGGED: dict = {}


def _iperf3_failing(conn, host: str, now_ms: Optional[int] = None) -> bool:
    """The last few scheduled tests against host all failed, the last one less than 6 hours ago.

    2026-11-08: one extra server accepted the TCP connection but closed every test (282 of 283
    "control socket has closed unexpectedly"), and it was tried again every minute.
    """
    if conn is None:
        return False
    now_ms = now_ms or int(time.time() * 1000)
    try:
        rows = conn.execute("SELECT status, ts FROM speedtest WHERE engine = 'iperf3' AND server_host = ? "
                            "AND status != 'skipped_busy' ORDER BY id DESC LIMIT ?", (host, IPERF3_FAIL_STREAK)).fetchall()
    except Exception:
        return False
    return (len(rows) == IPERF3_FAIL_STREAK and all(r[0] == "error" for r in rows)
            and now_ms - int(rows[0][1] or 0) < IPERF3_REST_SEC * 1000)


def _usable_iperf3_servers(cfg: Config, conn=None) -> List[tuple]:
    out = []
    for hp in iperf3_servers(cfg):
        if _iperf3_failing(conn, hp[0]):
            # Once per rest period, not every minute (2026-11-09: 200 identical warnings in 36 h).
            if time.time() - _IPERF3_REST_LOGGED.get(hp, 0.0) > IPERF3_REST_SEC:
                log.warning("iPerf3 server %s:%d left out for up to 6 h: its last %d tests all failed",
                            hp[0], hp[1], IPERF3_FAIL_STREAK)
                _IPERF3_REST_LOGGED[hp] = time.time()
            continue
        if conn is not None:
            # Only a check with the history can say the server is fine again; _iperf3_usable() asks without it,
            # and clearing the mark there made the warning come back at every cycle (17 an hour, 2026-11-10).
            _IPERF3_REST_LOGGED.pop(hp, None)
        if _answers(*hp):
            out.append(hp)
    return out


def _iperf3_usable(cfg: Config) -> bool:
    """At least one iPerf3 server is set and accepts a connection on its port."""
    return bool(_usable_iperf3_servers(cfg))


def _ookla_blocked_now(cfg: Config) -> bool:
    from nmb.speed.anti_ban import client_cooldown_remaining, scheduled_wait_remaining
    interval = 60 * int(getattr(getattr(cfg, "speedtest", None), "ookla_interval_min", 60) or 60)
    return client_cooldown_remaining() > 0 or scheduled_wait_remaining(interval) > 0


def _engine_due(conn, cfg: Config, engine: str, now_ms: int) -> bool:
    """Whether a scheduled test of this engine is due under its own interval."""
    minutes = int(getattr(cfg.speedtest, f"{engine}_interval_min", 0) or 0)
    if minutes <= 0:
        return True
    row = conn.execute("SELECT MAX(ts) FROM speedtest WHERE engine = ? AND status != 'skipped_busy'", (engine,)).fetchone()
    last = row[0] if row and row[0] else 0
    # 30 s of slack, so a run that started a little late does not skip a whole interval.
    due = now_ms - last >= minutes * 60_000 - 30_000
    if not due:
        log.info("%s skipped: its own interval (%d min) is not over yet", engine, minutes)
    return due


def _record_aborted(conn, trigger: str, engine: str, now_ms: int, reason: str) -> SpeedtestResult:
    """Save an aborted run without values; a partial result would not be a valid measurement."""
    reason = reason or "aborted: user traffic detected during the measurement"
    log.warning("speed test %s", reason)
    with db.tx(conn):
        conn.execute(
            "INSERT INTO speedtest (ts, trigger, status, error, engine) VALUES (?, ?, 'skipped_busy', ?, ?)",
            (now_ms, trigger, reason, engine),
        )
        conn.execute(
            "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warn', 'speed', 'speedtest_aborted', ?)",
            (now_ms, f"Scheduled speed test {reason}"),
        )
    return SpeedtestResult(status="skipped_busy", error=reason, engine=engine)


def _active_mode() -> str:
    conn = db.connect()
    try:
        row = conn.execute("SELECT v FROM kv WHERE k = 'active_mode'").fetchone()
        return str(row[0]) if row else ""
    except db.sqlite3.Error:
        return ""
    finally:
        conn.close()


def _save_visibility(visibility: str) -> None:
    conn = db.connect()
    try:
        with db.tx(conn):
            conn.execute(
                "INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('traffic_visibility', ?, ?)",
                (visibility, db.now_ms()),
            )
    finally:
        conn.close()


def _flag_server_mismatch(res: SpeedtestResult, target_server_id: Optional[int]) -> None:
    """Record when Ookla measured against a server other than the chosen one."""
    if not target_server_id or not res.server_id or int(res.server_id) == int(target_server_id):
        return
    log.warning("Ookla used server %s instead of the chosen server %s", res.server_id, target_server_id)
    try:
        raw = json.loads(res.raw_json) if res.raw_json else {}
    except (TypeError, ValueError):
        raw = {}
    raw["requested_server_id"] = int(target_server_id)
    res.raw_json = json.dumps(raw)


# NMB_MEASURE_LOCK: the update test run (nmb/common/updater.py) uses its own, or a scheduled test on the box
# holds this one and a test that runs a cycle gets "busy" (an update was refused on 2026-11-10 for that).
MEASURE_LOCK = os.environ.get("NMB_MEASURE_LOCK", "/run/nmb/speedtest.lock")
MEASURE_WAIT_SEC = 600   # a manual, web or Telegram test waits this long for a running one


def _measure_lock(wait_sec: float):
    """An exclusive lock across processes (web scheduler, Telegram bot, nmb-speed, nmb-selftest).

    2026-11-09: a Telegram test (Ookla) and a scheduled iPerf3 test of the web server ran at the same time;
    the old lock was per process, so each test measured the other's traffic too.
    """
    import fcntl
    from pathlib import Path as _P
    path = _P(MEASURE_LOCK)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        import tempfile
        fd = os.open(os.path.join(tempfile.gettempdir(), "nmb-speedtest.lock"), os.O_RDWR | os.O_CREAT, 0o666)
    t0 = time.monotonic()
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() - t0 >= wait_sec:
                os.close(fd)
                return None
            time.sleep(2)


def measurement_running_anywhere() -> bool:
    """True when any process on the box holds the measurement lock (a test is running now). Checks
    and releases at once; is_speedtest_running() only knows this process's own tests."""
    if is_speedtest_running():
        return True
    import fcntl
    try:
        fd = os.open(MEASURE_LOCK, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def run_measurement_cycle(cfg: Config, trigger: str = "schedule", *args, **kwargs) -> bool:
    """One measurement cycle at a time on the whole box (see _measure_lock)."""
    import fcntl
    wait = 0 if trigger == "schedule" else MEASURE_WAIT_SEC
    fd = _measure_lock(wait)
    if fd is None:
        reason = "another measurement was running on this box"
        log.warning("speed test (%s) not started: %s", trigger, reason)
        outcome = kwargs.get("outcome")
        if isinstance(outcome, dict):
            outcome.update(status="skipped_busy", error=reason)
        if kwargs.get("record_skip", True):
            try:
                conn = db.connect()
                with db.tx(conn):
                    conn.execute("INSERT INTO speedtest (ts, trigger, status, error, engine) VALUES (?, ?, 'skipped_busy', ?, ?)",
                                 (db.now_ms(), trigger, reason, kwargs.get("engine") or "all"))
                conn.close()
            except Exception as e:
                log.debug("could not record the skip: %s", e)
        return False
    try:
        return _run_measurement_cycle(cfg, trigger, *args, **kwargs)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _usb_test_not_allowed(cfg: Config, iface: str) -> bool:
    """A USB hotspot or modem carries a test only when it is the chosen measuring link, the router's WAN, or
    the only internet in standalone or bridge mode. While nmb-netd restarts (its state file is gone) or in
    router mode with the line down, the default route can briefly be the hotspot: two scheduled tests ran
    over mobile data that way during an update (2026-11-09)."""
    try:
        from nmb.netd.interfaces import usb_tether_kind
        if not iface or not usb_tether_kind(iface):
            return False
    except Exception:
        return False
    if getattr(cfg.network, "measurement_link", "auto") == "usb":
        return False
    try:
        st = json.loads(Path("/run/nmb/netd_state.json").read_text())
    except (OSError, ValueError):
        return True    # nmb-netd is (re)starting: the routes are not settled
    mode = st.get("active_mode")
    if mode == "mode_a":
        return (st.get("details") or {}).get("wan_interface") != iface
    return mode not in ("standalone", "mode_b")


def _run_measurement_cycle(
    cfg: Config,
    trigger: str = "schedule",
    force: bool = False,
    run_port_check: bool = True,
    custom_ports: Optional[List[int]] = None,
    server_id: Optional[int] = None,
    engine: Optional[str] = None,
    target_iface: Optional[str] = None,
    record_skip: bool = True,
    outcome: Optional[dict] = None,
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
                "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'speed', 'speedtest_skipped', 'Scheduled test skipped: speed testing is set to manual mode')",
                (now_ms,)
            )
        conn.close()
        return True

    # 0a. Router mode measures its own WAN. With that line down (PPPoE refused or redialing) a test would
    # leave over the USB hotspot or the Wi-Fi instead: the wrong line, and mobile data (2026-11-09: 19 tests
    # over the hotspot in an hour while DIGI refused the PPPoE login). No test then, unless one was asked
    # for on a chosen interface.
    if not target_iface:
        from nmb.netd.interfaces import _usable_address, router_wan_interface
        rw = router_wan_interface()
        if rw and not _usable_address(rw):
            reason = f"skipped: router mode, its internet line ({rw}) is down"
            log.warning("speed test %s", reason)
            if outcome is not None:
                outcome["wan_down"] = True
            return False

    # 0b. A metered line must not run out of data because of scheduled tests.
    limit_mb = float(getattr(cfg.speedtest, "daily_data_limit_mb", 0) or 0)
    if trigger == "schedule" and limit_mb > 0:
        budget_conn = db.connect()
        try:
            over_limit, used_mb = data_budget.limit_reached(budget_conn, limit_mb)
            if over_limit:
                reason = f"skipped: daily data limit reached ({used_mb:.0f} of {limit_mb:.0f} MB used today)"
                log.warning("speed test %s", reason)
                if outcome is not None:
                    outcome["data_limit"] = True
                with db.tx(budget_conn):
                    budget_conn.execute(
                        "INSERT INTO speedtest (ts, trigger, status, error, engine) VALUES (?, ?, 'skipped_busy', ?, ?)",
                        (now_ms, trigger, reason, engine),
                    )
                return False
        finally:
            budget_conn.close()

    # 0c. Mobile data over USB has its own daily limit, for every trigger (a manual test costs the same).
    try:
        from nmb.netd.interfaces import usb_tether_kind
        over_usb = getattr(cfg.network, "measurement_link", "auto") == "usb" or bool(target_iface and usb_tether_kind(target_iface))
    except Exception:
        over_usb = False
    if over_usb:
        from nmb.netd import usb_uplink
        usb_limit = float(getattr(getattr(cfg, "usb_uplink", None), "daily_limit_mb", 0) or 0)
        if usb_limit > 0:
            budget_conn = db.connect()
            try:
                over_limit, used_mb = data_budget.limit_reached(budget_conn, usb_limit, key=usb_uplink.USAGE_KEY)
                if over_limit:
                    reason = f"skipped: daily USB data limit reached ({used_mb:.0f} of {usb_limit:.0f} MB used today)"
                    log.warning("speed test %s", reason)
                    if outcome is not None:
                        outcome["data_limit"] = True
                    with db.tx(budget_conn):
                        budget_conn.execute(
                            "INSERT INTO speedtest (ts, trigger, status, error, engine) VALUES (?, ?, 'skipped_busy', ?, ?)",
                            (now_ms, trigger, reason, engine),
                        )
                    return False
            finally:
                budget_conn.close()

    # 1. Enforce Traffic Gate (Idle check with < 2% network load condition)
    tg_mode = getattr(cfg.speedtest, "idle_threshold_mode", "percent")
    thresh_pct = getattr(cfg.speedtest, "idle_threshold_percent", 2.0)
    fixed_kbps = getattr(cfg.speedtest, "idle_threshold_kbps", 500)
    max_wait = cfg.raw_parser.getfloat("speedtest", "idle_wait_max_sec", fallback=1800.0)

    # For scheduled automated tests, adjust wait timeout and consecutive idle seconds
    # dynamically based on schedule interval (especially for high-frequency second-level schedules).
    from nmb.speed.scheduler import get_cron_interval_seconds
    sched_cron = getattr(cfg.speedtest, "schedule_cron", "")
    interval_sec = get_cron_interval_seconds(sched_cron)
    consec_idle = 3.0

    if trigger == "schedule":
        if interval_sec is not None and interval_sec < 60.0:
            wait_timeout = min(max_wait, max(2.5, interval_sec * 0.75))
            consec_idle = min(3.0, max(1.0, interval_sec * 0.2))
        else:
            wait_timeout = min(max_wait, 60.0)
    else:
        wait_timeout = min(max_wait, 30.0)

    from nmb.netd.interfaces import find_preferred_measurement_interface
    pref_gate_iface, _, _ = find_preferred_measurement_interface(cfg, target_iface=target_iface)
    if not target_iface and _usb_test_not_allowed(cfg, pref_gate_iface):
        reason = f"skipped: no test over the USB hotspot ({pref_gate_iface}) unless it is the chosen measuring link"
        log.warning("speed test %s", reason)
        if outcome is not None:
            outcome["wan_down"] = True
        return False
    # Data cap of the link the tests would use (and of its connection type): automatic tests stop for the
    # rest of the period; manual ones still run and still count.
    if trigger == "schedule" and not force:
        from nmb.speed import data_cap
        cap_conn = db.connect()
        try:
            reached, why = data_cap.check(cap_conn, cfg, pref_gate_iface)
            if reached:
                log.warning("speed test skipped: %s", why)
                if outcome is not None:
                    outcome["data_limit"] = True
                    outcome["data_cap"] = why
                if data_cap.note_skip_due(cap_conn, pref_gate_iface):
                    with db.tx(cap_conn):
                        cap_conn.execute("INSERT INTO speedtest (ts, trigger, status, error, engine) VALUES (?, ?, 'skipped_busy', ?, ?)",
                                         (now_ms, trigger, f"skipped: {why}", engine))
                return False
        finally:
            cap_conn.close()
    from nmb.netd.lan_topology import traffic_monitor_device
    check_gate_iface = traffic_monitor_device(cfg.network, pref_gate_iface)
    monitor = None
    stop_enabled = bool(getattr(cfg.speedtest, "traffic_stop_enabled", False))
    if not force and stop_enabled:
        monitor = cross_traffic.ForeignTrafficMonitor.for_config(cfg, check_gate_iface, _active_mode())
        _save_visibility(monitor.visibility)
        # Without a view of other devices an idle line cannot be proven, so only ping keeps running.
        if trigger == "schedule" and monitor.visibility == cross_traffic.VISIBILITY_NONE:
            reason = "skipped: other devices' traffic is not visible to the box, so an idle network cannot be confirmed"
            log.warning("speed test %s", reason)
            if outcome is not None:
                outcome["blind"] = True
            if record_skip:
                conn = db.connect()
                with db.tx(conn):
                    conn.execute(
                        "INSERT INTO speedtest (ts, trigger, status, error, engine) VALUES (?, ?, 'skipped_busy', ?, ?)",
                        (now_ms, trigger, reason, engine),
                    )
                    conn.execute(
                        "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warn', 'speed', 'speedtest_skipped', ?)",
                        (now_ms, f"Scheduled speed test {reason}"),
                    )
                conn.close()
            return False
    if not force:
        gate = TrafficGate(check_gate_iface, strict=stop_enabled)
        cap_mbps = gate.get_interface_capacity_mbps(check_gate_iface, contract_down_mbps=cfg.isp.contract_down_mbps)
        gate_res = gate.wait_for_idle(
            threshold_kbps=fixed_kbps,
            max_wait_sec=wait_timeout,
            consecutive_idle_sec=consec_idle,
            iface=check_gate_iface,
            capacity_mbps=cap_mbps,
            threshold_percent=thresh_pct,
            mode=tg_mode,
            extra_kbps=monitor.router_kbps if monitor else None,
        )

        if not gate_res.cleared:
            if outcome is not None:
                outcome["deferred"] = True
            reason = (
                f"deferred: network traffic {gate_res.rate_kbps:.0f} kbps ({gate_res.load_percent:.2f}% load) exceeded the "
                f"{gate_res.threshold_kbps:.0f} kbps limit ({cap_mbps:.0f} Mbps capacity) to preserve test accuracy and protect active user traffic"
            )
            reason_hu = (
                f"Scheduled speed test deferred: network traffic {gate_res.rate_kbps:.0f} Kbps ({gate_res.load_percent:.2f}% load) "
                f"exceeded the {gate_res.threshold_kbps/1000.0:.1f} Mbps limit ({cap_mbps:.0f} Mbps capacity) "
                f"to preserve measurement accuracy and avoid disturbing client traffic."
            )
            log.warning("network busy: %s", reason)
            if not record_skip:
                return False
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
    usage_iface = check_gate_iface
    usage_start = data_budget.interface_bytes(usage_iface)
    target_server_id = server_id if server_id is not None else getattr(cfg.speedtest, "server_id", None)
    conn = db.connect()
    engines_to_run = ["ookla", "cloudflare", "fastcom", "rtr"] if engine == "all" else [engine or "ookla"]
    mixed = engine == "all"
    if trigger == "schedule" and engines_to_run == ["ookla"] and _ookla_blocked_now(cfg):
        # Ookla-only schedule while Ookla may not run (paused, or its hour is not over): run the
        # other engines instead, each stored under its own name, so the schedule still measures.
        log.info("Ookla cannot run now; this scheduled run uses Cloudflare and RTR-NetTest instead")
        engines_to_run = ["cloudflare", "fastcom", "rtr"]
        mixed = True
    if trigger == "schedule" and engines_to_run == ["iperf3"] and not _iperf3_usable(cfg):
        # iPerf3-only schedule: run only against a set server that answers; no empty rows.
        log.info("scheduled iPerf3 test skipped: no iPerf3 server is set, or it does not answer")
        conn.close()
        return True
    chosen = list(getattr(cfg.speedtest, "mixed_engines", None) or [])
    if trigger == "schedule" and engine == "all":
        # The owner may leave engines out of the scheduled mixed run for a while ([speedtest] mixed_engines).
        engines_to_run = [e for e in engines_to_run if e in chosen]
    if mixed and _iperf3_usable(cfg) and (trigger != "schedule" or engine != "all" or "iperf3" in chosen):
        # A mixed run includes iPerf3 when an iPerf3 server is set and answers.
        engines_to_run.append("iperf3")
    if trigger == "schedule" and engine == "all" and not engines_to_run:
        log.info("scheduled mixed run skipped: no engine is ticked for it")
        conn.close()
        return True
    if trigger == "schedule":
        # Each engine keeps its own minimum interval (Ookla's is checked in _run_single_engine).
        engines_to_run = [e for e in engines_to_run if e == "ookla" or _engine_due(conn, cfg, e, now_ms)]
        if not engines_to_run:
            conn.close()
            return True

    all_ok = True
    last_res = None
    token = cancel.CancelToken()
    stop_watch = threading.Event()
    # A person asked for manual runs, so only scheduled tests give way to other traffic.
    if monitor and trigger == "schedule":
        cross_traffic.watch(
            monitor, gate_res.threshold_kbps, stop_watch,
            lambda kbps: token.cancel(f"aborted: other traffic detected during the measurement ({kbps:.0f} kbps, 0 means counters unreadable)"),
        )
    try:
        with cancel.scope(token):
            for eng in engines_to_run:
                runs = [cfg]
                if eng == "iperf3" and trigger == "schedule":
                    # Each set iPerf3 server that answers, one after the other, each in its own row.
                    import copy
                    runs = []
                    for host, port in _usable_iperf3_servers(cfg, conn) or iperf3_servers(cfg)[:1]:
                        c2 = copy.copy(cfg)
                        c2.iperf = copy.copy(cfg.iperf)
                        c2.iperf.target_host, c2.iperf.target_port = host, port
                        runs.append(c2)
                for run_cfg in runs:
                    res = _run_single_engine(eng, run_cfg, trigger, target_server_id, conn, now_ms, target_iface=target_iface)
                    last_res = res
                    if res.status != "ok":
                        all_ok = False
                    if token.is_set():
                        break
                if token.is_set():
                    break
    finally:
        stop_watch.set()
        used_now = (data_budget.interface_bytes(usage_iface) - usage_start) / 1_000_000.0
        # Counting the data must never fail the measurement cycle: it sat outside the guard below and, with
        # traffic on the interface, made the cycle raise (the box's own update test run, 2026-11-10).
        try:
            data_budget.add_usage_mb(conn, used_now)
        except Exception:
            log.debug("daily usage accounting failed", exc_info=True)
        try:
            from nmb.netd.interfaces import usb_tether_kind
            if usage_iface and usb_tether_kind(usage_iface):
                from nmb.netd.usb_uplink import USAGE_KEY
                data_budget.add_usage_mb(conn, used_now, key=USAGE_KEY)
        except Exception:
            log.debug("usb usage accounting failed", exc_info=True)
        try:
            from nmb.speed import data_cap
            data_cap.add(conn, cfg, pref_gate_iface, used_now)   # per link and connection type ([data_cap])
        except Exception:
            log.debug("data cap accounting failed", exc_info=True)

    if token.is_set():
        if outcome is not None:
            outcome["deferred"] = True
        conn.close()
        return False

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
    parser.add_argument("--engine", "-e", choices=["ookla", "cloudflare", "fastcom", "rtr", "iperf3", "all"], help="Measurement engine")
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
        target_iface=args.interface,   # was parsed but never passed: every test ran on the default link
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
