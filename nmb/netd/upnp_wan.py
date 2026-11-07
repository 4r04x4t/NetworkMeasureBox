"""Read the gateway's WAN byte counters over UPnP (WANCommonInterfaceConfig)."""
from __future__ import annotations

import http.client
import logging
import socket
import time
import xml.etree.ElementTree as ET
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

from nmb.netd import interfaces

log = logging.getLogger("nmb.netd.upnp_wan")

SERVICE = "urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1"
MAX_XML_BYTES = 256 * 1024
DISCOVERY_CACHE_SEC = 600.0
_cache: Tuple[float, Optional[str]] = (0.0, None)


def _http(url: str, method: str = "GET", body: str = "", headers: Optional[dict] = None) -> bytes:
    parts = urlparse(url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=2.0)
    try:
        conn.request(method, parts.path + (f"?{parts.query}" if parts.query else ""), body, headers or {})
        resp = conn.getresponse()
        if resp.status != 200:
            raise OSError(f"HTTP {resp.status}")
        data = resp.read(MAX_XML_BYTES + 1)
    finally:
        conn.close()
    if len(data) > MAX_XML_BYTES:
        raise ValueError("UPnP response too large")
    return data


def _parse(data: bytes) -> ET.Element:
    # The sender is another LAN device, and these documents have no need for a DTD.
    if b"<!DOCTYPE" in data.upper():
        raise ValueError("UPnP response contains a DTD")
    return ET.fromstring(data)


def control_url_from_description(location: str, data: bytes) -> Optional[str]:
    for node in _parse(data).iter():
        if not node.tag.endswith("service"):
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in node}
        if fields.get("serviceType") == SERVICE and fields.get("controlURL"):
            url = urljoin(location, fields["controlURL"])
            if urlparse(url).hostname == urlparse(location).hostname:
                return url
    return None


def _discover() -> Optional[str]:
    gateway = interfaces.get_default_gateway()
    if not gateway:
        return None
    msg = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
        f"MX: 1\r\nST: {SERVICE}\r\n\r\n"
    ).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.5)
        sock.sendto(msg, ("239.255.255.250", 1900))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            # Only the gateway may describe the WAN; other LAN devices could spoof the reply.
            if addr[0] != gateway:
                continue
            for line in data.decode("latin-1").splitlines():
                if line.lower().startswith("location:"):
                    location = line.split(":", 1)[1].strip()
                    parts = urlparse(location)
                    if parts.scheme == "http" and parts.hostname == gateway:
                        return control_url_from_description(location, _http(location))
    return None


def find_control_url() -> Optional[str]:
    global _cache
    now = time.monotonic()
    if _cache[0] and now - _cache[0] < DISCOVERY_CACHE_SEC:
        return _cache[1]
    url = None
    try:
        url = _discover()
    except (OSError, ValueError, ET.ParseError) as e:
        log.debug("UPnP discovery failed: %s", e)
    _cache = (now, url)
    return url


def _soap(url: str, action: str) -> int:
    body = (
        '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{SERVICE}"/></s:Body></s:Envelope>'
    )
    headers = {"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{SERVICE}#{action}"'}
    for node in _parse(_http(url, "POST", body, headers)).iter():
        if node.tag.rsplit("}", 1)[-1].startswith("NewTotalBytes"):
            return int((node.text or "").strip())
    raise ValueError(f"no counter in {action} response")


def read_wan_bytes(url: str) -> Optional[Tuple[int, int]]:
    """Return (received, sent) WAN bytes, or None when the router does not answer."""
    try:
        return _soap(url, "GetTotalBytesReceived"), _soap(url, "GetTotalBytesSent")
    except (OSError, ValueError, ET.ParseError, http.client.HTTPException) as e:
        log.debug("UPnP counter read failed: %s", e)
        return None
