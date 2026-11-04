"""NetworkMeasureBox OS-Independent DNS Ad-Blocker & Sinkhole Subsystem (Pi-hole Equivalent).

Provides a lightweight, zero-dependency, ultra-fast DNS sinkhole and proxy daemon
capable of running in any network mode:
  - Standalone Mode (Mode C): Listens on port 53 (all interfaces / LAN IP); the user
    points their home router DHCP DNS setting to the box's IP (e.g. 192.168.8.218).
  - Router Mode (Mode A / Mode B): Directly serves DNS or integrates with dnsmasq
    so all LAN and Wi-Fi clients automatically have ads and trackers blocked.

Features:
  - Gravity Manager: Fetches, normalizes, deduplicates StevenBlack, AdAway, Peter Lowe lists.
  - Whitelist / Blacklist management with instant in-memory matching.
  - Fast RFC 1035 / RFC 7766 DNS sinkhole (A -> 0.0.0.0, AAAA -> ::, NODATA for others).
  - Upstream DNS forwarding (Cloudflare 1.1.1.1, Quad9 9.9.9.9, Google 8.8.8.8) with LRU caching.
  - Live Query Log (circular ring buffer in RAM) with client IP, domain, QTYPE, and latency.
  - Telemetry: Queries today, blocked count, % blocked, top domains, top clients.
  - Dynamic Router DHCP configuration instructions with the box's detected IP.
"""
from __future__ import annotations

import collections
import datetime
import ipaddress
import json
import logging
import os
import re
import select
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from collections import Counter, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("nmb.netd.adblock")

# Persistent and Runtime Storage Paths
def _resolve_data_dir() -> Path:
    std_dir = Path("/var/lib/nmb/adblock")
    if std_dir.exists() or os.access("/var/lib", os.W_OK):
        return std_dir
    # Fallback to local user or temp directory
    fallback = Path(os.environ.get("NMB_DATA_DIR", "/tmp/nmb")) / "adblock"
    return fallback

ADBLOCK_DIR = _resolve_data_dir()
GRAVITY_FILE = ADBLOCK_DIR / "gravity.list"
SOURCES_FILE = ADBLOCK_DIR / "sources.txt"
WHITELIST_FILE = ADBLOCK_DIR / "whitelist.txt"
BLACKLIST_FILE = ADBLOCK_DIR / "blacklist.txt"
CONFIG_FILE = ADBLOCK_DIR / "config.json"
STATS_FILE = ADBLOCK_DIR / "stats.json"
DNSMASQ_CONF_FILE = ADBLOCK_DIR / "dnsmasq.adblock.conf"
HOSTS_FILE = ADBLOCK_DIR / "hosts.adblock"

DEFAULT_SOURCES = [
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "https://adaway.org/hosts.txt",
    "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=0&mimetype=plaintext",
    "https://someonewhocares.org/hosts/zero/hosts",
]

DEFAULT_UPSTREAMS = [
    "1.1.1.1",       # Cloudflare Primary
    "9.9.9.9",       # Quad9 Security / Privacy
    "1.0.0.1",       # Cloudflare Secondary
    "149.112.112.112", # Quad9 Secondary
]

# Seed list of prominent ad / tracking / telemetry domains (instant protection offline)
SEED_BLOCKED_DOMAINS = {
    "doubleclick.net",
    "adservice.google.com",
    "googlesyndication.com",
    "google-analytics.com",
    "analytics.google.com",
    "pagead2.googlesyndication.com",
    "adnxs.com",
    "criteo.com",
    "criteo.net",
    "outbrain.com",
    "taboola.com",
    "rubiconproject.com",
    "scorecardresearch.com",
    "quantserve.com",
    "advertising.com",
    "advertising.amazon.com",
    "aax.amazon-adsystem.com",
    "popads.net",
    "propellerads.com",
    "adcolony.com",
    "unityads.unity3d.com",
    "applovin.com",
    "pixel.facebook.com",
    "an.facebook.com",
    "ads.tiktok.com",
    "analytics.tiktok.com",
    "ads.twitter.com",
    "analytics.twitter.com",
    "telemetry.microsoft.com",
    "v10.events.data.microsoft.com",
    "v20.events.data.microsoft.com",
    "admob.com",
    "moatads.com",
    "pubmatic.com",
    "casalemedia.com",
    "openx.net",
    "smartadserver.com",
    "yieldmo.com",
    "serving-sys.com",
    "adroll.com",
    "inmobi.com",
    "flurry.com",
    "chartbeat.net",
    "hotjar.com",
    "branch.io",
    "appsflyer.com",
    "adjust.com",
    "kochava.com",
}

# DNS Protocol Constants (RFC 1035)
QTYPE_A = 1
QTYPE_NS = 2
QTYPE_CNAME = 5
QTYPE_SOA = 6
QTYPE_PTR = 12
QTYPE_MX = 15
QTYPE_TXT = 16
QTYPE_AAAA = 28
QTYPE_SRV = 33
QTYPE_HTTPS = 65
QTYPE_ANY = 255

QTYPE_NAMES = {
    1: "A",
    2: "NS",
    5: "CNAME",
    6: "SOA",
    12: "PTR",
    15: "MX",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    65: "HTTPS",
    255: "ANY",
}

DNS_PORT = 53


class AdblockConfig:
    """Manages adblock configuration persistence."""

    def __init__(self):
        self.enabled: bool = True
        self.upstreams: List[str] = list(DEFAULT_UPSTREAMS)
        self.dns_port: int = DNS_PORT
        self.cache_ttl_max: int = 300
        self.query_logging: bool = True
        self.max_query_log: int = 2000
        self.blocking_mode: str = "null_ip" # "null_ip" (0.0.0.0/::) or "nxdomain"
        self.load()

    def load(self) -> None:
        if not CONFIG_FILE.exists():
            self.save()
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            self.enabled = bool(data.get("enabled", True))
            self.upstreams = data.get("upstreams", list(DEFAULT_UPSTREAMS))
            self.dns_port = int(data.get("dns_port", DNS_PORT))
            self.cache_ttl_max = int(data.get("cache_ttl_max", 300))
            self.query_logging = bool(data.get("query_logging", True))
            self.max_query_log = int(data.get("max_query_log", 2000))
            self.blocking_mode = data.get("blocking_mode", "null_ip")
        except Exception as e:
            log.warning("failed to load adblock config: %s", e)

    def save(self) -> None:
        try:
            ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "enabled": self.enabled,
                "upstreams": self.upstreams,
                "dns_port": self.dns_port,
                "cache_ttl_max": self.cache_ttl_max,
                "query_logging": self.query_logging,
                "max_query_log": self.max_query_log,
                "blocking_mode": self.blocking_mode,
            }
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("failed to save adblock config: %s", e)


def parse_dns_qname(data: bytes, offset: int = 12) -> Tuple[str, int]:
    """Decode a DNS question QNAME from raw packet bytes, supporting compression pointers."""
    labels = []
    curr = offset
    visited_pointers = set()
    packet_len = len(data)

    while curr < packet_len:
        length = data[curr]
        if length == 0:
            curr += 1
            break
        # RFC 1035 pointer
        if (length & 0xC0) == 0xC0:
            if curr + 1 >= packet_len:
                break
            pointer = ((length & 0x3F) << 8) | data[curr + 1]
            if pointer in visited_pointers or pointer >= packet_len:
                # Loop detected or out-of-bounds pointer
                break
            visited_pointers.add(pointer)
            sub, _ = parse_dns_qname(data, pointer)
            if sub:
                labels.append(sub)
            curr += 2
            break
        curr += 1
        if curr + length > packet_len:
            break
        label = data[curr : curr + length].decode("ascii", errors="ignore")
        labels.append(label)
        curr += length

    domain = ".".join(labels).strip(".").lower()
    return domain, curr


def parse_dns_query(data: bytes) -> Optional[Tuple[int, str, int, int, bytes]]:
    """Parse raw DNS query packet.

    Returns: (txid, domain, qtype, qclass, question_slice) or None
    """
    if len(data) < 16:
        return None
    try:
        txid, flags, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", data[:12])
        # If QR bit is 1, this is an answer, not a query
        if (flags & 0x8000) != 0:
            return None
        if qdcount < 1:
            return None

        domain, end_q = parse_dns_qname(data, 12)
        if end_q + 4 > len(data):
            return None
        qtype, qclass = struct.unpack("!HH", data[end_q : end_q + 4])
        question_slice = data[12 : end_q + 4]
        return txid, domain, qtype, qclass, question_slice
    except Exception:
        return None


def build_sinkhole_response(txid: int, qtype: int, question_slice: bytes, nxdomain: bool = False) -> bytes:
    """Synthesize an RFC 1035 DNS response redirecting blocked domains to 0.0.0.0 or ::."""
    if nxdomain:
        # Standard query response, Authoritative, Recursion Available, Name Error (RCODE=3)
        header = struct.pack("!HHHHHH", txid, 0x8583, 1, 0, 0, 0)
        return header + question_slice

    if qtype == QTYPE_A:
        # Response, NoError, 1 Answer (0.0.0.0, TTL=300)
        header = struct.pack("!HHHHHH", txid, 0x8180, 1, 1, 0, 0)
        # Pointer to question QNAME at offset 12: \xc0\x0c
        answer = b"\xc0\x0c" + struct.pack("!HHIH", QTYPE_A, 1, 300, 4) + bytes([0, 0, 0, 0])
        return header + question_slice + answer

    elif qtype == QTYPE_AAAA:
        # Response, NoError, 1 Answer (::, TTL=300)
        header = struct.pack("!HHHHHH", txid, 0x8180, 1, 1, 0, 0)
        answer = b"\xc0\x0c" + struct.pack("!HHIH", QTYPE_AAAA, 1, 300, 16) + (b"\x00" * 16)
        return header + question_slice + answer

    else:
        # For HTTPS (65), MX (15), TXT (16), etc.: return NoError with 0 answers (NODATA)
        header = struct.pack("!HHHHHH", txid, 0x8180, 1, 0, 0, 0)
        return header + question_slice


class AdblockEngine:
    """High-speed in-memory DNS filter, cache, and telemetry collector."""

    def __init__(self):
        self.config = AdblockConfig()
        self.lock = threading.RLock()
        self.blocked_domains: Set[str] = set()
        self.whitelist: Set[str] = set()
        self.blacklist: Set[str] = set()

        # Telemetry & Live Query Log (in RAM)
        self.query_log: deque = deque(maxlen=self.config.max_query_log)
        self.total_queries: int = 0
        self.blocked_queries: int = 0
        self.cached_queries: int = 0
        self.top_blocked: Counter = Counter()
        self.top_queried: Counter = Counter()
        self.top_clients: Counter = Counter()
        self.qtype_counts: Counter = Counter()
        self.last_gravity_update: Optional[float] = None
        self.last_update_status: str = "never"

        # Upstream Response Cache: key=(domain, qtype) -> (response_bytes, expire_time)
        self.cache: Dict[Tuple[str, int], Tuple[bytes, float]] = {}
        self.cache_lock = threading.Lock()

        self._load_local_data()

    def _load_local_data(self) -> None:
        """Load whitelist, blacklist, and gravity list from disk."""
        with self.lock:
            # 1. Whitelist
            self.whitelist = set()
            if WHITELIST_FILE.exists():
                for line in WHITELIST_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        self.whitelist.add(line)

            # 2. Blacklist
            self.blacklist = set()
            if BLACKLIST_FILE.exists():
                for line in BLACKLIST_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        self.blacklist.add(line)

            # 3. Gravity Blocklist
            self.blocked_domains = set(SEED_BLOCKED_DOMAINS)
            if GRAVITY_FILE.exists():
                try:
                    for line in GRAVITY_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = line.strip().lower()
                        if line and not line.startswith("#"):
                            self.blocked_domains.add(line)
                    self.last_gravity_update = GRAVITY_FILE.stat().st_mtime
                    self.last_update_status = "loaded_from_disk"
                except Exception as e:
                    log.warning("error reading gravity.list: %s", e)

            # Merge custom blacklist and prune whitelist
            self.blocked_domains.update(self.blacklist)
            self.blocked_domains.difference_update(self.whitelist)
            log.info("AdblockEngine loaded: %d blocked domains, %d whitelist, %d blacklist",
                     len(self.blocked_domains), len(self.whitelist), len(self.blacklist))

    def is_domain_blocked(self, domain: str) -> Tuple[bool, str]:
        """Check if domain should be sinkholed.

        Checks exact match and parent domain suffixes (e.g. sub.doubleclick.net matches doubleclick.net).
        Returns: (is_blocked, reason)
        """
        domain = domain.strip(".").lower()
        if not domain:
            return False, "empty"

        # Whitelist override takes priority
        if domain in self.whitelist:
            return False, "whitelisted"
        parts = domain.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.whitelist:
                return False, "whitelisted_parent"

        # User Blacklist check
        if domain in self.blacklist:
            return True, "blacklist"
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.blacklist:
                return True, "blacklist_parent"

        # Gravity Blocklist check
        if domain in self.blocked_domains:
            return True, "gravity"
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.blocked_domains:
                return True, "gravity_parent"

        return False, "permitted"

    def record_query(
        self,
        client_ip: str,
        domain: str,
        qtype_num: int,
        status: str,
        reason: str,
        latency_ms: float,
    ) -> None:
        """Record query telemetry into RAM buffer."""
        qtype_str = QTYPE_NAMES.get(qtype_num, str(qtype_num))
        now = time.time()
        time_str = datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S")

        entry = {
            "id": self.total_queries + 1,
            "timestamp": now,
            "time_str": time_str,
            "client_ip": client_ip,
            "domain": domain,
            "type": qtype_str,
            "status": status,
            "reason": reason,
            "latency_ms": round(latency_ms, 2),
        }

        with self.lock:
            self.total_queries += 1
            if status == "BLOCKED":
                self.blocked_queries += 1
                self.top_blocked[domain] += 1
            elif status == "CACHED":
                self.cached_queries += 1

            self.top_queried[domain] += 1
            self.top_clients[client_ip] += 1
            self.qtype_counts[qtype_str] += 1

            if self.config.query_logging:
                self.query_log.append(entry)

    def get_cached_response(self, domain: str, qtype: int, txid: int) -> Optional[bytes]:
        now = time.time()
        with self.cache_lock:
            entry = self.cache.get((domain, qtype))
            if entry:
                resp_bytes, expire_time = entry
                if expire_time > now:
                    # Update transaction ID in the first 2 bytes
                    return struct.pack("!H", txid) + resp_bytes[2:]
                else:
                    del self.cache[(domain, qtype)]
        return None

    def store_cache_response(self, domain: str, qtype: int, resp_bytes: bytes, ttl: int = 60) -> None:
        now = time.time()
        eff_ttl = max(10, min(ttl, self.config.cache_ttl_max))
        with self.cache_lock:
            # Simple size cap
            if len(self.cache) > 5000:
                self.cache.clear()
            self.cache[(domain, qtype)] = (resp_bytes, now + eff_ttl)

    def forward_upstream(self, query_packet: bytes) -> Optional[bytes]:
        """Forward DNS query to upstream DNS servers with failover."""
        for upstream in self.config.upstreams:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1.5)
                s.sendto(query_packet, (upstream, DNS_PORT))
                resp, _ = s.recvfrom(4096)
                if resp:
                    return resp
            except Exception:
                continue
            finally:
                if s:
                    s.close()
        return None

    def handle_dns_request(self, data: bytes, client_addr: Tuple[str, int]) -> bytes:
        """Process an incoming DNS packet from a client."""
        start_t = time.perf_counter()
        client_ip = client_addr[0]

        parsed = parse_dns_query(data)
        if not parsed:
            # Bad or unparseable query, drop or return refused
            return b""

        txid, domain, qtype, qclass, question_slice = parsed

        # If adblock is globally disabled, forward immediately
        if not self.config.enabled:
            upstream_resp = self.forward_upstream(data)
            duration = (time.perf_counter() - start_t) * 1000.0
            self.record_query(client_ip, domain, qtype, "ALLOWED", "disabled", duration)
            return upstream_resp or b""

        # Check blocklist
        is_blocked, reason = self.is_domain_blocked(domain)
        if is_blocked:
            resp = build_sinkhole_response(txid, qtype, question_slice, nxdomain=(self.config.blocking_mode == "nxdomain"))
            duration = (time.perf_counter() - start_t) * 1000.0
            self.record_query(client_ip, domain, qtype, "BLOCKED", reason, duration)
            return resp

        # Check in-memory cache
        cached = self.get_cached_response(domain, qtype, txid)
        if cached:
            duration = (time.perf_counter() - start_t) * 1000.0
            self.record_query(client_ip, domain, qtype, "CACHED", "cache", duration)
            return cached

        # Forward permitted query to upstream
        upstream_resp = self.forward_upstream(data)
        duration = (time.perf_counter() - start_t) * 1000.0

        if upstream_resp:
            self.store_cache_response(domain, qtype, upstream_resp, ttl=120)
            self.record_query(client_ip, domain, qtype, "ALLOWED", "upstream", duration)
            return upstream_resp
        else:
            self.record_query(client_ip, domain, qtype, "FAILED", "upstream_timeout", duration)
            return b""

    def get_stats(self) -> Dict[str, Any]:
        """Compile dashboard telemetry statistics."""
        with self.lock:
            pct = 0.0
            if self.total_queries > 0:
                pct = round((self.blocked_queries / self.total_queries) * 100.0, 1)

            top_blocked_list = [{"domain": d, "count": c} for d, c in self.top_blocked.most_common(10)]
            top_queried_list = [{"domain": d, "count": c} for d, c in self.top_queried.most_common(10)]
            top_clients_list = [{"ip": ip, "count": c} for ip, c in self.top_clients.most_common(10)]

            return {
                "enabled": self.config.enabled,
                "domains_in_blocklist": len(self.blocked_domains),
                "total_queries": self.total_queries,
                "blocked_queries": self.blocked_queries,
                "cached_queries": self.cached_queries,
                "blocked_percentage": pct,
                "whitelist_count": len(self.whitelist),
                "blacklist_count": len(self.blacklist),
                "last_gravity_update": self.last_gravity_update,
                "last_gravity_update_iso": datetime.datetime.fromtimestamp(self.last_gravity_update).isoformat() if self.last_gravity_update else None,
                "last_update_status": self.last_update_status,
                "top_blocked_domains": top_blocked_list,
                "top_queried_domains": top_queried_list,
                "top_clients": top_clients_list,
                "upstreams": self.config.upstreams,
                "blocking_mode": self.config.blocking_mode,
            }

    def get_recent_queries(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.lock:
            entries = list(self.query_log)
            return entries[-limit:][::-1]


_engine_instance: Optional[AdblockEngine] = None
_engine_lock = threading.Lock()


def get_adblock_engine() -> AdblockEngine:
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = AdblockEngine()
        return _engine_instance


# ------------------------------------------------------------------------------
# Gravity Blocklist Updater Routine
# ------------------------------------------------------------------------------
_gravity_update_lock = threading.Lock()
_gravity_update_state: Dict[str, Any] = {
    "in_progress": False,
    "last_run": None,
    "status": "idle",
    "domains_found": 0,
    "output": "",
    "error": None,
}


def get_gravity_update_status() -> Dict[str, Any]:
    with _gravity_update_lock:
        return dict(_gravity_update_state)


def execute_gravity_update(custom_sources: Optional[List[str]] = None, timeout: float = 20.0) -> Dict[str, Any]:
    """Fetch external ad/tracking lists, parse, deduplicate, and compile gravity files."""
    start_time = time.time()
    ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)

    sources = list(custom_sources or [])
    if not sources:
        if SOURCES_FILE.exists():
            for line in SOURCES_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
        if not sources:
            sources = list(DEFAULT_SOURCES)
            SOURCES_FILE.write_text("\n".join(sources) + "\n", encoding="utf-8")

    collected_domains: Set[str] = set(SEED_BLOCKED_DOMAINS)
    output_lines = [f"=== Updating Adblock Gravity ({len(sources)} sources) ==="]
    success_sources = 0

    domain_regex = re.compile(r"^(?:(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+)?([a-zA-Z0-9_\-\.]+)(?:\s+#.*)?$")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NetworkMeasureBox-AdBlock/2.0)"}

    for url in sources:
        output_lines.append(f"Downloading from: {url}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                count = 0
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith(("#", "!", ";")):
                        continue
                    m = domain_regex.match(line)
                    if m:
                        d = m.group(1).strip().lower()
                        # Exclude localhost and invalid domains
                        if d not in ("localhost", "localhost.localdomain", "broadcasthost", "local", "0.0.0.0", "127.0.0.1", "::1") and "." in d:
                            collected_domains.add(d)
                            count += 1
                output_lines.append(f"  -> Extracted {count} domains.")
                success_sources += 1
        except Exception as e:
            output_lines.append(f"  -> Failed to fetch source: {e}")

    # Remove whitelisted domains
    whitelist_count = 0
    engine = get_adblock_engine()
    with engine.lock:
        whitelist = set(engine.whitelist)
        blacklist = set(engine.blacklist)

    for wl in whitelist:
        if wl in collected_domains:
            collected_domains.discard(wl)
            whitelist_count += 1

    # Include custom blacklist
    collected_domains.update(blacklist)

    # 1. Write gravity.list (one domain per line)
    sorted_domains = sorted(collected_domains)
    GRAVITY_FILE.write_text("\n".join(sorted_domains) + "\n", encoding="utf-8")

    # 2. Write dnsmasq.adblock.conf (format: address=/domain/0.0.0.0)
    # This allows dnsmasq to directly use the blocklist if dnsmasq is handling DNS
    dnsmasq_lines = [f"address=/{d}/0.0.0.0" for d in sorted_domains]
    DNSMASQ_CONF_FILE.write_text("# NetworkMeasureBox Adblock Gravity for dnsmasq\n" + "\n".join(dnsmasq_lines) + "\n", encoding="utf-8")

    # 3. Write hosts.adblock (format: 0.0.0.0 domain)
    hosts_lines = [f"0.0.0.0 {d}" for d in sorted_domains]
    HOSTS_FILE.write_text("# NetworkMeasureBox Adblock Hosts File\n" + "\n".join(hosts_lines) + "\n", encoding="utf-8")

    # Reload engine in-memory data
    engine._load_local_data()
    duration = time.time() - start_time
    output_lines.append(f"\nGravity updated successfully in {duration:.2f}s.")
    output_lines.append(f"Total Blocked Domains Active: {len(sorted_domains):,}")

    return {
        "status": "ok",
        "total_domains": len(sorted_domains),
        "sources_checked": len(sources),
        "sources_succeeded": success_sources,
        "duration_sec": round(duration, 2),
        "output": "\n".join(output_lines),
    }


def trigger_gravity_update() -> Dict[str, Any]:
    """Trigger background gravity blocklist update."""
    global _gravity_update_state
    with _gravity_update_lock:
        if _gravity_update_state["in_progress"]:
            return {"status": "busy", "message": "Gravity update already in progress."}
        _gravity_update_state["in_progress"] = True
        _gravity_update_state["status"] = "running"
        _gravity_update_state["output"] = "Initiating gravity update...\n"
        _gravity_update_state["error"] = None
        _gravity_update_state["last_run"] = time.time()

    def _worker():
        try:
            res = execute_gravity_update()
            with _gravity_update_lock:
                _gravity_update_state["in_progress"] = False
                _gravity_update_state["status"] = res.get("status", "error")
                _gravity_update_state["domains_found"] = res.get("total_domains", 0)
                _gravity_update_state["output"] = res.get("output", "")
        except Exception as e:
            with _gravity_update_lock:
                _gravity_update_state["in_progress"] = False
                _gravity_update_state["status"] = "error"
                _gravity_update_state["error"] = str(e)
                _gravity_update_state["output"] += f"\nFailure: {e}\n"

    t = threading.Thread(target=_worker, daemon=True, name="nmb-gravity-updater")
    t.start()
    return {"status": "started", "message": "Gravity update started in background."}


# ------------------------------------------------------------------------------
# Whitelist & Blacklist Management
# ------------------------------------------------------------------------------
IPC_SOCKET_PATH = Path("/run/nmb/adblock.sock")
if not Path("/run/nmb").exists() and not os.access("/run", os.W_OK):
    IPC_SOCKET_PATH = Path("/tmp/nmb-adblock.sock")


def query_adblock_ipc(cmd: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Communicate with live Adblock daemon over local UNIX socket."""
    if not IPC_SOCKET_PATH.exists():
        return None
    s = None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.6)
        s.connect(str(IPC_SOCKET_PATH))
        payload = {"cmd": cmd}
        payload.update(kwargs)
        s.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        data = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk:
                break
        if data:
            return json.loads(data.decode("utf-8"))
    except Exception:
        pass
    finally:
        if s:
            s.close()
    return None


def get_whitelist_entries() -> List[str]:
    engine = get_adblock_engine()
    with engine.lock:
        return sorted(engine.whitelist)


def add_whitelist_entry(domain: str) -> bool:
    domain = domain.strip().lower().strip(".")
    if not domain or "." not in domain:
        return False
    engine = get_adblock_engine()
    with engine.lock:
        engine.whitelist.add(domain)
        engine.blacklist.discard(domain)
        engine.blocked_domains.discard(domain)
        ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
        WHITELIST_FILE.write_text("\n".join(sorted(engine.whitelist)) + "\n", encoding="utf-8")
        if BLACKLIST_FILE.exists():
            BLACKLIST_FILE.write_text("\n".join(sorted(engine.blacklist)) + "\n", encoding="utf-8")
    return True


def remove_whitelist_entry(domain: str) -> bool:
    domain = domain.strip().lower().strip(".")
    engine = get_adblock_engine()
    with engine.lock:
        if domain in engine.whitelist:
            engine.whitelist.remove(domain)
            ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
            WHITELIST_FILE.write_text("\n".join(sorted(engine.whitelist)) + "\n", encoding="utf-8")
            engine._load_local_data()
            return True
    return False


def get_blacklist_entries() -> List[str]:
    engine = get_adblock_engine()
    with engine.lock:
        return sorted(engine.blacklist)


def add_blacklist_entry(domain: str) -> bool:
    domain = domain.strip().lower().strip(".")
    if not domain or "." not in domain:
        return False
    engine = get_adblock_engine()
    with engine.lock:
        engine.blacklist.add(domain)
        engine.whitelist.discard(domain)
        engine.blocked_domains.add(domain)
        ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
        BLACKLIST_FILE.write_text("\n".join(sorted(engine.blacklist)) + "\n", encoding="utf-8")
        if WHITELIST_FILE.exists():
            WHITELIST_FILE.write_text("\n".join(sorted(engine.whitelist)) + "\n", encoding="utf-8")
    return True


def remove_blacklist_entry(domain: str) -> bool:
    domain = domain.strip().lower().strip(".")
    engine = get_adblock_engine()
    with engine.lock:
        if domain in engine.blacklist:
            engine.blacklist.remove(domain)
            ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
            BLACKLIST_FILE.write_text("\n".join(sorted(engine.blacklist)) + "\n", encoding="utf-8")
            engine._load_local_data()
            return True
    return False


# ------------------------------------------------------------------------------
# Dynamic Router DHCP Configuration Instructions Generator
# ------------------------------------------------------------------------------
def get_router_dhcp_guide() -> Dict[str, Any]:
    """Generate dynamic instructions with the box's current LAN IPs for router DHCP setup."""
    from nmb.netd.interfaces import get_ip_addresses, get_default_gateway

    # Detect current network IPs across physical interfaces
    primary_ipv4 = ""
    ipv6_addrs = []
    sys_net = Path("/sys/class/net")
    all_ifaces = [p.name for p in sys_net.glob("*")] if sys_net.exists() else []

    for iface in sorted(all_ifaces):
        if iface == "lo" or iface.startswith(("docker", "veth", "br", "tun", "tap", "wg")):
            continue
        ips = get_ip_addresses(iface)
        for ip in ips:
            if ":" not in ip and not ip.startswith("127."):
                if not primary_ipv4:
                    primary_ipv4 = ip.split("/")[0]
            elif ":" in ip and not ip.startswith("fe80:"):
                ipv6_addrs.append(ip.split("/")[0])

    if not primary_ipv4:
        # Fallback to local hostname resolution
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("1.1.1.1", 80))
            primary_ipv4 = s.getsockname()[0]
            s.close()
        except Exception:
            primary_ipv4 = "192.168.8.218"

    # Detect router gateway IP
    gateway_ip = "192.168.1.1"
    try:
        r = subprocess.run(["ip", "route", "show", "default"], stdout=subprocess.PIPE, text=True, timeout=2.0)
        m = re.search(r"default via ([^\s]+)", r.stdout)
        if m:
            gateway_ip = m.group(1)
    except Exception:
        pass

    steps_hu = [
        f"1. Lépj be a meglévő otthoni/irodai routered admin felületére (általában a böngészőben: http://{gateway_ip}).",
        "2. Keresd meg a 'Hálózat' / 'LAN' / 'DHCP Szerver' vagy 'DNS Beállítások' menüpontot.",
        f"3. Az Elsődleges DNS szerver (Primary DNS Server) mezőben add meg a mérőbox IP címét: {primary_ipv4}",
        "4. A Másodlagos DNS (Secondary DNS) mezőt hagyd üresen vagy állíts be redundanciaként egy szűrt címet (pl. 9.9.9.9), hogy a kliensek mindig a mérőboxot használják.",
        "5. Mentsd el a beállításokat. A router ezután automatikusan kiküldi ezt a DNS címet az összes csatlakozó eszköznek (mobilok, okostévék, PC-k), így a teljes helyi hálózaton megszűnnek a tolakodó reklámok és nyomkövetők!",
        f"Megjegyzés: Ha egyetlen gépen szeretnéd tesztelni, a hálózati kártya IPv4 DNS beállításánál add meg a {primary_ipv4} címet.",
    ]

    steps_en = [
        f"1. Log into your existing home or office router admin panel (usually: http://{gateway_ip}).",
        "2. Navigate to 'Network' / 'LAN' / 'DHCP Server' or 'DNS Settings'.",
        f"3. Change the Primary DNS Server IP address to NetworkMeasureBox: {primary_ipv4}",
        "4. Leave Secondary DNS blank to prevent clients from bypassing the ad-blocker sinkhole.",
        "5. Save settings. Every client device (phones, smart TVs, PCs) will automatically have ads and telemetry blocked network-wide!",
        f"Tip: To test on a single device first, manually set that device's IPv4 DNS to {primary_ipv4}.",
    ]

    return {
        "status": "ok",
        "box_ip": primary_ipv4,
        "ipv6_addrs": ipv6_addrs,
        "router_gateway_ip": gateway_ip,
        "steps_hu": steps_hu,
        "steps_en": steps_en,
    }


# ------------------------------------------------------------------------------
# DNS Server Daemon (Multi-Interface, UDP & TCP, Port 53)
# ------------------------------------------------------------------------------
class AdblockDNSServer:
    """Threaded UDP and TCP DNS Server bound to port 53."""

    def __init__(self, port: int = DNS_PORT):
        self.port = port
        self.running = False
        self.udp_sockets: List[socket.socket] = []
        self.tcp_sockets: List[socket.socket] = []
        self.threads: List[threading.Thread] = []
        self.engine = get_adblock_engine()

    def start(self) -> bool:
        if self.running:
            return True

        self.running = True
        self.udp_sockets = []
        self.tcp_sockets = []

        # Try binding to 0.0.0.0 and [::] first
        bound_any = False
        for family, addr in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
            try:
                # UDP socket
                u_sock = socket.socket(family, socket.SOCK_DGRAM)
                u_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    u_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass
                u_sock.bind((addr, self.port))
                self.udp_sockets.append(u_sock)

                # TCP socket
                t_sock = socket.socket(family, socket.SOCK_STREAM)
                t_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    t_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass
                t_sock.bind((addr, self.port))
                t_sock.listen(32)
                self.tcp_sockets.append(t_sock)

                bound_any = True
                log.info("AdblockDNSServer bound to %s:%d (UDP & TCP)", addr, self.port)
            except OSError as e:
                log.debug("failed binding to wildcard %s:%d: %s", addr, self.port, e)

        # If wildcard binding failed (e.g. dnsmasq bound to specific interface),
        # bind to all available physical interface IP addresses individually
        if not bound_any:
            log.info("Wildcard 0.0.0.0:53 in use; attempting individual IP socket binding...")
            from nmb.netd.interfaces import get_ip_addresses
            sys_net = Path("/sys/class/net")
            all_ifaces = [p.name for p in sys_net.glob("*")] if sys_net.exists() else []
            for iface in sorted(all_ifaces):
                if iface == "lo":
                    continue
                for ip in get_ip_addresses(iface):
                    clean_ip = ip.split("/")[0]
                    if ":" in clean_ip:
                        continue # focus on IPv4 for individual fallback
                    try:
                        u_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        u_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        u_sock.bind((clean_ip, self.port))
                        self.udp_sockets.append(u_sock)

                        t_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        t_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        t_sock.bind((clean_ip, self.port))
                        t_sock.listen(16)
                        self.tcp_sockets.append(t_sock)

                        bound_any = True
                        log.info("AdblockDNSServer bound to specific interface %s (%s:%d)", iface, clean_ip, self.port)
                    except OSError as e:
                        log.warning("failed binding to %s:%d: %s", clean_ip, self.port, e)

        if not bound_any:
            log.error("AdblockDNSServer could not bind to port %d on any interface!", self.port)
            self.running = False
            return False

        # Launch UDP listener threads
        for idx, u_sock in enumerate(self.udp_sockets):
            t = threading.Thread(target=self._udp_worker, args=(u_sock,), daemon=True, name=f"nmb-dns-udp-{idx}")
            t.start()
            self.threads.append(t)

        # Launch TCP listener threads
        for idx, t_sock in enumerate(self.tcp_sockets):
            t = threading.Thread(target=self._tcp_worker, args=(t_sock,), daemon=True, name=f"nmb-dns-tcp-{idx}")
            t.start()
            self.threads.append(t)

        # Launch local UNIX IPC control worker
        t_ipc = threading.Thread(target=self._ipc_worker, daemon=True, name="nmb-adblock-ipc")
        t_ipc.start()
        self.threads.append(t_ipc)

        log.info("AdblockDNSServer successfully started on port %d (%d UDP, %d TCP sockets, IPC enabled)",
                 self.port, len(self.udp_sockets), len(self.tcp_sockets))
        return True

    def stop(self) -> None:
        self.running = False
        try:
            if IPC_SOCKET_PATH.exists():
                IPC_SOCKET_PATH.unlink()
        except Exception:
            pass
        for s in self.udp_sockets:
            try:
                s.close()
            except Exception:
                pass
        for s in self.tcp_sockets:
            try:
                s.close()
            except Exception:
                pass
        self.udp_sockets.clear()
        self.tcp_sockets.clear()
        self.threads.clear()
        log.info("AdblockDNSServer stopped.")

    def _ipc_worker(self) -> None:
        try:
            IPC_SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
            if IPC_SOCKET_PATH.exists():
                IPC_SOCKET_PATH.unlink()
            ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            ipc_sock.bind(str(IPC_SOCKET_PATH))
            try:
                os.chmod(str(IPC_SOCKET_PATH), 0o666)
            except Exception:
                pass
            ipc_sock.listen(16)
            while self.running:
                r, _, _ = select.select([ipc_sock], [], [], 0.5)
                if not r:
                    continue
                conn, _ = ipc_sock.accept()
                threading.Thread(target=self._handle_ipc_conn, args=(conn,), daemon=True).start()
        except Exception as e:
            log.warning("Adblock IPC worker failed: %s", e)

    def _handle_ipc_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(1.5)
            line = conn.recv(4096).decode("utf-8", errors="replace").strip()
            if not line:
                return
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "status":
                resp = self.engine.get_stats()
                resp["is_running"] = True
                resp["guide"] = get_router_dhcp_guide()
                resp["update_status"] = get_gravity_update_status()
            elif cmd == "querylog":
                limit = int(req.get("limit", 50))
                resp = {"status": "ok", "queries": self.engine.get_recent_queries(limit)}
            elif cmd == "toggle":
                en = bool(req.get("enabled", True))
                self.engine.config.enabled = en
                self.engine.config.save()
                resp = {"status": "ok", "enabled": en, "is_running": True}
            elif cmd == "reload":
                self.engine._load_local_data()
                resp = {"status": "ok", "domains": len(self.engine.blocked_domains)}
            else:
                resp = {"status": "error", "message": "unknown command"}
            conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _udp_worker(self, sock: socket.socket) -> None:
        while self.running:
            try:
                r, _, _ = select.select([sock], [], [], 0.5)
                if not r:
                    continue
                data, addr = sock.recvfrom(4096)
                if not data:
                    continue
                # Process DNS query
                resp = self.engine.handle_dns_request(data, addr)
                if resp:
                    sock.sendto(resp, addr)
            except OSError:
                break
            except Exception as e:
                log.debug("UDP worker error: %s", e)

    def _tcp_worker(self, server_sock: socket.socket) -> None:
        while self.running:
            try:
                r, _, _ = select.select([server_sock], [], [], 0.5)
                if not r:
                    continue
                client_sock, client_addr = server_sock.accept()
                client_sock.settimeout(2.5)
                threading.Thread(target=self._handle_tcp_client, args=(client_sock, client_addr), daemon=True).start()
            except OSError:
                break
            except Exception as e:
                log.debug("TCP accept error: %s", e)

    def _handle_tcp_client(self, client_sock: socket.socket, client_addr: Tuple[str, int]) -> None:
        try:
            # Read 2-byte length prefix (RFC 7766)
            len_bytes = client_sock.recv(2)
            if len(len_bytes) < 2:
                return
            length = struct.unpack("!H", len_bytes)[0]
            data = b""
            while len(data) < length:
                chunk = client_sock.recv(length - len(data))
                if not chunk:
                    break
                data += chunk

            if len(data) == length:
                resp = self.engine.handle_dns_request(data, client_addr)
                if resp:
                    resp_with_prefix = struct.pack("!H", len(resp)) + resp
                    client_sock.sendall(resp_with_prefix)
        except Exception:
            pass
        finally:
            client_sock.close()


_adblock_daemon_instance: Optional[AdblockDNSServer] = None
_adblock_daemon_lock = threading.Lock()


def get_adblock_server() -> AdblockDNSServer:
    global _adblock_daemon_instance
    with _adblock_daemon_lock:
        if _adblock_daemon_instance is None:
            _adblock_daemon_instance = AdblockDNSServer()
        return _adblock_daemon_instance


def start_adblock_service() -> bool:
    """Start the adblock DNS sinkhole daemon."""
    server = get_adblock_server()
    return server.start()


def stop_adblock_service() -> None:
    """Stop the adblock DNS sinkhole daemon."""
    server = get_adblock_server()
    server.stop()


def is_adblock_running() -> bool:
    server = get_adblock_server()
    if server.running:
        return True
    # If called from CLI, check if port 53 is actively answering or systemd service is active
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.15)
            # DNS query for test
            s.sendto(b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06google\x03com\x00\x00\x01\x00\x01", ("127.0.0.1", DNS_PORT))
            resp, _ = s.recvfrom(512)
            if resp:
                return True
    except Exception:
        pass

    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", "nmb-adblock"], timeout=1.0)
        return r.returncode == 0
    except Exception:
        return False


def set_adblock_enabled(enabled: bool) -> Dict[str, Any]:
    """Enable or disable adblocking."""
    ipc_data = query_adblock_ipc("toggle", enabled=enabled)
    if ipc_data:
        return ipc_data

    engine = get_adblock_engine()
    engine.config.enabled = enabled
    engine.config.save()

    if enabled:
        if not is_adblock_running():
            start_adblock_service()

    return {
        "status": "ok",
        "enabled": engine.config.enabled,
        "is_running": is_adblock_running(),
    }


def get_live_recent_queries(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve recent queries, querying live daemon via IPC if available."""
    ipc_data = query_adblock_ipc("querylog", limit=limit)
    if ipc_data and "queries" in ipc_data:
        return ipc_data["queries"]
    return get_adblock_engine().get_recent_queries(limit)


def get_full_adblock_status() -> Dict[str, Any]:
    """Compile comprehensive adblock status, metrics, and guide."""
    ipc_data = query_adblock_ipc("status")
    if ipc_data and "total_queries" in ipc_data:
        return ipc_data

    engine = get_adblock_engine()
    stats = engine.get_stats()
    stats["is_running"] = is_adblock_running()
    stats["guide"] = get_router_dhcp_guide()
    stats["update_status"] = get_gravity_update_status()
    return stats


def run_daemon() -> int:
    """Run DNS adblock daemon in foreground for systemd / CLI."""
    import signal

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    log.info("Starting NetworkMeasureBox DNS Adblock Daemon...")
    server = get_adblock_server()
    if not server.start():
        log.error("Failed to start Adblock DNS Server on port %d", server.port)
        return 1

    shutdown_event = threading.Event()

    def _sig_handler(sig, frame):
        log.info("Received termination signal (%d), shutting down DNS Adblock daemon...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        while not shutdown_event.is_set():
            time.sleep(1.0)
    finally:
        server.stop()
        log.info("DNS Adblock daemon exited cleanly.")

    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        res = execute_gravity_update()
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("status") == "ok" else 1)
    else:
        sys.exit(run_daemon())
