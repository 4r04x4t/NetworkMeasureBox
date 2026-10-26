"""
Dynamic Public iPerf3 Server Directory and Probing Module for NetworkMeasureBox.

Fetches and normalizes public iPerf3 servers online without any hardcoding.
Primary source: https://export.iperf3serverlist.net/listed_iperf3_servers.json
Fallback source: https://iperf.fr/iperf-servers.php
Provides local filesystem caching with 24-hour TTL and fast TCP reachability probing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.speed.iperf_directory")

CACHE_PATHS = [
    Path("/var/lib/nmb/live/iperf_public_servers.json"),
    Path("/var/lib/nmb/iperf_public_servers.json"),
    Path("/run/nmb/iperf_public_servers.json"),
    Path("/tmp/iperf_public_servers.json"),
]

CACHE_TTL_SEC = 86400  # 24 hours


def _get_cache_path() -> Path:
    """Find a writable cache file location."""
    for p in CACHE_PATHS:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            continue
    return Path("/tmp/iperf_public_servers.json")


def _read_cache(max_age_sec: float = CACHE_TTL_SEC) -> Optional[Dict[str, Any]]:
    """Read cached server directory if valid and not expired."""
    p = _get_cache_path()
    if not p.exists():
        return None
    try:
        mtime = p.stat().st_mtime
        age = time.time() - mtime
        if age > max_age_sec:
            log.debug("iperf server cache expired (age=%.1fs, ttl=%.1fs)", age, max_age_sec)
            return None
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "servers" in data:
                data["cache_age_sec"] = int(age)
                return data
    except Exception as e:
        log.warning("could not read iperf server cache: %s", e)
    return None


def _write_cache(servers: List[Dict[str, Any]], source: str) -> None:
    """Save normalized server list to cache file."""
    p = _get_cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": source,
            "updated_at": int(time.time()),
            "count": len(servers),
            "servers": servers,
        }
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        log.info("cached %d public iperf3 servers to %s", len(servers), p)
    except Exception as e:
        log.warning("failed to cache iperf servers to %s: %s", p, e)


def _fetch_from_iperf3serverlist() -> List[Dict[str, Any]]:
    """
    Fetch public server list from export.iperf3serverlist.net.
    Provides structured JSON with ~170+ global servers.
    """
    urls = [
        "https://export.iperf3serverlist.net/listed_iperf3_servers.json",
        "http://export.iperf3serverlist.net/listed_iperf3_servers.json",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (NetworkMeasureBox Diagnostic Engine)",
        "Accept": "application/json",
    }
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list):
                continue
            servers: List[Dict[str, Any]] = []
            for item in data:
                host = str(item.get("IP/HOST", "")).strip()
                if not host:
                    continue
                port_raw = str(item.get("PORT", "5201")).strip()
                port = 5201
                m = re.match(r"^(\d+)", port_raw)
                if m:
                    try:
                        port = int(m.group(1))
                    except ValueError:
                        port = 5201

                continent = str(item.get("CONTINENT", "")).strip()
                country = str(item.get("COUNTRY", "")).strip()
                site = str(item.get("SITE", "")).strip()
                provider = str(item.get("PROVIDER", "")).strip()
                speed = str(item.get("GB/S", "")).strip()
                options = str(item.get("OPTIONS", "")).strip()

                servers.append({
                    "host": host,
                    "port": port,
                    "port_range": port_raw,
                    "continent": continent,
                    "country": country,
                    "site": site,
                    "provider": provider,
                    "speed": f"{speed}G" if speed and not speed.endswith("G") else speed,
                    "options": options,
                    "source": "iperf3serverlist.net",
                })
            if servers:
                log.info("successfully fetched %d servers from %s", len(servers), url)
                return servers
        except Exception as e:
            log.warning("failed fetching from %s: %s", url, e)
    return []


def _fetch_from_iperf_fr() -> List[Dict[str, Any]]:
    """
    Fallback: Scrape HTML directory from https://iperf.fr/iperf-servers.php.
    """
    url = "https://iperf.fr/iperf-servers.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (NetworkMeasureBox Diagnostic Engine)",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.DOTALL | re.IGNORECASE)
        servers: List[Dict[str, Any]] = []
        current_continent = "Global"

        for r in rows:
            # Check continent heading
            if "<th" in r.lower() and "colspan" in r.lower():
                th_match = re.search(r"<th[^>]*>(.*?)</th>", r, flags=re.DOTALL | re.IGNORECASE)
                if th_match:
                    clean_head = re.sub(r"<[^>]+>", "", th_match.group(1)).strip()
                    if clean_head:
                        current_continent = clean_head
                continue

            tds = re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.DOTALL | re.IGNORECASE)
            if len(tds) >= 4:
                # Host in tds[0]
                raw_hosts = re.findall(r"[\w\.\-]+(?:\.[\w\-]+)+", re.sub(r"<[^>]+>", " ", tds[0]))
                loc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tds[1])).strip()
                provider = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tds[3])).strip()
                port = 5201
                if len(tds) >= 7:
                    pm = re.search(r"(\d{4,5})", tds[6])
                    if pm:
                        port = int(pm.group(1))

                for h in raw_hosts:
                    if "." in h and not h.startswith("www.") and "google" not in h and not h.endswith(".php"):
                        servers.append({
                            "host": h,
                            "port": port,
                            "port_range": str(port),
                            "continent": current_continent,
                            "country": "",
                            "site": loc,
                            "provider": provider,
                            "speed": "",
                            "options": "",
                            "source": "iperf.fr",
                        })
        if servers:
            log.info("scraped %d servers from %s", len(servers), url)
            return servers
    except Exception as e:
        log.warning("failed fetching fallback from %s: %s", url, e)
    return []


def fetch_public_iperf_servers(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Retrieve public iPerf3 servers with caching and fallback.
    Returns structured dictionary with server records and metadata.
    """
    if not force_refresh:
        cached = _read_cache(max_age_sec=CACHE_TTL_SEC)
        if cached and cached.get("servers"):
            return {
                "status": "ok",
                "count": len(cached["servers"]),
                "servers": cached["servers"],
                "cached": True,
                "updated_at": cached.get("updated_at"),
                "source": cached.get("source", "cache"),
            }

    # Fetch from primary source
    servers = _fetch_from_iperf3serverlist()
    source_name = "iperf3serverlist.net"

    # Fallback to secondary source if primary failed
    if not servers:
        log.warning("primary iperf directory failed, trying secondary (iperf.fr)...")
        servers = _fetch_from_iperf_fr()
        source_name = "iperf.fr"

    if servers:
        _write_cache(servers, source_name)
        return {
            "status": "ok",
            "count": len(servers),
            "servers": servers,
            "cached": False,
            "updated_at": int(time.time()),
            "source": source_name,
        }

    # If both online sources failed, return stale cache if available
    stale_cache = _read_cache(max_age_sec=86400 * 30)
    if stale_cache and stale_cache.get("servers"):
        log.warning("using stale iperf server cache as both online sources are unavailable")
        return {
            "status": "ok",
            "count": len(stale_cache["servers"]),
            "servers": stale_cache["servers"],
            "cached": True,
            "stale": True,
            "updated_at": stale_cache.get("updated_at"),
            "source": "stale_cache",
        }

    return {
        "status": "error",
        "error": "Failed to retrieve public iPerf3 servers from online directories and no cache available.",
        "servers": [],
        "count": 0,
    }


def probe_iperf_server(host: str, port: int = 5201, timeout_sec: float = 3.0) -> Dict[str, Any]:
    """
    Perform a rapid TCP socket connection handshake to check server reachability and latency.
    Runs in < 100-300ms without starting a full benchmark.
    """
    host = str(host).strip()
    if not host:
        return {"status": "error", "reachable": False, "error": "Empty host specified."}

    t0 = time.time()
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout_sec)
        sock.close()
        rtt_ms = round((time.time() - t0) * 1000.0, 1)
        return {
            "status": "ok",
            "host": host,
            "port": port,
            "reachable": True,
            "rtt_ms": rtt_ms,
            "timestamp": int(time.time() * 1000),
        }
    except socket.timeout:
        return {
            "status": "timeout",
            "host": host,
            "port": port,
            "reachable": False,
            "error": f"Connection to {host}:{port} timed out after {timeout_sec:.1f}s (firewalled or offline).",
        }
    except Exception as e:
        return {
            "status": "error",
            "host": host,
            "port": port,
            "reachable": False,
            "error": str(e),
        }
