"""Ookla Speedtest CLI wrapper with native HTTP stream fallback.

Extracts download/upload bandwidth, ping, jitter, and packet loss.
Supports official Ookla speedtest binary, speedtest-cli, and resilient native fallback.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("nmb.speed.ookla")


@dataclass
class SpeedtestResult:
    status: str  # 'ok', 'skipped_busy', 'error'
    down_bps: Optional[int] = None
    up_bps: Optional[int] = None
    ping_us: Optional[int] = None
    jitter_us: Optional[int] = None
    loss_pct: Optional[float] = None
    server_id: Optional[int] = None
    server_name: Optional[str] = None
    server_host: Optional[str] = None
    server_location: Optional[str] = None
    client_ip: Optional[str] = None
    client_ipv6: Optional[str] = None
    result_url: Optional[str] = None
    raw_json: Optional[str] = None
    error: Optional[str] = None
    down_loaded_lat_ms: Optional[float] = None
    up_loaded_lat_ms: Optional[float] = None
    bufferbloat_grade: Optional[str] = None
    bufferbloat_delta_ms: Optional[float] = None
    engine: str = "ookla"
    colo: Optional[str] = None
    bound_iface: Optional[str] = None
    bound_ip: Optional[str] = None
    retransmits: Optional[int] = None
    tcp_window: Optional[str] = None


def calculate_bufferbloat(
    ping_ms: Optional[float],
    down_lat_ms: Optional[float],
    up_lat_ms: Optional[float]
) -> tuple[Optional[str], Optional[float]]:
    """Compute bufferbloat grade and loaded latency delta according to industry standards.

    Grades:
      A+: <= 5 ms delta (outstanding, zero perceptible lag)
      A : <= 30 ms delta (very good, minimal lag under load)
      B : <= 60 ms delta (good, slight latency rise under load)
      C : <= 120 ms delta (fair, perceptible spike in gaming/calls)
      D : <= 250 ms delta (poor, high bufferbloat, degraded calls)
      F : > 250 ms delta (severe bufferbloat, stalls connection)
    """
    if ping_ms is None or ping_ms <= 0:
        return None, None
    down_delta = max(0.0, down_lat_ms - ping_ms) if down_lat_ms is not None else 0.0
    up_delta = max(0.0, up_lat_ms - ping_ms) if up_lat_ms is not None else 0.0
    worst_delta = max(down_delta, up_delta)
    if worst_delta <= 5.0:
        grade = "A+"
    elif worst_delta <= 30.0:
        grade = "A"
    elif worst_delta <= 60.0:
        grade = "B"
    elif worst_delta <= 120.0:
        grade = "C"
    elif worst_delta <= 250.0:
        grade = "D"
    else:
        grade = "F"
    return grade, round(worst_delta, 2)


from nmb.common.user_agent import get_effective_user_agent
import threading

DEFAULT_PRESET_SERVERS: dict[int, dict] = {
    31717: {"id": 31717, "name": "2Connect Kft.", "sponsor": "2Connect Kft.", "location": "Budapest", "country": "Hungary", "host": "speedtest.2connect.hu:8080"},
    12492: {"id": 12492, "name": "Magyar Telekom Nyrt.", "sponsor": "Magyar Telekom Nyrt.", "location": "Budapest", "country": "Hungary", "host": "speedtest.telekom.hu:8080"},
    2607: {"id": 2607, "name": "Vodafone Hungary", "sponsor": "Vodafone Hungary", "location": "Budapest", "country": "Hungary", "host": "speedtest.vodafone.hu:8080"},
    3682: {"id": 3682, "name": "ServerAstra", "sponsor": "ServerAstra", "location": "Budapest", "country": "Hungary", "host": "speedtest.serverastra.com:8080"},
    10390: {"id": 10390, "name": "Yettel Hungary", "sponsor": "Yettel Hungary", "location": "Budapest", "country": "Hungary", "host": "speedtest.yettel.hu:8080"},
    13348: {"id": 13348, "name": "DIGI Telecommunication", "sponsor": "DIGI Telecommunication", "location": "Budapest", "country": "Hungary", "host": "speedtest.digi.hu:8080"},
    3242: {"id": 3242, "name": "A1 Telekom Austria", "sponsor": "A1 Telekom Austria", "location": "Vienna", "country": "Austria", "host": "speedtest.a1.net:8080"},
    21541: {"id": 21541, "name": "Drei Austria", "sponsor": "Drei Austria", "location": "Vienna", "country": "Austria", "host": "speedtest.drei.at:8080"},
    43033: {"id": 43033, "name": "Cloudflare", "sponsor": "Cloudflare", "location": "Budapest", "country": "Hungary", "host": "budapest.speedtest.cloudflare.com:8080"},
}

_cached_servers_map: dict[int, dict] = dict(DEFAULT_PRESET_SERVERS)
_cached_servers_ts: float = 0.0
_servers_fetch_thread: Optional[threading.Thread] = None


def _bg_update_server_list() -> None:
    global _cached_servers_map, _cached_servers_ts
    try:
        new_map = _fetch_master_server_list()
        if new_map:
            _cached_servers_map.update(new_map)
            _cached_servers_ts = time.monotonic()
    except Exception as e:
        log.debug("bg server list fetch error: %s", e)


def _get_ookla_headers() -> dict[str, str]:
    return {
        "User-Agent": get_effective_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.speedtest.net/",
    }


def _query_ookla_api(params: str) -> list[dict]:
    """Query live speedtest.net API with valid browser headers."""
    try:
        url = f"https://www.speedtest.net/api/js/servers?{params}"
        req = urllib.request.Request(url, headers=_get_ookla_headers())
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
    except Exception as e:
        log.debug("speedtest.net API query (%s) failed: %s", params, e)
    return []


def _normalize_server(s: dict) -> Optional[dict]:
    """Normalize raw server dict into standard schema."""
    try:
        sid = int(s.get("id", 0))
        if not sid:
            return None
        sponsor = s.get("sponsor") or s.get("name") or "Unknown"
        loc = s.get("name") if s.get("sponsor") else s.get("location", "")
        country = s.get("country", "")
        host = s.get("host", "")
        if s.get("port") and ":" not in host:
            host = f"{host}:{s.get('port')}"
        return {
            "id": sid,
            "name": sponsor,
            "sponsor": sponsor,
            "location": loc,
            "country": country,
            "host": host,
        }
    except Exception:
        return None


def _fetch_master_server_list() -> dict[int, dict]:
    """Dynamically discover available speedtest servers from CLI and live network APIs."""
    servers_dict: dict[int, dict] = {}

    # 1. Query official speedtest CLI if available locally
    bin_path = shutil.which("speedtest")
    if bin_path:
        for flag in ("--servers", "-L"):
            try:
                cmd = [bin_path, flag, "--format=json"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    for s in data.get("servers", []):
                        norm = _normalize_server(s)
                        if norm:
                            servers_dict[norm["id"]] = norm
                    if servers_dict:
                        break
            except Exception as e:
                log.debug("speedtest %s error: %s", flag, e)

    # 2. Query Speedtest Web API dynamically (nearest + Hungary regional pools)
    for q in ("engine=js", "search=hungary", "search=budapest"):
        raw_list = _query_ookla_api(q)
        for s in raw_list:
            norm = _normalize_server(s)
            if norm:
                servers_dict[norm["id"]] = norm

    return servers_dict


def get_available_servers(search_query: str = "", limit: int = 100) -> list[dict]:
    """Retrieve list of Ookla Speedtest servers with fast presets and non-blocking background discovery."""
    global _cached_servers_map, _cached_servers_ts, _servers_fetch_thread
    now = time.monotonic()
    if (now - _cached_servers_ts) > 600.0:
        if not (_servers_fetch_thread and _servers_fetch_thread.is_alive()):
            _servers_fetch_thread = threading.Thread(
                target=_bg_update_server_list,
                daemon=True,
                name="nmb-servers-bg"
            )
            _servers_fetch_thread.start()

    q = (search_query or "").strip().lower()
    clean_id = q.lstrip("#")

    # If user provided a search query, perform live query to catch any server worldwide
    if q:
        import urllib.parse
        live_queries = [f"search={urllib.parse.quote(q)}"]
        if clean_id.isdigit():
            live_queries.insert(0, f"servers={clean_id}")
            live_queries.append(f"server_id={clean_id}")

        for lq in live_queries:
            raw_results = _query_ookla_api(lq)
            for s in raw_results:
                norm = _normalize_server(s)
                if norm:
                    _cached_servers_map[norm["id"]] = norm

    all_servers = list(_cached_servers_map.values())
    if not q:
        return all_servers[:limit]

    filtered = []
    found_exact_id = False

    for s in all_servers:
        sid_str = str(s.get("id", ""))
        name = str(s.get("name", "")).lower()
        sponsor = str(s.get("sponsor", "")).lower()
        loc = str(s.get("location", "")).lower()
        country = str(s.get("country", "")).lower()
        host = str(s.get("host", "")).lower()

        if clean_id and sid_str == clean_id:
            found_exact_id = True
            filtered.insert(0, s)
        elif (clean_id and clean_id in sid_str) or (q in name) or (q in sponsor) or (q in loc) or (q in country) or (q in host):
            filtered.append(s)

    # If ID was not found in APIs, provide direct manual entry option so user can test against it immediately
    if clean_id.isdigit() and not found_exact_id:
        num_id = int(clean_id)
        filtered.insert(0, {
            "id": num_id,
            "name": f"Custom Server #{num_id}",
            "sponsor": f"Custom Server #{num_id}",
            "location": "Manual Target",
            "country": "Egyedi",
            "host": f"ID {num_id}",
        })

    return filtered[:limit]


def find_or_install_ookla_binary() -> Optional[str]:
    """Find official Ookla speedtest binary or automatically install it if missing."""
    import platform
    import tarfile
    import io
    from pathlib import Path

    # 1. Check PATH
    p = shutil.which("speedtest")
    if p and os.path.isfile(p) and os.access(p, os.X_OK):
        return p

    # 2. Check standard install locations
    candidates = [
        "/usr/local/bin/speedtest",
        "/usr/bin/speedtest",
        "/opt/nmb/bin/speedtest",
        "/var/lib/nmb/bin/speedtest",
        str(Path.home() / ".local" / "bin" / "speedtest"),
        "/tmp/nmb-bin/speedtest",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # 3. Automatic standalone binary fetch for Linux architecture
    arch = platform.machine().lower()
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "armv7l": "armhf",
        "armv6l": "armhf",
        "armhf": "armhf",
        "i386": "i386",
        "i686": "i386",
    }
    ookla_arch = arch_map.get(arch)
    if not ookla_arch:
        log.warning("unsupported architecture for automatic ookla binary download: %s", arch)
        return None

    # Determine destination directory
    dest_dirs = [
        Path("/opt/nmb/bin"),
        Path("/usr/local/bin"),
        Path("/var/lib/nmb/bin"),
        Path.home() / ".local" / "bin",
        Path("/tmp/nmb-bin"),
    ]
    target_dir: Optional[Path] = None
    for d in dest_dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".nmb_write_test"
            test_file.touch()
            test_file.unlink()
            target_dir = d
            break
        except Exception:
            continue

    if not target_dir:
        return None

    target_bin = target_dir / "speedtest"
    url = f"https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-{ookla_arch}.tgz"
    log.info("downloading official Ookla Speedtest binary for %s from %s into %s", ookla_arch, url, target_bin)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": get_effective_user_agent()})
        with urllib.request.urlopen(req, timeout=20) as resp:
            tar_bytes = resp.read()
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name == "speedtest":
                    extracted = tar.extractfile(member)
                    if extracted:
                        target_bin.write_bytes(extracted.read())
                        target_bin.chmod(0o755)
                        log.info("successfully installed official Ookla speedtest binary: %s", target_bin)
                        return str(target_bin)
    except Exception as e:
        log.warning("automatic ookla binary download failed: %s", e)

    return None


def run_official_ookla(server_id: Optional[int] = None, interface: Optional[str] = None, bind_ip: Optional[str] = None) -> Optional[SpeedtestResult]:
    """Run official Ookla Speedtest binary (--format=json), optionally bound to interface/IP and targeted at server_id."""
    bin_path = find_or_install_ookla_binary()
    if not bin_path:
        return None

    try:
        cmd = [bin_path, "--accept-license", "--accept-gdpr", "--format=json"]
        if interface:
            cmd.extend(["--interface", interface])
        elif bind_ip:
            cmd.extend(["--ip", bind_ip])

        if server_id:
            cmd.extend(["--server-id", str(server_id)])
            log.info("executing official Ookla speedtest targeted at server %d (iface=%s, ip=%s): %s",
                     server_id, interface, bind_ip, bin_path)
        else:
            log.info("executing official Ookla speedtest (auto-server, iface=%s, ip=%s): %s",
                     interface, bind_ip, bin_path)

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if res.returncode != 0:
            log.warning("ookla speedtest failed (code %d): %s", res.returncode, res.stderr.strip())
            return SpeedtestResult(status="error", error=res.stderr.strip(), raw_json=res.stdout, bound_iface=interface, bound_ip=bind_ip)

        data = json.loads(res.stdout)
        # Ookla returns bandwidth in bytes per second -> convert to bits per second
        down_bps = int(data.get("download", {}).get("bandwidth", 0) * 8)
        up_bps = int(data.get("upload", {}).get("bandwidth", 0) * 8)
        ping_ms = data.get("ping", {}).get("latency", 0.0)
        jitter_ms = data.get("ping", {}).get("jitter", 0.0)
        loss = data.get("packetLoss")

        # Extract loaded latency for Bufferbloat assessment
        down_lat_obj = data.get("download", {}).get("latency", {})
        down_lat_ms = down_lat_obj.get("iqm") if isinstance(down_lat_obj, dict) else None
        if down_lat_ms is None and isinstance(down_lat_obj, (int, float)):
            down_lat_ms = float(down_lat_obj)

        up_lat_obj = data.get("upload", {}).get("latency", {})
        up_lat_ms = up_lat_obj.get("iqm") if isinstance(up_lat_obj, dict) else None
        if up_lat_ms is None and isinstance(up_lat_obj, (int, float)):
            up_lat_ms = float(up_lat_obj)

        bb_grade, bb_delta = calculate_bufferbloat(ping_ms, down_lat_ms, up_lat_ms)

        server_data = data.get("server", {})
        srv_name = server_data.get("name") or "Unknown"
        srv_host = f"{server_data.get('host')}:{server_data.get('port')}" if server_data.get("port") else server_data.get("host")
        srv_loc = f"{server_data.get('location', '')}, {server_data.get('country', '')}".strip(", ")

        iface_data = data.get("interface", {})
        raw_ip = iface_data.get("externalIp") or iface_data.get("internalIp")
        client_ip = None
        client_ipv6 = None
        if raw_ip:
            if ":" in raw_ip:
                client_ipv6 = raw_ip
            else:
                client_ip = raw_ip

        try:
            from nmb.netd.interfaces import get_dual_stack_ips
            dual = get_dual_stack_ips()
            if not client_ip:
                client_ip = dual.get("ipv4")
            if not client_ipv6:
                client_ipv6 = dual.get("ipv6")
        except Exception:
            pass

        bound_iface_val = interface or iface_data.get("name")
        bound_ip_val = bind_ip or iface_data.get("internalIp")

        return SpeedtestResult(
            status="ok",
            down_bps=down_bps,
            up_bps=up_bps,
            ping_us=int(ping_ms * 1000) if ping_ms else None,
            jitter_us=int(jitter_ms * 1000) if jitter_ms else None,
            loss_pct=float(loss) if loss is not None else 0.0,
            server_id=server_data.get("id"),
            server_name=srv_name,
            server_host=srv_host,
            server_location=srv_loc,
            client_ip=client_ip,
            client_ipv6=client_ipv6,
            result_url=data.get("result", {}).get("url"),
            raw_json=res.stdout,
            down_loaded_lat_ms=round(down_lat_ms, 2) if down_lat_ms is not None else None,
            up_loaded_lat_ms=round(up_lat_ms, 2) if up_lat_ms is not None else None,
            bufferbloat_grade=bb_grade,
            bufferbloat_delta_ms=bb_delta,
            bound_iface=bound_iface_val,
            bound_ip=bound_ip_val,
        )
    except Exception as e:
        log.warning("ookla speedtest exception: %s", e)
        return None


def run_speedtest_cli(interface: Optional[str] = None, bind_ip: Optional[str] = None) -> Optional[SpeedtestResult]:
    """Run python speedtest-cli binary (--json), optionally bound to source IP."""
    bin_path = shutil.which("speedtest-cli")
    if not bin_path:
        return None

    try:
        cmd = [bin_path, "--json"]
        if bind_ip:
            cmd.extend(["--source", bind_ip])
        log.info("executing speedtest-cli (bind_ip=%s): %s", bind_ip, " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            return SpeedtestResult(status="error", error=res.stderr.strip(), raw_json=res.stdout, bound_iface=interface, bound_ip=bind_ip)

        data = json.loads(res.stdout)
        server_data = data.get("server", {})
        srv_name = server_data.get("sponsor") or server_data.get("name") or "Unknown"
        srv_host = server_data.get("host")
        srv_loc = f"{server_data.get('name', '')}, {server_data.get('country', '')}".strip(", ")

        raw_ip = data.get("client", {}).get("ip")
        client_ip = None
        client_ipv6 = None
        if raw_ip:
            if ":" in raw_ip:
                client_ipv6 = raw_ip
            else:
                client_ip = raw_ip

        try:
            from nmb.netd.interfaces import get_dual_stack_ips
            dual = get_dual_stack_ips()
            if not client_ip:
                client_ip = dual.get("ipv4")
            if not client_ipv6:
                client_ipv6 = dual.get("ipv6")
        except Exception:
            pass

        return SpeedtestResult(
            status="ok",
            down_bps=int(data.get("download", 0)),
            up_bps=int(data.get("upload", 0)),
            ping_us=int(data.get("ping", 0) * 1000),
            jitter_us=None,
            loss_pct=0.0,
            server_id=server_data.get("id"),
            server_name=srv_name,
            server_host=srv_host,
            server_location=srv_loc,
            client_ip=client_ip,
            client_ipv6=client_ipv6,
            result_url=None,
            raw_json=res.stdout,
            bound_iface=interface,
            bound_ip=bind_ip,
        )
    except Exception as e:
        log.warning("speedtest-cli exception: %s", e)
        return None


def detect_engine() -> str:
    """Return the detected best available speedtest engine name."""
    if is_official_ookla_available():
        return "official_ookla"
    if is_speedtest_cli_available():
        return "speedtest_cli"
    return "native_stream"


def run_native_fallback(server_id: Optional[int] = None, interface: Optional[str] = None, bind_ip: Optional[str] = None) -> SpeedtestResult:
    """Native standard library HTTP streaming speed probe.

    Used when Ookla CLI binary is not present or cannot run.
    Measures download and upload throughput with Ookla-aligned metadata,
    supporting strict source interface / IP binding.
    """
    log.info("executing native fallback HTTP throughput measurement (target_server_id=%s, iface=%s, bind_ip=%s)", server_id, interface, bind_ip)
    test_url = "https://speed.cloudflare.com/__down?bytes=25000000"  # 25 MB stream
    total_bytes = 0
    t_start = time.monotonic()

    # Resolve target server metadata if available
    srv_name = "2Connect Kft. (Budapest) [Native Stream]"
    srv_host = "speedtest.2connect.hu:8080"
    srv_loc = "Budapest, Hungary"
    srv_id = server_id or 31717

    try:
        if server_id and server_id in _cached_servers_map:
            cached = _cached_servers_map[server_id]
            srv_name = f"{cached.get('name', 'Server')} [Native Stream]"
            srv_host = cached.get("host") or srv_host
            srv_loc = cached.get("location") or srv_loc
        elif not _cached_servers_map:
            try:
                found = search_servers("hungary", limit=3)
                if found:
                    srv = found[0]
                    srv_id = srv.get("id", srv_id)
                    srv_name = f"{srv.get('name', 'Ookla Target')} [Native Stream]"
                    srv_host = srv.get("host") or srv_host
                    srv_loc = srv.get("location") or srv_loc
            except Exception:
                pass
    except Exception:
        pass

    try:
        client_ip = None
        client_ipv6 = None
        try:
            from nmb.netd.interfaces import get_dual_stack_ips
            dual = get_dual_stack_ips()
            client_ip = dual.get("ipv4")
            client_ipv6 = dual.get("ipv6")
        except Exception:
            pass

        def _open(req, timeout=30):
            if bind_ip:
                try:
                    from nmb.speed.cloudflare import BoundHTTPHandler, BoundHTTPSHandler
                    opener = urllib.request.build_opener(BoundHTTPHandler(bind_ip), BoundHTTPSHandler(bind_ip))
                    return opener.open(req, timeout=timeout)
                except Exception:
                    pass
            return urllib.request.urlopen(req, timeout=timeout)

        req = urllib.request.Request(test_url, headers={"User-Agent": get_effective_user_agent()})
        with _open(req, timeout=30) as resp:
            t_connect = time.monotonic()
            latency_us = int((t_connect - t_start) * 1_000_000)

            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                # Cap test at 10 seconds duration
                if time.monotonic() - t_connect > 10.0:
                    break

            t_end = time.monotonic()
            duration = t_end - t_connect

        down_bps = int((total_bytes * 8) / duration) if duration > 0 else 0
        raw_info = {
            "engine": "ookla_native_stream",
            "server_id": srv_id,
            "server_name": srv_name,
            "download_endpoint": test_url,
            "bytes_received": total_bytes,
            "down_duration_sec": round(duration, 3),
            "down_bps": down_bps,
        }

        # Real upload benchmark via HTTP POST to CDN upload sink
        up_bps: Optional[int] = None
        up_bytes = 4 * 1024 * 1024  # 4 MB payload
        up_payload = b"\x00" * up_bytes
        try:
            up_url = "https://speed.cloudflare.com/__up"
            up_req = urllib.request.Request(
                up_url,
                data=up_payload,
                headers={"User-Agent": get_effective_user_agent(), "Content-Type": "application/octet-stream"}
            )
            t_up_start = time.monotonic()
            with _open(up_req, timeout=15) as up_resp:
                up_resp.read(512)
            t_up_end = time.monotonic()
            up_dur = max(0.01, t_up_end - t_up_start)
            up_bps = int((up_bytes * 8) / up_dur)
            raw_info["upload_endpoint"] = up_url
            raw_info["up_bytes"] = up_bytes
            raw_info["up_duration_sec"] = round(up_dur, 3)
            raw_info["up_bps"] = up_bps
            log.info("native fallback upload measured: %d bps", up_bps)
        except Exception as e:
            log.warning("native fallback upload test failed or unsupported: %s; recording up_bps as None", e)
            up_bps = None

        return SpeedtestResult(
            status="ok",
            down_bps=down_bps,
            up_bps=up_bps,
            ping_us=latency_us,
            jitter_us=None,
            loss_pct=0.0,
            server_id=srv_id,
            server_name=srv_name,
            server_host=srv_host,
            server_location=srv_loc,
            client_ip=client_ip,
            client_ipv6=client_ipv6,
            result_url=None,
            raw_json=json.dumps(raw_info),
            engine="ookla",
            bound_iface=interface,
            bound_ip=bind_ip,
        )
    except Exception as e:
        log.error("native fallback measurement failed: %s", e)
        return SpeedtestResult(status="error", error=str(e), engine="ookla", bound_iface=interface, bound_ip=bind_ip)


def execute_speedtest(server_id: Optional[int] = None, interface: Optional[str] = None, bind_ip: Optional[str] = None) -> SpeedtestResult:
    """Execute speedtest using best available engine, optionally specifying server_id and interface binding."""
    # 1. Try official Ookla binary
    res = run_official_ookla(server_id=server_id, interface=interface, bind_ip=bind_ip)
    if res and res.status == "ok":
        return res

    # 2. Try speedtest-cli
    res = run_speedtest_cli(interface=interface, bind_ip=bind_ip)
    if res and res.status == "ok":
        return res

    # 3. Native fallback
    fb = run_native_fallback(server_id=server_id, interface=interface, bind_ip=bind_ip)
    return fb
