"""How the box was connected when it measured (owner, 2026-11-10).

A result means something else when the box sat behind another router than when it held the ISP's
address itself, so every speed test, outage and ping minute carries three stated facts:

- ``box_mode``: the box's operating mode then (``standalone`` = a client on an existing network,
  ``mode_a`` = router mode, ``mode_b`` = transparent bridge);
- ``uplink_kind``: the link the measurement used (``ethernet``, ``pppoe``, ``wifi``, ``usb``,
  ``bridge``, ``passthrough``, ``lag``);
- ``isp_path``: whether the box was directly on the ISP (``direct_pppoe``: its own PPPoE session;
  ``direct_public`` / ``direct_cgnat``: a public or carrier-grade NAT address on that link) or behind a
  router (``behind_router``: a private address, so another router - the customer's or the ISP's own -
  stood between the box and the ISP and may limit the results).

Anything that cannot be told for sure is None ("unknown"), never a guess. The mode alone proves
nothing about the position: standalone also runs on an ISP line that hands out a public address by
DHCP, and router mode can sit behind a home router (double NAT); the position comes from the address.
A global IPv6 address proves nothing either (every device behind a home router has one), so only IPv4
decides. ``setup_source`` says how a row's facts were obtained: ``recorded`` when it was measured,
``changed`` when the box's mode changed while it measured, ``derived`` when it was reconstructed later
from the event log and the stored interface and address.
"""
from __future__ import annotations

import bisect
import ipaddress
import json
import logging
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("nmb.common.net_setup")

MODES = ("standalone", "mode_a", "mode_b")
UPLINK_KINDS = ("ethernet", "pppoe", "wifi", "usb", "bridge", "passthrough", "lag")
ISP_PATHS = ("direct_pppoe", "direct_public", "direct_cgnat", "behind_router")
SOURCES = ("recorded", "changed", "derived")

SYS_CLASS_NET = Path("/sys/class/net")
PASSTHROUGH_BRIDGE = "br-pass"          # nmb/netd/lan_topology.py BRIDGE_NAME
ROUTER_LAN_BRIDGE = "br-lan"            # the box's own LAN in router mode: never a measuring uplink
ARPHRD_PPP = 512
CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NOT_UPLINKS = ("lo", "tailscale", "wg", "tun", "tap", "docker", "veth", "virbr", "zt")

SCHEMA = """
CREATE TABLE IF NOT EXISTS network_state (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,       -- from this moment on (ms, UTC)
    box_mode    TEXT,                   -- standalone / mode_a / mode_b; NULL = unknown (netd stopped, switching)
    iface       TEXT,                   -- the box's link towards the internet
    uplink_kind TEXT,
    isp_path    TEXT,
    source      TEXT NOT NULL,          -- recorded / derived
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS ix_network_state_ts ON network_state(ts);
"""


# ------------------------------------------------------------------------------------- classification
def address_class(value: object) -> Optional[str]:
    """'public', 'cgnat' or 'private' for an IPv4 address; None for anything else (IPv6, link-local, junk)."""
    if not value:
        return None
    text = str(value).strip().split("/", 1)[0].split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if addr.version != 4 or addr.is_link_local or addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        return None
    from nmb.common.netaddr import global_ip
    if global_ip(text):
        return "public"
    if addr in CGNAT:
        return "cgnat"
    if addr.is_private:
        return "private"
    return None


def isp_path_for(uplink_kind: Optional[str], ipv4: Optional[str]) -> Optional[str]:
    """Directly on the ISP or behind a router, from the link's own IPv4 address (None when not known)."""
    cls = address_class(ipv4)
    if cls is None:
        return None
    if uplink_kind == "pppoe":
        return "direct_pppoe"           # the box's own PPPoE session: nothing between it and the ISP
    return {"public": "direct_public", "cgnat": "direct_cgnat", "private": "behind_router"}[cls]


def uplink_kind_by_name(iface: Optional[str], box_mode: Optional[str] = None,
                        usb_ifaces: Sequence[str] = ()) -> Optional[str]:
    """The link kind from a stored interface name alone (for old rows, where the live system is gone).

    Only names that say it for sure: an unknown name or the box's own router LAN bridge gives None.
    usb_ifaces: interfaces the event log names as USB tethers (a tether is called eth1 or usb0, so its
    name proves nothing). The stored line type 'fwa' is no proof of USB either: it is also the
    configured type of an ordinary fixed-wireless home line.
    """
    if not iface:
        return None
    name = iface.lower()
    if iface in usb_ifaces or name.startswith(("usb", "wwan")):
        return "usb"
    if name.startswith("ppp"):
        return "pppoe"
    if name.startswith(("wlan", "wlp", "wlx")):
        return "wifi"
    if name == PASSTHROUGH_BRIDGE:
        return "passthrough"
    if name.startswith("bond"):
        return "lag"
    if name.startswith("br"):
        return "bridge" if box_mode == "mode_b" and name != ROUTER_LAN_BRIDGE else None
    if name.startswith(("eth", "en")):
        return "ethernet"
    return None


def uplink_kind_live(iface: Optional[str], box_mode: Optional[str] = None,
                     sys_class_net: Path = SYS_CLASS_NET) -> Optional[str]:
    """The link kind of a live interface from sysfs (type, wireless, bonding, bridge, USB driver)."""
    if not iface:
        return None
    name = iface.lower()
    if name.startswith(_NOT_UPLINKS):
        return None
    base = sys_class_net / iface
    try:
        if int((base / "type").read_text().strip()) == ARPHRD_PPP:
            return "pppoe"
    except (OSError, ValueError):
        if name.startswith("ppp"):
            return "pppoe"
    if (base / "wireless").exists() or (base / "phy80211").exists():
        return "wifi"
    if (base / "bonding").exists() or name.startswith("bond"):
        return "lag"
    if (base / "bridge").exists() or name.startswith("br"):
        if name == PASSTHROUGH_BRIDGE:
            return "passthrough"
        return "bridge" if box_mode == "mode_b" and name != ROUTER_LAN_BRIDGE else None
    try:
        from nmb.netd.interfaces import usb_tether_kind
        if usb_tether_kind(iface):
            return "usb"
    except Exception:
        log.debug("usb tether check failed for %s", iface, exc_info=True)
    if base.exists():
        return "ethernet"               # a wired port, a VLAN on one, or a USB Ethernet dongle
    return uplink_kind_by_name(iface, box_mode)


# ------------------------------------------------------------------------------------- live reads
def _ip_json(args: Sequence[str]) -> list:
    ip_bin = shutil.which("ip") or "/usr/sbin/ip"
    try:
        res = subprocess.run([ip_bin, "-j", *args], capture_output=True, text=True, timeout=5, check=False)
        return json.loads(res.stdout) if res.returncode == 0 and res.stdout.strip() else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def iface_ipv4(iface: Optional[str]) -> Optional[str]:
    """The first IPv4 address of an interface (not link-local), or None."""
    if not iface:
        return None
    for item in _ip_json(["-4", "addr", "show", "dev", iface]):
        for info in item.get("addr_info", []):
            local = info.get("local")
            if local and not str(local).startswith("169.254."):
                return str(local)
    return None


def default_route_iface() -> Optional[str]:
    """The interface of the IPv4 default route with the lowest metric."""
    routes = _ip_json(["-4", "route", "show", "default"])
    routes.sort(key=lambda r: r.get("metric", 0) or 0)
    for r in routes:
        if r.get("dev"):
            return str(r["dev"])
    return None


def active_mode(conn: sqlite3.Connection) -> Tuple[Optional[str], Optional[int]]:
    """(mode, switch time in ms) from kv active_mode, or (None, None)."""
    try:
        row = conn.execute("SELECT v, ts FROM kv WHERE k = 'active_mode'").fetchone()
    except sqlite3.Error:
        return None, None
    if not row or not row[0]:
        return None, None
    return (row[0] if row[0] in MODES else None), (int(row[1]) if row[1] is not None else None)


def describe_link(iface: Optional[str], bound_ip: Optional[str] = None, box_mode: Optional[str] = None,
                  ipv4_reader=None, kind_reader=None, default_iface=None) -> Dict[str, Optional[str]]:
    """{'iface', 'uplink_kind', 'isp_path'} of the link a measurement left through, read live.

    With no address to bind to, the engines leave through the default route, so that is the link
    described then (not the interface that was asked for). The position comes from the link's IPv4
    address also when the test itself used IPv6: a private IPv4 on the link means a router upstream,
    whichever address family a test then takes through it.
    """
    ipv4_reader = ipv4_reader or iface_ipv4
    kind_reader = kind_reader or uplink_kind_live
    default_iface = default_iface or default_route_iface
    egress = iface if bound_ip else (default_iface() or iface)
    ipv4 = bound_ip if address_class(bound_ip) else (ipv4_reader(egress) if egress else None)
    kind = kind_reader(egress, box_mode) if egress else None
    return {"iface": egress, "uplink_kind": kind, "isp_path": isp_path_for(kind, ipv4) if kind else None}


def describe_iface(iface: Optional[str], box_mode: Optional[str] = None, ipv4_reader=None,
                   kind_reader=None) -> Dict[str, Optional[str]]:
    """{'iface', 'uplink_kind', 'isp_path'} of a known link (netd's WAN), from its own IPv4 address."""
    ipv4_reader = ipv4_reader or iface_ipv4
    kind_reader = kind_reader or uplink_kind_live
    kind = kind_reader(iface, box_mode) if iface else None
    return {"iface": iface, "uplink_kind": kind,
            "isp_path": isp_path_for(kind, ipv4_reader(iface)) if kind else None}


def capture(conn: sqlite3.Connection, iface: Optional[str], bound_ip: Optional[str], **readers) -> Dict[str, Any]:
    """The setup at the start of a measurement: mode (with its switch time) and the link."""
    mode, mode_ts = active_mode(conn)
    facts = describe_link(iface, bound_ip, mode, **readers)
    facts.update(box_mode=mode, mode_ts=mode_ts)
    return facts


def switched_to_other_mode(conn: sqlite3.Connection, mode: Optional[str], start_ms: int, end_ms: int) -> bool:
    """A switch to another mode between start and end (a netd restart into the same mode is none)."""
    try:
        rows = conn.execute("SELECT detail FROM event WHERE kind = 'mode_change' AND ts > ? AND ts <= ?",
                            (start_ms, end_ms)).fetchall()
    except sqlite3.Error:
        return False
    for (detail,) in rows:
        parts = (detail or "").split(" to ", 1)
        target = parts[1].split(":", 1)[0].strip() if len(parts) == 2 else ""
        if target in MODES and target != mode:
            return True
    return False


def finish(conn: sqlite3.Connection, setup: Dict[str, Any], started_ms: int,
           now_ms: Optional[int] = None) -> Dict[str, Any]:
    """The facts to store when the measurement ends: 'changed' when the mode switched meanwhile."""
    now_ms = now_ms or int(time.time() * 1000)
    mode, _ = active_mode(conn)
    changed = (mode != setup.get("box_mode")) or switched_to_other_mode(conn, setup.get("box_mode"), started_ms, now_ms)
    return {"box_mode": setup.get("box_mode"), "uplink_kind": setup.get("uplink_kind"),
            "isp_path": setup.get("isp_path"), "setup_source": "changed" if changed else "recorded"}


# ------------------------------------------------------------------------------------- history
def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def record_state(conn: sqlite3.Connection, state: Dict[str, Optional[str]], ts: Optional[int] = None,
                 source: str = "recorded", detail: str = "") -> bool:
    """Append a network_state row when it differs from the newest one; True when written.

    Called by netd on every loop pass, so only a change is written (mode, link, kind or path).
    """
    ts = ts or int(time.time() * 1000)
    key = tuple(state.get(k) for k in ("box_mode", "iface", "uplink_kind", "isp_path"))
    try:
        last = conn.execute("SELECT box_mode, iface, uplink_kind, isp_path FROM network_state "
                            "WHERE source = 'recorded' ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        ensure_schema(conn)
        last = None
    if last is not None and tuple(last) == key and source == "recorded":
        return False
    conn.execute("INSERT INTO network_state (ts, box_mode, iface, uplink_kind, isp_path, source, detail) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)", (ts, *key, source, (detail or "")[:300]))
    return True


def netd_link(box_mode: Optional[str], details: Dict[str, Any], cfg_network: Any = None,
              measuring_iface=None) -> Optional[str]:
    """The link the measurements leave through, as netd sees it in a mode.

    In standalone that is the link the probe and the speed tests choose (measuring_iface: wired first, or
    the pinned Wi-Fi or USB link), which is not always the default route; the default route only when
    that gives nothing.
    """
    if box_mode == "mode_a":
        return details.get("wan_interface") or None
    if box_mode == "mode_b":
        return details.get("bridge") or getattr(cfg_network, "bridge_interface", None) or None
    chosen = None
    if measuring_iface is not None:
        try:
            chosen = measuring_iface()
        except Exception:
            log.debug("measuring link not determined", exc_info=True)
    return chosen or default_route_iface() or details.get("interface") or None


class Timeline:
    """The network_state history, for "what was the setup at time t" without a query per row."""

    def __init__(self, rows: List[Tuple[int, Optional[str], Optional[str], Optional[str], str]]):
        self.rows = sorted(rows, key=lambda r: r[0])
        self.times = [r[0] for r in self.rows]

    @classmethod
    def load(cls, conn: sqlite3.Connection, end_ms: Optional[int] = None) -> "Timeline":
        try:
            q = "SELECT ts, box_mode, uplink_kind, isp_path, source FROM network_state"
            args: tuple = ()
            if end_ms is not None:
                q += " WHERE ts <= ?"
                args = (end_ms,)
            rows = [tuple(r) for r in conn.execute(q + " ORDER BY ts, id", args).fetchall()]
        except sqlite3.Error:
            rows = []
        return cls(rows)

    def at(self, ts: int) -> Dict[str, Optional[str]]:
        i = bisect.bisect_right(self.times, ts) - 1
        if i < 0:
            return {"box_mode": None, "uplink_kind": None, "isp_path": None, "setup_source": None}
        _, mode, kind, path, source = self.rows[i]
        return {"box_mode": mode, "uplink_kind": kind, "isp_path": path, "setup_source": source}

    def periods(self, start_ms: int, end_ms: int, absorb_unknown_ms: int = 0) -> List[Dict[str, Any]]:
        """The setups of [start, end] as periods; consecutive equal setups are merged.

        absorb_unknown_ms: an unknown gap shorter than this between two equal setups (a netd restart
        into the same mode) is not shown as its own period; the raw history keeps it.
        """
        keys = ("box_mode", "uplink_kind", "isp_path")
        out: List[Dict[str, Any]] = []
        cur = dict(self.at(start_ms), start_ts=start_ms)
        for ts, mode, kind, path, source in self.rows:
            if ts <= start_ms:
                continue
            if ts > end_ms:
                break
            nxt = {"box_mode": mode, "uplink_kind": kind, "isp_path": path, "setup_source": source}
            if all(cur.get(k) == nxt[k] for k in keys):
                continue
            cur["end_ts"] = ts
            out.append(cur)
            cur = dict(nxt, start_ts=ts)
        cur["end_ts"] = end_ms
        out.append(cur)
        out = [p for p in out if p["end_ts"] > p["start_ts"]]
        if absorb_unknown_ms <= 0:
            return out
        merged: List[Dict[str, Any]] = []
        i = 0
        while i < len(out):
            p = out[i]
            gap = all(p[k] is None for k in keys) and p["end_ts"] - p["start_ts"] < absorb_unknown_ms
            if gap and merged and i + 1 < len(out) and all(merged[-1][k] == out[i + 1][k] for k in keys):
                merged[-1]["end_ts"] = out[i + 1]["end_ts"]
                i += 2
                continue
            merged.append(dict(p))
            i += 1
        return merged


def label_codes(row: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(box_mode, uplink_kind, isp_path, setup_source) of a row, each only when it is a known code."""
    mode = row.get("box_mode") if row.get("box_mode") in MODES else None
    kind = row.get("uplink_kind") if row.get("uplink_kind") in UPLINK_KINDS else None
    path = row.get("isp_path") if row.get("isp_path") in ISP_PATHS else None
    src = row.get("setup_source") if row.get("setup_source") in SOURCES else None
    return mode, kind, path, src

