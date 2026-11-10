"""Small address helpers shared by the speed engines and the reports."""
from __future__ import annotations

import ipaddress
from typing import Optional, Tuple

# Documentation ranges (RFC 5737, RFC 3849) never appear on a real line; they count as public so that
# tests can use them instead of somebody's real address (Quality Bar point 8).
_DOCUMENTATION = tuple(ipaddress.ip_network(n) for n in
                       ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"))


def global_ip(value: object) -> Optional[str]:
    """The address only when it is a public (globally routable) one, else None.

    A speed test row's client_ip is the address the line had on the internet. A LAN address
    (192.168.x), a CGNAT address (100.64.0.0/10), link-local or loopback is never that, and before
    2026-11-10 several engines stored such addresses (the box's own LAN address for iPerf3) or a
    cached address the test never used.
    """
    if not value:
        return None
    text = str(value).strip().strip("[]")
    if "%" in text:
        text = text.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if addr.is_global or any(addr in net for net in _DOCUMENTATION if net.version == addr.version):
        return str(addr)
    return None


def split_global(value: object) -> Tuple[Optional[str], Optional[str]]:
    """(ipv4, ipv6) from one reported address, keeping it only when it is public."""
    ip = global_ip(value)
    if ip is None:
        return None, None
    return (None, ip) if ":" in ip else (ip, None)


def is_local_ip(value: object) -> bool:
    """A LAN, link-local, ULA or loopback address (a server "on the local network"); CGNAT is not local."""
    if not value:
        return False
    text = str(value).strip().strip("[]").split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    if addr.version == 4 and addr in ipaddress.ip_network("100.64.0.0/10"):
        return False
    if any(addr in net for net in _DOCUMENTATION if net.version == addr.version):
        return False
    return addr.is_private or addr.is_link_local or addr.is_loopback


TRACE_HOST = "www.cloudflare.com"


def lookup_public_ip(source_ip: Optional[str], timeout: float = 6.0) -> Optional[str]:
    """The public address the line has, asked over the same source address (and so the same link and
    IP family) a test used: one HTTPS request to Cloudflare's trace page. None when it fails or the
    answer is not a public address; never a cached or other-family address in its place."""
    import http.client
    import ssl
    if not source_ip:
        return None
    try:
        conn = http.client.HTTPSConnection(TRACE_HOST, 443, timeout=timeout, source_address=(str(source_ip), 0),
                                           context=ssl.create_default_context())
        try:
            conn.request("GET", "/cdn-cgi/trace", headers={"User-Agent": "NetworkMeasureBox"})
            body = conn.getresponse().read(4096).decode("utf-8", "replace")
        finally:
            conn.close()
    except (OSError, http.client.HTTPException, ValueError):
        return None
    for line in body.splitlines():
        if line.startswith("ip="):
            return global_ip(line[3:].strip())
    return None


def client_address_for_test(local_host: Optional[str], remote_host: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(ipv4, ipv6, source) for a test whose own socket went from local_host to remote_host.

    - a server on the local network: the box's own local address, source "local" (the test measured the
      LAN, and that is the address the server saw);
    - a server on the internet and a public source address (no NAT): that address, source "socket";
    - a server on the internet behind NAT: the public address asked over the same source, "lookup";
    - nothing known: (None, None, None).
    """
    if not local_host:
        return None, None, None
    local = str(local_host).strip()
    six = ":" in local
    if remote_host and is_local_ip(remote_host):
        return (None, local, "local") if six else (local, None, "local")
    if global_ip(local):
        return (None, local, "socket") if six else (local, None, "socket")
    public = lookup_public_ip(local)
    if not public:
        return None, None, None
    return (None, public, "lookup") if ":" in public else (public, None, "lookup")
