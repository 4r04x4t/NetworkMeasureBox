"""
High-Performance HTTPS & HTTP CONNECT Proxy Server for NetworkMeasureBox.

Embedded, multi-threaded forward proxy supporting:
- HTTP CONNECT tunneling for end-to-end TLS / HTTPS encryption
- Standard HTTP request forwarding
- Optional Basic Proxy Authentication (RFC 7617)
- Optional TLS encrypted frontend
- Live connection tracking and byte transfer telemetry
"""
from __future__ import annotations

import base64
import logging
import select
import socket
import ssl
import threading
import time
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("nmb.netd.proxy")

_proxy_server: Optional[ProxyServer] = None
_proxy_lock = threading.Lock()

_proxy_stats = {
    "active_connections": 0,
    "total_connections": 0,
    "bytes_rx": 0,
    "bytes_tx": 0,
    "start_time": 0.0,
}


import struct

def parse_target_host_port(target: str, default_port: int = 443) -> Tuple[str, int]:
    """Parse host and port handling bracketed IPv6 literals, IPv4, and hostnames."""
    target = target.strip()
    if target.startswith("[") and "]" in target:
        host = target[1:target.find("]")]
        rest = target[target.find("]")+1:]
        port = int(rest.lstrip(":")) if rest.lstrip(":").isdigit() else default_port
        return host, port
    if ":" in target:
        if target.count(":") > 1:
            # Raw unbracketed IPv6 literal
            return target, default_port
        host, port_str = target.split(":", 1)
        port = int(port_str) if port_str.isdigit() else default_port
        return host, port
    return target, default_port


def query_manual_dns(name: str, nameserver: str, qtype: int = 1, timeout: float = 2.0) -> List[str]:
    """Query specific manual DNS resolver for A (1) or AAAA (28) records."""
    try:
        parts = name.strip(".").split(".")
        qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in parts) + b"\x00"
        tid = 0x5a3c
        header = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
        packet = header + qname + struct.pack("!HH", qtype, 1)

        is_ipv6_server = ":" in nameserver
        sock_family = socket.AF_INET6 if is_ipv6_server else socket.AF_INET
        s = socket.socket(sock_family, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(packet, (nameserver, 53))
            resp, _ = s.recvfrom(4096)
            if len(resp) < 12:
                return []
            ancount = struct.unpack("!H", resp[6:8])[0]
            idx = 12
            while idx < len(resp) and resp[idx] != 0:
                if resp[idx] >= 192:
                    idx += 2
                    break
                idx += 1 + resp[idx]
            if idx < len(resp) and resp[idx] == 0:
                idx += 1
            idx += 4
            ips: List[str] = []
            for _ in range(ancount):
                if idx >= len(resp):
                    break
                if resp[idx] >= 192:
                    idx += 2
                else:
                    while idx < len(resp) and resp[idx] != 0:
                        idx += 1 + resp[idx]
                    if idx < len(resp):
                        idx += 1
                if idx + 10 > len(resp):
                    break
                rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", resp[idx:idx+10])
                idx += 10
                rdata = resp[idx:idx+rdlen]
                idx += rdlen
                if rtype == 1 and rdlen == 4:
                    ips.append(socket.inet_ntop(socket.AF_INET, rdata))
                elif rtype == 28 and rdlen == 16:
                    ips.append(socket.inet_ntop(socket.AF_INET6, rdata))
            return ips
        finally:
            s.close()
    except Exception as e:
        log.debug("manual dns query %s on %s failed: %s", name, nameserver, e)
        return []


class ProxyServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8443,
        auth_enabled: bool = False,
        username: str = "",
        password: str = "",
        tls_enabled: bool = False,
        tls_cert: str = "",
        tls_key: str = "",
        listen_ipv6: bool = True,
        dns: str = "",
    ):
        self.host = host
        self.port = port
        self.auth_enabled = auth_enabled
        self.username = username
        self.password = password
        self.tls_enabled = tls_enabled
        self.tls_cert = tls_cert
        self.tls_key = tls_key
        self.listen_ipv6 = listen_ipv6
        self.dns = dns

        self.running = False
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> Tuple[bool, str]:
        if self.running:
            return True, "Proxy server is already running."

        try:
            # Dual-stack socket binding
            if self.listen_ipv6 and (self.host in ("0.0.0.0", "::", "")):
                try:
                    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                    except (AttributeError, OSError):
                        pass
                    sock.bind(("::", self.port))
                    self.sock = sock
                    self.host = "::"
                except Exception as e:
                    log.info("IPv6 dual-stack socket bind failed, falling back to IPv4: %s", e)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("0.0.0.0", self.port))
                    self.sock = sock
                    self.host = "0.0.0.0"
            else:
                family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
                self.sock = socket.socket(family, socket.SOCK_STREAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock.bind((self.host, self.port))

            self.sock.listen(128)

            if self.tls_enabled and self.tls_cert and self.tls_key:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(certfile=self.tls_cert, keyfile=self.tls_key)
                self.sock = ctx.wrap_socket(self.sock, server_side=True)

            self.running = True
            _proxy_stats["start_time"] = time.time()

            self.thread = threading.Thread(target=self._accept_loop, name=f"nmb-proxy-{self.port}", daemon=True)
            self.thread.start()

            log.info("HTTPS Proxy Server started on %s:%d (DualStack=%s, Auth=%s, TLS=%s)", self.host, self.port, self.listen_ipv6, self.auth_enabled, self.tls_enabled)
            return True, f"Proxy server listening on port {self.port} (Dual-Stack IPv4/IPv6)"
        except Exception as e:
            log.error("failed to start proxy server: %s", e)
            self.stop()
            return False, str(e)

    def stop(self) -> None:
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        log.info("HTTPS Proxy Server stopped.")

    def _accept_loop(self) -> None:
        while self.running and self.sock:
            try:
                client_sock, client_addr = self.sock.accept()
                _proxy_stats["total_connections"] += 1
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_addr),
                    daemon=True,
                )
                t.start()
            except Exception:
                break

    def _connect_remote(self, host: str, port: int, timeout: float = 10.0) -> socket.socket:
        """Connect to remote target with dual-stack IPv4/IPv6 and manual DNS resolvers."""
        # 1. Check if host is already an IP address literal
        try:
            socket.inet_pton(socket.AF_INET, host)
            return socket.create_connection((host, port), timeout=timeout)
        except OSError:
            try:
                socket.inet_pton(socket.AF_INET6, host)
                return socket.create_connection((host, port), timeout=timeout)
            except OSError:
                pass

        # 2. Host is a domain name. If custom manual DNS resolvers configured, query them:
        dns_servers = [d.strip() for d in self.dns.split(",") if d.strip()] if self.dns else []
        if dns_servers:
            candidate_ips: List[str] = []
            for ns in dns_servers:
                aaaa_ips = query_manual_dns(host, ns, qtype=28, timeout=2.0)
                a_ips = query_manual_dns(host, ns, qtype=1, timeout=2.0)
                candidate_ips.extend(aaaa_ips)
                candidate_ips.extend(a_ips)
                if candidate_ips:
                    break

            for cand_ip in candidate_ips:
                try:
                    return socket.create_connection((cand_ip, port), timeout=timeout)
                except Exception:
                    continue

        # 3. Fallback to standard system resolver
        return socket.create_connection((host, port), timeout=timeout)

    def _handle_client(self, client_sock: socket.socket, client_addr: Tuple[str, int]) -> None:
        with _proxy_lock:
            _proxy_stats["active_connections"] += 1
        try:
            client_sock.settimeout(15.0)
            initial_data = client_sock.recv(4096)
            if not initial_data:
                return

            header_text = initial_data.decode("latin1", errors="ignore")
            lines = header_text.split("\r\n")
            if not lines:
                return

            req_line = lines[0].split()
            if len(req_line) < 3:
                return

            method, target, proto = req_line[0], req_line[1], req_line[2]

            # Authentication check
            if self.auth_enabled and self.username and self.password:
                auth_header = None
                for line in lines[1:]:
                    if line.lower().startswith("proxy-authorization:"):
                        auth_header = line.split(":", 1)[1].strip()
                        break

                valid = False
                if auth_header and auth_header.lower().startswith("basic "):
                    try:
                        creds = base64.b64decode(auth_header.split(" ", 1)[1]).decode("latin1")
                        u, p = creds.split(":", 1)
                        valid = (u == self.username and p == self.password)
                    except Exception:
                        valid = False

                if not valid:
                    resp = (
                        "HTTP/1.1 407 Proxy Authentication Required\r\n"
                        'Proxy-Authenticate: Basic realm="NetworkMeasureBox Proxy"\r\n'
                        "Content-Type: text/plain\r\n"
                        "Content-Length: 32\r\n\r\n"
                        "407 Proxy Authentication Required"
                    )
                    client_sock.sendall(resp.encode("latin1"))
                    return

            if method.upper() == "CONNECT":
                # HTTPS / TLS CONNECT tunneling
                host, port = parse_target_host_port(target, default_port=443)
                try:
                    remote_sock = self._connect_remote(host, port, timeout=10.0)
                except Exception as e:
                    client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    return

                client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._tunnel_bidirectional(client_sock, remote_sock)

            else:
                # Standard HTTP proxy request
                if "://" in target:
                    from urllib.parse import urlparse
                    parsed = urlparse(target)
                    host = parsed.hostname or ""
                    port = parsed.port or 80
                    path = parsed.path or "/"
                    if parsed.query:
                        path += f"?{parsed.query}"
                else:
                    host, port = parse_target_host_port(target, default_port=80)
                    path = "/"

                try:
                    remote_sock = self._connect_remote(host, port, timeout=10.0)
                except Exception:
                    client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    return

                # Send initial data to remote
                remote_sock.sendall(initial_data)
                self._tunnel_bidirectional(client_sock, remote_sock)

        except Exception as e:
            log.debug("proxy connection exception: %s", e)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            with _proxy_lock:
                _proxy_stats["active_connections"] = max(0, _proxy_stats["active_connections"] - 1)

    def _tunnel_bidirectional(self, sock1: socket.socket, sock2: socket.socket) -> None:
        """Stream data bidirectionally between two sockets using select()."""
        sock1.setblocking(False)
        sock2.setblocking(False)
        sockets = [sock1, sock2]

        while self.running:
            try:
                readable, _, exceptional = select.select(sockets, [], sockets, 60.0)
                if exceptional:
                    break
                if not readable:
                    break

                for s in readable:
                    data = s.recv(16384)
                    if not data:
                        return
                    peer = sock2 if s is sock1 else sock1
                    peer.sendall(data)

                    n = len(data)
                    with _proxy_lock:
                        if s is sock1:
                            _proxy_stats["bytes_rx"] += n
                        else:
                            _proxy_stats["bytes_tx"] += n
            except Exception:
                break
        try:
            sock1.close()
            sock2.close()
        except Exception:
            pass


def get_proxy_status() -> Dict[str, Any]:
    """Retrieve runtime status and telemetry of HTTPS Proxy Server."""
    global _proxy_server
    is_running = _proxy_server is not None and _proxy_server.running

    with _proxy_lock:
        stats = dict(_proxy_stats)

    uptime = round(time.time() - stats["start_time"], 1) if is_running and stats["start_time"] > 0 else 0

    return {
        "running": is_running,
        "host": _proxy_server.host if _proxy_server else "0.0.0.0",
        "port": _proxy_server.port if _proxy_server else 8443,
        "auth_enabled": _proxy_server.auth_enabled if _proxy_server else False,
        "username": _proxy_server.username if _proxy_server else "",
        "tls_enabled": _proxy_server.tls_enabled if _proxy_server else False,
        "listen_ipv6": _proxy_server.listen_ipv6 if _proxy_server else True,
        "dns": _proxy_server.dns if _proxy_server else "",
        "active_connections": stats["active_connections"],
        "total_connections": stats["total_connections"],
        "bytes_rx": stats["bytes_rx"],
        "bytes_tx": stats["bytes_tx"],
        "uptime_seconds": uptime,
    }


def start_proxy_server(
    host: str = "0.0.0.0",
    port: int = 8443,
    auth_enabled: bool = False,
    username: str = "",
    password: str = "",
    tls_enabled: bool = False,
    tls_cert: str = "",
    tls_key: str = "",
    listen_ipv6: bool = True,
    dns: str = "",
) -> Tuple[bool, str]:
    """Start or restart the HTTPS Proxy Server with dual-stack IPv4/IPv6 support."""
    global _proxy_server
    with _proxy_lock:
        if _proxy_server:
            _proxy_server.stop()
        _proxy_server = ProxyServer(
            host=host,
            port=port,
            auth_enabled=auth_enabled,
            username=username,
            password=password,
            tls_enabled=tls_enabled,
            tls_cert=tls_cert,
            tls_key=tls_key,
            listen_ipv6=listen_ipv6,
            dns=dns,
        )
        return _proxy_server.start()


def stop_proxy_server() -> None:
    """Stop the HTTPS Proxy Server."""
    global _proxy_server
    with _proxy_lock:
        if _proxy_server:
            _proxy_server.stop()
            _proxy_server = None
