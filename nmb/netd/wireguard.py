"""
WireGuard VPN Server Manager for NetworkMeasureBox.

Manages WireGuard server lifecycle, key generation, peer management,
QR code generation for mobile clients, and runtime transfer telemetry.
Works across all operational modes (standalone, active gateway, passive bridge).
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.wireguard")

WG_DIR = Path(os.environ.get("NMB_WG_DIR", "/var/lib/nmb/wireguard"))
WG_CONF = WG_DIR / "wg0.conf"
WG_PEERS_FILE = WG_DIR / "peers.json"
SERVER_PRIV_KEY = WG_DIR / "server_private.key"
SERVER_PUB_KEY = WG_DIR / "server_public.key"


def is_private_ip(ip_str: str) -> bool:
    """Return True if ip_str is a private LAN, loopback, or link-local IP."""
    if not ip_str:
        return False
    try:
        clean_ip = ip_str.split(":")[0].strip("[]")
        ip_obj = ipaddress.ip_address(clean_ip)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    except ValueError:
        return False


def get_device_addresses() -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Detect local IPv4 and global unicast IPv6 addresses on active physical network interfaces."""
    v4_addrs: List[Tuple[str, str]] = []
    v6_addrs: List[Tuple[str, str]] = []
    try:
        res = subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True, timeout=2, check=False)
        if res.returncode == 0:
            for iface in json.loads(res.stdout):
                name = iface.get("ifname", "")
                if name in ("lo", "wg0", "tun0") or name.startswith("docker"):
                    continue
                for a in iface.get("addr_info", []):
                    fam = a.get("family")
                    scope = a.get("scope")
                    loc = a.get("local", "")
                    if fam == "inet" and scope == "global" and loc:
                        v4_addrs.append((name, loc))
                    elif fam == "inet6" and scope == "global" and loc:
                        # Exclude link-local (fe80::) and ULA (fd::, fc::)
                        if not loc.startswith("fe80") and not loc.startswith("fd") and not loc.startswith("fc"):
                            v6_addrs.append((name, loc))
    except Exception as e:
        log.debug("error detecting local addresses: %s", e)
    return v4_addrs, v6_addrs


def get_candidate_endpoints(
    port: int = 51820,
    public_endpoint: str = "",
    duckdns_domain: str = "",
    request_host: str = "",
) -> List[Dict[str, Any]]:
    """Assemble candidate connection endpoints for clients (LAN, DDNS, IPv6, Public IP)."""
    candidates: List[Dict[str, Any]] = []
    seen_hosts = set()

    v4_addrs, v6_addrs = get_device_addresses()

    # 1. Check if user is currently browsing WebUI from a local LAN IP
    req_host_clean = request_host.split(":")[0].strip("[]")
    is_req_private = is_private_ip(req_host_clean)

    if is_req_private and req_host_clean:
        candidates.append({
            "id": "current-host",
            "type": "lan",
            "host": req_host_clean,
            "port": port,
            "endpoint": f"{req_host_clean}:{port}",
            "label": f"🏠 Helyi LAN / WebUI cím ({req_host_clean})",
            "desc": "Ajánlott otthoni Wi-Fi / helyi kapcsolathoz (0ms NAT késleltetés, nincs router loopback hiba)",
            "is_default": True,
        })
        seen_hosts.add(req_host_clean)

    for iface, ip in v4_addrs:
        if ip not in seen_hosts:
            is_def = (len(candidates) == 0 and is_req_private)
            candidates.append({
                "id": f"lan-{iface}",
                "type": "lan",
                "host": ip,
                "port": port,
                "endpoint": f"{ip}:{port}",
                "label": f"🏠 Helyi hálózat / Wi-Fi [{iface}] ({ip})",
                "desc": "Közvetlen kapcsolat a mérőbox belső IP címével",
                "is_default": is_def,
            })
            seen_hosts.add(ip)

    # 2. Dynamic DNS (DuckDNS / Public Endpoint)
    ddns_host = public_endpoint.split(":")[0].strip() or (duckdns_domain + ".duckdns.org" if duckdns_domain else "")
    if ddns_host and ddns_host not in seen_hosts:
        is_def = (len(candidates) == 0) or (req_host_clean == ddns_host) or (not is_req_private and bool(req_host_clean))
        candidates.append({
            "id": "ddns",
            "type": "ddns",
            "host": ddns_host,
            "port": port,
            "endpoint": f"{ddns_host}:{port}",
            "label": f"🌐 Dinamikus DNS ({ddns_host})",
            "desc": "Távoli mobilnetes eléréshez (A fő routeren az 51820 UDP porttovábbítás szükséges!)",
            "is_default": is_def,
        })
        seen_hosts.add(ddns_host)

    # 3. Global IPv6
    for iface, ip6 in v6_addrs:
        if ip6 not in seen_hosts:
            candidates.append({
                "id": f"ipv6-{iface}",
                "type": "ipv6",
                "host": ip6,
                "port": port,
                "endpoint": f"[{ip6}]:{port}",
                "label": f"⚡ Közvetlen IPv6 [{iface}] ([{ip6}])",
                "desc": "Közvetlen kapcsolat IPv6-on (megkerüli az IPv4 NAT-ot és router porttovábbítást)",
                "is_default": False,
            })
            seen_hosts.add(ip6)

    # 4. Detected Public WAN IPv4
    from nmb.netd.duckdns import get_duckdns_status
    duck_st = get_duckdns_status()
    wan_ip = duck_st.get("last_ip") or ""
    if wan_ip and wan_ip not in seen_hosts:
        candidates.append({
            "id": "wan-ipv4",
            "type": "wan_v4",
            "host": wan_ip,
            "port": port,
            "endpoint": f"{wan_ip}:{port}",
            "label": f"🌍 Publikus WAN IPv4 ({wan_ip})",
            "desc": "Közvetlen publikus IP (A fő routeren az 51820 UDP porttovábbítás szükséges!)",
            "is_default": False,
        })
        seen_hosts.add(wan_ip)

    # If still no candidates, fallback to localhost
    if not candidates:
        candidates.append({
            "id": "fallback",
            "type": "lan",
            "host": "127.0.0.1",
            "port": port,
            "endpoint": f"127.0.0.1:{port}",
            "label": f"127.0.0.1:{port}",
            "desc": "",
            "is_default": True,
        })

    return candidates


def _ensure_dir() -> None:
    try:
        WG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(WG_DIR, 0o700)
    except Exception:
        pass


def is_wireguard_available() -> bool:
    """Return True if wg command is installed on system."""
    return shutil.which("wg") is not None


def run_helper(cmd: str) -> Tuple[int, str]:
    """Execute privileged wireguard action via nmb-helper."""
    helper_paths = ["/usr/local/bin/nmb-helper", "/opt/nmb/bin/nmb-helper"]
    helper = None
    for p in helper_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            helper = p
            break
    if not helper:
        helper = "nmb-helper"

    try:
        proc = subprocess.run(
            ["sudo", "-n", helper, cmd],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:
        log.error("nmb-helper %s execution failed: %s", cmd, e)
        return 1, str(e)


def gen_keypair() -> Tuple[str, str]:
    """Generate WireGuard private and public keypair."""
    try:
        priv_proc = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True)
        priv = priv_proc.stdout.strip()
        pub_proc = subprocess.run(["wg", "pubkey"], input=priv, capture_output=True, text=True, check=True)
        pub = pub_proc.stdout.strip()
        return priv, pub
    except Exception as e:
        log.error("failed to generate wg keypair via CLI: %s", e)
        # Fallback to random base64 (for dry-run/fallback)
        priv = base64.b64encode(os.urandom(32)).decode("ascii")
        pub = base64.b64encode(os.urandom(32)).decode("ascii")
        return priv, pub


def gen_psk() -> str:
    """Generate preshared key."""
    try:
        res = subprocess.run(["wg", "genpsk"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return base64.b64encode(os.urandom(32)).decode("ascii")


def get_or_create_server_keys() -> Tuple[str, str]:
    """Ensure server private and public keys exist."""
    _ensure_dir()
    if SERVER_PRIV_KEY.exists() and SERVER_PUB_KEY.exists():
        priv = SERVER_PRIV_KEY.read_text().strip()
        pub = SERVER_PUB_KEY.read_text().strip()
        if priv and pub:
            return priv, pub

    priv, pub = gen_keypair()
    SERVER_PRIV_KEY.write_text(priv)
    SERVER_PUB_KEY.write_text(pub)
    os.chmod(SERVER_PRIV_KEY, 0o600)
    return priv, pub


def load_peers() -> List[Dict[str, Any]]:
    """Load stored peer definitions with dual-stack IPv4/IPv6 support."""
    _ensure_dir()
    if not WG_PEERS_FILE.exists():
        return []
    try:
        data = json.loads(WG_PEERS_FILE.read_text())
        peers = data.get("peers", []) if isinstance(data, dict) else []
        modified = False
        for p in peers:
            if not p.get("client_ipv6"):
                c_ip = p.get("client_ip", "10.8.0.2")
                host_num = c_ip.split(".")[-1] if "." in c_ip else "2"
                p["client_ipv6"] = f"fd42:42:42::{host_num}"
                modified = True
        if modified:
            save_peers(peers)
        return peers
    except Exception as e:
        log.error("failed to load peers.json: %s", e)
        return []


def save_peers(peers: List[Dict[str, Any]]) -> None:
    """Save peer definitions atomically."""
    _ensure_dir()
    tmp_path = WG_PEERS_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps({"peers": peers, "updated_at": time.time()}, indent=2))
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(WG_PEERS_FILE)


def generate_server_config(
    port: int = 51820,
    subnet: str = "10.8.0.1/24",
    subnet_ipv6: str = "fd42:42:42::1/64",
) -> str:
    """Generate wg0.conf containing dual-stack server interface and all active peers."""
    server_priv, _ = get_or_create_server_keys()
    peers = load_peers()

    lines = [
        "# NetworkMeasureBox WireGuard Server Configuration",
        "# Generated automatically - Do not edit manually",
        "[Interface]",
        f"Address = {subnet}, {subnet_ipv6}",
        f"ListenPort = {port}",
        f"PrivateKey = {server_priv}",
        "SaveConfig = false",
        "",
    ]

    for p in peers:
        if not p.get("enabled", True):
            continue
        c_ip = p.get("client_ip", "10.8.0.2")
        c_ipv6 = p.get("client_ipv6")
        if not c_ipv6:
            host_num = c_ip.split(".")[-1] if "." in c_ip else "2"
            c_ipv6 = f"fd42:42:42::{host_num}"
        lines.append(f"# Peer: {p.get('name', 'client')}")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {p.get('public_key')}")
        if p.get("preshared_key"):
            lines.append(f"PresharedKey = {p.get('preshared_key')}")
        lines.append(f"AllowedIPs = {c_ip}/32, {c_ipv6}/128")
        lines.append("")

    return "\n".join(lines)


def apply_configuration(
    port: int = 51820,
    subnet: str = "10.8.0.1/24",
    subnet_ipv6: str = "fd42:42:42::1/64",
) -> Tuple[bool, str]:
    """Write config file and reload wg0 interface via nmb-helper."""
    _ensure_dir()
    conf_content = generate_server_config(port=port, subnet=subnet, subnet_ipv6=subnet_ipv6)
    WG_CONF.write_text(conf_content)
    os.chmod(WG_CONF, 0o600)

    # Apply via helper
    rc, out = run_helper("wireguard-apply")
    if rc == 0:
        run_helper("vpn-nat")
        return True, "WireGuard dual-stack configuration applied and interface restarted successfully."
    return False, f"Failed to apply WireGuard config: {out}"


def get_live_peer_stats() -> Dict[str, Dict[str, Any]]:
    """Query wg show wg0 dump for real-time handshake and transfer bytes."""
    stats: Dict[str, Dict[str, Any]] = {}
    if not is_wireguard_available():
        return stats
    try:
        proc = subprocess.run(["wg", "show", "wg0", "dump"], capture_output=True, text=True, timeout=3, check=False)
        if proc.returncode != 0:
            return stats
        lines = proc.stdout.splitlines()
        for line in lines[1:]:  # First line is server interface
            parts = line.strip().split("\t")
            if len(parts) >= 8:
                pubkey = parts[0]
                endpoint = parts[2]
                allowed_ips = parts[3]
                handshake_ts = int(parts[4]) if parts[4].isdigit() else 0
                rx_bytes = int(parts[5]) if parts[5].isdigit() else 0
                tx_bytes = int(parts[6]) if parts[6].isdigit() else 0
                stats[pubkey] = {
                    "endpoint": endpoint if endpoint != "(none)" else "--",
                    "allowed_ips": allowed_ips,
                    "last_handshake": handshake_ts,
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes,
                }
    except Exception as e:
        log.debug("error reading wg dump: %s", e)
    return stats


def get_wireguard_status(
    port: int = 51820,
    subnet: str = "10.8.0.1/24",
    subnet_ipv6: str = "fd42:42:42::1/64",
    dns: str = "",
    public_endpoint: str = "",
    duckdns_domain: str = "",
    request_host: str = "",
) -> Dict[str, Any]:
    """Retrieve complete status of WireGuard VPN server and connected peers."""
    installed = is_wireguard_available()
    _, server_pub = get_or_create_server_keys() if installed else ("", "")
    peers = load_peers()
    live_stats = get_live_peer_stats()

    is_running = False
    try:
        proc = subprocess.run(["ip", "link", "show", "wg0"], capture_output=True, text=True, timeout=2, check=False)
        is_running = proc.returncode == 0
    except Exception:
        pass

    peer_list = []
    now = time.time()
    for p in peers:
        pub = p.get("public_key", "")
        stat = live_stats.get(pub, {})
        hs = stat.get("last_handshake", 0)
        is_online = (now - hs < 180) if hs > 0 else False
        c_ip = p.get("client_ip", "")
        c_ipv6 = p.get("client_ipv6", "")

        peer_list.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "client_ip": c_ip,
            "client_ipv6": c_ipv6,
            "allowed_ips": f"{c_ip}/32, {c_ipv6}/128" if c_ipv6 else f"{c_ip}/32",
            "public_key": pub,
            "created_at": p.get("created_at"),
            "enabled": p.get("enabled", True),
            "endpoint": stat.get("endpoint", "--"),
            "last_handshake": hs,
            "latest_handshake": hs,
            "latest_handshake_ago": f"{int(now - hs)}s ago" if hs > 0 else "--",
            "is_online": is_online,
            "rx_bytes": stat.get("rx_bytes", 0),
            "tx_bytes": stat.get("tx_bytes", 0),
            "transfer_rx": stat.get("rx_bytes", 0),
            "transfer_tx": stat.get("tx_bytes", 0),
        })

    candidates = get_candidate_endpoints(
        port=port,
        public_endpoint=public_endpoint,
        duckdns_domain=duckdns_domain,
        request_host=request_host,
    )

    return {
        "installed": installed,
        "running": is_running,
        "active": is_running,
        "interface": "wg0",
        "port": port,
        "subnet": subnet,
        "subnet_ipv6": subnet_ipv6,
        "dns": dns,
        "server_public_key": server_pub,
        "total_peers": len(peers),
        "online_peers": sum(1 for p in peer_list if p.get("is_online")),
        "peers": peer_list,
        "endpoint_candidates": candidates,
    }


def add_peer(
    name: str,
    client_ip: Optional[str] = None,
    client_ipv6: Optional[str] = None,
    port: int = 51820,
    subnet: str = "10.8.0.1/24",
    subnet_ipv6: str = "fd42:42:42::1/64",
) -> Dict[str, Any]:
    """Create a new client peer with dual-stack IPv4/IPv6 and return its credentials."""
    clean_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    if not clean_name:
        clean_name = f"client-{int(time.time())}"

    peers = load_peers()
    if any(p.get("name") == clean_name for p in peers):
        return {"status": "error", "message": f"Peer with name '{clean_name}' already exists."}

    used_ips = {p.get("client_ip") for p in peers}
    host_num = 2
    if not client_ip:
        for n in range(2, 250):
            cand = f"10.8.0.{n}"
            if cand not in used_ips:
                client_ip = cand
                host_num = n
                break
    if not client_ip:
        client_ip = "10.8.0.2"
        host_num = 2
    else:
        try:
            host_num = int(client_ip.split(".")[-1])
        except Exception:
            host_num = len(peers) + 2

    if not client_ipv6:
        client_ipv6 = f"fd42:42:42::{host_num}"

    priv, pub = gen_keypair()
    psk = gen_psk()
    peer_id = f"peer-{int(time.time())}-{len(peers)+1}"

    new_peer = {
        "id": peer_id,
        "name": clean_name,
        "client_ip": client_ip,
        "client_ipv6": client_ipv6,
        "private_key": priv,
        "public_key": pub,
        "preshared_key": psk,
        "created_at": time.time(),
        "enabled": True,
    }
    peers.append(new_peer)
    save_peers(peers)

    # Apply configuration immediately
    apply_configuration(port=port, subnet=subnet, subnet_ipv6=subnet_ipv6)

    return {
        "status": "ok",
        "peer": new_peer,
        "message": f"Peer '{clean_name}' successfully created.",
    }


def delete_peer(peer_id_or_name: str) -> bool:
    """Remove a peer by ID or name and re-apply server config."""
    peers = load_peers()
    initial_len = len(peers)
    peers = [p for p in peers if p.get("id") != peer_id_or_name and p.get("name") != peer_id_or_name]
    if len(peers) == initial_len:
        return False
    save_peers(peers)
    apply_configuration()
    return True


def get_client_config(
    peer_name_or_id: str,
    endpoint_host: str = "",
    port: int = 51820,
    dns_servers: str = "",
) -> Optional[str]:
    """Generate downloadable WireGuard client configuration (.conf) with dual-stack support."""
    peers = load_peers()
    peer = next((p for p in peers if p.get("id") == peer_name_or_id or p.get("name") == peer_name_or_id), None)
    if not peer:
        return None

    _, server_pub = get_or_create_server_keys()
    endpoint_str = str(endpoint_host).strip()
    if not endpoint_str:
        from nmb.netd.duckdns import detect_public_ip
        endpoint_str = detect_public_ip() or "YOUR_PUBLIC_IP"

    c_ip = peer.get("client_ip", "10.8.0.2")
    c_ipv6 = peer.get("client_ipv6")
    if not c_ipv6:
        host_num = c_ip.split(".")[-1] if "." in c_ip else "2"
        c_ipv6 = f"fd42:42:42::{host_num}"

    dns_val = dns_servers.strip() if dns_servers else "1.1.1.1, 2606:4700:4700::1111, 8.8.8.8"

    # Format endpoint cleanly whether it already contains port, IPv6 brackets, etc.
    if endpoint_str.startswith("["):
        if "]:" in endpoint_str:
            endpoint_formatted = endpoint_str
        else:
            endpoint_formatted = f"{endpoint_str}:{port}"
    elif ":" in endpoint_str:
        if endpoint_str.count(":") == 1:
            endpoint_formatted = endpoint_str
        else:
            endpoint_formatted = f"[{endpoint_str}]:{port}"
    else:
        endpoint_formatted = f"{endpoint_str}:{port}"

    lines = [
        f"# NetworkMeasureBox WireGuard Dual-Stack Client: {peer.get('name')}",
        "[Interface]",
        f"PrivateKey = {peer.get('private_key')}",
        f"Address = {c_ip}/32, {c_ipv6}/128",
        f"DNS = {dns_val}",
        "",
        "[Peer]",
        f"PublicKey = {server_pub}",
        f"PresharedKey = {peer.get('preshared_key')}",
        f"Endpoint = {endpoint_formatted}",
        "AllowedIPs = 0.0.0.0/0, ::/0",
        "PersistentKeepalive = 25",
    ]
    return "\n".join(lines)


def get_client_qr_png_bytes(
    peer_name_or_id: str,
    endpoint_host: str = "",
    port: int = 51820,
    dns_servers: str = "",
) -> Optional[bytes]:
    """Generate raw PNG bytes for WireGuard client QR code."""
    if peer_name_or_id and "[Interface]" in peer_name_or_id:
        conf = peer_name_or_id
    else:
        conf = get_client_config(peer_name_or_id, endpoint_host=endpoint_host, port=port, dns_servers=dns_servers)
    if not conf:
        return None

    # 1. Primary: Native qrencode binary (instant, low RAM overhead)
    qrencode_bin = shutil.which("qrencode")
    if qrencode_bin:
        try:
            proc = subprocess.run(
                [qrencode_bin, "-t", "PNG", "-s", "6", "-m", "2", "-o", "-"],
                input=conf.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=5,
            )
            if proc.stdout:
                return proc.stdout
        except Exception as e:
            log.warning("qrencode CLI execution failed: %s", e)

    # 2. Secondary fallback: Python qrcode library
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(conf)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        log.warning("python qrcode generation failed: %s", e)

    return None


def get_client_qr_svg(
    peer_name_or_id: str,
    endpoint_host: str = "",
    port: int = 51820,
    dns_servers: str = "",
) -> Optional[str]:
    """Generate SVG XML string for WireGuard client QR code."""
    if peer_name_or_id and "[Interface]" in peer_name_or_id:
        conf = peer_name_or_id
    else:
        conf = get_client_config(peer_name_or_id, endpoint_host=endpoint_host, port=port, dns_servers=dns_servers)
    if not conf:
        return None

    qrencode_bin = shutil.which("qrencode")
    if qrencode_bin:
        try:
            proc = subprocess.run(
                [qrencode_bin, "-t", "SVG", "-m", "2", "-o", "-"],
                input=conf.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=5,
                text=True,
            )
            if proc.stdout:
                return proc.stdout
        except Exception as e:
            log.warning("qrencode SVG generation failed: %s", e)

    return None


def get_client_qr_data_uri(
    peer_name_or_id: str,
    endpoint_host: str = "",
    port: int = 51820,
    dns_servers: str = "",
) -> Optional[str]:
    """Generate QR code base64 data-uri for mobile app scanning or WebGUI display."""
    png_bytes = get_client_qr_png_bytes(peer_name_or_id, endpoint_host=endpoint_host, port=port, dns_servers=dns_servers)
    if png_bytes:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"

    svg = get_client_qr_svg(peer_name_or_id, endpoint_host=endpoint_host, port=port, dns_servers=dns_servers)
    if svg:
        import urllib.parse
        return f"data:image/svg+xml;utf8,{urllib.parse.quote(svg)}"

    return None
