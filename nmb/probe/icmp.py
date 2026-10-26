"""Native ICMP packet formatting, checksum calculation, and socket handling.

Supports both Linux unprivileged ping sockets (SOCK_DGRAM) and raw sockets (SOCK_RAW).
Pure Python standard library (struct, socket).
"""
from __future__ import annotations

import logging
import os
import socket
import struct
import time
from typing import Optional, Tuple

log = logging.getLogger("nmb.probe.icmp")

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0


def checksum(data: bytes) -> int:
    """Calculate the Internet Checksum (RFC 1071) of a byte sequence."""
    if len(data) % 2 == 1:
        data += b"\x00"

    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        total = (total & 0xFFFF) + (total >> 16)

    return (~total) & 0xFFFF


def build_echo_request(ident: int, seq: int, payload_size: int = 56) -> bytes:
    """Construct an ICMP Echo Request packet.

    Header format:
      0                   1                   2                   3
      0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
     +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
     |     Type      |     Code      |          Checksum             |
     +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
     |           Identifier          |        Sequence Number        |
     +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
     |     Data (High-res timestamp in nanoseconds + padding)        |
    """
    ident = ident & 0xFFFF
    seq = seq & 0xFFFF

    # Payload: 8-byte uint64 nanosecond timestamp + padding
    send_ns = time.time_ns()
    payload = struct.pack("!Q", send_ns)
    if len(payload) < payload_size:
        payload += bytes([i % 256 for i in range(payload_size - len(payload))])

    # Header with dummy checksum 0
    header_dummy = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, 0, ident, seq)
    chk = checksum(header_dummy + payload)

    # Real header with calculated checksum
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, chk, ident, seq)
    return header + payload


def parse_echo_reply(data: bytes, is_raw: bool) -> Optional[Tuple[int, int, int, int]]:
    """Parse received packet and extract (icmp_type, ident, seq, send_ns).

    If is_raw=True, strips IPv4 header (first 20+ bytes) before parsing ICMP.
    """
    offset = 0
    if is_raw:
        if len(data) < 20:
            return None
        # IP header length is lower nibble of first byte in 32-bit words
        ip_hl = (data[0] & 0x0F) * 4
        offset = ip_hl

    if len(data) < offset + 8:
        return None

    icmp_type, icmp_code, _, ident, seq = struct.unpack_from("!BBHHH", data, offset)
    if icmp_type != ICMP_ECHO_REPLY:
        return None

    payload_offset = offset + 8
    send_ns = 0
    if len(data) >= payload_offset + 8:
        send_ns = struct.unpack_from("!Q", data, payload_offset)[0]

    return icmp_type, ident, seq, send_ns


# Linux socket constants (from asm-generic/socket.h and net/socket.h)
SO_PRIORITY = getattr(socket, "SO_PRIORITY", 12)
SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)
SO_BUSY_POLL = getattr(socket, "SO_BUSY_POLL", 46)
SO_BINDTODEVICE = getattr(socket, "SO_BINDTODEVICE", 25)
IP_TOS = getattr(socket, "IP_TOS", 1)


def apply_kernel_socket_tuning(sock: socket.socket, bind_iface: Optional[str] = None) -> None:
    """Apply low-latency, high-precision kernel socket options.

    1. SO_TIMESTAMPNS: Kernel nanosecond packet timestamping for jitter-free RTT
    2. SO_PRIORITY: Set to 6 (TC_PRIO_INTERACTIVE) for kernel QoS priority queueing
    3. IP_TOS: Set to 0xB8 (DSCP 46 / Expedited Forwarding)
    4. SO_RCVBUF: 1MB buffer to prevent skb drops during network traffic spikes
    5. SO_SNDBUF: 256KB send buffer
    6. SO_BUSY_POLL: Low latency kernel busy polling (if supported)
    7. SO_BINDTODEVICE: Direct kernel binding to physical egress interface
    """
    # 1. Nanosecond kernel timestamping (bypasses userspace scheduling delays)
    try:
        sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
        log.debug("Kernel nanosecond socket timestamping (SO_TIMESTAMPNS) enabled")
    except Exception as e:
        log.debug("SO_TIMESTAMPNS not supported: %s", e)

    # 2. Kernel Socket Priority (QoS)
    try:
        sock.setsockopt(socket.SOL_SOCKET, SO_PRIORITY, 6)
    except Exception as e:
        log.debug("SO_PRIORITY not set: %s", e)

    # 3. IP DSCP Expedited Forwarding (TOS)
    try:
        sock.setsockopt(socket.IPPROTO_IP, IP_TOS, 0xB8)
    except Exception as e:
        log.debug("IP_TOS not set: %s", e)

    # 4. Large Socket Buffers (Burst Absorption)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
    except Exception as e:
        log.debug("SO_RCVBUF/SO_SNDBUF adjustment: %s", e)

    # 5. Kernel Busy Poll (Low latency)
    try:
        sock.setsockopt(socket.SOL_SOCKET, SO_BUSY_POLL, 50)
    except Exception as e:
        pass

    # 6. Bind to device if specified
    if bind_iface:
        try:
            sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, bind_iface.encode("utf-8") + b"\x00")
            log.debug("Socket bound directly to kernel device %s", bind_iface)
        except Exception as e:
            log.debug("SO_BINDTODEVICE(%s) failed: %s", bind_iface, e)


def extract_kernel_timestamp_ns(ancdata: list) -> Optional[int]:
    """Extract nanosecond kernel receive timestamp from recvmsg ancdata (SO_TIMESTAMPNS)."""
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if cmsg_level == socket.SOL_SOCKET and cmsg_type == SO_TIMESTAMPNS:
            if len(cmsg_data) >= 16:
                # struct timespec { time_t tv_sec; long tv_nsec; }
                sec, nsec = struct.unpack("qq", cmsg_data[:16])
                return sec * 1_000_000_000 + nsec
    return None


def create_icmp_socket(bind_iface: Optional[str] = None) -> Tuple[socket.socket, bool]:
    """Create ICMP socket with unprivileged SOCK_DGRAM first, falling back to SOCK_RAW.
    Applies deep kernel network optimizations (nanosecond timestamping, QoS, buffers).

    Returns (sock, is_raw_mode).
    """
    # 1. Try unprivileged ICMP socket (Linux ping_group_range)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
        sock.setblocking(False)
        apply_kernel_socket_tuning(sock, bind_iface)
        log.debug("created ICMP SOCK_DGRAM socket (unprivileged, kernel-tuned)")
        return sock, False
    except OSError as e:
        log.debug("SOCK_DGRAM ICMP failed: %s; trying SOCK_RAW", e)

    # 2. Try raw socket (requires CAP_NET_RAW or root)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        sock.setblocking(False)
        apply_kernel_socket_tuning(sock, bind_iface)
        log.debug("created ICMP SOCK_RAW socket (kernel-tuned)")
        return sock, True
    except OSError as e:
        log.error("failed to create ICMP socket: %s", e)
        raise
