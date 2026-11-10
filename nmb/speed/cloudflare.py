"""Cloudflare Speed Test Engine (cloudflare-speed-cli reproduction).

Pure Python, zero external dependencies.
Measures download/upload throughput, idle latency, loaded latency (bufferbloat),
and extracts Cloudflare global edge metadata (Airport Colo code, ASN, City, Country, Client IP).
"""
from __future__ import annotations

import collections
import json
import logging
import socket
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import http.client
from nmb.speed import cancel
from nmb.common.user_agent import get_effective_user_agent
from nmb.speed.ookla import SpeedtestResult, calculate_bufferbloat

log = logging.getLogger("nmb.speed.cloudflare")

HOST = "speed.cloudflare.com"
BASE_URL = f"https://{HOST}"

# Fixed-time parallel transfers: short downloads mostly measure TCP ramp-up, not the line.
STREAMS = 4
TEST_SECONDS = 8.0
WARMUP_SECONDS = 2.0
REQUEST_BYTES = 100_000_000
UPLOAD_REQUEST_BYTES = 25_000_000
READ_CHUNK_BYTES = 262_144
SEND_CHUNK_BYTES = 65_536

_bound_source_ip: Optional[str] = None


class BoundHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, source_ip: str):
        self.source_ip = source_ip
        super().__init__()

    def http_open(self, req):
        return self.do_open(self._build_conn, req)

    def _build_conn(self, host, **kwargs):
        kwargs["source_address"] = (self.source_ip, 0)
        return http.client.HTTPConnection(host, **kwargs)


class BoundHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, source_ip: str):
        self.source_ip = source_ip
        super().__init__()

    def https_open(self, req):
        return self.do_open(self._build_conn, req)

    def _build_conn(self, host, **kwargs):
        kwargs["source_address"] = (self.source_ip, 0)
        return http.client.HTTPSConnection(host, **kwargs)


def _open_url(req: urllib.request.Request, timeout: float = 10.0):
    if _bound_source_ip:
        opener = urllib.request.build_opener(BoundHTTPHandler(_bound_source_ip), BoundHTTPSHandler(_bound_source_ip))
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _current_ua() -> str:
    try:
        return get_effective_user_agent()
    except Exception:
        log.debug("suppressed exception", exc_info=True)
        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/133.0.6943.126 Safari/537.36"


@dataclass
class CloudflareMeta:
    client_ip: str = ""
    colo: str = ""
    city: str = ""
    country: str = ""
    asn: str = ""
    latitude: str = ""
    longitude: str = ""
    postal_code: str = ""
    timezone: str = ""


@dataclass
class CloudflareSpeedResult:
    status: str  # 'ok', 'error'
    down_bps: Optional[int] = None
    up_bps: Optional[int] = None
    ping_us: Optional[int] = None
    jitter_us: Optional[int] = None
    loss_pct: Optional[float] = None   # this engine does not measure packet loss
    down_loaded_lat_ms: Optional[float] = None
    up_loaded_lat_ms: Optional[float] = None
    bufferbloat_grade: Optional[str] = None
    bufferbloat_delta_ms: Optional[float] = None
    meta: CloudflareMeta = field(default_factory=CloudflareMeta)
    recovered_streams: int = 0
    tier_downloads: Dict[str, float] = field(default_factory=dict)
    tier_uploads: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None

    def to_speedtest_result(self, bound_iface: Optional[str] = None, bound_ip: Optional[str] = None) -> SpeedtestResult:
        """Convert to standard NMB SpeedtestResult for DB persistence."""
        srv_name = f"Cloudflare Edge ({self.meta.colo})" if self.meta.colo else "Cloudflare Edge"
        # The city/country headers describe the CLIENT (the box's own town), not the server: the server's
        # place is only known through its colo code (2026-11-10: rows said the box's town next to colo BUD).
        srv_loc = f"Cloudflare {self.meta.colo}" if self.meta.colo else None
        srv_host = f"speed.cloudflare.com [{self.meta.colo}]" if self.meta.colo else "speed.cloudflare.com"

        # Only the address Cloudflare saw for this test, and only a public one; no cached address of the
        # other IP family that the test never used.
        from nmb.common.netaddr import split_global
        v4, v6 = split_global(self.meta.client_ip)

        return SpeedtestResult(
            status=self.status,
            down_bps=self.down_bps,
            up_bps=self.up_bps,
            ping_us=self.ping_us,
            jitter_us=self.jitter_us,
            loss_pct=self.loss_pct,
            server_id=None,
            server_name=srv_name,
            server_host=srv_host,
            server_location=srv_loc,
            client_ip=v4,
            client_ipv6=v6,
            result_url=None,  # Cloudflare gives no page for a single result
            raw_json=json.dumps({
                "engine": "cloudflare",
                "colo": self.meta.colo,
                "client_city": self.meta.city,
                "client_country": self.meta.country,
                "client_asn": self.meta.asn,
                "recovered_tls_streams": self.recovered_streams,
                "tier_downloads_mbps": self.tier_downloads,
                "tier_uploads_mbps": self.tier_uploads,
                "down_loaded_lat_ms": self.down_loaded_lat_ms,
                "up_loaded_lat_ms": self.up_loaded_lat_ms,
                "bufferbloat_grade": self.bufferbloat_grade,
                "bufferbloat_delta_ms": self.bufferbloat_delta_ms,
            }),
            error=self.error,
            down_loaded_lat_ms=self.down_loaded_lat_ms,
            up_loaded_lat_ms=self.up_loaded_lat_ms,
            bufferbloat_grade=self.bufferbloat_grade,
            bufferbloat_delta_ms=self.bufferbloat_delta_ms,
            engine="cloudflare",
            colo=self.meta.colo or None,
            bound_iface=bound_iface,
            bound_ip=bound_ip,
        )


def _cf_headers() -> Dict[str, str]:
    """Generate realistic browser headers including Origin/Referer to avoid Cloudflare WAF 429 rate-limiting."""
    return {
        "User-Agent": _current_ua(),
        "Referer": "https://speed.cloudflare.com/",
        "Origin": "https://speed.cloudflare.com",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def _get_request(url: str, timeout: float = 10.0) -> Tuple[bytes, dict]:
    req = urllib.request.Request(url, headers=_cf_headers())
    with _open_url(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers)


def _post_request(url: str, data: bytes, timeout: float = 12.0) -> Tuple[bytes, dict]:
    headers = _cf_headers()
    headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(url, data=data, headers=headers)
    with _open_url(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers)


def fetch_cloudflare_metadata() -> CloudflareMeta:
    """Probe Cloudflare edge to extract client IP, colo, city, country, ASN."""
    meta = CloudflareMeta()
    try:
        _, headers = _get_request(f"{BASE_URL}/__down?bytes=0", timeout=5.0)
        meta.client_ip = headers.get("cf-meta-ip") or headers.get("CF-Connecting-IP") or ""
        meta.colo = headers.get("colo") or headers.get("cf-meta-colo") or ""
        meta.city = headers.get("city") or ""
        meta.country = headers.get("country") or ""
        meta.asn = headers.get("asn") or ""
        meta.latitude = headers.get("latitude") or ""
        meta.longitude = headers.get("longitude") or ""
        meta.postal_code = headers.get("postalCode") or ""
        meta.timezone = headers.get("timezone") or ""
    except Exception as e:
        log.warning("failed to fetch cloudflare metadata: %s", e)
    return meta


def _new_connection(timeout: float = 15.0) -> http.client.HTTPSConnection:
    """Open an established HTTPS connection, so later timing excludes TCP and TLS setup."""
    source = (_bound_source_ip, 0) if _bound_source_ip else None
    conn = http.client.HTTPSConnection(HOST, timeout=timeout, source_address=source)
    conn.connect()
    return conn


def _tcp_connect_ms(timeout: float = 3.0) -> float:
    """Return the TCP handshake time in milliseconds; it excludes TLS and server processing."""
    source = (_bound_source_ip, 0) if _bound_source_ip else None
    t0 = time.monotonic()
    with socket.create_connection((HOST, 443), timeout=timeout, source_address=source):
        return (time.monotonic() - t0) * 1000.0


def measure_idle_latency(count: int = 8) -> Tuple[Optional[float], Optional[float], List[float]]:
    """Measure idle latency and jitter in milliseconds from TCP handshakes."""
    socket.getaddrinfo(HOST, 443)
    latencies: List[float] = []
    for _ in range(count):
        try:
            latencies.append(_tcp_connect_ms())
        except OSError as e:
            log.warning("idle latency sample failed: %s", e)
        time.sleep(0.08)

    if not latencies:
        return None, None, []

    median_lat = statistics.median(latencies)
    deltas = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
    jitter = statistics.mean(deltas) if deltas else None   # one sample gives no jitter, not 0
    return median_lat, jitter, latencies


def _probe_loaded_latency(stop_event: threading.Event, output_list: List[float]) -> None:
    """Sample latency from TCP handshakes during a transfer."""
    while not stop_event.wait(0.5):
        try:
            output_list.append(_tcp_connect_ms())
        except OSError as e:
            log.debug("loaded latency sample failed: %s", e)


class _RateLimited(Exception):
    """Cloudflare asked us to stop; retrying would make it worse."""


class _ByteMeter:
    """Thread-safe byte counter that ignores the TCP ramp-up period."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bytes = 0
        self.errors: List[str] = []

    def add(self, count: int, now: float, window_start: float, window_end: float) -> None:
        if window_start <= now <= window_end:
            with self._lock:
                self.bytes += count

    def error(self, message: str) -> None:
        with self._lock:
            self.errors.append(message)


def _download_worker(conn, meter: _ByteMeter, start: threading.Event, window: Tuple[float, float], stop_at: List[float]) -> None:
    buffer = bytearray(READ_CHUNK_BYTES)
    start.wait()
    while time.monotonic() < stop_at[0]:
        try:
            conn = _download_until_stop(conn, buffer, meter, window, stop_at)
        except _RateLimited as e:
            meter.error(str(e))
            break
        except (OSError, http.client.HTTPException) as e:
            # One dropped TLS stream should not lower the result for the rest of the window.
            meter.error(str(e))
            conn.close()
            time.sleep(0.2)
            try:
                conn = _new_connection()
            except (OSError, http.client.HTTPException) as reconnect_error:
                meter.error(str(reconnect_error))
                return
    conn.close()


def _download_until_stop(conn, buffer, meter, window, stop_at):
    while time.monotonic() < stop_at[0]:
        conn.request("GET", f"/__down?bytes={REQUEST_BYTES}", headers=_cf_headers())
        response = conn.getresponse()
        if response.status == 429:
            raise _RateLimited("HTTP 429")
        if response.status != 200:
            raise http.client.HTTPException(f"HTTP {response.status}")
        while time.monotonic() < stop_at[0]:
            count = response.readinto(buffer)
            if not count:
                break
            meter.add(count, time.monotonic(), window[0], window[1])
    return conn


def _upload_worker(conn, meter: _ByteMeter, start: threading.Event, window: Tuple[float, float], stop_at: List[float]) -> None:
    payload = b"0" * SEND_CHUNK_BYTES
    start.wait()
    try:
        while time.monotonic() < stop_at[0]:
            headers = _cf_headers()
            headers["Content-Type"] = "application/octet-stream"
            headers["Content-Length"] = str(UPLOAD_REQUEST_BYTES)
            conn.putrequest("POST", "/__up")
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders()
            sent = 0
            while sent < UPLOAD_REQUEST_BYTES:
                if time.monotonic() >= stop_at[0]:
                    return
                chunk = payload[:UPLOAD_REQUEST_BYTES - sent]
                conn.send(chunk)
                sent += len(chunk)
                meter.add(len(chunk), time.monotonic(), window[0], window[1])
            response = conn.getresponse()
            response.read()
            if response.status != 200:
                raise http.client.HTTPException(f"HTTP {response.status}")
    except (OSError, http.client.HTTPException) as e:
        meter.error(str(e))
    finally:
        conn.close()


def _measure_throughput(worker, streams: int = STREAMS, duration: float = TEST_SECONDS,
                        warmup: float = WARMUP_SECONDS) -> Tuple[float, List[str]]:
    """Run parallel transfers for a fixed time and return Mbps over the post-warmup window."""
    cancel.check()
    meter = _ByteMeter()
    conns = []
    for _ in range(streams):
        try:
            conns.append(_new_connection())
        except (OSError, http.client.HTTPException) as e:
            meter.error(str(e))
    if not conns:
        return 0.0, meter.errors

    start = threading.Event()
    window = [0.0, 0.0]
    stop_at = [0.0]
    threads = [threading.Thread(target=worker, args=(c, meter, start, window, stop_at), daemon=True) for c in conns]
    for thread in threads:
        thread.start()
    now = time.monotonic()
    window[0], window[1] = now + warmup, now + duration
    stop_at[0] = now + duration
    start.set()
    deadline = time.monotonic() + duration + 20.0
    for thread in threads:
        while thread.is_alive() and time.monotonic() < deadline:
            if cancel.is_requested():
                stop_at[0] = 0.0
            thread.join(timeout=0.25)
    cancel.check()
    return (meter.bytes * 8) / ((duration - warmup) * 1_000_000.0), meter.errors


def _link_capacity_mbps(interface: Optional[str]) -> Optional[float]:
    """Return the negotiated link speed, or None when the kernel does not report one."""
    if not interface:
        return None
    try:
        speed = int(Path(f"/sys/class/net/{interface}/speed").read_text().strip())
    except (OSError, ValueError):
        return None
    return float(speed) if speed > 0 else None


def _plausible_mbps(mbps: float, capacity: Optional[float], direction: str) -> Optional[float]:
    """Discard a physically impossible result instead of storing it."""
    if capacity and mbps > capacity * 1.05:
        log.error("discarding impossible cloudflare %s result: %.1f Mbps on a %.0f Mbps link", direction, mbps, capacity)
        return None
    return mbps


def split_transfer_errors(errors: List[str]) -> Tuple[List[str], List[str]]:
    """Separate TLS stream drops the workers recover from, from errors that can affect a result."""
    recovered = [e for e in errors if "RECORD_LAYER_FAILURE" in e]
    return recovered, [e for e in errors if "RECORD_LAYER_FAILURE" not in e]


def execute_cloudflare_speedtest(interface: Optional[str] = None, bind_ip: Optional[str] = None) -> SpeedtestResult:
    """Execute complete Cloudflare Speed Test mirroring cloudflare-speed-cli with optional interface binding."""
    global _bound_source_ip
    _bound_source_ip = bind_ip
    log.info("starting Cloudflare global edge network measurement cycle (iface=%s, bind_ip=%s)", interface, bind_ip)
    t_start = time.monotonic()

    # 1. Edge Metadata
    meta = fetch_cloudflare_metadata()
    log.info("cloudflare edge connected: colo=%s, city=%s, client_ip=%s, asn=%s",
             meta.colo, meta.city, meta.client_ip, meta.asn)

    # 2. Idle Latency & Jitter
    idle_lat, jitter, _ = measure_idle_latency(count=5)
    log.info("idle latency: %.2f ms, jitter: %.2f ms", idle_lat or 0.0, jitter or 0.0)

    capacity = _link_capacity_mbps(interface)

    # 3. Download Throughput & Loaded Download Latency
    down_loaded_lats: List[float] = []
    stop_probe = threading.Event()
    probe = threading.Thread(target=_probe_loaded_latency, args=(stop_probe, down_loaded_lats), daemon=True)
    probe.start()
    measured_down, down_errors = _measure_throughput(_download_worker)
    stop_probe.set()
    probe.join(timeout=4.0)
    mean_down_mbps = _plausible_mbps(measured_down, capacity, "download")
    # No sample under load means unknown, not "the same as idle" (that gave a made-up A+ grade).
    loaded_down_lat = statistics.median(down_loaded_lats) if down_loaded_lats else None

    # 4. Upload Throughput & Loaded Upload Latency
    up_loaded_lats: List[float] = []
    stop_probe = threading.Event()
    probe = threading.Thread(target=_probe_loaded_latency, args=(stop_probe, up_loaded_lats), daemon=True)
    probe.start()
    measured_up, up_errors = _measure_throughput(_upload_worker)
    stop_probe.set()
    probe.join(timeout=4.0)
    mean_up_mbps = _plausible_mbps(measured_up, capacity, "upload")
    loaded_up_lat = statistics.median(up_loaded_lats) if up_loaded_lats else None

    window_label = f"{STREAMS}x{TEST_SECONDS:.0f}s"
    tier_downloads = {window_label: round(measured_down, 2)}
    tier_uploads = {window_label: round(measured_up, 2)}
    transfer_errors = down_errors + up_errors
    # A TLS stream that drops and reconnects did not change results in repeated tests on the box.
    recovered, serious = split_transfer_errors(transfer_errors)
    if recovered:
        log.info("cloudflare: %d TLS streams dropped and reconnected", len(recovered))
    if serious:
        log.warning("cloudflare transfer errors: %s", serious[:4])

    # 5. Bufferbloat Calculation
    bb_grade, bb_delta = calculate_bufferbloat(idle_lat, loaded_down_lat, loaded_up_lat)
    log.info("cloudflare speedtest finished: Down: %.2f Mbps, Up: %.2f Mbps, Lat: %.2f ms, Bufferbloat: %s (+%.1f ms)",
             mean_down_mbps or 0.0, mean_up_mbps or 0.0, idle_lat or 0.0, bb_grade or "N/A", bb_delta or 0.0)

    res = CloudflareSpeedResult(
        status="ok" if (mean_down_mbps and mean_up_mbps) else "error",
        down_bps=int(mean_down_mbps * 1_000_000) if mean_down_mbps else None,
        up_bps=int(mean_up_mbps * 1_000_000) if mean_up_mbps else None,
        ping_us=round(idle_lat * 1000) if idle_lat is not None else None,
        jitter_us=round(jitter * 1000) if jitter is not None else None,
        loss_pct=None,          # not measured by this engine
        down_loaded_lat_ms=round(loaded_down_lat, 2) if loaded_down_lat else None,
        up_loaded_lat_ms=round(loaded_up_lat, 2) if loaded_up_lat else None,
        bufferbloat_grade=bb_grade,
        bufferbloat_delta_ms=bb_delta,
        meta=meta,
        recovered_streams=len(recovered),
        tier_downloads=tier_downloads,
        tier_uploads=tier_uploads,
        error="; ".join(transfer_errors[:3]) or None if not (mean_down_mbps and mean_up_mbps) else None,
    )
    from nmb.common.memory import trim_process_memory
    trim_process_memory()
    return res.to_speedtest_result(bound_iface=interface, bound_ip=bind_ip)
