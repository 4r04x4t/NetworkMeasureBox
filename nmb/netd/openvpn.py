"""
OpenVPN Server Manager for NetworkMeasureBox.

Manages OpenVPN server lifecycle, elliptic curve PKI (prime256v1),
unified standalone .ovpn client profile generation, and real-time client connection telemetry.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.openvpn")

OV_DIR = Path(os.environ.get("NMB_OV_DIR", "/var/lib/nmb/openvpn"))
PKI_DIR = OV_DIR / "pki"
OV_CONF = OV_DIR / "server.conf"
CLIENTS_FILE = OV_DIR / "clients.json"
STATUS_LOG = Path("/var/log/nmb/openvpn-status.log")


def _ensure_dir() -> None:
    OV_DIR.mkdir(parents=True, exist_ok=True)
    PKI_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OV_DIR, 0o700)
    os.chmod(PKI_DIR, 0o700)


def is_openvpn_available() -> bool:
    """Return True if openvpn executable exists on system."""
    return shutil.which("openvpn") is not None


def run_helper(cmd: str) -> Tuple[int, str]:
    """Execute privileged OpenVPN action via nmb-helper."""
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
        log.error("nmb-helper %s failed: %s", cmd, e)
        return 1, str(e)


def init_pki() -> bool:
    """Initialize ultra-fast, secure Elliptic Curve (prime256v1) PKI and tls-crypt."""
    _ensure_dir()
    ca_crt = PKI_DIR / "ca.crt"
    ca_key = PKI_DIR / "ca.key"
    server_crt = PKI_DIR / "server.crt"
    server_key = PKI_DIR / "server.key"
    tls_crypt = PKI_DIR / "tls-crypt.key"

    if ca_crt.exists() and ca_key.exists() and server_crt.exists() and server_key.exists() and tls_crypt.exists():
        return True

    log.info("initializing OpenVPN Elliptic Curve PKI...")
    try:
        # 1. Generate CA Key and Cert
        if not (ca_crt.exists() and ca_key.exists()):
            subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(ca_key)], check=True)
            subprocess.run(
                ["openssl", "req", "-new", "-x509", "-days", "3650", "-key", str(ca_key), "-out", str(ca_crt), "-subj", "/CN=NMB-OpenVPN-CA"],
                check=True,
            )

        # 2. Generate Server Key and Cert
        if not (server_crt.exists() and server_key.exists()):
            csr_path = PKI_DIR / "server.csr"
            subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(server_key)], check=True)
            subprocess.run(["openssl", "req", "-new", "-key", str(server_key), "-out", str(csr_path), "-subj", "/CN=nmb-vpn-server"], check=True)
            subprocess.run(
                ["openssl", "x509", "-req", "-days", "3650", "-in", str(csr_path), "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(server_crt)],
                check=True,
            )
            if csr_path.exists():
                csr_path.unlink()

        # 3. Generate TLS-Crypt Pre-Shared Key
        if not tls_crypt.exists():
            bin_ov = shutil.which("openvpn")
            if bin_ov:
                subprocess.run([bin_ov, "--genkey", "secret", str(tls_crypt)], check=True)
            else:
                # Fallback to random 2048-bit hex block
                tls_crypt.write_text(os.urandom(256).hex())

        # Set secure permissions
        for f in (ca_key, server_key, tls_crypt):
            if f.exists():
                os.chmod(f, 0o600)
        for f in (ca_crt, server_crt):
            if f.exists():
                os.chmod(f, 0o644)

        return True
    except Exception as e:
        log.error("failed to initialize OpenVPN PKI: %s", e)
        return False


def load_clients() -> List[Dict[str, Any]]:
    """Load stored OpenVPN client records."""
    _ensure_dir()
    if not CLIENTS_FILE.exists():
        return []
    try:
        data = json.loads(CLIENTS_FILE.read_text())
        return data.get("clients", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_clients(clients: List[Dict[str, Any]]) -> None:
    """Save client records atomically."""
    _ensure_dir()
    tmp_path = CLIENTS_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps({"clients": clients, "updated_at": time.time()}, indent=2))
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(CLIENTS_FILE)


def generate_server_config(proto: str = "udp", port: int = 1194, subnet: str = "10.9.0.0") -> str:
    """Generate server.conf file."""
    ca_crt = PKI_DIR / "ca.crt"
    server_crt = PKI_DIR / "server.crt"
    server_key = PKI_DIR / "server.key"
    tls_crypt = PKI_DIR / "tls-crypt.key"

    lines = [
        "# NetworkMeasureBox OpenVPN Server Configuration",
        f"port {port}",
        f"proto {proto}",
        "dev tun0",
        f"ca {ca_crt}",
        f"cert {server_crt}",
        f"key {server_key}",
        "dh none",
        f"tls-crypt {tls_crypt}",
        "topology subnet",
        f"server {subnet} 255.255.255.0",
        f"ifconfig-pool-persist {OV_DIR / 'ipp.txt'}",
        'push "redirect-gateway def1 bypass-dhcp"',
        'push "dhcp-option DNS 1.1.1.1"',
        'push "dhcp-option DNS 8.8.8.8"',
        "keepalive 10 120",
        "cipher AES-256-GCM",
        "data-ciphers AES-256-GCM:CHACHA20-POLY1305",
        "user nobody",
        "group nogroup",
        "persist-key",
        "persist-tun",
        f"status {STATUS_LOG} 5",
        "verb 3",
    ]
    return "\n".join(lines)


def apply_configuration(proto: str = "udp", port: int = 1194, subnet: str = "10.9.0.0") -> Tuple[bool, str]:
    """Write server config and apply via nmb-helper."""
    init_pki()
    conf_content = generate_server_config(proto=proto, port=port, subnet=subnet)
    OV_CONF.write_text(conf_content)
    os.chmod(OV_CONF, 0o600)

    rc, out = run_helper("openvpn-apply")
    if rc == 0:
        run_helper("vpn-nat")
        return True, "OpenVPN server started successfully."
    return False, f"Failed to start OpenVPN server: {out}"


def get_openvpn_status(proto: str = "udp", port: int = 1194) -> Dict[str, Any]:
    """Retrieve runtime status of OpenVPN server."""
    installed = is_openvpn_available()
    is_running = False

    try:
        proc = subprocess.run(["ip", "link", "show", "tun0"], capture_output=True, text=True, timeout=2, check=False)
        is_running = proc.returncode == 0
    except Exception:
        pass

    clients = load_clients()

    # Parse status log for connected clients
    connected_map: Dict[str, Dict[str, Any]] = {}
    if STATUS_LOG.exists():
        try:
            content = STATUS_LOG.read_text(errors="ignore")
            # CLIENT LIST section
            in_client_list = False
            for line in content.splitlines():
                if line.startswith("Common Name,"):
                    in_client_list = True
                    continue
                if line.startswith("ROUTING TABLE"):
                    in_client_list = False
                    break
                if in_client_list and "," in line:
                    parts = line.split(",")
                    if len(parts) >= 5:
                        cn = parts[0]
                        r_ip = parts[1]
                        b_recv = int(parts[2]) if parts[2].isdigit() else 0
                        b_sent = int(parts[3]) if parts[3].isdigit() else 0
                        connected_map[cn] = {
                            "real_address": r_ip,
                            "bytes_recv": b_recv,
                            "bytes_sent": b_sent,
                            "connected_since": parts[4],
                        }
        except Exception as e:
            log.debug("error reading openvpn status log: %s", e)

    client_list = []
    for c in clients:
        cn = c.get("name", "")
        conn = connected_map.get(cn, {})
        client_list.append({
            "name": cn,
            "created_at": c.get("created_at"),
            "is_online": cn in connected_map,
            "real_address": conn.get("real_address", "--"),
            "bytes_recv": conn.get("bytes_recv", 0),
            "bytes_sent": conn.get("bytes_sent", 0),
            "connected_since": conn.get("connected_since", "--"),
        })

    return {
        "installed": installed,
        "running": is_running,
        "interface": "tun0",
        "proto": proto,
        "port": port,
        "subnet": "10.9.0.0/24",
        "total_clients": len(clients),
        "online_clients": len(connected_map),
        "clients": client_list,
    }


def add_client(name: str) -> Dict[str, Any]:
    """Create a new OpenVPN client certificate and record."""
    init_pki()
    clean_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    if not clean_name:
        clean_name = f"client-{int(time.time())}"

    clients = load_clients()
    if any(c.get("name") == clean_name for c in clients):
        return {"status": "error", "message": f"Client '{clean_name}' already exists."}

    client_key = PKI_DIR / f"{clean_name}.key"
    client_csr = PKI_DIR / f"{clean_name}.csr"
    client_crt = PKI_DIR / f"{clean_name}.crt"
    ca_crt = PKI_DIR / "ca.crt"
    ca_key = PKI_DIR / "ca.key"

    try:
        subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(client_key)], check=True)
        subprocess.run(["openssl", "req", "-new", "-key", str(client_key), "-out", str(client_csr), "-subj", f"/CN={clean_name}"], check=True)
        subprocess.run(
            ["openssl", "x509", "-req", "-days", "3650", "-in", str(client_csr), "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(client_crt)],
            check=True,
        )
        if client_csr.exists():
            client_csr.unlink()
        os.chmod(client_key, 0o600)
    except Exception as e:
        return {"status": "error", "message": f"OpenSSL certificate creation failed: {e}"}

    new_client = {
        "name": clean_name,
        "created_at": time.time(),
    }
    clients.append(new_client)
    save_clients(clients)

    return {"status": "ok", "client": new_client, "message": f"Client '{clean_name}' created successfully."}


def delete_client(name: str) -> bool:
    """Delete an OpenVPN client certificate and record."""
    clients = load_clients()
    initial_len = len(clients)
    clients = [c for c in clients if c.get("name") != name]
    if len(clients) == initial_len:
        return False
    save_clients(clients)

    for ext in (".key", ".crt"):
        f = PKI_DIR / f"{name}{ext}"
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass
    return True


def get_unified_ovpn_profile(name: str, endpoint_host: str = "", proto: str = "udp", port: int = 1194) -> Optional[str]:
    """Generate complete, standalone unified .ovpn profile with inline certificates."""
    init_pki()
    ca_crt = PKI_DIR / "ca.crt"
    tls_crypt = PKI_DIR / "tls-crypt.key"
    client_crt = PKI_DIR / f"{name}.crt"
    client_key = PKI_DIR / f"{name}.key"

    if not (ca_crt.exists() and tls_crypt.exists() and client_crt.exists() and client_key.exists()):
        return None

    if not endpoint_host:
        from nmb.netd.duckdns import detect_public_ip
        endpoint_host = detect_public_ip() or "YOUR_PUBLIC_IP"

    ca_text = ca_crt.read_text().strip()
    tls_text = tls_crypt.read_text().strip()
    crt_text = client_crt.read_text().strip()
    key_text = client_key.read_text().strip()

    ovpn = f"""# NetworkMeasureBox Unified OpenVPN Client Profile: {name}
client
dev tun
proto {proto}
remote {endpoint_host} {port}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
data-ciphers AES-256-GCM:CHACHA20-POLY1305
verb 3

<ca>
{ca_text}
</ca>

<cert>
{crt_text}
</cert>

<key>
{key_text}
</key>

<tls-crypt>
{tls_text}
</tls-crypt>
"""
    return ovpn
