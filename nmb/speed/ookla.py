"""Ookla Speedtest CLI wrapper with native HTTP stream fallback.

Extracts download/upload bandwidth, ping, jitter, and packet loss.
Supports official Ookla speedtest binary, speedtest-cli, and resilient native fallback.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from nmb.speed import cancel

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
    # Where client_ip/client_ipv6 came from: "engine" (the measuring server reported it), "lookup" (asked
    # over the same link after the test), "socket" (the test's own public source address), "local" (a
    # server on the local network: the box's own local address).
    client_ip_source: Optional[str] = None


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
    # Only the directions whose latency under load was really sampled count. A missing one used to
    # count as "no rise", so a test without any loaded sample got A+ and 0 ms (2026-11-10).
    deltas = [max(0.0, lat - ping_ms) for lat in (down_lat_ms, up_lat_ms) if lat is not None]
    if not deltas:
        return None, None
    worst_delta = max(deltas)
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

# No built-in servers: the list always comes from Ookla (the servers nearest to this box,
# wherever it is), so it never goes stale and has no country baked in.
DEFAULT_PRESET_SERVERS: dict[int, dict] = {}

_cached_servers_map: dict[int, dict] = dict(DEFAULT_PRESET_SERVERS)
_cached_servers_ts: float = 0.0
_servers_fetch_thread: Optional[threading.Thread] = None


SERVER_LIST_MAX_AGE_SEC = 300.0


def _bg_update_server_list() -> None:
    """Replace the list with Ookla's current one; servers Ookla no longer lists drop out."""
    global _cached_servers_map, _cached_servers_ts
    try:
        new_map = _fetch_master_server_list()
        if new_map:
            _cached_servers_map = {**DEFAULT_PRESET_SERVERS, **new_map}
            _cached_servers_ts = time.monotonic()
            return
    except Exception as e:
        log.debug("bg server list fetch error: %s", e)
    # Ookla did not answer: keep the old list and try again in a minute, without making
    # every page load wait for it.
    _cached_servers_ts = time.monotonic() - SERVER_LIST_MAX_AGE_SEC + 60.0


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
        log.debug("suppressed exception", exc_info=True)
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

    # 2. Speedtest Web API: the servers nearest to this box
    for q in ("engine=js&limit=50",):
        raw_list = _query_ookla_api(q)
        for s in raw_list:
            norm = _normalize_server(s)
            if norm:
                servers_dict[norm["id"]] = norm

    return servers_dict


def get_available_servers(search_query: str = "", limit: int = 100, refresh: bool = False) -> list[dict]:
    """Retrieve list of Ookla Speedtest servers with fast presets and non-blocking background discovery."""
    global _cached_servers_map, _cached_servers_ts, _servers_fetch_thread
    now = time.monotonic()
    if refresh or not _cached_servers_ts:
        # Asked for explicitly, or the first request: wait for Ookla's current list.
        _bg_update_server_list()
    elif (now - _cached_servers_ts) > SERVER_LIST_MAX_AGE_SEC:
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


# SHA-256 of the 1.2.0 archives; root runs this binary, so a changed download must not be used.
OOKLA_SHA256 = {
    "x86_64": "5690596c54ff9bed63fa3732f818a05dbc2db19ad36ed68f21ca5f64d5cfeeb7",
    "aarch64": "3953d231da3783e2bf8904b6dd72767c5c6e533e163d3742fd0437affa431bd3",
    "armhf": "e45fcdebbd8a185553535533dd032d6b10bc8c64eee4139b1147b9c09835d08d",
    "i386": "9ff7e18dbae7ee0e03c66108445a2fb6ceea6c86f66482e1392f55881b772fe8",
}


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

    # 2. Check standard install locations; root runs this binary, so only root-owned folders count
    candidates = [
        "/usr/local/bin/speedtest",
        "/usr/bin/speedtest",
        "/opt/nmb/bin/speedtest",
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
            log.debug("suppressed exception", exc_info=True)
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
        if hashlib.sha256(tar_bytes).hexdigest() != OOKLA_SHA256.get(ookla_arch):
            log.error("Ookla download for %s failed its checksum; not installing it", ookla_arch)
            return None
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


OOKLA_HOME = Path(os.environ.get("NMB_OOKLA_HOME", "/var/lib/nmb/ookla"))


def ookla_env() -> Optional[dict]:
    """A home the Ookla CLI can write to, so it keeps its accepted licence between runs.

    The Web UI runs as ``nmb``, whose home (/home/nmb) does not exist and is read-only under
    systemd's ProtectHome; without this every run started as a brand-new client.
    """
    cfg_dir = OOKLA_HOME / ".config" / "ookla"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(cfg_dir, os.W_OK):
            raise PermissionError(str(cfg_dir))
    except OSError as e:
        log.warning("Ookla CLI cannot keep its settings (%s); it starts as a new client every run", e)
        return None
    return dict(os.environ, HOME=str(OOKLA_HOME), XDG_CONFIG_HOME=str(OOKLA_HOME / ".config"))


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

        res = cancel.run(cmd, timeout=120, env=ookla_env())

        if res.returncode != 0:
            log.warning("ookla speedtest failed (code %d): %s", res.returncode, res.stderr.strip())
            return SpeedtestResult(status="error", error=res.stderr.strip(), raw_json=res.stdout, bound_iface=interface, bound_ip=bind_ip)

        data = json.loads(res.stdout)
        # Ookla returns bandwidth in bytes per second -> convert to bits per second
        down_bw = (data.get("download") or {}).get("bandwidth")
        up_bw = (data.get("upload") or {}).get("bandwidth")
        down_bps = int(down_bw * 8) if down_bw is not None else None
        up_bps = int(up_bw * 8) if up_bw is not None else None
        ping_ms = (data.get("ping") or {}).get("latency")
        jitter_ms = (data.get("ping") or {}).get("jitter")
        # Ookla leaves packetLoss out when it could not measure it: then it is unknown, not 0 %.
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
        # Only the address Ookla's server saw, and only a public one: internalIp is the box's LAN
        # address (it stays in bound_ip), and a cached address of the other IP family was never used
        # by this test.
        from nmb.common.netaddr import split_global
        client_ip, client_ipv6 = split_global(iface_data.get("externalIp"))

        bound_iface_val = interface or iface_data.get("name")
        bound_ip_val = bind_ip or iface_data.get("internalIp")

        return SpeedtestResult(
            status="ok" if (down_bps or up_bps) else "error",
            error=None if (down_bps or up_bps) else "Ookla returned no download or upload result",
            down_bps=down_bps,
            up_bps=up_bps,
            ping_us=round(ping_ms * 1000) if ping_ms else None,
            jitter_us=round(jitter_ms * 1000) if jitter_ms is not None else None,
            loss_pct=float(loss) if loss is not None else None,
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
        res = cancel.run(cmd, timeout=120)
        if res.returncode != 0:
            return SpeedtestResult(status="error", error=res.stderr.strip(), raw_json=res.stdout, bound_iface=interface, bound_ip=bind_ip)

        data = json.loads(res.stdout)
        server_data = data.get("server", {})
        srv_name = server_data.get("sponsor") or server_data.get("name") or "Unknown"
        srv_host = server_data.get("host")
        srv_loc = f"{server_data.get('name', '')}, {server_data.get('country', '')}".strip(", ")

        from nmb.common.netaddr import split_global
        client_ip, client_ipv6 = split_global((data.get("client") or {}).get("ip"))
        down = data.get("download")
        up = data.get("upload")
        ping = data.get("ping")

        return SpeedtestResult(
            status="ok" if (down or up) else "error",
            error=None if (down or up) else "speedtest-cli returned no download or upload result",
            down_bps=int(down) if down is not None else None,
            up_bps=int(up) if up is not None else None,
            ping_us=round(ping * 1000) if ping else None,
            jitter_us=None,
            loss_pct=None,          # speedtest-cli does not measure packet loss
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


def execute_speedtest(server_id: Optional[int] = None, interface: Optional[str] = None, bind_ip: Optional[str] = None) -> SpeedtestResult:
    """Run the official Ookla CLI, against server_id when one is chosen.

    An Ookla failure is returned as an error. The runner then falls back to another
    engine that records its own name, so a result never claims an Ookla server it did
    not use.
    """
    res = run_official_ookla(server_id=server_id, interface=interface, bind_ip=bind_ip)
    if res is not None:
        return res
    cancel.check()
    # Without the official binary, speedtest-cli is still Ookla's network, but it
    # cannot target a server, so it only stands in when no server was chosen.
    if not server_id:
        res = run_speedtest_cli(interface=interface, bind_ip=bind_ip)
        if res and res.status == "ok":
            return res
    return SpeedtestResult(status="error", error="Ookla speedtest CLI is not available",
                           bound_iface=interface, bound_ip=bind_ip)
