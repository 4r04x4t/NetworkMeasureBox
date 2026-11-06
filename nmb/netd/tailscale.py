"""
Tailscale Mesh VPN integration for NetworkMeasureBox.

Provides secure remote management access to the NetworkMeasureBox Web UI and SSH
without requiring public port forwarding, dynamic DNS, or carrier-grade NAT (CGNAT) traversal.
Strictly configured for management plane access: does NOT replace upstream default routes
or act as an exit node (--accept-routes=false --advertise-exit-node=false).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.netd.tailscale")

_tailscale_lock = threading.Lock()
_cached_auth_url: str = ""


def is_tailscale_installed() -> bool:
    """Check if tailscale and tailscaled binaries exist on PATH."""
    return bool(shutil.which("tailscale"))


def is_tailscaled_active() -> bool:
    """Check if tailscaled systemd service or daemon process is active."""
    if shutil.which("systemctl"):
        try:
            res = subprocess.run(
                ["systemctl", "is-active", "tailscaled"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return res.stdout.strip() == "active"
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    # Fallback to pgrep
    try:
        res = subprocess.run(["pgrep", "-x", "tailscaled"], capture_output=True, timeout=2)
        return res.returncode == 0
    except Exception:
        return False


def get_tailscale_status() -> Dict[str, Any]:
    """Retrieve structured real-time status of the Tailscale daemon and node."""
    global _cached_auth_url

    installed = is_tailscale_installed()
    active = is_tailscaled_active()

    status_data: Dict[str, Any] = {
        "installed": installed,
        "active": active,
        "backend_state": "NotInstalled" if not installed else ("Stopped" if not active else "NoState"),
        "tailscale_ips": [],
        "tailscale_ipv4": "",
        "tailscale_ipv6": "",
        "magic_dns_name": "",
        "dns_name": "",
        "hostname": "",
        "node_id": "",
        "auth_url": _cached_auth_url,
        "peers_count": 0,
        "peers": [],
        "web_url": "",
        "version": "",
    }

    if not installed or not active:
        return status_data

    try:
        res = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw = json.loads(res.stdout)
            status_data["version"] = raw.get("Version", "")
            status_data["backend_state"] = raw.get("BackendState", "Unknown")

            auth_url = raw.get("AuthURL", "")
            if auth_url:
                _cached_auth_url = auth_url
                status_data["auth_url"] = auth_url
            elif status_data["backend_state"] == "Running":
                _cached_auth_url = ""
                status_data["auth_url"] = ""

            ips = raw.get("TailscaleIPs", []) or []
            status_data["tailscale_ips"] = ips
            for ip in ips:
                if ":" in ip and not status_data["tailscale_ipv6"]:
                    status_data["tailscale_ipv6"] = ip
                elif "." in ip and not status_data["tailscale_ipv4"]:
                    status_data["tailscale_ipv4"] = ip

            self_info = raw.get("Self", {}) or {}
            dns_name = self_info.get("DNSName", "").rstrip(".")
            status_data["magic_dns_name"] = dns_name
            status_data["dns_name"] = dns_name
            status_data["hostname"] = self_info.get("HostName", "")
            status_data["node_id"] = str(self_info.get("ID", ""))

            if status_data["tailscale_ipv4"]:
                status_data["web_url"] = f"http://{status_data['tailscale_ipv4']}/"

            # Peers list
            peers_raw = raw.get("Peer", {}) or {}
            peer_list: List[Dict[str, Any]] = []
            for p_id, p in peers_raw.items():
                p_ips = p.get("TailscaleIPs", []) or []
                v4 = next((x for x in p_ips if "." in x), "")
                peer_list.append({
                    "name": p.get("HostName", "Unknown"),
                    "HostName": p.get("HostName", "Unknown"),
                    "dns_name": p.get("DNSName", "").rstrip("."),
                    "DNSName": p.get("DNSName", "").rstrip("."),
                    "ip": v4,
                    "TailscaleIPs": p_ips,
                    "os": p.get("OS", "unknown"),
                    "OS": p.get("OS", "unknown"),
                    "online": bool(p.get("Online", False)),
                    "Online": bool(p.get("Online", False)),
                    "last_seen": p.get("LastSeen", ""),
                })
            status_data["peers_count"] = len(peer_list)
            status_data["peers"] = peer_list[:10]  # First 10 peers
    except Exception as e:
        log.debug("error querying tailscale status: %s", e)

    return status_data


def tailscale_up(
    auth_key: str = "",
    hostname: str = "networkmeasurebox",
    accept_routes: bool = False,
    advertise_exit_node: bool = False,
    accept_dns: bool = False,
    ssh: bool = True,
) -> Dict[str, Any]:
    """
    Connect device to Tailscale network.
    Enforces management-only access (--accept-routes=false --advertise-exit-node=false)
    so upstream telemetry and local routing remain unaffected.
    """
    global _cached_auth_url

    if not is_tailscale_installed():
        return {"ok": False, "error": "Tailscale is not installed on this system."}

    # Ensure tailscaled service is started
    if shutil.which("systemctl") and not is_tailscaled_active():
        try:
            subprocess.run(["systemctl", "start", "tailscaled"], check=False, timeout=5)
        except Exception as e:
            log.warning("failed to start tailscaled service: %s", e)

    cmd = [
        "tailscale",
        "up",
        "--reset",
        f"--accept-routes={str(accept_routes).lower()}",
        f"--advertise-exit-node={str(advertise_exit_node).lower()}",
        f"--accept-dns={str(accept_dns).lower()}",
    ]
    if ssh:
        cmd.append("--ssh")
    if hostname.strip():
        # sanitize hostname: alphanumeric and dashes only
        clean_host = re.sub(r"[^a-zA-Z0-9-]", "", hostname.strip())
        if clean_host:
            cmd.append(f"--hostname={clean_host}")
    if auth_key.strip():
        cmd.append(f"--authkey={auth_key.strip()}")

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=4,
        )
        combined = f"{res.stdout}\n{res.stderr}"

        # Check for login URL
        url_match = re.search(r"(https://login\.tailscale\.com/a/[a-zA-Z0-9]+)", combined)
        if url_match:
            _cached_auth_url = url_match.group(1)
            return {
                "ok": True,
                "needs_login": True,
                "auth_url": _cached_auth_url,
                "message": "Interactive authentication required. Click the link to authorize this device.",
            }

        if res.returncode == 0:
            _cached_auth_url = ""
            return {"ok": True, "message": "Tailscale connected successfully!"}
        else:
            return {"ok": False, "error": res.stderr.strip() or res.stdout.strip()}
    except subprocess.TimeoutExpired:
        # Timeout often happens when tailscale up is waiting for interactive login
        # Check if auth_url is available from status
        st = get_tailscale_status()
        if st.get("auth_url"):
            return {
                "ok": True,
                "needs_login": True,
                "auth_url": st["auth_url"],
                "message": "Authorization URL generated.",
            }
        return {"ok": False, "error": "Tailscale connection command timed out."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tailscale_down() -> Dict[str, Any]:
    """Disconnect from Tailscale mesh network."""
    global _cached_auth_url
    if not is_tailscale_installed():
        return {"ok": False, "error": "Tailscale is not installed."}

    try:
        res = subprocess.run(["tailscale", "down"], capture_output=True, text=True, timeout=10)
        _cached_auth_url = ""
        if res.returncode == 0:
            return {"ok": True, "message": "Tailscale disconnected."}
        return {"ok": False, "error": res.stderr.strip() or res.stdout.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tailscale_logout() -> Dict[str, Any]:
    """Log out completely and unregister node from Tailnet."""
    global _cached_auth_url
    if not is_tailscale_installed():
        return {"ok": False, "error": "Tailscale is not installed."}

    try:
        res = subprocess.run(["tailscale", "logout"], capture_output=True, text=True, timeout=10)
        _cached_auth_url = ""
        if res.returncode == 0:
            return {"ok": True, "message": "Tailscale logged out successfully."}
        return {"ok": False, "error": res.stderr.strip() or res.stdout.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
