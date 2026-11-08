"""Share the box's Wi-Fi internet on its LAN port, with its own DHCP (``[wifi_share]``).

When the box is on Wi-Fi and its Ethernet port has no upstream (no default route through it and no
other DHCP server answering on it), ``nmb-netd`` (root) makes the port a small router:

* the port gets ``address`` (192.168.77.1/24 by default);
* a dnsmasq instance of its own serves DHCP on that port only (``--port=0``: no DNS server, so it
  never clashes with the ad blocker; clients get the DNS servers the Wi-Fi uses);
* an nftables table ``nmb_wifishare`` masquerades the subnet out of the Wi-Fi interface.

It never serves DHCP on a network that has its own: before it starts, and every minute while it
runs, it sends a DHCPDISCOVER on the port and stops if any server other than itself answers, or if
the port gets a default route. That makes it safe to leave on: plug the cable into the home router
and the box goes back to being a client there.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import random
import shutil
import signal
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.wifi_share")

STATE_FILE = Path("/run/nmb/wifi_share.json")
PID_FILE = Path("/run/nmb/wifi_share_dnsmasq.pid")
LEASE_FILE = Path("/run/nmb/wifi_share.leases")
NFT_TABLE = "nmb_wifishare"
PROBE_EVERY_SEC = 60.0

_last_probe = 0.0
_last_probe_servers: List[str] = []
_last_carrier: Optional[bool] = None


def _bin(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for d in ("/usr/sbin", "/sbin", "/usr/bin"):
        if Path(d, name).exists():
            return str(Path(d, name))
    return None


def _run(cmd: List[str], timeout: float = 10.0, stdin: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=stdin)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def _settings(cfg: Any) -> Dict[str, Any]:
    ws = getattr(cfg, "wifi_share", None)
    net = ipaddress.ip_interface(str(getattr(ws, "address", "192.168.77.1/24") or "192.168.77.1/24"))
    hosts = list(net.network.hosts())
    return {
        "enabled": bool(getattr(ws, "enabled", False)),
        "lan": str(getattr(ws, "lan_interface", "eth0") or "eth0"),
        "address": str(net),
        "ip": str(net.ip),
        "network": str(net.network),
        "start": str(hosts[min(99, len(hosts) - 2)]) if len(hosts) > 2 else str(hosts[0]),
        "end": str(hosts[min(199, len(hosts) - 1)]),
    }


def _has_carrier(iface: str) -> bool:
    try:
        return Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
    except OSError:
        return False


def _default_route_dev(iface: str) -> bool:
    rc, out, _ = _run(["ip", "-4", "route", "show", "default", "dev", iface], timeout=4)
    return rc == 0 and "default" in out


def _addresses(iface: str) -> List[str]:
    rc, out, _ = _run(["ip", "-4", "-o", "addr", "show", "dev", iface], timeout=4)
    res = []
    for line in out.splitlines() if rc == 0 else []:
        parts = line.split()
        if "inet" in parts:
            res.append(parts[parts.index("inet") + 1])
    return res


def _wifi_dns() -> List[str]:
    servers = []
    for path in ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf"):
        try:
            for line in Path(path).read_text().splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    ip = parts[1]
                    try:
                        a = ipaddress.ip_address(ip)
                    except ValueError:
                        continue
                    if a.version == 4 and not a.is_loopback and ip not in servers:
                        servers.append(ip)
        except OSError:
            continue
        if servers:
            break
    return servers[:2] or ["1.1.1.1", "9.9.9.9"]


def _mac(iface: str) -> bytes:
    try:
        return bytes.fromhex(Path(f"/sys/class/net/{iface}/address").read_text().strip().replace(":", ""))
    except (OSError, ValueError):
        return os.urandom(6)


def build_discover(mac: bytes, xid: int) -> bytes:
    """A minimal DHCPDISCOVER (RFC 2131) asking for a broadcast reply."""
    pkt = struct.pack("!BBBBIHH4s4s4s4s16s64s128s", 1, 1, 6, 0, xid, 0, 0x8000,
                      b"\0" * 4, b"\0" * 4, b"\0" * 4, b"\0" * 4, mac.ljust(16, b"\0"), b"\0" * 64, b"\0" * 128)
    return pkt + b"\x63\x82\x53\x63" + b"\x35\x01\x01" + b"\x37\x03\x01\x03\x06" + b"\xff"


def parse_offer_server(data: bytes, xid: int) -> Optional[str]:
    """The server identifier (option 54) of a DHCPOFFER for this transaction, or None."""
    if len(data) < 240 or data[0] != 2 or struct.unpack("!I", data[4:8])[0] != xid or data[236:240] != b"\x63\x82\x53\x63":
        return None
    i, msg_type, server = 240, None, None
    while i < len(data):
        code = data[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        if i + 1 >= len(data):
            break
        length = data[i + 1]
        val = data[i + 2:i + 2 + length]
        if code == 53 and length == 1:
            msg_type = val[0]
        elif code == 54 and length == 4:
            server = socket.inet_ntoa(val)
        i += 2 + length
    if msg_type != 2:
        return None
    return server or socket.inet_ntoa(data[20:24])


def probe_dhcp_servers(iface: str, timeout: float = 3.0) -> List[str]:
    """Send a DHCPDISCOVER on ``iface`` and return the servers that offer an address (needs root)."""
    xid = random.getrandbits(32)
    servers: List[str] = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, 25, iface.encode() + b"\0")  # SO_BINDTODEVICE
        s.bind(("0.0.0.0", 68))
        s.settimeout(0.5)
        s.sendto(build_discover(_mac(iface), xid), ("255.255.255.255", 67))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, _ = s.recvfrom(1500)
            except socket.timeout:
                continue
            srv = parse_offer_server(data, xid)
            if srv and srv not in servers:
                servers.append(srv)
    except OSError as e:
        log.debug("dhcp probe on %s failed: %s", iface, e)
    finally:
        s.close()
    return servers


def _state() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def is_active() -> bool:
    return bool(_state().get("active"))


def shared_lan_interface() -> Optional[str]:
    """The LAN port the box is sharing Wi-Fi on; it is no uplink for speed tests then."""
    st = _state()
    return st.get("lan") if st.get("active") else None


def _write_state(**kw: Any) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(dict(kw, ts=int(time.time()))))
    except OSError as e:
        log.debug("wifi share state: %s", e)


def _dnsmasq_running() -> bool:
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _start_dnsmasq(s: Dict[str, Any], dns: List[str]) -> bool:
    dnsmasq = _bin("dnsmasq")
    if not dnsmasq:
        log.warning("wifi share: dnsmasq not installed")
        return False
    cmd = [dnsmasq, "--port=0", f"--interface={s['lan']}", "--bind-interfaces", "--except-interface=lo",
           f"--dhcp-range={s['start']},{s['end']},255.255.255.0,12h",
           f"--dhcp-option=3,{s['ip']}", f"--dhcp-option=6,{','.join(dns)}",
           f"--dhcp-leasefile={LEASE_FILE}", f"--pid-file={PID_FILE}",
           "--conf-file=/dev/null", "--log-facility=-"]
    rc, out, err = _run(cmd, timeout=10)
    if rc != 0:
        log.warning("wifi share: dnsmasq did not start: %s", (err or out).strip()[:200])
    return rc == 0


def _stop_dnsmasq() -> None:
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def nft_ruleset(network: str, lan: str, wifi: str) -> str:
    return f"""table ip {NFT_TABLE} {{
  chain postrouting {{ type nat hook postrouting priority 100; policy accept;
    ip saddr {network} oifname "{wifi}" masquerade
  }}
  chain forward {{ type filter hook forward priority 0; policy accept;
    iifname "{lan}" oifname "{wifi}" accept
    iifname "{wifi}" oifname "{lan}" ct state established,related accept
    iifname "{wifi}" oifname "{lan}" drop
  }}
}}
"""


def _apply_nat(s: Dict[str, Any], wifi: str) -> bool:
    nft = _bin("nft")
    if not nft:
        log.warning("wifi share: nft not installed")
        return False
    _run([nft, "delete", "table", "ip", NFT_TABLE], timeout=5)
    rc, _, err = _run([nft, "-f", "-"], timeout=5, stdin=nft_ruleset(s["network"], s["lan"], wifi))
    if rc != 0:
        log.warning("wifi share: nft rules failed: %s", err.strip()[:200])
        return False
    try:
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1")
    except OSError:
        pass
    return True


def stop(cfg: Any, reason: str = "") -> None:
    s = _settings(cfg)
    st = _state()
    lan = st.get("lan") or s["lan"]
    _stop_dnsmasq()
    nft = _bin("nft")
    if nft:
        _run([nft, "delete", "table", "ip", NFT_TABLE], timeout=5)
    addr = st.get("address") or s["address"]
    if addr in _addresses(lan):
        _run(["ip", "addr", "del", addr, "dev", lan], timeout=4)
    if st.get("active"):
        log.info("wifi share stopped on %s%s", lan, f": {reason}" if reason else "")
    _write_state(active=False, lan=lan, reason=reason)


def sync(cfg: Any) -> Dict[str, Any]:
    """Start, keep or stop sharing; called by nmb-netd every loop (root)."""
    global _last_probe, _last_probe_servers, _last_carrier
    s = _settings(cfg)
    st = _state()
    from nmb.netd.wifi_uplink import uplink_interface, _ipv4_and_gateway
    wifi = uplink_interface(cfg)
    wifi_ip, wifi_gw = _ipv4_and_gateway(wifi) if wifi else (None, None)

    def off(code: str, reason: str) -> Dict[str, Any]:
        if st.get("active") or _dnsmasq_running():
            stop(cfg, reason)
        _write_state(active=False, lan=s["lan"], reason=reason, code=code)
        return {"active": False, "reason": reason, "code": code}

    if not s["enabled"]:
        return off("off", "turned off")
    if s["lan"] == wifi:
        return off("same_iface", "the LAN port is the Wi-Fi interface")
    if not (wifi_ip and wifi_gw):
        return off("no_wifi", "Wi-Fi has no internet connection")
    if not Path(f"/sys/class/net/{s['lan']}").exists():
        return off("no_port", f"{s['lan']} does not exist")
    if _default_route_dev(s["lan"]):
        return off("own_internet", f"{s['lan']} has its own internet connection")

    now = time.monotonic()
    carrier = _has_carrier(s["lan"])
    if carrier and _last_carrier is False:
        # A cable was just plugged in, maybe into another router: stop serving first, then look.
        _stop_dnsmasq()
        _last_probe = 0.0
    _last_carrier = carrier
    if carrier and now - _last_probe >= PROBE_EVERY_SEC:
        _last_probe = now
        _last_probe_servers = [x for x in probe_dhcp_servers(s["lan"]) if x != s["ip"]]
    if _last_probe_servers:
        # Another DHCP server on this cable: the box must not hand out addresses there.
        return off("other_dhcp", f"another DHCP server answers on {s['lan']} ({', '.join(_last_probe_servers)})")

    if s["address"] not in _addresses(s["lan"]):
        _run(["ip", "link", "set", s["lan"], "up"], timeout=4)
        _run(["ip", "addr", "add", s["address"], "dev", s["lan"]], timeout=4)
    nft = _bin("nft")
    rc, out, _ = _run([nft, "list", "table", "ip", NFT_TABLE], timeout=5) if nft else (1, "", "")
    if rc != 0 or f'oifname "{wifi}"' not in out or s["network"] not in out:
        _apply_nat(s, wifi)
    if not _dnsmasq_running():
        _start_dnsmasq(s, _wifi_dns())
    if not st.get("active"):
        log.info("wifi share started: %s (%s) -> %s, DHCP %s-%s", s["lan"], s["address"], wifi, s["start"], s["end"])
    _write_state(active=True, lan=s["lan"], address=s["address"], wifi=wifi, reason="")
    return {"active": True, "lan": s["lan"], "wifi": wifi}


def leases() -> List[Dict[str, str]]:
    out = []
    try:
        for line in LEASE_FILE.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                out.append({"expires": parts[0], "mac": parts[1], "ip": parts[2], "hostname": "" if parts[3] == "*" else parts[3]})
    except OSError:
        pass
    return out


def wired_ports() -> List[str]:
    """Physical wired ports (they have a device and no radio)."""
    base = Path("/sys/class/net")
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir()
                  if (p / "device").exists() and not (p / "wireless").exists() and not (p / "phy80211").exists())


def status(cfg: Any) -> Dict[str, Any]:
    s = _settings(cfg)
    st = _state()
    return {
        "enabled": s["enabled"], "lan_interface": s["lan"], "address": s["address"],
        "dhcp_range": f"{s['start']} - {s['end']}",
        "active": bool(st.get("active")), "reason": st.get("reason") or "", "code": st.get("code") or "",
        "dhcp_servers": list(_last_probe_servers),
        "wifi": st.get("wifi"), "carrier": _has_carrier(s["lan"]),
        "leases": leases() if st.get("active") else [],
        "ports": wired_ports(),
    }
