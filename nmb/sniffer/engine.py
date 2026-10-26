"""High-performance network packet sniffer and flow inspector.

Captures and dissects raw frames via AF_PACKET (pure Python standard library).
Extracts protocol metrics, Top Talkers, DNS queries, TCP anomalies, and PCAP streams.
"""
from __future__ import annotations

import collections
import io
import logging
import socket
import struct
import threading
import time
from dataclasses import asdict, dataclass
from typing import Deque, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.sniffer")

PORT_SERVICES = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    67: "DHCP-Server",
    68: "DHCP-Client",
    80: "HTTP",
    123: "NTP",
    443: "HTTPS",
    853: "DNS-over-TLS",
    1883: "MQTT",
    1900: "SSDP",
    5060: "SIP",
    5353: "mDNS",
    8080: "HTTP-Proxy",
    8443: "HTTPS-Alt",
}


@dataclass
class PacketRecord:
    id: int
    ts: float
    time_str: str
    iface: str
    proto: str
    src_ip: str
    dst_ip: str
    src_port: Optional[int]
    dst_port: Optional[int]
    length: int
    flags: str
    summary: str


class SnifferEngine:
    """Multi-threaded AF_PACKET raw frame sniffer and flow analyzer."""

    def __init__(self, default_iface: str = "eth0", max_packets: int = 250):
        from nmb.common.memory import is_low_memory_system
        if is_low_memory_system():
            max_packets = min(max_packets, 100)
        self.default_iface = default_iface
        self.max_packets = max_packets
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._packet_counter = 0

        # Ring buffers & telemetry stats
        self.recent_packets: Deque[PacketRecord] = collections.deque(maxlen=max_packets)
        self.recent_dns: Deque[dict] = collections.deque(maxlen=100)
        self.proto_counts: collections.Counter = collections.Counter()
        self.proto_bytes: collections.Counter = collections.Counter()
        self.top_sources: collections.Counter = collections.Counter()
        self.top_destinations: collections.Counter = collections.Counter()
        self.top_ports: collections.Counter = collections.Counter()

        # Anomaly counters
        self.tcp_syn_count = 0
        self.tcp_rst_count = 0
        self.tcp_retrans_hints = 0

        # PCAP in-memory ring buffer (rolling last 500 frames for download)
        self._pcap_frames: Deque[Tuple[float, bytes]] = collections.deque(maxlen=500)
        self.active_iface = default_iface

    def start(self, iface: Optional[str] = None) -> bool:
        with self._lock:
            if self.running:
                return True
            self.active_iface = iface or self.default_iface
            self._stop_event.clear()
            self.running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="nmb-sniffer")
            self._thread.start()
            log.info("packet sniffer started on interface: %s", self.active_iface)
            return True

    def stop(self) -> None:
        with self._lock:
            if not self.running:
                return
            self._stop_event.set()
            self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        log.info("packet sniffer stopped")

    def clear(self) -> None:
        with self._lock:
            self.recent_packets.clear()
            self.recent_dns.clear()
            self.proto_counts.clear()
            self.proto_bytes.clear()
            self.top_sources.clear()
            self.top_destinations.clear()
            self.top_ports.clear()
            self.tcp_syn_count = 0
            self.tcp_rst_count = 0
            self._pcap_frames.clear()
            self._packet_counter = 0
        from nmb.common.memory import trim_process_memory
        trim_process_memory()
        log.info("packet sniffer telemetry cleared")

    def _capture_loop(self) -> None:
        sock: Optional[socket.socket] = None
        try:
            # ETH_P_ALL = 0x0003
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
            sock.settimeout(0.5)
            if self.active_iface and self.active_iface != "any":
                try:
                    sock.bind((self.active_iface, 0))
                except Exception as e:
                    log.warning("could not bind AF_PACKET to %s: %s; capturing on any interface", self.active_iface, e)
        except Exception as e:
            log.error("failed to open raw AF_PACKET socket (CAP_NET_RAW required): %s", e)
            self.running = False
            return

        while not self._stop_event.is_set():
            try:
                raw_pkt, sa = sock.recvfrom(65535)
                recv_time = time.time()
                iface_name = sa[0] if sa and len(sa) > 0 else self.active_iface
                self._process_raw_frame(recv_time, iface_name, raw_pkt)
            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    log.debug("sniffer recv exception: %s", e)
                break

        if sock:
            try:
                sock.close()
            except Exception:
                pass
        self.running = False

    def _process_raw_frame(self, ts: float, iface: str, raw: bytes) -> None:
        if len(raw) < 14:
            return

        with self._lock:
            self._packet_counter += 1
            pkt_id = self._packet_counter
            self._pcap_frames.append((ts, raw))

        time_str = time.strftime("%H:%M:%S", time.localtime(ts)) + f".{int((ts % 1) * 1000):03d}"
        eth_type = struct.unpack("!H", raw[12:14])[0]

        proto_name = "Other"
        src_ip = "Unknown"
        dst_ip = "Unknown"
        src_port: Optional[int] = None
        dst_port: Optional[int] = None
        flags_str = ""
        summary = ""

        # 1. IPv4 (0x0800)
        if eth_type == 0x0800 and len(raw) >= 34:
            ip_header = raw[14:34]
            ihl = (ip_header[0] & 0x0F) * 4
            ip_proto = ip_header[9]
            src_ip = socket.inet_ntoa(ip_header[12:16])
            dst_ip = socket.inet_ntoa(ip_header[16:20])
            payload = raw[14 + ihl :]

            # TCP (6)
            if ip_proto == 6 and len(payload) >= 20:
                proto_name = "TCP"
                src_port, dst_port, seq, ack, offset_res, flags_val = struct.unpack("!HHIIBB", payload[:14])
                tcp_flags = []
                if flags_val & 0x02:
                    tcp_flags.append("SYN")
                    self.tcp_syn_count += 1
                if flags_val & 0x10:
                    tcp_flags.append("ACK")
                if flags_val & 0x08:
                    tcp_flags.append("PSH")
                if flags_val & 0x01:
                    tcp_flags.append("FIN")
                if flags_val & 0x04:
                    tcp_flags.append("RST")
                    self.tcp_rst_count += 1
                flags_str = f"[{', '.join(tcp_flags)}]" if tcp_flags else ""

                svc = PORT_SERVICES.get(dst_port) or PORT_SERVICES.get(src_port)
                svc_desc = f" ({svc})" if svc else ""
                summary = f"{src_ip}:{src_port} -> {dst_ip}:{dst_port}{svc_desc} {flags_str}"

            # UDP (17)
            elif ip_proto == 17 and len(payload) >= 8:
                proto_name = "UDP"
                src_port, dst_port, ulen, ucheck = struct.unpack("!HHHH", payload[:8])
                udp_payload = payload[8:]

                # Check for DNS (port 53)
                if src_port == 53 or dst_port == 53:
                    proto_name = "DNS"
                    dns_desc = self._parse_dns_summary(udp_payload, src_port == 53)
                    summary = f"DNS {dns_desc}"
                    if dst_port == 53:
                        # Log DNS Query
                        qname, qtype = self._extract_dns_query(udp_payload)
                        if qname:
                            self.recent_dns.appendleft({
                                "ts": ts,
                                "time": time_str,
                                "client": src_ip,
                                "domain": qname,
                                "qtype": qtype,
                            })
                else:
                    svc = PORT_SERVICES.get(dst_port) or PORT_SERVICES.get(src_port)
                    svc_desc = f" ({svc})" if svc else ""
                    summary = f"UDP {src_ip}:{src_port} -> {dst_ip}:{dst_port}{svc_desc} len={len(payload)}"

            # ICMP (1)
            elif ip_proto == 1 and len(payload) >= 4:
                proto_name = "ICMP"
                icmp_type, icmp_code = struct.unpack("!BB", payload[:2])
                type_desc = {0: "Echo Reply", 3: "Destination Unreachable", 8: "Echo Request", 11: "Time Exceeded"}.get(
                    icmp_type, f"Type {icmp_type}"
                )
                summary = f"ICMP {type_desc} from {src_ip} -> {dst_ip}"

            else:
                proto_name = f"IPv4-{ip_proto}"
                summary = f"IPv4 proto {ip_proto}: {src_ip} -> {dst_ip} len={len(raw)}"

        # 2. ARP (0x0806)
        elif eth_type == 0x0806 and len(raw) >= 42:
            proto_name = "ARP"
            arp_data = raw[14:42]
            op, s_mac, s_ip, d_mac, d_ip = struct.unpack("!H6s4s6s4s", arp_data[6:28])
            src_ip = socket.inet_ntoa(s_ip)
            dst_ip = socket.inet_ntoa(d_ip)
            op_name = "Request" if op == 1 else ("Reply" if op == 2 else f"Op {op}")
            summary = f"ARP {op_name}: who has {dst_ip}? Tell {src_ip}" if op == 1 else f"ARP {op_name}: {src_ip} is at MAC"

        # 3. IPv6 (0x86DD)
        elif eth_type == 0x86DD and len(raw) >= 54:
            proto_name = "IPv6"
            src_ip = socket.inet_ntop(socket.AF_INET6, raw[22:38])
            dst_ip = socket.inet_ntop(socket.AF_INET6, raw[38:54])
            next_hdr = raw[20]
            summary = f"IPv6 (next={next_hdr}): {src_ip} -> {dst_ip}"

        record = PacketRecord(
            id=pkt_id,
            ts=ts,
            time_str=time_str,
            iface=iface,
            proto=proto_name,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
            length=len(raw),
            flags=flags_str,
            summary=summary,
        )

        with self._lock:
            self.recent_packets.appendleft(record)
            self.proto_counts[proto_name] += 1
            self.proto_bytes[proto_name] += len(raw)
            if src_ip != "Unknown":
                self.top_sources[src_ip] += 1
            if dst_ip != "Unknown":
                self.top_destinations[dst_ip] += 1
            if dst_port:
                self.top_ports[dst_port] += 1
            elif src_port:
                self.top_ports[src_port] += 1

    def _parse_dns_summary(self, payload: bytes, is_reply: bool) -> str:
        if len(payload) < 12:
            return "truncated"
        try:
            tx_id, flags, qdcount, ancount = struct.unpack("!HHHH", payload[:8])
            qname, qtype = self._extract_dns_query(payload)
            prefix = "Reply" if is_reply else "Query"
            if qname:
                return f"{prefix} for {qname} ({qtype})"
            return f"{prefix} id=0x{tx_id:04x} qd={qdcount} an={ancount}"
        except Exception:
            return "malformed"

    def _extract_dns_query(self, payload: bytes) -> Tuple[str, str]:
        if len(payload) < 12:
            return "", ""
        try:
            offset = 12
            labels = []
            while offset < len(payload):
                length = payload[offset]
                offset += 1
                if length == 0:
                    break
                if (length & 0xC0) == 0xC0:
                    # Compressed label pointer
                    offset += 1
                    break
                labels.append(payload[offset : offset + length].decode("utf-8", errors="replace"))
                offset += length

            domain = ".".join(labels)
            qtype = "A"
            if offset + 2 <= len(payload):
                type_val = struct.unpack("!H", payload[offset : offset + 2])[0]
                qtype_map = {1: "A", 28: "AAAA", 5: "CNAME", 15: "MX", 16: "TXT", 12: "PTR", 255: "ANY"}
                qtype = qtype_map.get(type_val, f"TYPE{type_val}")
            return domain, qtype
        except Exception:
            return "", ""

    def get_stats(self) -> dict:
        """Return snapshot of sniffer status, counters, top talkers, and recent packets."""
        with self._lock:
            total_pkts = sum(self.proto_counts.values())
            total_bytes = sum(self.proto_bytes.values())

            # Format top talkers
            top_src = [{"ip": ip, "count": c} for ip, c in self.top_sources.most_common(8)]
            top_dst = [{"ip": ip, "count": c} for ip, c in self.top_destinations.most_common(8)]
            top_ports_list = [
                {"port": p, "service": PORT_SERVICES.get(p, str(p)), "count": c}
                for p, c in self.top_ports.most_common(8)
            ]

            return {
                "running": self.running,
                "interface": self.active_iface,
                "total_packets": total_pkts,
                "total_bytes": total_bytes,
                "tcp_syn_count": self.tcp_syn_count,
                "tcp_rst_count": self.tcp_rst_count,
                "protocols": dict(self.proto_counts.most_common(6)),
                "top_sources": top_src,
                "top_destinations": top_dst,
                "top_ports": top_ports_list,
                "recent_dns": list(self.recent_dns)[:25],
                "recent_packets": [asdict(p) for p in list(self.recent_packets)[:100]],
            }

    def generate_pcap_bytes(self) -> bytes:
        """Serialize captured packets into standard libpcap 2.4 binary format."""
        with self._lock:
            frames = list(self._pcap_frames)

        buf = io.BytesIO()
        # Libpcap global header: magic=0xa1b2c3d4, v2.4, thiszone=0, sigfigs=0, snaplen=65535, network=1 (Ethernet)
        buf.write(struct.pack("!IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))

        for ts, data in frames:
            sec = int(ts)
            usec = int((ts - sec) * 1_000_000)
            length = min(len(data), 65535)
            # Packet header: ts_sec, ts_usec, incl_len, orig_len
            buf.write(struct.pack("!IIII", sec, usec, length, len(data)))
            buf.write(data[:length])

        return buf.getvalue()


_sniffer_instance: Optional[SnifferEngine] = None


def get_sniffer(default_iface: str = "eth0") -> SnifferEngine:
    global _sniffer_instance
    if _sniffer_instance is None:
        _sniffer_instance = SnifferEngine(default_iface=default_iface)
    return _sniffer_instance
