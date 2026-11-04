"""
Visual & Hop-by-Hop Traceroute Engine for NetworkMeasureBox.
Traces intermediate ISP routers and packet latencies to any destination
with real-time hop streaming, protocol selection (ICMP/UDP/TCP), and fallback engines.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.speed.traceroute")

_trace_lock = threading.Lock()
_trace_running = False
_active_proc: Optional[subprocess.Popen] = None
_stop_requested = False

_latest_trace_result: Optional[Dict[str, Any]] = None

_ip_geo_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def _country_code_to_flag(code: str) -> str:
    """Convert 2-letter ISO country code into Unicode regional indicator flag emoji."""
    if not code or len(code) != 2 or not code.isalpha():
        return "🌐"
    return chr(ord(code[0].upper()) + 127397) + chr(ord(code[1].upper()) + 127397)


def _is_valid_ip(addr: str) -> bool:
    """Check if string is a valid IPv4 or IPv6 address."""
    if not addr or addr == "*":
        return False
    try:
        ipaddress.ip_address(addr.strip("[]()"))
        return True
    except ValueError:
        return False


def classify_hop_type(ip: str, target_ip: str = "") -> str:
    """
    Classify hop category: 'target', 'lan', 'cgnat', 'public', or 'timeout'.
    """
    if not ip or ip == "*":
        return "timeout"
    clean_ip = ip.strip("[]()")
    if target_ip and clean_ip == target_ip.strip("[]()"):
        return "target"
    try:
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            return "lan"
        if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in ipaddress.IPv4Network("100.64.0.0/10"):
            return "cgnat"
        return "public"
    except Exception:
        return "public"


def enrich_hop_ips(hops: List[Dict[str, Any]]) -> None:
    """
    Look up Country, ISO code, Flag emoji, and Provider/ISP/AS for all hop IP addresses.
    Utilizes local memory cache, private network classification, and fast batch REST API.
    """
    to_query: List[str] = []

    with _cache_lock:
        for h in hops:
            ip = h.get("ip", "")
            if not ip or ip == "*" or ip in _ip_geo_cache:
                continue
            try:
                ip_obj = ipaddress.ip_address(ip.strip("[]()"))
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    _ip_geo_cache[ip] = {
                        "country": "Local Network",
                        "country_code": "LAN",
                        "flag": "🏠",
                        "isp": "Local Gateway / Private Subnet",
                        "org": "LAN",
                        "as": "",
                    }
                elif isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in ipaddress.IPv4Network("100.64.0.0/10"):
                    _ip_geo_cache[ip] = {
                        "country": "Carrier-Grade NAT",
                        "country_code": "CGNAT",
                        "flag": "📡",
                        "isp": "ISP Carrier-Grade NAT (RFC 6598)",
                        "org": "CGNAT",
                        "as": "",
                    }
                else:
                    to_query.append(ip)
            except ValueError:
                _ip_geo_cache[ip] = {
                    "country": "--",
                    "country_code": "",
                    "flag": "",
                    "isp": "--",
                    "org": "",
                    "as": "",
                }

    # Deduplicate and batch query public IPs
    to_query = list(dict.fromkeys(to_query))
    if to_query:
        # 1. Try ip-api.com batch endpoint
        try:
            from nmb.common.user_agent import get_effective_user_agent
            req = urllib.request.Request(
                "http://ip-api.com/batch?fields=query,status,country,countryCode,isp,org,as,asname",
                data=json.dumps(to_query[:100]).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": get_effective_user_agent()}
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                with _cache_lock:
                    for item in data:
                        q = item.get("query")
                        if q and item.get("status") == "success":
                            cc = item.get("countryCode", "")
                            _ip_geo_cache[q] = {
                                "country": item.get("country", "Unknown"),
                                "country_code": cc,
                                "flag": _country_code_to_flag(cc),
                                "isp": item.get("isp") or item.get("org") or item.get("asname") or "Unknown ISP",
                                "org": item.get("org", ""),
                                "as": item.get("as", ""),
                            }
                        elif q and item.get("message") == "private range":
                            _ip_geo_cache[q] = {
                                "country": "Private Network",
                                "country_code": "RFC1918",
                                "flag": "🔒",
                                "isp": "Internal ISP Subnet",
                                "org": "",
                                "as": "",
                            }
        except Exception as e:
            log.warning("batch ip-api lookup failed: %s; falling back to individual queries", e)
            with _cache_lock:
                for ip in to_query:
                    if ip not in _ip_geo_cache:
                        try:
                            from nmb.common.user_agent import get_effective_user_agent
                            f_req = urllib.request.Request(
                                f"https://ipwho.is/{ip}",
                                headers={"User-Agent": get_effective_user_agent()}
                            )
                            with urllib.request.urlopen(f_req, timeout=1.8) as f_resp:
                                f_data = json.loads(f_resp.read().decode("utf-8"))
                                if f_data.get("success"):
                                    cc = f_data.get("country_code", "")
                                    connection = f_data.get("connection", {})
                                    _ip_geo_cache[ip] = {
                                        "country": f_data.get("country", "Unknown"),
                                        "country_code": cc,
                                        "flag": _country_code_to_flag(cc),
                                        "isp": connection.get("isp") or connection.get("org") or "Unknown ISP",
                                        "org": connection.get("org", ""),
                                        "as": connection.get("asn", ""),
                                    }
                        except Exception:
                            pass

    # Map enriched data onto each hop
    with _cache_lock:
        for h in hops:
            ip = h.get("ip", "")
            h["hostname"] = h.get("host") or ip
            if ip == "*" or not ip:
                h["country"] = "--"
                h["country_code"] = ""
                h["flag"] = ""
                h["isp"] = "-- (Silent Hop / Timeout)"
                h["org"] = ""
                h["as"] = ""
            else:
                geo = _ip_geo_cache.get(ip, {})
                h["country"] = geo.get("country", "Unknown")
                h["country_code"] = geo.get("country_code", "")
                h["flag"] = geo.get("flag", "🌐")
                h["isp"] = geo.get("isp", "Unknown ISP")
                h["org"] = geo.get("org", "")
                h["as"] = geo.get("as", "")


def is_traceroute_available() -> bool:
    """Check if traceroute binary is available on system PATH."""
    return shutil.which("traceroute") is not None


def is_mtr_available() -> bool:
    """Check if mtr binary is available on system PATH."""
    return shutil.which("mtr") is not None


def is_tracepath_available() -> bool:
    """Check if tracepath binary is available on system PATH."""
    return shutil.which("tracepath") is not None


def is_traceroute_running() -> bool:
    """Return whether a traceroute probe is currently active."""
    return _trace_running


def get_latest_traceroute() -> Optional[Dict[str, Any]]:
    """Return the most recent traceroute result."""
    return _latest_trace_result


def stop_traceroute() -> Dict[str, Any]:
    """Gracefully interrupt and stop the running traceroute process."""
    global _stop_requested, _active_proc
    _stop_requested = True
    proc = _active_proc
    if proc is not None:
        try:
            log.info("Terminating running traceroute process pid=%s", proc.pid)
            proc.terminate()
            # Give it a brief moment to exit cleanly
            threading.Thread(target=_force_kill_proc, args=(proc,), daemon=True).start()
        except Exception as e:
            log.warning("Failed to terminate traceroute process: %s", e)
    return {"status": "ok", "message": "Traceroute stop requested."}


def _force_kill_proc(proc: subprocess.Popen) -> None:
    time.sleep(1.2)
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass


def _parse_traceroute_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single line of standard traceroute output.
    Examples:
      1  _gateway (192.168.8.1)  0.334 ms  0.294 ms  0.275 ms
      2  lo0.bdr1.bud.invitel.net (213.163.38.1)  4.120 ms  4.095 ms  4.050 ms
      3  * * *
      4  * cloudflare.bix.hu (193.188.137.27)  7.653 ms * *
      5  2001:db8::1 (2001:db8::1)  1.234 ms  1.120 ms  1.050 ms
    """
    line = line.strip()
    if not line or line.startswith("traceroute") or line.startswith("Selected") or line.startswith("traceroute to"):
        return None

    m = re.match(r"^(\d+)\s+(.+)$", line)
    if not m:
        return None

    hop_idx = int(m.group(1))
    rest = m.group(2).strip()

    # Extract all ms values
    rtt_matches = re.findall(r"([0-9.]+)\s*ms", rest)
    rtt_vals = [round(float(v), 2) for v in rtt_matches]

    # Find IP address (IPv4 first, IPv6 if colons present)
    m4 = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", rest)
    valid_ips = [ip for ip in m4 if _is_valid_ip(ip)]

    if not valid_ips and ":" in rest:
        m6 = re.findall(r"\(?([0-9a-fA-F:]{3,45})\)?", rest)
        valid_ips = [ip.strip("()") for ip in m6 if ":" in ip and _is_valid_ip(ip.strip("()"))]

    if not valid_ips:
        # Complete packet loss on this hop
        return {
            "hop": hop_idx,
            "ip": "*",
            "host": "*",
            "hostname": "*",
            "rtt_ms": None,
            "rtts": [],
            "loss_pct": 100.0,
            "status": "timeout",
            "hop_type": "timeout",
        }

    found_ip = valid_ips[0]

    # Hostname: pattern `<hostname> (<ip>)` or first token if not IP
    host_str = found_ip
    m_host = re.search(r"(?:\s+|^)([a-zA-Z0-9_\-\.]+)\s+\(" + re.escape(found_ip) + r"\)", rest)
    if m_host:
        candidate_host = m_host.group(1).strip()
        if (
            candidate_host
            and candidate_host != found_ip
            and not _is_valid_ip(candidate_host)
            and not re.match(r"^\d+$", candidate_host)
        ):
            host_str = candidate_host
    else:
        parts = rest.split()
        if parts and parts[0] != found_ip and parts[0] != "*" and not parts[0].startswith("("):
            token = parts[0].strip("()")
            if (
                re.match(r"^[a-zA-Z0-9_\-\.]+$", token)
                and not re.match(r"^[0-9.]+$", token)
                and not _is_valid_ip(token)
            ):
                host_str = token

    avg_rtt = round(sum(rtt_vals) / len(rtt_vals), 2) if rtt_vals else None
    loss = round(((3 - len(rtt_vals)) / 3.0) * 100.0, 1)

    return {
        "hop": hop_idx,
        "ip": found_ip,
        "host": host_str,
        "hostname": host_str,
        "rtt_ms": avg_rtt,
        "rtts": rtt_vals,
        "loss_pct": max(0.0, loss),
        "status": "ok",
        "hop_type": classify_hop_type(found_ip),
    }


def _run_ping_ttl_traceroute(target: str, max_hops: int, pref_iface: str, resolved_ip: str) -> List[Dict[str, Any]]:
    """
    Fallback traceroute engine using pure ICMP ping with incrementing TTL.
    Used when no external traceroute, mtr, or tracepath binary is installed.
    """
    global _stop_requested, _active_proc, _latest_trace_result
    hops: List[Dict[str, Any]] = []

    for ttl in range(1, max_hops + 1):
        if _stop_requested:
            break

        cmd = ["ping", "-c", "1", "-t", str(ttl), "-W", "1"]
        if pref_iface:
            cmd.extend(["-I", pref_iface])
        cmd.append(target)

        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            _active_proc = p
            stdout, _ = p.communicate(timeout=2.0)
        except Exception:
            stdout = ""

        # Parse output for gateway or echo reply
        # Time to live exceeded: "From 192.168.8.1 icmp_seq=1 Time to live exceeded"
        # Echo reply: "64 bytes from 1.1.1.1: icmp_seq=1 ttl=56 time=5.68 ms"
        hop_ip = "*"
        hop_rtt = None
        m_gw = re.search(r"From\s+([0-9a-fA-F:.]+).*Time to live exceeded", stdout)
        m_reply = re.search(r"bytes from\s+([0-9a-fA-F:.]+):.*time=([0-9.]+)\s*ms", stdout)

        if m_reply:
            hop_ip = m_reply.group(1).strip()
            hop_rtt = round(float(m_reply.group(2)), 2)
            loss = 0.0
        elif m_gw:
            hop_ip = m_gw.group(1).strip()
            m_ms = re.search(r"time=([0-9.]+)\s*ms", stdout)
            hop_rtt = round(float(m_ms.group(1)), 2) if m_ms else None
            loss = 0.0
        else:
            loss = 100.0

        hop_dict: Dict[str, Any] = {
            "hop": ttl,
            "ip": hop_ip,
            "host": hop_ip,
            "hostname": hop_ip,
            "rtt_ms": hop_rtt,
            "rtts": [hop_rtt] if hop_rtt is not None else [],
            "loss_pct": loss,
            "status": "ok" if hop_ip != "*" else "timeout",
            "hop_type": classify_hop_type(hop_ip, resolved_ip),
        }
        hops.append(hop_dict)
        if _latest_trace_result:
            _latest_trace_result["hops"] = list(hops)
            _latest_trace_result["hops_count"] = len(hops)

        if hop_ip != "*" and resolved_ip and hop_ip == resolved_ip:
            # Reached target destination
            break

    return hops


def run_traceroute(
    target: str = "",
    max_hops: int = 30,
    host: str = "",
    method: str = "icmp",
    ip_version: str = "auto",
) -> Dict[str, Any]:
    """
    Execute a hop-by-hop visual traceroute to the destination target.
    Streams hops progressively into _latest_trace_result so UI receives real-time updates.
    """
    global _trace_running, _latest_trace_result, _active_proc, _stop_requested

    raw_target = (target or host).strip()
    if not raw_target:
        return {"status": "error", "error": "Target destination cannot be empty."}

    # Clean target: strip http://, https://, paths, or ports if pasted from browser
    raw_target = re.sub(r"^https?://", "", raw_target).split("/")[0].split(":")[0].strip()
    if not raw_target or raw_target.startswith("-"):
        return {"status": "error", "error": "Target destination cannot begin with '-'."}

    if not re.match(r"^[a-zA-Z0-9.\-_:]+$", raw_target):
        return {"status": "error", "error": "Invalid characters in destination address."}

    try:
        max_hops = max(1, min(64, int(max_hops)))
    except (ValueError, TypeError):
        max_hops = 30

    method = (method or "icmp").lower().strip()
    if method not in ("icmp", "udp", "tcp"):
        method = "icmp"

    ip_version = (ip_version or "auto").lower().strip()
    if ip_version not in ("auto", "ipv4", "ipv6"):
        ip_version = "auto"

    with _trace_lock:
        if _trace_running:
            return {"status": "busy", "message": "A traceroute is already in progress."}
        _trace_running = True
        _stop_requested = False

    t0 = time.time()
    hops: List[Dict[str, Any]] = []

    # Initialize running state
    resolved_ip = ""
    try:
        from nmb.netd.dns import resolve_cached
        ok, ip_cand, _, _ = resolve_cached(raw_target)
        if ok and ip_cand:
            resolved_ip = ip_cand
        else:
            infos = socket.getaddrinfo(raw_target, None)
            if infos:
                resolved_ip = infos[0][4][0]
    except Exception:
        resolved_ip = raw_target

    _latest_trace_result = {
        "status": "running",
        "target": raw_target,
        "resolved_ip": resolved_ip,
        "method": method,
        "ip_version": ip_version,
        "hops_count": 0,
        "hops": [],
        "total_hops": 0,
        "dest_rtt_ms": None,
        "loss_hops": 0,
        "responsive_hops": 0,
        "destination_reached": False,
        "carriers": [],
        "elapsed_sec": 0.0,
        "timestamp": int(time.time() * 1000),
    }

    try:
        from nmb.netd.interfaces import find_preferred_measurement_interface
        pref_iface, _, is_wired = find_preferred_measurement_interface()

        if is_traceroute_available():
            # Build traceroute command
            cmd = ["traceroute", "-m", str(max_hops), "-q", "3", "-w", "2"]

            # Method selection
            if method == "icmp":
                cmd.append("-I")
            elif method == "tcp":
                cmd.extend(["-T", "-p", "80"])
            elif method == "udp":
                # Standard traceroute uses UDP probes by default
                cmd.append("-U")

            # IP version
            if ip_version == "ipv4":
                cmd.append("-4")
            elif ip_version == "ipv6":
                cmd.append("-6")

            # Preferred interface (wired priority)
            if is_wired and pref_iface:
                cmd.extend(["-i", pref_iface])

            cmd.extend(["--", raw_target])
            log.info("Executing traceroute: %s", " ".join(cmd))

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _active_proc = proc

            target_reached = False
            for line in iter(proc.stdout.readline, ""):
                if _stop_requested:
                    break
                parsed = _parse_traceroute_line(line)
                if parsed:
                    # Enrich hop type with resolved IP awareness
                    parsed["hop_type"] = classify_hop_type(parsed["ip"], resolved_ip)
                    hops.append(parsed)

                    # Update streaming state
                    _latest_trace_result["hops"] = list(hops)
                    _latest_trace_result["hops_count"] = len(hops)
                    _latest_trace_result["elapsed_sec"] = round(time.time() - t0, 1)

                    if parsed.get("ip") and parsed["ip"] == resolved_ip:
                        target_reached = True
                        # Destination reached - terminate further probing early
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        break

            try:
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        elif is_tracepath_available():
            # Tracepath fallback
            cmd = ["tracepath", "-m", str(max_hops), "-n", raw_target]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            _active_proc = proc
            for line in iter(proc.stdout.readline, ""):
                if _stop_requested:
                    break
                line = line.strip()
                # Parse lines: " 1:  192.168.8.1  0.722ms"
                m_tp = re.match(r"^\s*(\d+):?\s+([0-9a-fA-F:.]+)\s+([0-9.]+)\s*ms", line)
                if m_tp:
                    h_idx = int(m_tp.group(1))
                    h_ip = m_tp.group(2)
                    h_rtt = round(float(m_tp.group(3)), 2)
                    h_dict = {
                        "hop": h_idx,
                        "ip": h_ip,
                        "host": h_ip,
                        "hostname": h_ip,
                        "rtt_ms": h_rtt,
                        "rtts": [h_rtt],
                        "loss_pct": 0.0,
                        "status": "ok",
                        "hop_type": classify_hop_type(h_ip, resolved_ip),
                    }
                    hops.append(h_dict)
                    _latest_trace_result["hops"] = list(hops)
                    _latest_trace_result["hops_count"] = len(hops)
                    if h_ip == resolved_ip:
                        break
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass

        else:
            # Fallback pure ping TTL engine
            hops = _run_ping_ttl_traceroute(
                target=raw_target,
                max_hops=max_hops,
                pref_iface=pref_iface if is_wired else "",
                resolved_ip=resolved_ip,
            )

        # Post-process: enrich geolocation and ISP data for all discovered hops
        enrich_hop_ips(hops)

        # Summary calculations
        total_hops = len(hops)
        loss_hops = sum(1 for h in hops if h.get("status") == "timeout" or h.get("ip") == "*")
        responsive_hops = total_hops - loss_hops
        loss_pct = round((loss_hops / total_hops * 100.0), 1) if total_hops > 0 else 0.0

        dest_rtt = None
        for h in reversed(hops):
            if h.get("rtt_ms") is not None:
                dest_rtt = h["rtt_ms"]
                break

        dest_reached = any(h.get("ip") == resolved_ip for h in hops) if resolved_ip else False
        if not dest_reached and hops and hops[-1].get("ip") != "*":
            # If last hop responded and we got this far
            if hops[-1].get("hop_type") == "target" or hops[-1].get("ip") == resolved_ip:
                dest_reached = True

        carriers = list(
            dict.fromkeys(
                h["isp"]
                for h in hops
                if h.get("isp")
                and h["isp"]
                not in (
                    "--",
                    "Local Gateway / Private Subnet",
                    "ISP Carrier-Grade NAT (RFC 6598)",
                    "Internal ISP Subnet",
                    "Unknown ISP",
                    "-- (Silent Hop / Timeout)",
                )
            )
        )

        elapsed = round(time.time() - t0, 2)
        result = {
            "status": "stopped" if _stop_requested else "ok",
            "target": raw_target,
            "resolved_ip": resolved_ip,
            "method": method,
            "ip_version": ip_version,
            "hops_count": len(hops),
            "hops": hops,
            "total_hops": total_hops,
            "dest_rtt_ms": dest_rtt,
            "loss_hops": loss_hops,
            "responsive_hops": responsive_hops,
            "loss_pct": loss_pct,
            "destination_reached": dest_reached,
            "carriers": carriers,
            "elapsed_sec": elapsed,
            "timestamp": int(time.time() * 1000),
        }
        _latest_trace_result = result
        return result

    except Exception as e:
        log.error("traceroute error: %s", e)
        res = {
            "status": "error",
            "error": str(e),
            "target": raw_target,
            "hops": hops,
            "hops_count": len(hops),
            "elapsed_sec": round(time.time() - t0, 2),
            "timestamp": int(time.time() * 1000),
        }
        _latest_trace_result = res
        return res

    finally:
        with _trace_lock:
            _trace_running = False
            _active_proc = None
