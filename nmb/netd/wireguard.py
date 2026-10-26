"""
WireGuard VPN Server Manager for NetworkMeasureBox.

Manages WireGuard server lifecycle, key generation, peer management,
QR code generation for mobile clients, and runtime transfer telemetry.
Works across all operational modes (standalone, active gateway, passive bridge).
"""
from __future__ import annotations

import base64
import io
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


def _ensure_dir() -> None:
    WG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(WG_DIR, 0o700)


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
    """Load stored peer definitions."""
    _ensure_dir()
    if not WG_PEERS_FILE.exists():
        return []
    try:
        data = json.loads(WG_PEERS_FILE.read_text())
        return data.get("peers", []) if isinstance(data, dict) else []
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


def generate_server_config(port: int = 51820, subnet: str = "10.8.0.1/24") -> str:
    """Generate wg0.conf containing server interface and all active peers."""
    server_priv, _ = get_or_create_server_keys()
    peers = load_peers()

    lines = [
        "# NetworkMeasureBox WireGuard Server Configuration",
        "# Generated automatically - Do not edit manually",
        "[Interface]",
        f"Address = {subnet}",
        f"ListenPort = {port}",
        f"PrivateKey = {server_priv}",
        "SaveConfig = false",
        "",
    ]

    for p in peers:
        if not p.get("enabled", True):
            continue
        lines.append(f"# Peer: {p.get('name', 'client')}")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {p.get('public_key')}")
        if p.get("preshared_key"):
            lines.append(f"PresharedKey = {p.get('preshared_key')}")
        lines.append(f"AllowedIPs = {p.get('client_ip')}/32")
        lines.append("")

    return "\n".join(lines)


def apply_configuration(port: int = 51820, subnet: str = "10.8.0.1/24") -> Tuple[bool, str]:
    """Write config file and reload wg0 interface via nmb-helper."""
    _ensure_dir()
    conf_content = generate_server_config(port=port, subnet=subnet)
    WG_CONF.write_text(conf_content)
    os.chmod(WG_CONF, 0o600)

    # Apply via helper
    rc, out = run_helper("wireguard-apply")
    if rc == 0:
        run_helper("vpn-nat")
        return True, "WireGuard configuration applied and interface restarted successfully."
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


def get_wireguard_status(port: int = 51820, subnet: str = "10.8.0.1/24") -> Dict[str, Any]:
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

        peer_list.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "client_ip": p.get("client_ip"),
            "public_key": pub,
            "created_at": p.get("created_at"),
            "enabled": p.get("enabled", True),
            "endpoint": stat.get("endpoint", "--"),
            "last_handshake": hs,
            "is_online": is_online,
            "rx_bytes": stat.get("rx_bytes", 0),
            "tx_bytes": stat.get("tx_bytes", 0),
        })

    return {
        "installed": installed,
        "running": is_running,
        "interface": "wg0",
        "port": port,
        "subnet": subnet,
        "server_public_key": server_pub,
        "total_peers": len(peers),
        "online_peers": sum(1 for p in peer_list if p.get("is_online")),
        "peers": peer_list,
    }


def add_peer(name: str, client_ip: Optional[str] = None) -> Dict[str, Any]:
    """Create a new client peer and return its credentials."""
    clean_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    if not clean_name:
        clean_name = f"client-{int(time.time())}"

    peers = load_peers()
    if any(p.get("name") == clean_name for p in peers):
        return {"status": "error", "message": f"Peer with name '{clean_name}' already exists."}

    # Determine next available IP in 10.8.0.x
    used_ips = {p.get("client_ip") for p in peers}
    if not client_ip:
        for host_num in range(2, 250):
            cand = f"10.8.0.{host_num}"
            if cand not in used_ips:
                client_ip = cand
                break
    if not client_ip:
        client_ip = "10.8.0.2"

    priv, pub = gen_keypair()
    psk = gen_psk()
    peer_id = f"peer-{int(time.time())}-{len(peers)+1}"

    new_peer = {
        "id": peer_id,
        "name": clean_name,
        "client_ip": client_ip,
        "private_key": priv,
        "public_key": pub,
        "preshared_key": psk,
        "created_at": time.time(),
        "enabled": True,
    }
    peers.append(new_peer)
    save_peers(peers)

    # Apply configuration immediately
    apply_configuration()

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


def get_client_config(peer_name_or_id: str, endpoint_host: str = "", port: int = 51820) -> Optional[str]:
    """Generate downloadable WireGuard client configuration (.conf)."""
    peers = load_peers()
    peer = next((p for p in peers if p.get("id") == peer_name_or_id or p.get("name") == peer_name_or_id), None)
    if not peer:
        return None

    _, server_pub = get_or_create_server_keys()
    if not endpoint_host:
        from nmb.netd.duckdns import detect_public_ip
        endpoint_host = detect_public_ip() or "YOUR_PUBLIC_IP"

    lines = [
        f"# NetworkMeasureBox WireGuard Client: {peer.get('name')}",
        "[Interface]",
        f"PrivateKey = {peer.get('private_key')}",
        f"Address = {peer.get('client_ip')}/32",
        "DNS = 1.1.1.1, 8.8.8.8",
        "",
        "[Peer]",
        f"PublicKey = {server_pub}",
        f"PresharedKey = {peer.get('preshared_key')}",
        f"Endpoint = {endpoint_host}:{port}",
        "AllowedIPs = 0.0.0.0/0, ::/0",
        "PersistentKeepalive = 25",
    ]
    return "\n".join(lines)


def get_client_qr_data_uri(peer_name_or_id: str, endpoint_host: str = "", port: int = 51820) -> Optional[str]:
    """Generate QR code base64 PNG data-uri for mobile app scanning."""
    conf = get_client_config(peer_name_or_id, endpoint_host=endpoint_host, port=port)
    if not conf:
        return None

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
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        log.warning("qrcode generation failed: %s", e)
        return None
