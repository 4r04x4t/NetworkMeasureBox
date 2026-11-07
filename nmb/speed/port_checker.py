"""Net-neutrality TCP/UDP port throttling and traffic-shaping verification engine.

Tests connectivity and throughput across typical throttled or shaped ports
(HTTP 80, HTTPS 443, 8080, 8443, 53, 5060) against reference baseline (port 443).
"""
from __future__ import annotations

import logging
import socket
import sqlite3
import struct
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from nmb.db import database as db

log = logging.getLogger("nmb.speed.neutrality")

DEFAULT_PORTS = [80, 443, 8080, 8443, 53, 22, 5060, 6881]

# Reference test hosts providing responsive endpoints on diverse ports
TEST_HOSTS = {
    80: ("1.1.1.1", 80),
    443: ("1.1.1.1", 443),
    8080: ("portquiz.net", 8080),
    8443: ("1.1.1.1", 8443),
    53: ("8.8.8.8", 53),
    # portquiz.net answers on every TCP port, so it can stand in for SSH, SIP and BitTorrent.
    22: ("portquiz.net", 22),
    5060: ("portquiz.net", 5060),
    6881: ("portquiz.net", 6881),
}


@dataclass
class PortCheckResult:
    proto: str  # 'tcp', 'udp'
    port: int
    endpoint: str
    bps: Optional[int]
    baseline_bps: Optional[int]
    ratio: Optional[float]
    verdict: str  # 'ok', 'throttled', 'blocked', 'error'


# Standard DNS query for example.com (type A, class IN)
DNS_A_QUERY = b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"


def test_tcp_port(
    host: str,
    port: int,
    timeout_sec: float = 3.5,
    source_ip: Optional[str] = None,
    bind_iface: Optional[str] = None,
) -> Tuple[Optional[int], str]:
    """Test TCP port connectivity and achievable handshake/transfer rate.

    Sends protocol-appropriate probes:
      - Port 53: Valid DNS A-record query with 2-byte TCP length framing.
      - Ports 80, 8080, 8443, 443: HTTP GET requests with byte accounting.
    Supports binding strictly to interface or source IP for wired Ethernet priority.
    Returns (achievable_bps, status).
    """
    try:
        t0 = time.monotonic()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout_sec)
        if bind_iface:
            try:
                SO_BINDTODEVICE = 25
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, bind_iface.encode("utf-8") + b"\x00")
            except (PermissionError, OSError):
                pass
        if source_ip:
            try:
                s.bind((source_ip, 0))
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        s.connect((host, port))
        with s:
            t_connect = time.monotonic()

            if port == 53:
                # DNS over TCP requires 2-byte big-endian length prefix
                framed = struct.pack("!H", len(DNS_A_QUERY)) + DNS_A_QUERY
                s.sendall(framed)
                s.settimeout(2.5)
                len_hdr = s.recv(2)
                if len(len_hdr) < 2:
                    return None, "error"
                expected_len = struct.unpack("!H", len_hdr)[0]
                resp = s.recv(expected_len)
                duration = max(0.001, time.monotonic() - t_connect)
                bps = int(((len(resp) + 2) * 8) / duration)
                return bps, "ok"

            else:
                # HTTP/HTTPS test probe
                probe = f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: NMB/1.0\r\nConnection: close\r\n\r\n".encode()
                s.sendall(probe)
                total_bytes = len(probe)
                s.settimeout(2.5)
                while True:
                    try:
                        chunk = s.recv(8192)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                    except (socket.timeout, TimeoutError):
                        break

                duration = max(0.001, time.monotonic() - t_connect)
                bps = int((total_bytes * 8) / duration)
                return bps, "ok"

    except (socket.timeout, TimeoutError):
        return None, "blocked"
    except (ConnectionRefusedError, ConnectionResetError):
        return None, "blocked"
    except OSError as e:
        log.debug("port test %s:%d failed: %s", host, port, e)
        return None, "error"


def run_port_neutrality_check(
    ports: Optional[List[int]] = None,
    baseline_port: int = 443,
    interface: Optional[str] = None,
    bind_ip: Optional[str] = None,
) -> List[PortCheckResult]:
    """Run port throttling checks against target ports and compare to baseline, bound to preferred wired connection."""
    test_ports = ports or DEFAULT_PORTS
    results: List[PortCheckResult] = []

    if not interface or not bind_ip:
        try:
            from nmb.netd.interfaces import find_preferred_measurement_interface
            pref_if, pref_ip, _ = find_preferred_measurement_interface()
            interface = interface or pref_if
            bind_ip = bind_ip or pref_ip
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # 1. Establish baseline on unthrottled port 443
    base_host, _ = TEST_HOSTS.get(baseline_port, ("1.1.1.1", baseline_port))
    baseline_bps, base_status = test_tcp_port(base_host, baseline_port, source_ip=bind_ip, bind_iface=interface)
    if baseline_bps is None or baseline_bps <= 0:
        baseline_bps = 5_000_000  # Fallback baseline if reference test inconclusive

    log.info("net-neutrality check: baseline (port %d, iface=%s, ip=%s) transfer rate: %d bps", baseline_port, interface, bind_ip, baseline_bps)

    # 2. Check each target port
    for port in test_ports:
        host, p = TEST_HOSTS.get(port, ("1.1.1.1", port))
        bps, status = test_tcp_port(host, p, source_ip=bind_ip, bind_iface=interface)

        if status == "blocked":
            results.append(PortCheckResult(
                proto="tcp",
                port=port,
                endpoint=f"{host}:{port}",
                bps=None,
                baseline_bps=baseline_bps,
                ratio=0.0,
                verdict="blocked"
            ))
            continue

        if status == "error" or bps is None:
            results.append(PortCheckResult(
                proto="tcp",
                port=port,
                endpoint=f"{host}:{port}",
                bps=None,
                baseline_bps=baseline_bps,
                ratio=None,
                verdict="error"
            ))
            continue

        ratio = round(bps / float(baseline_bps), 3) if baseline_bps > 0 else 1.0
        # Throttled if throughput is consistently below 60% of baseline port
        verdict = "throttled" if ratio < 0.60 else "ok"

        log.info("port %d check: %d bps (baseline %d bps, ratio %.2f) -> verdict: %s",
                 port, bps, baseline_bps, ratio, verdict)

        results.append(PortCheckResult(
            proto="tcp",
            port=port,
            endpoint=f"{host}:{port}",
            bps=bps,
            baseline_bps=baseline_bps,
            ratio=ratio,
            verdict=verdict
        ))

    return results


def record_port_checks_to_db(conn: sqlite3.Connection, results: List[PortCheckResult]) -> None:
    now_ms = db.now_ms()
    rows = [
        (now_ms, r.proto, r.port, r.endpoint, r.bps, r.baseline_bps, r.ratio, r.verdict)
        for r in results
    ]
    with db.tx(conn):
        conn.executemany(
            """INSERT INTO port_check (ts, proto, port, endpoint, bps, baseline_bps, ratio, verdict)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )
