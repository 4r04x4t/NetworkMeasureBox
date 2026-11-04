"""Cloudflare Speed Test Engine (cloudflare-speed-cli reproduction).

Pure Python, zero external dependencies.
Measures download/upload throughput, idle latency, loaded latency (bufferbloat),
and extracts Cloudflare global edge metadata (Airport Colo code, ASN, City, Country, Client IP).
"""
from __future__ import annotations

import collections
import json
import logging
import statistics
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import http.client
from nmb.common.user_agent import get_effective_user_agent
from nmb.speed.ookla import SpeedtestResult, calculate_bufferbloat

log = logging.getLogger("nmb.speed.cloudflare")

BASE_URL = "https://speed.cloudflare.com"

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
    loss_pct: Optional[float] = 0.0
    down_loaded_lat_ms: Optional[float] = None
    up_loaded_lat_ms: Optional[float] = None
    bufferbloat_grade: Optional[str] = None
    bufferbloat_delta_ms: Optional[float] = None
    meta: CloudflareMeta = field(default_factory=CloudflareMeta)
    tier_downloads: Dict[str, float] = field(default_factory=dict)
    tier_uploads: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None

    def to_speedtest_result(self, bound_iface: Optional[str] = None, bound_ip: Optional[str] = None) -> SpeedtestResult:
        """Convert to standard NMB SpeedtestResult for DB persistence."""
        srv_name = f"Cloudflare Edge ({self.meta.colo})" if self.meta.colo else "Cloudflare Global Edge"
        srv_loc = f"{self.meta.city}, {self.meta.country}" if self.meta.city else "Anycast Edge"
        srv_host = f"speed.cloudflare.com [{self.meta.colo}]" if self.meta.colo else "speed.cloudflare.com"

        raw_ip = self.meta.client_ip
        v4 = None
        v6 = None
        if raw_ip:
            if ":" in raw_ip:
                v6 = raw_ip
            else:
                v4 = raw_ip

        try:
            from nmb.netd.interfaces import get_dual_stack_ips
            dual = get_dual_stack_ips()
            if not v4:
                v4 = dual.get("ipv4")
            if not v6:
                v6 = dual.get("ipv6")
        except Exception:
            pass

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
            result_url="https://speed.cloudflare.com",
            raw_json=json.dumps({
                "engine": "cloudflare",
                "colo": self.meta.colo,
                "city": self.meta.city,
                "country": self.meta.country,
                "asn": self.meta.asn,
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


def _get_request(url: str, timeout: float = 10.0) -> Tuple[bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _current_ua()})
    with _open_url(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers)


def _post_request(url: str, data: bytes, timeout: float = 12.0) -> Tuple[bytes, dict]:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": _current_ua(), "Content-Type": "application/octet-stream"}
    )
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


def measure_idle_latency(count: int = 15) -> Tuple[Optional[float], Optional[float], List[float]]:
    """Measure idle round-trip latency and jitter in milliseconds against Cloudflare edge."""
    latencies: List[float] = []
    url = f"{BASE_URL}/__down?bytes=0"

    for _ in range(count):
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": _current_ua()})
            with _open_url(req, timeout=4.0) as resp:
                _ = resp.read()
            latencies.append((time.monotonic() - t0) * 1000.0)
        except Exception:
            pass
        time.sleep(0.04)

    if not latencies:
        return None, None, []

    median_lat = statistics.median(latencies)
    # Jitter according to RFC 3550
    deltas = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
    jitter = statistics.mean(deltas) if deltas else 0.0
    return median_lat, jitter, latencies


def _probe_loaded_latency(stop_event: threading.Event, output_list: List[float]):
    """Concurrently probe latency to measure loaded bufferbloat latency."""
    url = f"{BASE_URL}/__down?bytes=0"
    while not stop_event.is_set():
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": _current_ua()})
            with _open_url(req, timeout=3.0) as resp:
                _ = resp.read()
            output_list.append((time.monotonic() - t0) * 1000.0)
        except Exception:
            pass
        time.sleep(0.08)


def measure_download_tier(byte_count: int, stop_loaded_probe: Optional[threading.Event] = None) -> Tuple[int, float]:
    """Download specific chunk tier in streamed blocks to measure sustained throughput."""
    url = f"{BASE_URL}/__down?bytes={byte_count}"
    req = urllib.request.Request(url, headers={"User-Agent": _current_ua()})
    b_read = 0
    with _open_url(req, timeout=25.0) as resp:
        t0 = time.monotonic()
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            b_read += len(chunk)
        dur = max(0.001, time.monotonic() - t0)
    return b_read, dur


def measure_upload_tier(byte_count: int) -> Tuple[int, float]:
    """Upload byte chunk and return (bytes_written, duration_sec)."""
    # Bound upload payload in memory (max 10MB) to protect 512MB RAM devices
    from nmb.common.memory import is_low_memory_system
    max_payload = 10_000_000 if is_low_memory_system() else 25_000_000
    actual_count = min(byte_count, max_payload)
    payload = b"0" * actual_count
    url = f"{BASE_URL}/__up"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"User-Agent": _current_ua(), "Content-Type": "application/octet-stream"}
    )
    with _open_url(req, timeout=25.0) as resp:
        t0 = time.monotonic()
        _ = resp.read(512)
        dur = max(0.001, time.monotonic() - t0)
    return actual_count, dur


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
    idle_lat, jitter, _ = measure_idle_latency(count=12)
    log.info("idle latency: %.2f ms, jitter: %.2f ms", idle_lat or 0.0, jitter or 0.0)

    # 3. Download Throughput & Loaded Download Latency
    tier_downloads: Dict[str, float] = {}
    down_loaded_lats: List[float] = []
    stop_down_probe = threading.Event()
    down_probe_thread = threading.Thread(
        target=_probe_loaded_latency,
        args=(stop_down_probe, down_loaded_lats),
        daemon=True
    )
    down_probe_thread.start()

    total_down_bytes = 0
    total_down_sec = 0.0
    download_tiers = [
        ("1MB", 1_000_000),
        ("10MB", 10_000_000),
        ("25MB", 25_000_000),
    ]

    for label, b_count in download_tiers:
        try:
            b_read, dur = measure_download_tier(b_count)
            mbps = (b_read * 8) / (dur * 1_000_000.0)
            tier_downloads[label] = round(mbps, 2)
            total_down_bytes += b_read
            total_down_sec += dur
        except Exception as e:
            log.warning("error in download tier %s: %s", label, e)

    stop_down_probe.set()
    down_probe_thread.join(timeout=1.0)

    # Sustained rate reflects maximum stabilized window tier
    mean_down_mbps = max(tier_downloads.values()) if tier_downloads else ((total_down_bytes * 8) / (total_down_sec * 1_000_000.0) if total_down_sec > 0 else 0.0)
    loaded_down_lat = statistics.median(down_loaded_lats) if down_loaded_lats else idle_lat

    # 4. Upload Throughput & Loaded Upload Latency
    tier_uploads: Dict[str, float] = {}
    up_loaded_lats: List[float] = []
    stop_up_probe = threading.Event()
    up_probe_thread = threading.Thread(
        target=_probe_loaded_latency,
        args=(stop_up_probe, up_loaded_lats),
        daemon=True
    )
    up_probe_thread.start()

    total_up_bytes = 0
    total_up_sec = 0.0
    upload_tiers = [
        ("1MB", 1_000_000),
        ("5MB", 5_000_000),
        ("10MB", 10_000_000),
    ]

    for label, b_count in upload_tiers:
        try:
            b_sent, dur = measure_upload_tier(b_count)
            mbps = (b_sent * 8) / (dur * 1_000_000.0)
            tier_uploads[label] = round(mbps, 2)
            total_up_bytes += b_sent
            total_up_sec += dur
        except Exception as e:
            log.warning("error in upload tier %s: %s", label, e)

    stop_up_probe.set()
    up_probe_thread.join(timeout=1.0)

    # Sustained rate reflects maximum stabilized window tier
    mean_up_mbps = max(tier_uploads.values()) if tier_uploads else ((total_up_bytes * 8) / (total_up_sec * 1_000_000.0) if total_up_sec > 0 else 0.0)
    loaded_up_lat = statistics.median(up_loaded_lats) if up_loaded_lats else idle_lat

    # 5. Bufferbloat Calculation
    bb_grade, bb_delta = calculate_bufferbloat(idle_lat, loaded_down_lat, loaded_up_lat)
    log.info("cloudflare speedtest finished: Down: %.2f Mbps, Up: %.2f Mbps, Lat: %.2f ms, Bufferbloat: %s (+%.1f ms)",
             mean_down_mbps, mean_up_mbps, idle_lat or 0.0, bb_grade or "N/A", bb_delta or 0.0)

    res = CloudflareSpeedResult(
        status="ok" if (mean_down_mbps > 0 or mean_up_mbps > 0) else "error",
        down_bps=int(mean_down_mbps * 1_000_000),
        up_bps=int(mean_up_mbps * 1_000_000),
        ping_us=int((idle_lat or 0.0) * 1000),
        jitter_us=int((jitter or 0.0) * 1000),
        loss_pct=0.0,
        down_loaded_lat_ms=round(loaded_down_lat, 2) if loaded_down_lat else None,
        up_loaded_lat_ms=round(loaded_up_lat, 2) if loaded_up_lat else None,
        bufferbloat_grade=bb_grade,
        bufferbloat_delta_ms=bb_delta,
        meta=meta,
        tier_downloads=tier_downloads,
        tier_uploads=tier_uploads,
    )
    from nmb.common.memory import trim_process_memory
    trim_process_memory()
    return res.to_speedtest_result(bound_iface=interface, bound_ip=bind_ip)
