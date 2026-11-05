"""NetworkMeasureBox OS-Independent DNS Ad-Blocker & Sinkhole Subsystem (Pi-hole Equivalent).

Provides a lightweight, zero-dependency, ultra-fast DNS sinkhole and proxy daemon
capable of running in any network mode:
  - Standalone Mode (Mode C): Listens on port 53 (all interfaces / LAN IP); the user
    points their home router DHCP DNS setting to the box's IP (e.g. 192.168.1.100).
  - Router Mode (Mode A / Mode B): Directly serves DNS or integrates with dnsmasq
    so all LAN and Wi-Fi clients automatically have ads and trackers blocked.

Features:
  - Gravity Manager: Fetches, normalizes, deduplicates StevenBlack, AdAway, Peter Lowe lists.
  - Adlists Management: Custom blocklist URLs with individual enable/disable toggle.
  - Whitelist / Blacklist management with instant in-memory matching.
  - RegEx & Wildcard domain matching for advanced pattern-based blocking/allowing.
  - Local DNS Records (custom.list): Maps LAN hostnames directly to IPs with <0.1ms latency.
  - Fast RFC 1035 / RFC 7766 DNS sinkhole (A -> 0.0.0.0, AAAA -> ::, NODATA for others).
  - Upstream DNS forwarding (Cloudflare 1.1.1.1, Quad9 9.9.9.9, Google 8.8.8.8) with LRU caching.
  - Temporary Disablement / Pause: Pauses blocking for 30s, 5m, 15m, or custom duration.
  - 24-Hour Time-Series Activity Telemetry (10-minute buckets: total, blocked, cached).
  - Query Types (A, AAAA, HTTPS, PTR, TXT, SRV) & Upstream Destination telemetry.
  - Top Clients with Hostname Resolution, Top Blocked & Permitted Domains.
  - Live Query Log (circular ring buffer in RAM) with client IP, domain, QTYPE, and latency.
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
ADLISTS_FILE = ADBLOCK_DIR / "adlists.json"
WHITELIST_FILE = ADBLOCK_DIR / "whitelist.txt"
BLACKLIST_FILE = ADBLOCK_DIR / "blacklist.txt"
REGEX_BLACKLIST_FILE = ADBLOCK_DIR / "regex_blacklist.txt"
REGEX_WHITELIST_FILE = ADBLOCK_DIR / "regex_whitelist.txt"
CUSTOM_DNS_FILE = ADBLOCK_DIR / "custom.list"
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

DEFAULT_ADLISTS = [
    {
        "url": "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
        "name": "StevenBlack Unified Hosts (Adware + Malware)",
        "enabled": True,
        "count": 0,
        "updated_at": None,
    },
    {
        "url": "https://adaway.org/hosts.txt",
        "name": "AdAway Official Mobile Adlist",
        "enabled": True,
        "count": 0,
        "updated_at": None,
    },
    {
        "url": "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=0&mimetype=plaintext",
        "name": "Peter Lowe's Ad & Tracking Server List",
        "enabled": True,
        "count": 0,
        "updated_at": None,
    },
    {
        "url": "https://someonewhocares.org/hosts/zero/hosts",
        "name": "SomeoneWhoCares Zero Hosts",
        "enabled": True,
        "count": 0,
        "updated_at": None,
    },
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
        self.disabled_until: Optional[float] = None
        self.upstreams: List[str] = list(DEFAULT_UPSTREAMS)
        self.dns_port: int = DNS_PORT
        self.cache_ttl_max: int = 300
        self.query_logging: bool = True
        self.max_query_log: int = 2000
        self.blocking_mode: str = "null_ip"  # "null_ip" (0.0.0.0/::) or "nxdomain"
        self.load()

    def load(self) -> None:
        if not CONFIG_FILE.exists():
            self.save()
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            self.enabled = bool(data.get("enabled", True))
            self.disabled_until = data.get("disabled_until")
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
                "disabled_until": self.disabled_until,
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


def build_dns_response_ip(txid: int, qtype: int, question_slice: bytes, ip_str: str, ttl: int = 300) -> bytes:
    """Synthesize an RFC 1035 DNS response with a specific IPv4 or IPv6 address (Pi-hole custom.list)."""
    ip_str = ip_str.strip()
    if ":" in ip_str and qtype == QTYPE_AAAA:
        try:
            ip_bytes = socket.inet_pton(socket.AF_INET6, ip_str)
            header = struct.pack("!HHHHHH", txid, 0x8180, 1, 1, 0, 0)
            answer = b"\xc0\x0c" + struct.pack("!HHIH", QTYPE_AAAA, 1, ttl, 16) + ip_bytes
            return header + question_slice + answer
        except Exception:
            pass
    elif ":" not in ip_str and qtype == QTYPE_A:
        try:
            ip_bytes = socket.inet_aton(ip_str)
            header = struct.pack("!HHHHHH", txid, 0x8180, 1, 1, 0, 0)
            answer = b"\xc0\x0c" + struct.pack("!HHIH", QTYPE_A, 1, ttl, 4) + ip_bytes
            return header + question_slice + answer
        except Exception:
            pass

    # NODATA for unmatched query type (e.g. AAAA requested for IPv4-only local record)
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

        # Temporary Disablement State
        self.disabled_until: Optional[float] = self.config.disabled_until

        # Pi-hole Style Extensions
        self.adlists: List[Dict[str, Any]] = []
        self.custom_dns: Dict[str, str] = {}  # domain -> IP
        self.regex_blacklist: List[Dict[str, Any]] = []  # {"pattern": str, "regex": Pattern, "comment": str}
        self.regex_whitelist: List[Dict[str, Any]] = []

        # 24-Hour Time-Series Buckets (10-minute intervals: timestamp -> {total, blocked, cached, forwarded})
        self.history_buckets: Dict[int, Dict[str, int]] = {}

        # Telemetry & Live Query Log (in RAM)
        self.query_log: deque = deque(maxlen=self.config.max_query_log)
        self.total_queries: int = 0
        self.blocked_queries: int = 0
        self.cached_queries: int = 0
        self.top_blocked: Counter = Counter()
        self.top_queried: Counter = Counter()
        self.top_clients: Counter = Counter()
        self.client_queries: Counter = Counter()
        self.client_blocked: Counter = Counter()
        self.qtype_counts: Counter = Counter()
        self.upstream_counts: Counter = Counter()
        self.hostname_cache: Dict[str, str] = {}
        self.last_gravity_update: Optional[float] = None
        self.last_update_status: str = "never"

        # Upstream Response Cache: key=(domain, qtype) -> (response_bytes, expire_time)
        self.cache: Dict[Tuple[str, int], Tuple[bytes, float]] = {}
        self.cache_lock = threading.Lock()

        self._load_local_data()

    def _load_local_data(self) -> None:
        """Load whitelist, blacklist, regex rules, adlists, custom local DNS, and gravity list from disk."""
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

            # 3. Adlists (Gravity Sources)
            self.adlists = []
            if ADLISTS_FILE.exists():
                try:
                    self.adlists = json.loads(ADLISTS_FILE.read_text(encoding="utf-8"))
                except Exception as e:
                    log.warning("error reading adlists.json: %s", e)
            if not self.adlists:
                # Migrate from sources.txt or load defaults
                migrated = []
                if SOURCES_FILE.exists():
                    for line in SOURCES_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            name = line.split("/")[-1] or "Custom Blocklist"
                            migrated.append({"url": line, "name": name, "enabled": True, "count": 0, "updated_at": None})
                if not migrated:
                    migrated = list(DEFAULT_ADLISTS)
                self.adlists = migrated
                try:
                    ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
                    ADLISTS_FILE.write_text(json.dumps(self.adlists, indent=2), encoding="utf-8")
                except Exception:
                    pass

            # 4. Custom Local DNS Records (custom.list)
            self.custom_dns = {}
            if CUSTOM_DNS_FILE.exists():
                for line in CUSTOM_DNS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[0].strip()
                            dom = parts[1].strip().lower().strip(".")
                            self.custom_dns[dom] = ip

            # 5. Regex Blacklist & Whitelist
            self.regex_blacklist = []
            if REGEX_BLACKLIST_FILE.exists():
                for line in REGEX_BLACKLIST_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split("#", 1)
                        pat = parts[0].strip()
                        comm = parts[1].strip() if len(parts) > 1 else ""
                        try:
                            rgx = re.compile(pat, re.IGNORECASE)
                            self.regex_blacklist.append({"pattern": pat, "regex": rgx, "comment": comm})
                        except re.error as e:
                            log.warning("invalid regex in blacklist: %s (%s)", pat, e)

            self.regex_whitelist = []
            if REGEX_WHITELIST_FILE.exists():
                for line in REGEX_WHITELIST_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split("#", 1)
                        pat = parts[0].strip()
                        comm = parts[1].strip() if len(parts) > 1 else ""
                        try:
                            rgx = re.compile(pat, re.IGNORECASE)
                            self.regex_whitelist.append({"pattern": pat, "regex": rgx, "comment": comm})
                        except re.error as e:
                            log.warning("invalid regex in whitelist: %s (%s)", pat, e)

            # 6. Gravity Blocklist
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
            log.info("AdblockEngine loaded: %d gravity domains, %d whitelist, %d blacklist, %d regex, %d local DNS",
                     len(self.blocked_domains), len(self.whitelist), len(self.blacklist),
                     len(self.regex_blacklist) + len(self.regex_whitelist), len(self.custom_dns))

    def is_blocking_active(self) -> bool:
        """Check whether DNS ad-blocking is currently active or temporarily paused."""
        if not self.config.enabled:
            return False
        if self.disabled_until is not None:
            if time.time() < self.disabled_until:
                return False
            else:
                self.disabled_until = None
                self.config.disabled_until = None
                self.config.save()
        return True

    def disable_temporarily(self, duration_seconds: int = 0) -> Dict[str, Any]:
        """Disable ad-blocking for a specified duration (0 = indefinite pause)."""
        with self.lock:
            if duration_seconds > 0:
                self.disabled_until = time.time() + duration_seconds
                self.config.disabled_until = self.disabled_until
            else:
                self.config.enabled = False
                self.disabled_until = None
                self.config.disabled_until = None
            self.config.save()
        return {
            "status": "ok",
            "enabled": self.is_blocking_active(),
            "disabled_until": self.disabled_until,
            "seconds_left": duration_seconds,
        }

    def enable_blocking(self) -> Dict[str, Any]:
        """Re-enable ad-blocking immediately."""
        with self.lock:
            self.config.enabled = True
            self.disabled_until = None
            self.config.disabled_until = None
            self.config.save()
        return {
            "status": "ok",
            "enabled": True,
            "disabled_until": None,
            "seconds_left": 0,
        }

    def is_domain_blocked(self, domain: str) -> Tuple[bool, str]:
        """Check if domain should be sinkholed according to Pi-hole rules.

        Evaluation order:
          1. Exact & Subdomain Whitelist
          2. Regex Whitelist
          3. Exact & Subdomain Blacklist
          4. Regex Blacklist
          5. Gravity Adlists
        """
        domain = domain.strip(".").lower()
        if not domain:
            return False, "empty"

        # 1. Exact Whitelist & Parent Whitelist
        if domain in self.whitelist:
            return False, "whitelisted"
        parts = domain.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.whitelist:
                return False, "whitelisted_parent"

        # 2. Regex Whitelist
        for item in self.regex_whitelist:
            rgx = item.get("regex")
            if rgx and rgx.search(domain):
                return False, "regex_whitelist"

        # 3. Exact Blacklist & Parent Blacklist
        if domain in self.blacklist:
            return True, "blacklist"
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.blacklist:
                return True, "blacklist_parent"

        # 4. Regex Blacklist
        for item in self.regex_blacklist:
            rgx = item.get("regex")
            if rgx and rgx.search(domain):
                return True, "regex_blacklist"

        # 5. Gravity Blocklist (exact & parent subdomains)
        if domain in self.blocked_domains:
            return True, "gravity"
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self.blocked_domains:
                return True, "gravity_parent"

        return False, "permitted"

    def resolve_hostname(self, ip: str) -> str:
        """Resolve client hostname via reverse DNS, custom DNS, /etc/hosts, or DHCP leases."""
        if not ip or ip == "127.0.0.1" or ip == "::1":
            return "localhost"
        if ip in self.hostname_cache:
            return self.hostname_cache[ip]

        # Check custom DNS reverse match
        for dom, target_ip in self.custom_dns.items():
            if target_ip == ip:
                self.hostname_cache[ip] = dom
                return dom

        # Check /etc/hosts
        try:
            hosts_path = Path("/etc/hosts")
            if hosts_path.exists():
                for line in hosts_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[0] == ip:
                            self.hostname_cache[ip] = parts[1]
                            return parts[1]
        except Exception:
            pass

        # Check dnsmasq.leases if present
        for lease_path in (Path("/var/lib/misc/dnsmasq.leases"), Path("/tmp/dnsmasq.leases")):
            try:
                if lease_path.exists():
                    for line in lease_path.read_text(encoding="utf-8", errors="replace").splitlines():
                        parts = line.split()
                        if len(parts) >= 4 and parts[2] == ip and parts[3] != "*":
                            self.hostname_cache[ip] = parts[3]
                            return parts[3]
            except Exception:
                pass

        return ip

    def record_query(
        self,
        client_ip: str,
        domain: str,
        qtype_num: int,
        status: str,
        reason: str,
        latency_ms: float,
        upstream: str = "",
    ) -> None:
        """Record query telemetry into RAM buffer and 24h time-series buckets."""
        qtype_str = QTYPE_NAMES.get(qtype_num, str(qtype_num))
        now = time.time()
        time_str = datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S")

        entry = {
            "id": self.total_queries + 1,
            "timestamp": now,
            "time_str": time_str,
            "client_ip": client_ip,
            "client_name": self.resolve_hostname(client_ip),
            "domain": domain,
            "type": qtype_str,
            "status": status,
            "reason": reason,
            "upstream": upstream,
            "latency_ms": round(latency_ms, 2),
        }

        with self.lock:
            self.total_queries += 1
            if status == "BLOCKED":
                self.blocked_queries += 1
                self.top_blocked[domain] += 1
                self.client_blocked[client_ip] += 1
            elif status == "CACHED":
                self.cached_queries += 1

            self.top_queried[domain] += 1
            self.top_clients[client_ip] += 1
            self.client_queries[client_ip] += 1
            self.qtype_counts[qtype_str] += 1
            if upstream:
                self.upstream_counts[upstream] += 1

            # 10-minute time bucket for 24h activity time-series chart
            bucket = int(now // 600) * 600
            b = self.history_buckets.setdefault(bucket, {"total": 0, "blocked": 0, "cached": 0, "forwarded": 0})
            b["total"] += 1
            if status == "BLOCKED":
                b["blocked"] += 1
            elif status == "CACHED":
                b["cached"] += 1
            else:
                b["forwarded"] += 1

            # Prune buckets older than 24 hours
            cutoff = now - 86400
            for old_b in [k for k in self.history_buckets if k < cutoff]:
                del self.history_buckets[old_b]

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
            if len(self.cache) > 5000:
                self.cache.clear()
            self.cache[(domain, qtype)] = (resp_bytes, now + eff_ttl)

    def forward_upstream(self, query_packet: bytes) -> Tuple[Optional[bytes], str]:
        """Forward DNS query to upstream DNS servers with failover.

        Returns: (response_bytes, answering_upstream_ip)
        """
        for upstream in self.config.upstreams:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1.5)
                s.sendto(query_packet, (upstream, DNS_PORT))
                resp, _ = s.recvfrom(4096)
                if resp:
                    return resp, upstream
            except Exception:
                continue
            finally:
                if s:
                    s.close()
        return None, ""

    def handle_dns_request(self, data: bytes, client_addr: Tuple[str, int]) -> bytes:
        """Process an incoming DNS packet from a client with full Pi-hole pipeline."""
        start_t = time.perf_counter()
        client_ip = client_addr[0]

        parsed = parse_dns_query(data)
        if not parsed:
            # Bad or unparseable query, drop
            return b""

        txid, domain, qtype, qclass, question_slice = parsed

        # 1. Check Local DNS Records (custom.list) first
        if domain in self.custom_dns:
            target_ip = self.custom_dns[domain]
            resp = build_dns_response_ip(txid, qtype, question_slice, target_ip)
            duration = (time.perf_counter() - start_t) * 1000.0
            self.record_query(client_ip, domain, qtype, "ALLOWED", "local_dns", duration, upstream="local_dns")
            return resp

        # 2. Check if ad-blocker is temporarily paused or globally disabled
        blocking_active = self.is_blocking_active()
        if not blocking_active:
            upstream_resp, upstream_ip = self.forward_upstream(data)
            duration = (time.perf_counter() - start_t) * 1000.0
            reason = "temp_disabled" if (self.disabled_until and time.time() < self.disabled_until) else "disabled"
            self.record_query(client_ip, domain, qtype, "ALLOWED", reason, duration, upstream=upstream_ip or "upstream")
            return upstream_resp or b""

        # 3. Check Blocklists (Gravity, Blacklist, RegEx)
        is_blocked, reason = self.is_domain_blocked(domain)
        if is_blocked:
            resp = build_sinkhole_response(txid, qtype, question_slice, nxdomain=(self.config.blocking_mode == "nxdomain"))
            duration = (time.perf_counter() - start_t) * 1000.0
            self.record_query(client_ip, domain, qtype, "BLOCKED", reason, duration, upstream="blocked")
            return resp

        # 4. Check in-memory DNS cache
        cached = self.get_cached_response(domain, qtype, txid)
        if cached:
            duration = (time.perf_counter() - start_t) * 1000.0
            self.record_query(client_ip, domain, qtype, "CACHED", "cache", duration, upstream="cache")
            return cached

        # 5. Forward permitted query to Upstream DNS
        upstream_resp, upstream_ip = self.forward_upstream(data)
        duration = (time.perf_counter() - start_t) * 1000.0

        if upstream_resp:
            self.store_cache_response(domain, qtype, upstream_resp, ttl=120)
            self.record_query(client_ip, domain, qtype, "ALLOWED", "upstream", duration, upstream=upstream_ip or "upstream")
            return upstream_resp
        else:
            self.record_query(client_ip, domain, qtype, "FAILED", "upstream_timeout", duration, upstream="timeout")
            return b""

    def get_timeline(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Return 10-minute interval activity data over the past 24 hours (144 data points)."""
        now = time.time()
        current_bucket = int(now // 600) * 600
        total_slots = int(hours * 6)  # 144 slots for 24h
        start_bucket = current_bucket - (total_slots - 1) * 600

        timeline = []
        with self.lock:
            for i in range(total_slots):
                ts = start_bucket + i * 600
                b = self.history_buckets.get(ts, {"total": 0, "blocked": 0, "cached": 0, "forwarded": 0})
                t_dt = datetime.datetime.fromtimestamp(ts)
                timeline.append({
                    "timestamp": ts,
                    "time_str": t_dt.strftime("%H:%M"),
                    "total": b["total"],
                    "blocked": b["blocked"],
                    "cached": b["cached"],
                    "forwarded": b["forwarded"],
                })
        return timeline

    def get_top_clients(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Compile top client devices with reverse hostname resolution and block statistics."""
        with self.lock:
            result = []
            for ip, total in self.client_queries.most_common(limit):
                blk = self.client_blocked.get(ip, 0)
                pct = round((blk / total) * 100.0, 1) if total > 0 else 0.0
                result.append({
                    "ip": ip,
                    "hostname": self.resolve_hostname(ip),
                    "total": total,
                    "blocked": blk,
                    "blocked_pct": pct,
                })
            return result

    def get_stats(self) -> Dict[str, Any]:
        """Compile Pi-hole style dashboard telemetry statistics."""
        with self.lock:
            pct = 0.0
            if self.total_queries > 0:
                pct = round((self.blocked_queries / self.total_queries) * 100.0, 1)

            now = time.time()
            disabled_left = 0
            if self.disabled_until and self.disabled_until > now:
                disabled_left = int(self.disabled_until - now)

            top_blocked_list = [{"domain": d, "count": c} for d, c in self.top_blocked.most_common(10)]
            top_queried_list = [{"domain": d, "count": c} for d, c in self.top_queried.most_common(10)]
            top_clients_list = self.get_top_clients(10)

            # Ensure common query types exist in dictionary
            qtypes = dict(self.qtype_counts)
            for k in ("A", "AAAA", "HTTPS", "PTR", "TXT"):
                if k not in qtypes:
                    qtypes[k] = 0

            # Ensure upstream distribution exists
            up_counts = dict(self.upstream_counts)
            if "cache" not in up_counts:
                up_counts["cache"] = self.cached_queries
            if "blocked" not in up_counts:
                up_counts["blocked"] = self.blocked_queries

            return {
                "enabled": self.is_blocking_active(),
                "config_enabled": self.config.enabled,
                "disabled_until": self.disabled_until,
                "disabled_seconds_left": disabled_left,
                "domains_in_blocklist": len(self.blocked_domains),
                "total_queries": self.total_queries,
                "blocked_queries": self.blocked_queries,
                "cached_queries": self.cached_queries,
                "blocked_percentage": pct,
                "whitelist_count": len(self.whitelist),
                "blacklist_count": len(self.blacklist),
                "regex_blacklist_count": len(self.regex_blacklist),
                "regex_whitelist_count": len(self.regex_whitelist),
                "custom_dns_count": len(self.custom_dns),
                "adlists_count": len(self.adlists),
                "last_gravity_update": self.last_gravity_update,
                "last_gravity_update_iso": datetime.datetime.fromtimestamp(self.last_gravity_update).isoformat() if self.last_gravity_update else None,
                "last_update_status": self.last_update_status,
                "top_blocked_domains": top_blocked_list,
                "top_queried_domains": top_queried_list,
                "top_clients": top_clients_list,
                "query_types": qtypes,
                "upstream_destinations": up_counts,
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

    engine = get_adblock_engine()
    active_sources: List[Dict[str, Any]] = []

    if custom_sources:
        for s in custom_sources:
            active_sources.append({"url": s, "name": s.split("/")[-1] or "Source", "enabled": True})
    else:
        with engine.lock:
            for item in engine.adlists:
                if item.get("enabled", True):
                    active_sources.append(item)

    if not active_sources:
        for url in DEFAULT_SOURCES:
            active_sources.append({"url": url, "name": url.split("/")[-1], "enabled": True})

    collected_domains: Set[str] = set(SEED_BLOCKED_DOMAINS)
    output_lines = [f"=== Updating Adblock Gravity ({len(active_sources)} active sources) ==="]
    success_sources = 0

    domain_regex = re.compile(r"^(?:(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+)?([a-zA-Z0-9_\-\.]+)(?:\s+#.*)?$")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NetworkMeasureBox-AdBlock/2.0)"}

    for src in active_sources:
        url = src.get("url", "")
        name = src.get("name", url)
        output_lines.append(f"Downloading [{name}] from: {url}")
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
                src["count"] = count
                src["updated_at"] = datetime.datetime.now().isoformat()
                output_lines.append(f"  -> Extracted {count:,} domains.")
                success_sources += 1
        except Exception as e:
            output_lines.append(f"  -> Failed to fetch source: {e}")

    # Save updated counts back to adlists.json
    try:
        with engine.lock:
            _save_adlists(engine.adlists)
    except Exception:
        pass

    # Remove whitelisted domains
    whitelist_count = 0
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
        "sources_checked": len(active_sources),
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
        s.settimeout(0.8)
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
    query_adblock_ipc("reload")
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
            query_adblock_ipc("reload")
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
    query_adblock_ipc("reload")
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
            query_adblock_ipc("reload")
            return True
    return False


# ------------------------------------------------------------------------------
# Adlists (Gravity Sources) Management
# ------------------------------------------------------------------------------
def _save_adlists(adlists: List[Dict[str, Any]]) -> None:
    try:
        ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
        ADLISTS_FILE.write_text(json.dumps(adlists, indent=2), encoding="utf-8")
        enabled_urls = [it["url"] for it in adlists if it.get("enabled", True)]
        SOURCES_FILE.write_text("\n".join(enabled_urls) + "\n", encoding="utf-8")
    except Exception as e:
        log.warning("failed to save adlists: %s", e)


def get_adlists() -> List[Dict[str, Any]]:
    ipc_res = query_adblock_ipc("adlists")
    if ipc_res and "adlists" in ipc_res:
        return ipc_res["adlists"]
    engine = get_adblock_engine()
    with engine.lock:
        return list(engine.adlists)


def add_adlist(url: str, name: str = "") -> bool:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False
    engine = get_adblock_engine()
    with engine.lock:
        for item in engine.adlists:
            if item.get("url") == url:
                return True
        engine.adlists.append({
            "url": url,
            "name": name.strip() or url.split("/")[-1] or "Custom Blocklist",
            "enabled": True,
            "count": 0,
            "updated_at": None,
        })
        _save_adlists(engine.adlists)
    query_adblock_ipc("reload")
    return True


def remove_adlist(url: str) -> bool:
    url = url.strip()
    engine = get_adblock_engine()
    with engine.lock:
        orig_len = len(engine.adlists)
        engine.adlists = [it for it in engine.adlists if it.get("url") != url]
        if len(engine.adlists) != orig_len:
            _save_adlists(engine.adlists)
            query_adblock_ipc("reload")
            return True
    return False


def toggle_adlist(url: str, enabled: bool) -> bool:
    url = url.strip()
    engine = get_adblock_engine()
    with engine.lock:
        for item in engine.adlists:
            if item.get("url") == url:
                item["enabled"] = enabled
                _save_adlists(engine.adlists)
                query_adblock_ipc("reload")
                return True
    return False


# ------------------------------------------------------------------------------
# Local DNS Records (Pi-hole custom.list)
# ------------------------------------------------------------------------------
def _save_custom_dns(records: Dict[str, str]) -> None:
    try:
        ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
        lines = [f"{ip} {dom}" for dom, ip in sorted(records.items())]
        CUSTOM_DNS_FILE.write_text("# NetworkMeasureBox Local DNS Records (Pi-hole custom.list)\n" + "\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.warning("failed to save custom.list: %s", e)


def get_local_dns_records() -> List[Dict[str, str]]:
    ipc_res = query_adblock_ipc("localdns")
    if ipc_res and "records" in ipc_res:
        return ipc_res["records"]
    engine = get_adblock_engine()
    with engine.lock:
        return [{"domain": d, "ip": ip} for d, ip in sorted(engine.custom_dns.items())]


def add_local_dns_record(domain: str, ip: str) -> bool:
    domain = domain.strip().lower().strip(".")
    ip = ip.strip()
    if not domain or not ip:
        return False
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False

    engine = get_adblock_engine()
    with engine.lock:
        engine.custom_dns[domain] = ip
        _save_custom_dns(engine.custom_dns)
    query_adblock_ipc("reload")
    return True


def remove_local_dns_record(domain: str) -> bool:
    domain = domain.strip().lower().strip(".")
    engine = get_adblock_engine()
    with engine.lock:
        if domain in engine.custom_dns:
            del engine.custom_dns[domain]
            _save_custom_dns(engine.custom_dns)
            query_adblock_ipc("reload")
            return True
    return False


# ------------------------------------------------------------------------------
# RegEx & Wildcard Domain Filtering
# ------------------------------------------------------------------------------
def _save_regex_file(file_path: Path, items: List[Dict[str, Any]]) -> None:
    try:
        ADBLOCK_DIR.mkdir(parents=True, exist_ok=True)
        lines = []
        for it in items:
            comm = f" # {it['comment']}" if it.get("comment") else ""
            lines.append(f"{it['pattern']}{comm}")
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.warning("failed to save regex file %s: %s", file_path, e)


def get_regex_filters() -> Dict[str, List[Dict[str, Any]]]:
    ipc_res = query_adblock_ipc("regex")
    if ipc_res and "regex" in ipc_res:
        return ipc_res["regex"]
    engine = get_adblock_engine()
    with engine.lock:
        return {
            "blacklist": [{"pattern": it["pattern"], "comment": it.get("comment", "")} for it in engine.regex_blacklist],
            "whitelist": [{"pattern": it["pattern"], "comment": it.get("comment", "")} for it in engine.regex_whitelist],
        }


def add_regex_filter(pattern: str, kind: str = "black", comment: str = "") -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return False

    engine = get_adblock_engine()
    with engine.lock:
        target_list = engine.regex_blacklist if kind == "black" else engine.regex_whitelist
        target_file = REGEX_BLACKLIST_FILE if kind == "black" else REGEX_WHITELIST_FILE
        for it in target_list:
            if it["pattern"] == pattern:
                return True
        target_list.append({"pattern": pattern, "regex": compiled, "comment": comment})
        _save_regex_file(target_file, target_list)
    query_adblock_ipc("reload")
    return True


def remove_regex_filter(pattern: str, kind: str = "black") -> bool:
    pattern = pattern.strip()
    engine = get_adblock_engine()
    with engine.lock:
        target_list = engine.regex_blacklist if kind == "black" else engine.regex_whitelist
        target_file = REGEX_BLACKLIST_FILE if kind == "black" else REGEX_WHITELIST_FILE
        orig_len = len(target_list)
        new_list = [it for it in target_list if it["pattern"] != pattern]
        if len(new_list) != orig_len:
            if kind == "black":
                engine.regex_blacklist = new_list
            else:
                engine.regex_whitelist = new_list
            _save_regex_file(target_file, new_list)
            query_adblock_ipc("reload")
            return True
    return False


# ------------------------------------------------------------------------------
# Dynamic Router DHCP Configuration Instructions Generator
# ------------------------------------------------------------------------------
def get_router_dhcp_guide() -> Dict[str, Any]:
    """Generate dynamic instructions with the box's current LAN IPs for router DHCP setup."""
    from nmb.netd.interfaces import get_ip_addresses, get_default_gateway

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
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("1.1.1.1", 80))
            primary_ipv4 = s.getsockname()[0]
            s.close()
        except Exception:
            primary_ipv4 = "192.168.1.100"

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

        # Fallback to individual interface IPs
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
                        continue
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
            conn.settimeout(2.0)
            line = conn.recv(8192).decode("utf-8", errors="replace").strip()
            if not line:
                return
            req = json.loads(line)
            cmd = req.get("cmd")

            if cmd == "status":
                resp = self.engine.get_stats()
                resp["is_running"] = True
                resp["guide"] = get_router_dhcp_guide()
                resp["update_status"] = get_gravity_update_status()

            elif cmd == "charts":
                resp = {
                    "status": "ok",
                    "timeline": self.engine.get_timeline(),
                    "query_types": dict(self.engine.qtype_counts),
                    "upstreams": dict(self.engine.upstream_counts),
                    "clients": self.engine.get_top_clients(10),
                }

            elif cmd == "querylog":
                limit = int(req.get("limit", 50))
                resp = {"status": "ok", "queries": self.engine.get_recent_queries(limit)}

            elif cmd == "toggle":
                en = bool(req.get("enabled", True))
                if en:
                    resp = self.engine.enable_blocking()
                else:
                    resp = self.engine.disable_temporarily(0)

            elif cmd == "disable_temp":
                dur = int(req.get("duration", 0))
                resp = self.engine.disable_temporarily(dur)

            elif cmd == "enable":
                resp = self.engine.enable_blocking()

            elif cmd == "adlists":
                resp = {"status": "ok", "adlists": get_adlists()}

            elif cmd == "adlist_add":
                url = req.get("url", "").strip()
                name = req.get("name", "")
                ok = add_adlist(url, name)
                resp = {"status": "ok" if ok else "error"}

            elif cmd == "adlist_remove":
                url = req.get("url", "").strip()
                ok = remove_adlist(url)
                resp = {"status": "ok" if ok else "error"}

            elif cmd == "adlist_toggle":
                url = req.get("url", "").strip()
                en = bool(req.get("enabled", True))
                ok = toggle_adlist(url, en)
                resp = {"status": "ok" if ok else "error"}

            elif cmd == "localdns":
                resp = {"status": "ok", "records": get_local_dns_records()}

            elif cmd == "localdns_add":
                dom = req.get("domain", "")
                ip = req.get("ip", "")
                ok = add_local_dns_record(dom, ip)
                resp = {"status": "ok" if ok else "error"}

            elif cmd == "localdns_remove":
                dom = req.get("domain", "")
                ok = remove_local_dns_record(dom)
                resp = {"status": "ok" if ok else "error"}

            elif cmd == "regex":
                resp = {"status": "ok", "regex": get_regex_filters()}

            elif cmd == "regex_add":
                pattern = req.get("pattern", "")
                kind = req.get("kind", "black")
                comment = req.get("comment", "")
                ok = add_regex_filter(pattern, kind, comment)
                resp = {"status": "ok" if ok else "error"}

            elif cmd == "regex_remove":
                pattern = req.get("pattern", "")
                kind = req.get("kind", "black")
                ok = remove_regex_filter(pattern, kind)
                resp = {"status": "ok" if ok else "error"}

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
    server = get_adblock_server()
    return server.start()


def stop_adblock_service() -> None:
    server = get_adblock_server()
    server.stop()


def is_adblock_running() -> bool:
    server = get_adblock_server()
    if server.running:
        return True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.15)
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


def set_adblock_enabled(enabled: bool, *args, **kwargs) -> Dict[str, Any]:
    """Enable or disable adblocking (with backward-compatible signature)."""
    if enabled:
        return enable_adblock()
    else:
        return disable_adblock_temporarily(0)


def disable_adblock_temporarily(duration: int = 0) -> Dict[str, Any]:
    """Pause adblocking for duration seconds (0 = indefinite)."""
    ipc_data = query_adblock_ipc("disable_temp", duration=duration)
    if ipc_data:
        return ipc_data
    engine = get_adblock_engine()
    return engine.disable_temporarily(duration)


def enable_adblock() -> Dict[str, Any]:
    """Resume adblocking."""
    ipc_data = query_adblock_ipc("enable")
    if ipc_data:
        return ipc_data
    engine = get_adblock_engine()
    res = engine.enable_blocking()
    if not is_adblock_running():
        start_adblock_service()
    res["is_running"] = is_adblock_running()
    return res


def get_live_recent_queries(limit: int = 50) -> List[Dict[str, Any]]:
    ipc_data = query_adblock_ipc("querylog", limit=limit)
    if ipc_data and "queries" in ipc_data:
        return ipc_data["queries"]
    return get_adblock_engine().get_recent_queries(limit)


def get_full_adblock_status() -> Dict[str, Any]:
    ipc_data = query_adblock_ipc("status")
    if ipc_data and "total_queries" in ipc_data:
        return ipc_data

    engine = get_adblock_engine()
    stats = engine.get_stats()
    stats["is_running"] = is_adblock_running()
    stats["guide"] = get_router_dhcp_guide()
    stats["update_status"] = get_gravity_update_status()
    return stats


def get_charts_telemetry() -> Dict[str, Any]:
    """Compile 24h timeline, query types, upstream destinations, and top clients."""
    ipc_data = query_adblock_ipc("charts")
    if ipc_data and "timeline" in ipc_data:
        return ipc_data

    engine = get_adblock_engine()
    return {
        "status": "ok",
        "timeline": engine.get_timeline(),
        "query_types": dict(engine.qtype_counts),
        "upstreams": dict(engine.upstream_counts),
        "clients": engine.get_top_clients(10),
    }


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
