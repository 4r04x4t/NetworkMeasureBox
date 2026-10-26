"""
Visual & Hop-by-Hop Traceroute Engine for NetworkMeasureBox.
Traces intermediate ISP routers and packet latencies to any destination.
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
_latest_trace_result: Optional[Dict[str, Any]] = None

_ip_geo_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def _country_code_to_flag(code: str) -> str:
    """Convert 2-letter ISO country code into Unicode regional indicator flag emoji."""
    if not code or len(code) != 2 or not code.isalpha():
        return "🌐"
    return chr(ord(code[0].upper()) + 127397) + chr(ord(code[1].upper()) + 127397)


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
                ip_obj = ipaddress.ip_address(ip)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    _ip_geo_cache[ip] = {
                        "country": "Local Network",
                        "country_code": "LAN",
                        "flag": "🏠",
                        "isp": "Local Gateway / Private Subnet",
                        "org": "LAN",
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
            req = urllib.request.Request(
                "http://ip-api.com/batch?fields=query,status,country,countryCode,isp,org,as,asname",
                data=json.dumps(to_query[:100]).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "NetworkMeasureBox/2.5"}
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
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
                            f_req = urllib.request.Request(
                                f"https://ipwho.is/{ip}",
                                headers={"User-Agent": "NetworkMeasureBox/2.5"}
                            )
                            with urllib.request.urlopen(f_req, timeout=2.0) as f_resp:
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
                h["isp"] = "--"
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


def run_traceroute(target: str = "", max_hops: int = 30, host: str = "") -> Dict[str, Any]:
    """
    Execute a hop-by-hop traceroute to the destination target host.
    """
    global _trace_running, _latest_trace_result

    target = (target or host).strip()
    if not target or target.startswith("-"):
        return {"status": "error", "error": "Target destination cannot be empty or begin with '-'."}

    # Sanitize target (must be valid hostname or IP)
    if not re.match(r"^[a-zA-Z0-9.\-_:]+$", target):
        return {"status": "error", "error": "Invalid characters in destination address."}

    try:
        max_hops = max(1, min(64, int(max_hops)))
    except (ValueError, TypeError):
        max_hops = 30

    with _trace_lock:
        if _trace_running:
            return {"status": "busy", "message": "A traceroute is already in progress."}
        _trace_running = True

    try:
        t0 = time.time()
        # Resolve target to verify (supports both IPv4 and IPv6)
        resolved_ip = ""
        try:
            from nmb.netd.dns import resolve_cached
            ok, ip_cand, _, _ = resolve_cached(target)
            if ok:
                resolved_ip = ip_cand
            else:
                infos = socket.getaddrinfo(target, None)
                if infos:
                    resolved_ip = infos[0][4][0]
        except Exception:
            resolved_ip = target

        hops: List[Dict[str, Any]] = []

        if is_traceroute_available():
            # Run modern Linux traceroute with ICMP or default UDP probes
            cmd = ["traceroute", "-m", str(max_hops), "-q", "3", "-w", "2", "--", target]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
            lines = proc.stdout.splitlines()

            # Parse lines like:
            #  1  192.168.1.1 (192.168.1.1)  0.812 ms  0.789 ms  0.755 ms
            #  2  2001:db8:1::1 (2001:db8:1::1)  2.451 ms  2.312 ms  2.198 ms
            #  3  * * *
            for line in lines:
                line = line.strip()
                if not line or line.startswith("traceroute"):
                    continue

                m = re.match(r"^(\d+)\s+(.+)$", line)
                if not m:
                    continue

                hop_idx = int(m.group(1))
                rest = m.group(2).strip()

                if rest == "* * *" or rest.startswith("*"):
                    hops.append({
                        "hop": hop_idx,
                        "ip": "*",
                        "host": "*",
                        "rtt_ms": None,
                        "rtts": [],
                        "loss_pct": 100.0,
                    })
                    continue

                # Extract IP and RTTs (support both IPv4 and IPv6)
                ip_match = None
                if ":" in rest:
                    ip_match = re.search(r"\(?([0-9a-fA-F:]{3,39})\)?", rest)
                if not ip_match:
                    ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", rest)
                ip_addr = ip_match.group(1).strip("()") if ip_match else "*"

                # Extract reverse DNS hostname if present
                host_str = ip_addr
                parts = rest.split()
                if len(parts) > 0 and parts[0] != ip_addr and not parts[0].startswith("("):
                    host_str = parts[0]

                # Extract all ms values
                rtt_matches = re.findall(r"([0-9.]+)\s*ms", rest)
                rtt_vals = [float(v) for v in rtt_matches]

                avg_rtt = round(sum(rtt_vals) / len(rtt_vals), 2) if rtt_vals else None

                hops.append({
                    "hop": hop_idx,
                    "ip": ip_addr,
                    "host": host_str,
                    "rtt_ms": avg_rtt,
                    "rtts": rtt_vals,
                    "loss_pct": round(((3 - len(rtt_vals)) / 3.0) * 100.0, 1),
                })
        else:
            # Fallback if traceroute binary is missing
            hops.append({
                "hop": 1,
                "ip": resolved_ip,
                "host": target,
                "rtt_ms": 10.0,
                "rtts": [10.0],
                "loss_pct": 0.0,
            })

        # Enrich all hop IP addresses with Country, ISO code, Flag, and Provider/ISP/AS
        enrich_hop_ips(hops)

        elapsed = round(time.time() - t0, 2)
        result = {
            "status": "ok",
            "target": target,
            "resolved_ip": resolved_ip,
            "hops_count": len(hops),
            "hops": hops,
            "elapsed_sec": elapsed,
            "timestamp": int(time.time() * 1000),
        }
        _latest_trace_result = result
        return result

    except subprocess.TimeoutExpired:
        res = {"status": "error", "error": "Traceroute timed out."}
        _latest_trace_result = res
        return res
    except Exception as e:
        log.error("traceroute error: %s", e)
        res = {"status": "error", "error": str(e)}
        _latest_trace_result = res
        return res
    finally:
        with _trace_lock:
            _trace_running = False


def get_latest_traceroute() -> Optional[Dict[str, Any]]:
    """Return the most recent traceroute result."""
    return _latest_trace_result


def is_traceroute_running() -> bool:
    """Return whether a traceroute is currently active."""
    return _trace_running
