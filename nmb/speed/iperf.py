"""
iPerf3 Performance Testing and Daemon Service for NetworkMeasureBox.
Supports precision TCP/UDP bandwidth, jitter and packet loss probing (Client & Server modes).
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
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.speed.iperf")

_iperf_lock = threading.Lock()
_iperf_running = False
_iperf_server_proc: Optional[subprocess.Popen] = None
_iperf_server_port: int = 5201
_latest_iperf_result: Optional[Dict[str, Any]] = None


def is_iperf_available() -> bool:
    """Check if iperf3 binary is available on system PATH."""
    return shutil.which("iperf3") is not None


def run_iperf_client_test(
    host: str,
    port: int = 5201,
    duration: int = 10,
    protocol: str = "tcp",
    parallel: int = 1,
    reverse: bool = False,
    bidir: bool = False,
    direction: Optional[str] = None,
    bandwidth: Optional[str] = None,
    udp: bool = False,
    target_bandwidth: Optional[str] = None,
    bind_address: Optional[str] = None,
    congestion: Optional[str] = "bbr",
) -> Dict[str, Any]:
    """
    Run an iPerf3 client bandwidth measurement against a remote or LAN iperf3 server.
    Supports unidirectional (upload/download) and simultaneous bidirectional (--bidir) testing,
    with kernel BBR congestion control acceleration.
    """
    global _iperf_running, _latest_iperf_result

    host = (host or "").strip()
    if not host or host.startswith("-") or not re.match(r"^[a-zA-Z0-9.\-_:]+$", host):
        res = {"status": "error", "host": host, "port": port, "error": "Invalid target host format (must be valid hostname or IP, cannot start with '-')."}
        _latest_iperf_result = res
        return res

    try:
        port = max(1, min(65535, int(port)))
    except (ValueError, TypeError):
        port = 5201
    try:
        duration = max(1, min(60, int(duration)))
    except (ValueError, TypeError):
        duration = 10
    try:
        parallel = max(1, min(16, int(parallel)))
    except (ValueError, TypeError):
        parallel = 1

    if direction:
        d_lower = str(direction).lower().strip()
        if d_lower in ("bidir", "both", "duplex", "full-duplex"):
            bidir = True
        elif d_lower in ("down", "download", "reverse"):
            reverse = True
            bidir = False
        elif d_lower in ("up", "upload"):
            reverse = False
            bidir = False

    if bidir:
        reverse = False

    if udp:
        protocol = "udp"
    if target_bandwidth and not bandwidth:
        bandwidth = target_bandwidth
    if bandwidth:
        bw_str = str(bandwidth).strip()
        if not re.match(r"^[0-9]+[kKmMgG]?$", bw_str):
            bandwidth = None
        else:
            bandwidth = bw_str

    if bind_address:
        bind_clean = str(bind_address).strip()
        if not re.match(r"^[a-zA-Z0-9.\-_:%]+$", bind_clean):
            bind_address = None
        else:
            bind_address = bind_clean

    if not is_iperf_available():
        res = {
            "status": "error",
            "host": host,
            "port": port,
            "error": "iperf3 binary is not installed on this system. Please install via system package manager.",
        }
        _latest_iperf_result = res
        return res

    with _iperf_lock:
        if _iperf_running:
            return {"status": "busy", "message": "An iPerf3 test is already running."}
        _iperf_running = True

    try:
        cmd = [
            "iperf3",
            "-c", host,
            "-p", str(port),
            "-t", str(max(1, min(60, duration))),
            "-P", str(max(1, min(16, parallel))),
            "--connect-timeout", "4000",
            "-J",  # JSON output
        ]

        if bind_address:
            cmd.extend(["-B", bind_address])

        if protocol.lower() == "udp":
            cmd.append("-u")
            if bandwidth:
                cmd.extend(["-b", bandwidth])
        else:
            if bandwidth:
                cmd.extend(["-b", bandwidth])
            # Kernel TCP Congestion Control Acceleration (BBR / CUBIC)
            if congestion:
                try:
                    from pathlib import Path
                    avail_cc = Path("/proc/sys/net/ipv4/tcp_available_congestion_control").read_text()
                except Exception:
                    avail_cc = "bbr cubic reno"
                target_cc = str(congestion).strip().lower()
                if target_cc in avail_cc:
                    cmd.extend(["-C", target_cc])

        if bidir:
            cmd.append("--bidir")
        elif reverse:
            cmd.append("-R")

        log.info("running iperf3: %s", " ".join(cmd))
        log.debug("iperf3 initiating: host=%s, port=%d, duration=%d, proto=%s, streams=%d, reverse=%s, bidir=%s, bind=%s",
                  host, port, duration, protocol, parallel, reverse, bidir, bind_address)
        t0 = time.time()
        # Cap subprocess timeout to duration + 10s (connect timeout will bail after 4s anyway)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=duration + 12)
        elapsed = time.time() - t0
        log.debug("iperf3 process finished in %.2fs (exit code %d, stdout_len=%d, stderr_len=%d)",
                  elapsed, proc.returncode, len(proc.stdout or ""), len(proc.stderr or ""))

        if proc.returncode != 0 and not proc.stdout:
            err = proc.stderr.strip() or f"iperf3 exited with code {proc.returncode}"
            res = {
                "status": "error",
                "host": host,
                "port": port,
                "error": err,
                "cmd": " ".join(cmd),
                "timestamp": int(time.time() * 1000),
            }
            _latest_iperf_result = res
            return res

        try:
            raw_data = json.loads(proc.stdout)
        except Exception:
            res = {
                "status": "error",
                "host": host,
                "port": port,
                "error": proc.stderr.strip() or "Could not parse JSON output from iperf3",
                "raw_output": proc.stdout[:2000],
                "cmd": " ".join(cmd),
                "timestamp": int(time.time() * 1000),
            }
            _latest_iperf_result = res
            return res

        # Check if iperf3 returned an explicit error in JSON
        if "error" in raw_data:
            err_msg = str(raw_data["error"]).strip()
            res = {
                "status": "error",
                "host": host,
                "port": port,
                "protocol": protocol.upper(),
                "error": err_msg,
                "cmd": " ".join(cmd),
                "timestamp": int(time.time() * 1000),
                "raw_output": f"Error: {err_msg}\nCommand: {' '.join(cmd)}",
            }
            _latest_iperf_result = res
            return res

        # Extract summary metrics from JSON
        start_info = raw_data.get("start", {})
        test_start = start_info.get("test_start", {})
        is_bidir = bidir or (test_start.get("bidir") == 1)

        end = raw_data.get("end", {})
        sum_sent = end.get("sum_sent", {})
        sum_received = end.get("sum_received", {})

        if is_bidir:
            sum_rcv_bidir = end.get("sum_received_bidir_reverse", {})
            if not sum_rcv_bidir:
                sum_rcv_bidir = end.get("sum_bidir_reverse", {})

            up_bps = sum_sent.get("bits_per_second", 0.0)
            down_bps = sum_rcv_bidir.get("bits_per_second", 0.0)
            bps = up_bps + down_bps

            up_mbps = round(up_bps / 1_000_000.0, 2)
            down_mbps = round(down_bps / 1_000_000.0, 2)
            total_mbps = round(bps / 1_000_000.0, 2)

            retransmits = sum_sent.get("retransmits", 0) if protocol.lower() == "tcp" else None
            sum_sent_rev = end.get("sum_sent_bidir_reverse", {})
            server_retx = sum_sent_rev.get("retransmits", 0) if protocol.lower() == "tcp" else 0

            jitter_ms = None
            lost_percent = None
            if protocol.lower() == "udp":
                jitter_ms = sum_rcv_bidir.get("jitter_ms")
                if jitter_ms is None:
                    jitter_ms = sum_sent.get("jitter_ms")
                lost_percent = sum_rcv_bidir.get("lost_percent")
                if lost_percent is None:
                    lost_percent = sum_sent.get("lost_percent")
        else:
            sum_data = sum_received if reverse else sum_sent
            if not sum_data:
                sum_data = end.get("sum", {})

            bps = sum_data.get("bits_per_second", 0.0)
            up_bps = None if reverse else bps
            down_bps = bps if reverse else None
            up_mbps = None if reverse else round(bps / 1_000_000.0, 2)
            down_mbps = round(bps / 1_000_000.0, 2) if reverse else None
            total_mbps = round(bps / 1_000_000.0, 2)

            retransmits = sum_sent.get("retransmits", 0) if protocol.lower() == "tcp" else None
            server_retx = 0

            jitter_ms = None
            lost_percent = None
            if protocol.lower() == "udp":
                udp_sum = end.get("sum", {})
                jitter_ms = udp_sum.get("jitter_ms")
                lost_percent = udp_sum.get("lost_percent")

        # Extract round-trip latency (RTT) from stream sender statistics
        rtt_ms = None
        streams = end.get("streams", [])
        if streams:
            for s in streams:
                sender_info = s.get("sender", {})
                if "mean_rtt" in sender_info and sender_info["mean_rtt"]:
                    rtt_ms = round(sender_info["mean_rtt"] / 1000.0, 2)
                    break

        # Connection metadata
        connected_list = start_info.get("connected", [])
        local_host = connected_list[0].get("local_host") if connected_list else None
        remote_host = connected_list[0].get("remote_host") if connected_list else None
        log.debug("iperf3 metrics parsed: %.2f Mbps (up=%s, down=%s), RTT=%sms, retransmits=%s, jitter=%sms, loss=%s%% (endpoints: local=%s, remote=%s)",
                  total_mbps, up_mbps, down_mbps, rtt_ms, retransmits, jitter_ms, lost_percent, local_host, remote_host)

        # Build clean raw text representation
        if is_bidir:
            dir_label = "Simultaneous Both Ways / Full Duplex (--bidir)"
            raw_lines = [
                f"=== iPerf3 Benchmark Results ===",
                f"Target: {host}:{port} ({remote_host or host})",
                f"Local Endpoint: {local_host or '--'}",
                f"Protocol: {protocol.upper()} | Streams: {parallel} | Direction: {dir_label}",
                f"Upload Speed (Client -> Server): {up_mbps:.2f} Mbps ({(up_bps / 8000000.0):.2f} MB/s)",
                f"Download Speed (Server -> Client): {down_mbps:.2f} Mbps ({(down_bps / 8000000.0):.2f} MB/s)",
                f"Combined Throughput: {total_mbps:.2f} Mbps ({(bps / 8000000.0):.2f} MB/s)",
            ]
            if protocol.lower() == "tcp":
                retx_detail = f"TCP Retransmissions: Client TX {retransmits or 0}"
                if server_retx:
                    retx_detail += f", Server TX {server_retx}"
                raw_lines.append(retx_detail)
                if rtt_ms is not None:
                    raw_lines.append(f"RTT (Round Trip Latency): {rtt_ms:.2f} ms")
            else:
                raw_lines.append(f"UDP Jitter: {jitter_ms if jitter_ms is not None else 0.0:.2f} ms")
                raw_lines.append(f"Packet Loss: {lost_percent if lost_percent is not None else 0.0:.2f}%")
            raw_lines.append(f"Test Duration: {elapsed:.2f}s | Command: {' '.join(cmd)}")
        else:
            dir_label = "Download (Server -> Client)" if reverse else "Upload (Client -> Server)"
            raw_lines = [
                f"=== iPerf3 Benchmark Results ===",
                f"Target: {host}:{port} ({remote_host or host})",
                f"Local Endpoint: {local_host or '--'}",
                f"Protocol: {protocol.upper()} | Streams: {parallel} | Direction: {dir_label}",
                f"Throughput: {bps / 1000000.0:.2f} Mbps ({(bps / 8000000.0):.2f} MB/s)",
            ]
            if protocol.lower() == "tcp":
                raw_lines.append(f"TCP Retransmissions: {retransmits if retransmits is not None else 0}")
                if rtt_ms is not None:
                    raw_lines.append(f"RTT (Round Trip Latency): {rtt_ms:.2f} ms")
            else:
                raw_lines.append(f"UDP Jitter: {jitter_ms if jitter_ms is not None else 0.0:.2f} ms")
                raw_lines.append(f"Packet Loss: {lost_percent if lost_percent is not None else 0.0:.2f}%")
            raw_lines.append(f"Test Duration: {elapsed:.2f}s | Command: {' '.join(cmd)}")

        # TCP Window / Buffer telemetry
        win_size = test_start.get("window_size") or test_start.get("rcvbuf") or test_start.get("sndbuf")
        blk_size = test_start.get("blksize")
        mss_val = start_info.get("tcp_mss_default")
        if win_size and win_size > 0:
            tcp_window_str = f"{win_size // 1024} KB"
        elif blk_size and blk_size > 0:
            tcp_window_str = f"Block: {blk_size // 1024} KB"
        elif mss_val:
            tcp_window_str = f"MSS: {mss_val} B"
        else:
            tcp_window_str = "Auto (TCP Autotuning)"

        res = {
            "status": "ok",
            "host": host,
            "port": port,
            "protocol": protocol.upper(),
            "duration_sec": duration,
            "parallel_streams": parallel,
            "reverse": reverse,
            "bidir": is_bidir,
            "is_bidirectional": is_bidir,
            "direction": "bidir" if is_bidir else ("download" if reverse else "upload"),
            "bps": bps,
            "mbps": total_mbps,
            "upload_bps": up_bps,
            "upload_mbps": up_mbps,
            "download_bps": down_bps,
            "download_mbps": down_mbps,
            "retransmits": retransmits,
            "jitter_ms": round(jitter_ms, 2) if jitter_ms is not None else None,
            "lost_percent": round(lost_percent, 2) if lost_percent is not None else None,
            "rtt_ms": rtt_ms,
            "elapsed_sec": round(elapsed, 2),
            "local_host": local_host,
            "remote_host": remote_host,
            "bound_address": bind_address or local_host,
            "tcp_window": tcp_window_str,
            "timestamp": int(time.time() * 1000),
            "cmd": " ".join(cmd),
            "raw_output": "\n".join(raw_lines),
        }
        _latest_iperf_result = res
        return res

    except subprocess.TimeoutExpired:
        res = {
            "status": "error",
            "host": host,
            "port": port,
            "error": f"iPerf3 test timed out after maximum allowable duration ({duration + 12}s).",
            "cmd": " ".join(cmd),
            "timestamp": int(time.time() * 1000),
            "raw_output": f"Error: iPerf3 test timed out.\nHost {host}:{port} did not complete test within {duration + 12}s.",
        }
        _latest_iperf_result = res
        return res
    except Exception as e:
        log.error("iperf3 execution error: %s", e)
        res = {
            "status": "error",
            "host": host,
            "port": port,
            "error": str(e),
            "timestamp": int(time.time() * 1000),
            "raw_output": f"Error: {e}",
        }
        _latest_iperf_result = res
        return res
    finally:
        with _iperf_lock:
            _iperf_running = False


def get_latest_iperf_result() -> Optional[Dict[str, Any]]:
    """Return the most recent iperf test result."""
    return _latest_iperf_result


def is_iperf_running() -> bool:
    """Return whether a client test is currently executing."""
    return _iperf_running


def start_iperf_server(port: int = 5201) -> Dict[str, Any]:
    """Start local iperf3 server daemon on the box."""
    global _iperf_server_proc, _iperf_server_port
    if not is_iperf_available():
        return {"status": "error", "message": "iperf3 binary is not installed."}

    try:
        port = max(1024, min(65535, int(port)))
    except (ValueError, TypeError):
        port = 5201

    if _iperf_server_proc and _iperf_server_proc.poll() is None:
        return {
            "status": "ok",
            "message": f"iPerf3 server is already running on port {_iperf_server_port}.",
            "server": get_iperf_server_status(),
        }

    try:
        cmd = ["iperf3", "-s", "-p", str(port)]
        _iperf_server_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _iperf_server_port = port
        time.sleep(0.3)
        if _iperf_server_proc.poll() is not None:
            return {"status": "error", "message": f"iPerf3 server failed to start on port {port} (port may be in use)."}
        return {
            "status": "ok",
            "message": f"iPerf3 server started successfully on port {port} (PID {_iperf_server_proc.pid}).",
            "server": get_iperf_server_status(),
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to start iperf3 server: {e}"}


def is_iperf_port_listening(port: int = 5201) -> bool:
    """Quickly check if port is currently open and accepting connections on localhost."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def stop_iperf_server() -> Dict[str, Any]:
    """Stop local iperf3 server daemon."""
    global _iperf_server_proc
    stopped_any = False
    if _iperf_server_proc and _iperf_server_proc.poll() is None:
        try:
            _iperf_server_proc.terminate()
            _iperf_server_proc.wait(timeout=3)
            _iperf_server_proc = None
            stopped_any = True
        except Exception:
            _iperf_server_proc.kill()
            _iperf_server_proc = None
            stopped_any = True

    # If port is still listening from external or orphaned process, try pkill
    if is_iperf_port_listening(_iperf_server_port):
        try:
            subprocess.run(["pkill", "-f", "iperf3 -s"], timeout=2.0)
            stopped_any = True
        except Exception:
            pass

    msg = "iPerf3 server stopped." if stopped_any else "iPerf3 server was not running."
    return {"status": "ok", "message": msg, "server": get_iperf_server_status()}


def get_iperf_server_status() -> Dict[str, Any]:
    """Get the running status of local iperf3 server."""
    running = _iperf_server_proc is not None and _iperf_server_proc.poll() is None
    pid = _iperf_server_proc.pid if running else None
    
    # Also check if port is listening (e.g. started by external service or prior daemon)
    if not running and is_iperf_port_listening(_iperf_server_port):
        running = True

    return {
        "server_running": running,
        "is_running": running,
        "pid": pid,
        "port": _iperf_server_port,
        "available": is_iperf_available(),
    }

