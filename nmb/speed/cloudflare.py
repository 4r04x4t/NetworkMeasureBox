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

from nmb.speed.ookla import SpeedtestResult, calculate_bufferbloat

log = logging.getLogger("nmb.speed.cloudflare")

USER_AGENT = "cloudflare-speed-cli/1.0 (NetworkMeasureBox/2.5; Linux)"
BASE_URL = "https://speed.cloudflare.com"


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

    def to_speedtest_result(self) -> SpeedtestResult:
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
        )


def _get_request(url: str, timeout: float = 10.0) -> Tuple[bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers)


def _post_request(url: str, data: bytes, timeout: float = 12.0) -> Tuple[bytes, dict]:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/octet-stream"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
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
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                _ = resp.read()
            output_list.append((time.monotonic() - t0) * 1000.0)
        except Exception:
            pass
        time.sleep(0.08)


def measure_download_tier(byte_count: int, stop_loaded_probe: Optional[threading.Event] = None) -> Tuple[int, float]:
    """Download specific chunk tier in small streamed blocks to prevent RAM bloat."""
    url = f"{BASE_URL}/__down?bytes={byte_count}"
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    b_read = 0
    with urllib.request.urlopen(req, timeout=25.0) as resp:
        while True:
            chunk = resp.read(65536)
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
    t0 = time.monotonic()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/octet-stream"}
    )
    with urllib.request.urlopen(req, timeout=25.0) as resp:
        _ = resp.read()
    dur = max(0.001, time.monotonic() - t0)
    return actual_count, dur


def execute_cloudflare_speedtest() -> SpeedtestResult:
    """Execute complete Cloudflare Speed Test mirroring cloudflare-speed-cli."""
    log.info("starting Cloudflare global edge network measurement cycle")
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

    mean_down_mbps = (total_down_bytes * 8) / (total_down_sec * 1_000_000.0) if total_down_sec > 0 else 0.0
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

    mean_up_mbps = (total_up_bytes * 8) / (total_up_sec * 1_000_000.0) if total_up_sec > 0 else 0.0
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
    return res.to_speedtest_result()
