"""Netflix Fast.com speed test engine (pure Python, no Node or Go needed).

It works like gesquive/fast-cli and sindresorhus/fast-cli do, through Fast.com's own API:

1. the API token is read from Fast.com's page script (with a known token as a fallback);
2. ``api.fast.com/netflix/speedtest/v2`` names the client (IP, ISP, ASN, city, country) and
   up to five Netflix Open Connect (OCA) servers near it, with their city and country;
3. unloaded latency: ``/speedtest/range/0-0`` requests on an open connection to each server,
   the same request Fast.com times, plus the TCP handshake time;
4. download: 16 parallel ``GET /speedtest/range/0-<n>`` streams spread over the servers for a
   fixed time, the TCP ramp-up left out; upload: ``POST`` of the same size to the same URLs;
5. loaded latency during both transfers (bufferbloat), per-second throughput samples,
   per-server bytes and the "stable" speed Fast.com shows (the mean once the speed settles).

The transfers use plain HTTP (``https=false`` in the API call; see ``USE_TLS``), the server names
come from the HTTPS list. Everything measured goes into ``raw_json`` so a row keeps the full detail.
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import socket
import ssl
import statistics
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from nmb.speed import cancel
from nmb.speed.ookla import SpeedtestResult, calculate_bufferbloat

log = logging.getLogger("nmb.speed.fastcom")

FAST_PAGE = "https://fast.com/"
API_URL = "https://api.fast.com/netflix/speedtest/v2?https={https}&token={token}&urlCount={count}"
# The token is the same for every visitor and has not changed in years; used when the page cannot be read.
FALLBACK_TOKEN = "YXNkZmFzZGxmbnNkYWZoYXNkZmhrYWxm"
URL_COUNT = 5
STREAMS = 16
# Plain HTTP to the Netflix servers. On a Raspberry Pi 4 (no AES instructions) TLS took 77-88 % of
# the CPU at 910 Mbps, so other services running at the same time pulled the result down (656 Mbps
# once); plain HTTP needs 50-56 %. The API call and the token stay on HTTPS.
USE_TLS = False
TEST_SECONDS = 15.0
WARMUP_SECONDS = 3.0
DOWN_RANGE = 26_214_400          # 25 MiB per request, as Fast.com uses
UP_RANGE = 10_000_000
READ_CHUNK = 262_144
SEND_CHUNK = 65_536
SAMPLE_SECONDS = 0.5

_bound_source_ip: Optional[str] = None
_token_cache: Dict[str, Any] = {"token": None, "ts": 0.0}


def _ua() -> str:
    try:
        from nmb.common.user_agent import get_effective_user_agent
        return get_effective_user_agent()
    except Exception:
        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0 Safari/537.36"


def _headers() -> Dict[str, str]:
    return {"User-Agent": _ua(), "Origin": "https://fast.com", "Referer": "https://fast.com/"}


def _http_get(url: str, timeout: float = 10.0) -> bytes:
    u = urllib.parse.urlsplit(url)
    source = (_bound_source_ip, 0) if _bound_source_ip else None
    conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, source_address=source)
    try:
        conn.request("GET", (u.path or "/") + (f"?{u.query}" if u.query else ""), headers=_headers())
        r = conn.getresponse()
        body = r.read()
        if r.status != 200:
            raise http.client.HTTPException(f"HTTP {r.status} from {u.hostname}")
        return body
    finally:
        conn.close()


def fetch_token() -> str:
    """Fast.com's API token from its page script; cached for a day."""
    if _token_cache["token"] and time.time() - _token_cache["ts"] < 86400:
        return _token_cache["token"]
    token = None
    try:
        page = _http_get(FAST_PAGE).decode("utf-8", "replace")
        m = re.search(r'src="(/app-[^"]+\.js)"', page)
        if m:
            js = _http_get(urllib.parse.urljoin(FAST_PAGE, m.group(1))).decode("utf-8", "replace")
            t = re.search(r'token:"([A-Za-z0-9]+)"', js)
            if t:
                token = t.group(1)
    except Exception as e:
        log.info("fast.com token could not be read from the page (%s); using the known one", e)
    token = token or FALLBACK_TOKEN
    _token_cache.update(token=token, ts=time.time())
    return token


@dataclass
class FastTarget:
    url: str
    host: str
    city: str = ""
    country: str = ""
    name: str = ""          # OCA host name, when the server is reached by its address
    tcp_ms: Optional[float] = None
    latency_ms: Optional[float] = None
    latency_samples: List[float] = field(default_factory=list)
    down_bytes: int = 0
    up_bytes: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """``bud002 · digihu`` from ``ipv4-c001-bud002-digihu-isp.1.oca.nflxvideo.net``."""
        m = re.match(r"ipv[46]-(c\d+)-([a-z]{3}\d{3})-([a-z0-9]+)-(isp|ix)", self.name or self.host)
        if m:
            return f"{m.group(2)} {m.group(1)} · {m.group(3)} ({m.group(4).upper()})"
        return self.name or self.host

    def range_path(self, spec: str) -> str:
        u = urllib.parse.urlsplit(self.url)
        return f"{u.path}/range/{spec}?{u.query}"


def _oca_names(token: str) -> Dict[str, str]:
    """IP address -> OCA host name; the plain-HTTP list names its servers only by address."""
    names: Dict[str, str] = {}
    try:
        data = json.loads(_http_get(API_URL.format(https="true", token=token, count=URL_COUNT)).decode())
        for t in data.get("targets") or []:
            host = urllib.parse.urlsplit(str(t.get("url") or "")).hostname or ""
            if host:
                for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
                    names.setdefault(info[4][0], host)
    except Exception as e:
        log.debug("fast.com server names: %s", e)
    return names


def fetch_targets(token: str) -> Tuple[Dict[str, Any], List[FastTarget]]:
    data = json.loads(_http_get(API_URL.format(https="true" if USE_TLS else "false", token=token, count=URL_COUNT)).decode())
    names = {} if USE_TLS else _oca_names(token)
    targets = []
    for t in data.get("targets") or []:
        url = str(t.get("url") or "")
        host = urllib.parse.urlsplit(url).hostname or ""
        if not url.startswith(("https://", "http://")) or not host:
            continue
        loc = t.get("location") or {}
        targets.append(FastTarget(url=url, host=host, city=str(loc.get("city") or ""), country=str(loc.get("country") or ""),
                                  name=names.get(host, "")))
    return data.get("client") or {}, targets


def _connect(host: str, timeout: float = 10.0):
    source = (_bound_source_ip, 0) if _bound_source_ip else None
    if USE_TLS:
        conn = http.client.HTTPSConnection(host, 443, timeout=timeout, source_address=source)
    else:
        conn = http.client.HTTPConnection(host, 80, timeout=timeout, source_address=source)
    conn.connect()
    return conn


def _tcp_ms(host: str, timeout: float = 3.0) -> float:
    source = (_bound_source_ip, 0) if _bound_source_ip else None
    t0 = time.monotonic()
    with socket.create_connection((host, 443 if USE_TLS else 80), timeout=timeout, source_address=source):
        return (time.monotonic() - t0) * 1000.0


def _range0_ms(conn, target: FastTarget) -> float:
    """One ``range/0-0`` round trip on an open connection (Fast.com's own latency request)."""
    t0 = time.monotonic()
    conn.request("GET", target.range_path("0-0"), headers=_headers())
    r = conn.getresponse()
    r.read()
    if r.status != 200:
        raise http.client.HTTPException(f"HTTP {r.status}")
    return (time.monotonic() - t0) * 1000.0


def measure_unloaded(targets: List[FastTarget], count: int = 6) -> None:
    for tg in targets:
        cancel.check()
        try:
            tg.tcp_ms = round(_tcp_ms(tg.host), 2)
            conn = _connect(tg.host)
            try:
                _range0_ms(conn, tg)  # the first one includes the server warming up
                for _ in range(count):
                    tg.latency_samples.append(round(_range0_ms(conn, tg), 2))
                    time.sleep(0.05)
            finally:
                conn.close()
            tg.latency_ms = round(min(tg.latency_samples), 2) if tg.latency_samples else None
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            tg.errors.append(f"latency: {e}")


class _Meter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.total = 0          # bytes inside the measuring window
        self.all_bytes = 0      # every byte, for the per-second curve
        self.errors: List[str] = []

    def add(self, n: int, tg: FastTarget, attr: str, in_window: bool) -> None:
        with self.lock:
            self.all_bytes += n
            if in_window:
                self.total += n
                setattr(tg, attr, getattr(tg, attr) + n)


def _down_worker(tg: FastTarget, meter: _Meter, start: threading.Event, win: List[float]) -> None:
    buf = bytearray(READ_CHUNK)
    start.wait()
    conn = None
    while time.monotonic() < win[1]:
        try:
            conn = conn or _connect(tg.host)
            conn.request("GET", tg.range_path(f"0-{DOWN_RANGE}"), headers=_headers())
            r = conn.getresponse()
            if r.status != 200:
                raise http.client.HTTPException(f"HTTP {r.status}")
            while time.monotonic() < win[1]:
                n = r.readinto(buf)
                if not n:
                    break
                now = time.monotonic()
                meter.add(n, tg, "down_bytes", win[0] <= now <= win[1])
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            meter.errors.append(f"{tg.host}: {e}")
            tg.errors.append(f"download: {e}")
            if conn:
                conn.close()
            conn = None
            time.sleep(0.2)
    if conn:
        conn.close()


def _up_worker(tg: FastTarget, meter: _Meter, start: threading.Event, win: List[float]) -> None:
    payload = b"\0" * SEND_CHUNK
    start.wait()
    conn = None
    while time.monotonic() < win[1]:
        try:
            conn = conn or _connect(tg.host)
            conn.putrequest("POST", tg.range_path(f"0-{UP_RANGE}"))
            for k, v in _headers().items():
                conn.putheader(k, v)
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(UP_RANGE))
            conn.endheaders()
            sent = 0
            while sent < UP_RANGE:
                if time.monotonic() >= win[1]:
                    conn.close()
                    return
                chunk = payload[:UP_RANGE - sent]
                conn.send(chunk)
                sent += len(chunk)
                now = time.monotonic()
                meter.add(len(chunk), tg, "up_bytes", win[0] <= now <= win[1])
            r = conn.getresponse()
            r.read()
            if r.status != 200:
                raise http.client.HTTPException(f"HTTP {r.status}")
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            meter.errors.append(f"{tg.host}: {e}")
            tg.errors.append(f"upload: {e}")
            if conn:
                conn.close()
            conn = None
            time.sleep(0.2)
    if conn:
        conn.close()


def _loaded_probe(tg: FastTarget, stop: threading.Event, out: List[float]) -> None:
    """Latency under load on its own connection to the closest server."""
    try:
        conn = _connect(tg.host)
    except (OSError, ssl.SSLError):
        return
    try:
        while not stop.wait(0.4):
            try:
                out.append(round(_range0_ms(conn, tg), 2))
            except (OSError, http.client.HTTPException, ssl.SSLError):
                conn.close()
                try:
                    conn = _connect(tg.host)
                except (OSError, ssl.SSLError):
                    return
    finally:
        conn.close()


def _stable_mbps(samples: List[float]) -> Optional[float]:
    """Fast.com's shown speed: the mean from the first sample that reaches 90 % of the settled speed.

    The settled speed is the median of the second half of the samples, so the ramp-up is left out.
    """
    if not samples:
        return None
    ref = statistics.median(samples[len(samples) // 2:])
    start = next((i for i, v in enumerate(samples) if v >= 0.9 * ref), 0)
    return round(statistics.mean(samples[start:]), 2)


def _transfer(worker, targets: List[FastTarget], probe_target: Optional[FastTarget]) -> Dict[str, Any]:
    cancel.check()
    meter = _Meter()
    start = threading.Event()
    win = [0.0, 0.0]
    threads = [threading.Thread(target=worker, args=(targets[i % len(targets)], meter, start, win), daemon=True)
               for i in range(STREAMS)]
    for th in threads:
        th.start()
    loaded: List[float] = []
    stop_probe = threading.Event()
    probe = None
    if probe_target:
        probe = threading.Thread(target=_loaded_probe, args=(probe_target, stop_probe, loaded), daemon=True)
        probe.start()
    t0 = time.monotonic()
    win[0], win[1] = t0 + WARMUP_SECONDS, t0 + TEST_SECONDS
    start.set()
    samples: List[float] = []
    last_bytes, last_t = 0, t0
    while time.monotonic() < win[1]:
        if cancel.is_requested():
            win[1] = 0.0
            break
        time.sleep(SAMPLE_SECONDS)
        now = time.monotonic()
        with meter.lock:
            b = meter.all_bytes
        samples.append(round((b - last_bytes) * 8 / ((now - last_t) * 1e6), 2))
        last_bytes, last_t = b, now
    for th in threads:
        th.join(timeout=15)
    stop_probe.set()
    if probe:
        probe.join(timeout=3)
    cancel.check()
    mean = meter.total * 8 / ((TEST_SECONDS - WARMUP_SECONDS) * 1e6)
    return {
        "mean_mbps": round(mean, 2),
        "stable_mbps": _stable_mbps(samples[int(WARMUP_SECONDS / SAMPLE_SECONDS):]),
        "peak_mbps": max(samples) if samples else None,
        "samples_mbps": samples,
        "bytes": meter.total,
        "loaded_latency_ms": loaded,
        "errors": meter.errors[:10],
    }


def execute_fastcom_speedtest(interface: Optional[str] = None, bind_ip: Optional[str] = None) -> SpeedtestResult:
    global _bound_source_ip
    _bound_source_ip = bind_ip
    log.info("starting Fast.com (Netflix) speed test (iface=%s, bind_ip=%s)", interface, bind_ip)
    t_start = time.monotonic()
    try:
        token = fetch_token()
        client, targets = fetch_targets(token)
    except Exception as e:
        log.warning("fast.com API failed: %s", e)
        return SpeedtestResult(status="error", error=f"Fast.com API: {e}", engine="fastcom",
                               bound_iface=interface, bound_ip=bind_ip)
    if not targets:
        return SpeedtestResult(status="error", error="Fast.com returned no servers", engine="fastcom",
                               bound_iface=interface, bound_ip=bind_ip)

    measure_unloaded(targets)
    reachable = [t for t in targets if t.latency_ms is not None] or targets
    reachable.sort(key=lambda t: t.latency_ms if t.latency_ms is not None else 1e9)
    closest = reachable[0]
    all_lat = [s for t in reachable for s in t.latency_samples]
    idle = min(all_lat) if all_lat else None
    closest_samples = closest.latency_samples
    jitter = (statistics.mean(abs(closest_samples[i] - closest_samples[i - 1]) for i in range(1, len(closest_samples)))
              if len(closest_samples) > 1 else None)

    down = _transfer(_down_worker, reachable, closest)
    up = _transfer(_up_worker, reachable, closest)
    down_mbps = down["stable_mbps"] or down["mean_mbps"]
    up_mbps = up["stable_mbps"] or up["mean_mbps"]
    loaded_down = statistics.median(down["loaded_latency_ms"]) if down["loaded_latency_ms"] else None
    loaded_up = statistics.median(up["loaded_latency_ms"]) if up["loaded_latency_ms"] else None
    bb_grade, bb_delta = calculate_bufferbloat(idle, loaded_down, loaded_up)

    ip = str(client.get("ip") or "")
    loc = client.get("location") or {}
    servers = [{
        "host": t.host, "name": t.name or t.host, "label": t.label, "city": t.city, "country": t.country,
        "tcp_connect_ms": t.tcp_ms, "latency_ms": t.latency_ms, "latency_samples_ms": t.latency_samples,
        "download_mbps": round(t.down_bytes * 8 / ((TEST_SECONDS - WARMUP_SECONDS) * 1e6), 2),
        "upload_mbps": round(t.up_bytes * 8 / ((TEST_SECONDS - WARMUP_SECONDS) * 1e6), 2),
        "errors": t.errors[:5],
    } for t in targets]
    raw = {
        "engine": "fastcom",
        "client": {"ip": ip, "isp": client.get("isp"), "asn": client.get("asn"),
                   "city": loc.get("city"), "country": loc.get("country")},
        "servers": servers,
        "closest_server": closest.host,
        "unloaded_latency_ms": idle,
        "jitter_ms": round(jitter, 2) if jitter is not None else None,
        "loaded_latency_down_ms": loaded_down,
        "loaded_latency_up_ms": loaded_up,
        "download": {k: v for k, v in down.items()},
        "upload": {k: v for k, v in up.items()},
        "bufferbloat_grade": bb_grade,
        "bufferbloat_delta_ms": bb_delta,
        "transport": "https" if USE_TLS else "http",
        "streams": STREAMS, "test_seconds": TEST_SECONDS, "warmup_seconds": WARMUP_SECONDS,
        "duration_sec": round(time.monotonic() - t_start, 1),
        "method": "Fast.com API (api.fast.com/netflix/speedtest/v2), range requests to Netflix Open Connect servers",
    }
    ok = bool(down_mbps) and bool(up_mbps)
    errors = down["errors"] + up["errors"]
    log.info("fast.com finished: down %.2f Mbps (peak %s), up %.2f Mbps, latency %s ms, loaded %s/%s ms, servers %d",
             down_mbps or 0, down["peak_mbps"], up_mbps or 0, idle, loaded_down, loaded_up, len(targets))
    where = ", ".join(x for x in (closest.city, closest.country) if x)
    return SpeedtestResult(
        status="ok" if ok else "error",
        down_bps=int(down_mbps * 1e6) if down_mbps else None,
        up_bps=int(up_mbps * 1e6) if up_mbps else None,
        ping_us=int(idle * 1000) if idle is not None else None,
        jitter_us=int(jitter * 1000) if jitter is not None else None,
        loss_pct=None,
        server_name=f"Fast.com (Netflix): {closest.label}",
        server_host=closest.name or closest.host,
        server_location=f"{where} · {len(reachable)} servers" if where else f"{len(reachable)} servers",
        client_ip=ip if ip and ":" not in ip else None,
        client_ipv6=ip if ":" in ip else None,
        result_url=None,  # Fast.com keeps no page for a result
        raw_json=json.dumps(raw),
        error=None if ok else ("; ".join(errors[:3]) or "no data transferred"),
        down_loaded_lat_ms=round(loaded_down, 2) if loaded_down else None,
        up_loaded_lat_ms=round(loaded_up, 2) if loaded_up else None,
        bufferbloat_grade=bb_grade,
        bufferbloat_delta_ms=bb_delta,
        engine="fastcom",
        colo=(closest.name or closest.host).split("-")[2].upper() if (closest.name or closest.host).count("-") >= 3 else None,
        bound_iface=interface,
        bound_ip=bind_ip,
    )
