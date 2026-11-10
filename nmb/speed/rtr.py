"""RTR-NetTest (netztest.at / Open-RMBT) measurement engine for NetworkMeasureBox.

BEREC-compliant regulatory speed measurement protocol.
Zero external dependencies, pure Python standard library.
Communicates with RTR-NetTest Control Server and 100G measurement clusters,
registers certified tests, and submits results for Open Data publication.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import subprocess
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from nmb.speed import cancel
from nmb.speed.ookla import SpeedtestResult
from nmb.speed.rmbt import connection, control, pretest, tests, uuid_store

log = logging.getLogger("nmb.speed.rtr")

DEFAULT_RTR_CONTROL = "https://c01.netztest.at"
VERSION = "1.1.1"


def find_native_rmbt_client() -> Optional[str]:
    """Check for compiled native C open-rmbt-client-cli executable."""
    for cand in ("/usr/local/bin/rmbt-client", "/usr/bin/rmbt-client", "/opt/nmb/bin/rmbt-client"):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which("rmbt-client")


def _output_tail(*streams, limit: int = 400) -> str:
    """Return the end of the first non-empty process output, for diagnosing client failures."""
    for stream in streams:
        if isinstance(stream, bytes):
            stream = stream.decode("utf-8", "replace")
        if stream and stream.strip():
            return stream.strip()[-limit:]
    return "(no output)"


RTR_HOME = "/var/lib/nmb"


def _rtr_env() -> Optional[dict]:
    """HOME for the native client: it keeps its client UUID in $HOME/.rmbt_client_uuid. The services run with
    HOME=/home/nmb, which does not exist, so every test was a new client (2026-11-09)."""
    import os
    if os.path.isdir(RTR_HOME) and os.access(RTR_HOME, os.W_OK):
        return dict(os.environ, HOME=RTR_HOME)
    return None


def _client_ips(interface: Optional[str], bind_ip: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """The public address the test used: asked over the same link (by source address), not the default route.

    2026-11-08: the native client's rows had no client IP at all (2512 of 2522), and the generic lookup
    would give the home line's address for a test over USB.
    """
    if bind_ip and ":" not in bind_ip:
        try:
            import http.client
            import ssl
            conn = http.client.HTTPSConnection("www.cloudflare.com", 443, timeout=6,
                                               source_address=(bind_ip, 0), context=ssl.create_default_context())
            conn.request("GET", "/cdn-cgi/trace", headers={"User-Agent": "NetworkMeasureBox"})
            body = conn.getresponse().read(4096).decode("utf-8", "replace")
            conn.close()
            for line in body.splitlines():
                if line.startswith("ip="):
                    from nmb.common.netaddr import split_global
                    return split_global(line[3:].strip())
        except Exception:
            log.debug("client IP over %s failed", bind_ip, exc_info=True)
    # No cached or LAN address instead: an address this test did not use is not its client IP.
    return None, None


def _run_native_rmbt_speedtest(
    host: str,
    duration_sec: int,
    force_threads: int,
    interface: Optional[str],
    bind_ip: Optional[str],
) -> Optional[SpeedtestResult]:
    native_bin = find_native_rmbt_client()
    if not native_bin:
        return None

    cmd = [
        native_bin,
        "-v",
        "--host", host,
        "-d", str(duration_sec),
        "-t", str(force_threads or 3),
        "--set-version", f"NMB-{VERSION}",
    ]
    if bind_ip:
        # Leave over the asked link (USB, Wi-Fi), not the default route (2026-11-09: it was never passed).
        cmd += ["--bind", bind_ip]
    log.info("invoking native C Open-RMBT binary: %s", " ".join(cmd))
    try:
        proc = cancel.run(cmd, timeout=duration_sec * 3 + 30, env=_rtr_env())
    except subprocess.TimeoutExpired as e:
        log.warning(
            "native C rmbt-client timed out after %ss; falling back to Python engine; output: %s",
            e.timeout, _output_tail(e.stderr, e.stdout),
        )
        return None
    except Exception as e:
        log.warning("native C rmbt-client execution failed: %s; falling back to Python engine", e)
        return None

    final_data = None
    share_url = None
    test_uuid = None
    open_uuid = None
    measure_server = None
    for line in proc.stdout.splitlines():
        if "Result:" in line and "netztest.at/share/" in line:
            share_url = line.split()[-1].strip()
        if line.startswith("Server:") and measure_server is None:
            # "Server:   <addr>:<port> (TLS)": the measurement server RTR assigned, not the control host
            parts = line.split()
            if len(parts) >= 2:
                measure_server = parts[1]
        if line.startswith("{") and '"FINAL_RESULT"' in line:
            try:
                final_data = json.loads(line)
            except Exception:
                log.debug("suppressed exception", exc_info=True)

    if not final_data:
        log.warning(
            "native C rmbt-client did not produce FINAL_RESULT (code=%d); falling back to Python; output: %s",
            proc.returncode, _output_tail(proc.stderr, proc.stdout),
        )
        return None

    down_mbps = float(final_data.get("down", 0.0))
    up_mbps = float(final_data.get("up", 0.0))
    ping_ms = float(final_data["pingMedian"]) if final_data.get("pingMedian") is not None else None
    # Older binaries print only the median; never invent the minimum or the jitter.
    ping_min_ms = float(final_data["pingMin"]) if final_data.get("pingMin") else None
    jitter_ms = float(final_data["pingJitter"]) if final_data.get("pingJitter") is not None and "pingMin" in final_data else None
    down_bps = int(down_mbps * 1e6)
    up_bps = int(up_mbps * 1e6)
    open_uuid = final_data.get("openTestUuid")
    test_uuid = final_data.get("testUuid")
    if not share_url and open_uuid:
        base = urlparse(host)
        share_url = f"{base.scheme}://{base.netloc}/share/{open_uuid}"

    # RTR does not sample latency under load, so bufferbloat stays unknown instead of estimated.
    loaded_down_lat = None
    loaded_up_lat = None
    grade, delta = None, None

    raw_json = json.dumps({
        "engine": "rtr-nettest-native-c",
        "control_host": host,
        "test_uuid": test_uuid,
        "open_test_uuid": open_uuid,
        "share_url": share_url,
        "dl_threads": final_data.get("downThreads", force_threads),
        "ul_threads": final_data.get("upThreads", force_threads),
        "ping_min_ms": ping_min_ms,
        "ping_median_ms": ping_ms,
        "ping_count": final_data.get("pingCount"),
        "measurement_server": measure_server,
        "down_bytes": final_data.get("downBytes"),
        "up_bytes": final_data.get("upBytes"),
    })
    v4, v6 = _client_ips(interface, bind_ip)

    return SpeedtestResult(
        status="ok",
        down_bps=down_bps,
        up_bps=up_bps,
        ping_us=(round((ping_min_ms if ping_min_ms is not None else ping_ms) * 1000)
                 if (ping_min_ms is not None or ping_ms is not None) else None),
        jitter_us=round(jitter_ms * 1000) if jitter_ms is not None else None,
        loss_pct=None,          # RMBT does not measure packet loss
        client_ip=v4,
        client_ipv6=v6,
        server_name="RTR-NetTest (Native C Open-RMBT)",
        server_host=measure_server or urlparse(host).netloc,
        server_location=None,   # RTR does not say where its measurement server stands
        result_url=share_url,   # only a real result page, never the project's home page
        raw_json=raw_json,
        down_loaded_lat_ms=loaded_down_lat,
        up_loaded_lat_ms=loaded_up_lat,
        bufferbloat_grade=grade,
        bufferbloat_delta_ms=delta,
        engine="rtr",
        colo=None,
        bound_iface=interface,
        bound_ip=bind_ip,
    )


def execute_rtr_speedtest(
    host: str = DEFAULT_RTR_CONTROL,
    duration_sec: int = 4,
    force_threads: int = 3,
    use_ws: bool = True,
    interface: Optional[str] = None,
    bind_ip: Optional[str] = None,
) -> SpeedtestResult:
    """Execute complete RTR-NetTest (netztest.at / Open-RMBT) measurement cycle."""
    if not host.startswith("http://") and not host.startswith("https://"):
        host = "https://" + host

    if bind_ip:
        if ":" in bind_ip:
            if "c01.netztest.at" in host:
                host = host.replace("c01.netztest.at", "c01v6.netztest.at")
        else:
            if "c01.netztest.at" in host:
                host = host.replace("c01.netztest.at", "c01v4.netztest.at")

    # Prefer official native C client if available
    native_res = _run_native_rmbt_speedtest(host, duration_sec, force_threads, interface, bind_ip)
    if native_res is not None:
        return native_res

    log.info("starting RTR-NetTest (netztest.at) BEREC regulatory measurement against %s (iface=%s, bind_ip=%s)", host, interface, bind_ip)
    connection.set_bind_target(interface=interface, bind_ip=bind_ip)

    # 1. UUID Resolution & Terms acceptance
    stored = uuid_store.load()
    client_uuid = control.request_settings(host, stored, VERSION, debug=False)
    if client_uuid != stored:
        uuid_store.save(client_uuid)
    log.info("RTR client uuid verified: %s", client_uuid)

    # 2. Request test parameters from Control Server
    params = control.request_test(host, client_uuid, VERSION, use_ws=use_ws, debug=False)
    log.info("allocated RTR test server: %s:%d, open_uuid=%s",
             params.server_addr, params.server_port, params.open_test_uuid)

    protocol = connection.PROTO_WS if (use_ws or params.server_type == "RMBTws") else connection.PROTO_HTTP
    port = params.server_port
    no_tls_verify = False

    if params.wait > 0:
        time.sleep(min(params.wait, 2))

    # 3. Pre-test baseline calibration
    pt = pretest.run_pretest(
        params.server_addr, port, params.encryption, no_tls_verify,
        protocol, params.token, min(params.num_threads, 12)
    )

    from nmb.common.memory import is_low_memory_system, trim_process_memory
    max_th = 3 if is_low_memory_system() else 8
    dl_threads = max(1, min(force_threads or pt.dl_threads, max_th))
    ul_threads = max(1, min(force_threads or pt.ul_threads, max_th))
    dl_chunk = pt.chunk_size
    ul_chunk = min(dl_chunk, tests.MAX_UL_CHUNK)
    test_duration = max(3, min(params.duration, duration_sec))

    log.info("RTR plan: dl_threads=%d, ul_threads=%d, chunk=%d KiB, duration=%ds",
             dl_threads, ul_threads, dl_chunk // 1024, test_duration)

    test_begin_ms = int(time.time() * 1000)

    # 4. Ping Phase
    ping_conn = connection.RmbtConn.connect(params.server_addr, port, params.encryption, no_tls_verify, protocol)
    ping_conn.greeting(params.token)
    ping_results = tests.run_ping(ping_conn, 1.0, 10, 40)
    ping_conn.quit()
    ping_conn.close()

    # The server's timings, in the order sent, as the native client and RTR itself use them; no ping
    # means no value (it used to invent 15 ms), and jitter is the mean change between successive pings
    # (it used to be median minus minimum, which is not jitter).
    import statistics
    rtts = [r.server_ns for r in ping_results if r.server_ns > 0] or [r.client_ns for r in ping_results if r.client_ns > 0]
    min_ping_ms = min(rtts) / 1e6 if rtts else None
    median_ping_ms = statistics.median(rtts) / 1e6 if rtts else None
    jitter_fallback_ms = (statistics.fmean(abs(b - a) for a, b in zip(rtts, rtts[1:])) / 1e6
                          if len(rtts) >= 2 else None)
    ping_shortest_server = min((r.server_ns for r in ping_results if r.server_ns > 0), default=min(rtts) if rtts else 0)

    # 5. Multi-threaded Download Phase
    from nmb.speed.rmbt.__main__ import _run_phase
    dl_results = _run_phase(
        dl_threads, params.server_addr, port, params.encryption, no_tls_verify,
        protocol, params.token, test_duration, dl_chunk, False, "download"
    )

    dl_bytes = sum(r.bytes for r in dl_results) if dl_results else 0
    dl_ns = max((r.elapsed_ns for r in dl_results), default=1)
    dl_mbps = dl_bytes * 8.0 / (dl_ns / 1e9) / 1e6

    # 6. Multi-threaded Upload Phase
    ul_results = _run_phase(
        ul_threads, params.server_addr, port, params.encryption, no_tls_verify,
        protocol, params.token, test_duration, ul_chunk, False, "upload"
    )

    ul_bytes = sum(r.bytes for r in ul_results) if ul_results else 0
    ul_ns = max((r.elapsed_ns for r in ul_results), default=1)
    ul_mbps = ul_bytes * 8.0 / (ul_ns / 1e9) / 1e6

    base = urlparse(host)
    share_url = f"{base.scheme}://{base.netloc}/share/{params.open_test_uuid}" if params.open_test_uuid else None
    log.info("RTR measurement complete: Down: %.2f Mbps, Up: %.2f Mbps, Ping: %s ms, Link: %s",
             dl_mbps, ul_mbps, f"{min_ping_ms:.2f}" if min_ping_ms is not None else "n/a", share_url)

    # 7. Submit Result to Control Server
    speed_detail = []
    for r in dl_results:
        for (b, t) in r.samples:
            speed_detail.append({"direction": "download", "thread": r.thread_id, "time": t, "bytes": b})
    for r in ul_results:
        for (b, t) in r.samples:
            speed_detail.append({"direction": "upload", "thread": r.thread_id, "time": t, "bytes": b})

    result_payload = {
        "client_language": "en",
        "client_name": "RMBTws" if protocol == connection.PROTO_WS else "RMBT",
        "client_uuid": client_uuid,
        "client_version": VERSION,
        "client_software_version": VERSION,
        "geoLocations": [],
        "model": "NetworkMeasureBox (Raspberry Pi 4B)",
        "network_type": 98,
        "platform": "Linux",
        "product": "nmb-rtr-agent",
        "pings": [{"value": r.client_ns, "value_server": r.server_ns, "time_ns": r.time_ns} for r in ping_results],
        "test_bytes_download": dl_bytes,
        "test_bytes_upload": ul_bytes,
        "test_nsec_download": dl_ns,
        "test_nsec_upload": ul_ns,
        "test_num_threads": len(dl_results),
        "num_threads_ul": len(ul_results),
        "test_ping_shortest": ping_shortest_server,
        "test_speed_download": int(dl_bytes * 8e6 / dl_ns) if dl_ns else 0,
        "test_speed_upload": int(ul_bytes * 8e6 / ul_ns) if ul_ns else 0,
        "test_token": params.token,
        "test_uuid": params.test_uuid,
        "time": test_begin_ms,
        "timezone": "UTC",
        "type": "DESKTOP",
        "version_code": "1",
        "speed_detail": speed_detail,
        "user_server_selection": False,
        "test_status": "0",
        "test_port_remote": port,
    }
    control.submit_result(host, result_payload, debug=False)

    # RTR does not sample latency under load, so bufferbloat stays unknown instead of estimated.
    bb_grade, bb_delta = None, None

    v4, v6 = _client_ips(interface, bind_ip)

    res = SpeedtestResult(
        status="ok" if (dl_bytes > 0 or ul_bytes > 0) else "error",
        down_bps=int(dl_mbps * 1_000_000),
        up_bps=int(ul_mbps * 1_000_000),
        ping_us=round(min_ping_ms * 1000) if min_ping_ms is not None else None,
        jitter_us=round(jitter_fallback_ms * 1000) if jitter_fallback_ms is not None else None,
        loss_pct=None,          # RMBT does not measure packet loss
        server_id=None,
        server_name=f"RTR-NetTest ({params.server_addr})",
        server_host=f"{params.server_addr}:{params.server_port}",
        server_location=None,
        client_ip=v4,
        client_ipv6=v6,
        result_url=share_url,
        raw_json=json.dumps({
            "engine": "rtr-nettest",
            "control_host": host,
            "test_uuid": params.test_uuid,
            "open_test_uuid": params.open_test_uuid,
            "share_url": share_url,
            "dl_threads": len(dl_results),
            "ul_threads": len(ul_results),
            "ping_min_ms": round(min_ping_ms, 2) if min_ping_ms is not None else None,
            "ping_median_ms": round(median_ping_ms, 2) if median_ping_ms is not None else None,
            "ping_count": len(rtts),
            "down_bytes": dl_bytes, "up_bytes": ul_bytes,
        }),
        error=None,
        down_loaded_lat_ms=None,
        up_loaded_lat_ms=None,
        bufferbloat_grade=bb_grade,
        bufferbloat_delta_ms=bb_delta,
        engine="rtr",
        colo=None,
        bound_iface=interface,
        bound_ip=bind_ip,
    )
    trim_process_memory()
    return res
