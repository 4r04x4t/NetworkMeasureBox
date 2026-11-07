"""LAN passthrough and link aggregation for a probe connected behind a router.

Topology applied in standalone mode:

    router ==[uplink port, or bond of selected ports]== NMB --[passthrough ports]-- LAN devices

* Link aggregation joins the selected wired NICs into one Linux bond device.
* Passthrough adds a Layer 2 bridge between the uplink and the selected ports, so
  downstream devices stay on the router's own subnet and receive its DHCP leases.
* The probe's own IP address lives on the top-most device (bridge > bond > port).

Traffic counters must be read from ``monitor_device``: a Linux bridge device only
counts frames addressed to the host, so forwarded client traffic would be missed.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from nmb.netd import interfaces

log = logging.getLogger("nmb.netd.lan_topology")

BOND_NAME = "bond0"
BRIDGE_NAME = "br-pass"
SYS_CLASS_NET = Path("/sys/class/net")

LAG_MODES = ("802.3ad", "balance-rr", "balance-xor", "balance-tlb", "balance-alb", "active-backup")
LAG_HASH_POLICIES = ("layer2", "layer2+3", "layer3+4")
LACP_RATES = ("slow", "fast")


@dataclass(frozen=True)
class Topology:
    uplink_ports: tuple
    passthrough_ports: tuple
    lag_enabled: bool
    passthrough_enabled: bool

    @property
    def active(self) -> bool:
        return self.lag_enabled or self.passthrough_enabled

    @property
    def uplink_device(self) -> str:
        """Device that carries all traffic towards the router."""
        return BOND_NAME if self.lag_enabled else self.uplink_ports[0]

    @property
    def ip_device(self) -> str:
        """Device that holds the probe's IP address."""
        return BRIDGE_NAME if self.passthrough_enabled else self.uplink_device

    @property
    def monitor_device(self) -> str:
        """Device whose counters include forwarded client traffic."""
        return self.uplink_device


def resolve_topology(cfg) -> Topology:
    """Build the desired topology from a NetworkConfig."""
    lag_enabled = bool(getattr(cfg, "lag_enabled", False))
    passthrough_enabled = bool(getattr(cfg, "lan_passthrough_enabled", False))
    uplink = list(getattr(cfg, "lag_ports", [])) if lag_enabled else [cfg.wan_interface]
    downstream = list(getattr(cfg, "passthrough_ports", [])) if passthrough_enabled else []
    return Topology(tuple(uplink), tuple(downstream), lag_enabled, passthrough_enabled)


def interfaces_bridge_master(iface: str) -> str:
    from nmb.netd.interfaces import bridge_master
    return bridge_master(iface) or ""


def traffic_monitor_device(cfg, iface: str) -> str:
    """Return the device to read traffic counters from when measuring on iface."""
    topo = resolve_topology(cfg)
    if topo.active and iface == topo.ip_device:
        return topo.monitor_device
    # A bridge's own counters leave out the traffic it forwards; the WAN port has all of it.
    wan = getattr(cfg, "wan_interface", "")
    if wan and interfaces_bridge_master(wan) == iface:
        return wan
    return iface


def validate_settings(
    lag_enabled: bool,
    lag_ports: Iterable[str],
    lag_mode: str,
    lag_hash_policy: str,
    lacp_rate: str,
    passthrough_enabled: bool,
    passthrough_ports: Iterable[str],
    wan_interface: str,
    wired_ports: Iterable[str],
) -> List[str]:
    """Return problems with the requested settings; an empty list means valid."""
    errors: List[str] = []
    lag = list(lag_ports)
    downstream = list(passthrough_ports)
    wired = set(wired_ports)

    if lag_enabled:
        if len(set(lag)) < 2:
            errors.append("Link aggregation needs at least two ports.")
        if lag_mode not in LAG_MODES:
            errors.append(f"Unsupported aggregation mode: {lag_mode}")
        if lag_hash_policy not in LAG_HASH_POLICIES:
            errors.append(f"Unsupported hash policy: {lag_hash_policy}")
        if lacp_rate not in LACP_RATES:
            errors.append(f"Unsupported LACP rate: {lacp_rate}")
        unknown = sorted(set(lag) - wired)
        if unknown:
            errors.append(f"Not usable as aggregated wired ports: {', '.join(unknown)}")

    if passthrough_enabled:
        if not downstream:
            errors.append("LAN passthrough needs at least one downstream port.")
        unknown = sorted(set(downstream) - wired)
        if unknown:
            errors.append(f"Not usable as wired passthrough ports: {', '.join(unknown)}")
        if not lag_enabled and wan_interface not in wired:
            errors.append(f"The uplink {wan_interface} is not a wired port, so it cannot be bridged.")
        uplink = set(lag) if lag_enabled else {wan_interface}
        overlap = sorted(uplink & set(downstream))
        if overlap:
            errors.append(f"A port cannot be both uplink and passthrough: {', '.join(overlap)}")

    return errors


def _ip(*args: str) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin:
        log.error("'ip' command not found")
        return False
    res = interfaces.run_cmd([ip_bin, *args], check=False)
    if res.returncode != 0:
        log.error("ip %s failed: %s", " ".join(args), (res.stderr or "").strip())
    return res.returncode == 0


def setup_bond(members: List[str], mode: str, hash_policy: str, lacp_rate: str) -> bool:
    """Create the bond and enslave members. Members must be down while enslaved."""
    if interfaces.interface_exists(BOND_NAME):
        _ip("link", "delete", "dev", BOND_NAME)

    args = ["link", "add", BOND_NAME, "type", "bond", "mode", mode, "miimon", "100"]
    if mode in ("802.3ad", "balance-xor", "balance-tlb"):
        args += ["xmit_hash_policy", hash_policy]
    if mode == "802.3ad":
        args += ["lacp_rate", lacp_rate]
    if not _ip(*args):
        return False

    for port in members:
        if not interfaces.interface_exists(port):
            log.error("aggregation member %s does not exist", port)
            return False
        interfaces.flush_ip_addresses(port)
        interfaces.set_link_down(port)
        if not _ip("link", "set", "dev", port, "master", BOND_NAME):
            return False
        interfaces.set_link_up(port)

    return interfaces.set_link_up(BOND_NAME)


def apply_topology(cfg) -> Optional[Topology]:
    """Apply the configured topology. Returns it on success; rolls back on failure."""
    topo = resolve_topology(cfg)
    if not topo.active:
        return None

    log.info("applying LAN topology: uplink=%s lag=%s passthrough=%s",
             topo.uplink_ports, topo.lag_enabled, topo.passthrough_ports)
    # Remove leftovers from an unclean shutdown before building anything.
    teardown_topology(topo)
    ok = True
    if topo.lag_enabled:
        ok = setup_bond(
            list(topo.uplink_ports),
            getattr(cfg, "lag_mode", "802.3ad"),
            getattr(cfg, "lag_hash_policy", "layer3+4"),
            getattr(cfg, "lacp_rate", "fast"),
        )
    else:
        interfaces.flush_ip_addresses(topo.uplink_device)

    if ok and topo.passthrough_enabled:
        ok = interfaces.setup_bridge(BRIDGE_NAME, [topo.uplink_device, *topo.passthrough_ports])

    if not ok:
        log.error("LAN topology setup failed; rolling back")
        teardown_topology(topo)
        return None
    return topo


def teardown_topology(topo: Optional[Topology]) -> None:
    """Remove the bridge and bond, then release every member port."""
    if topo is None:
        return
    if interfaces.interface_exists(BRIDGE_NAME):
        _ip("link", "delete", "dev", BRIDGE_NAME)
    if interfaces.interface_exists(BOND_NAME):
        _ip("link", "delete", "dev", BOND_NAME)
    for port in (*topo.uplink_ports, *topo.passthrough_ports):
        if interfaces.interface_exists(port):
            interfaces.flush_ip_addresses(port)
            interfaces.set_link_up(port)


def _read_sys(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _port_status(port: str) -> dict:
    speed = _read_sys(SYS_CLASS_NET / port / "speed")
    return {
        "name": port,
        "carrier": interfaces.get_carrier(port),
        "speed_mbps": int(speed) if speed.lstrip("-").isdigit() and int(speed) > 0 else None,
    }


def get_runtime_status(cfg) -> dict:
    """Describe what is actually configured in the kernel right now."""
    topo = resolve_topology(cfg)
    bond_exists = interfaces.interface_exists(BOND_NAME)
    bridge_exists = interfaces.interface_exists(BRIDGE_NAME)
    applied = (not topo.lag_enabled or bond_exists) and (not topo.passthrough_enabled or bridge_exists)

    lag_members = [_port_status(p) for p in topo.uplink_ports] if topo.lag_enabled else []
    active_speeds = [m["speed_mbps"] for m in lag_members if m["carrier"] and m["speed_mbps"]]

    return {
        "requested": topo.active,
        "applied": topo.active and applied,
        "ip_device": topo.ip_device if topo.active else None,
        "ip_addresses": interfaces.get_ip_addresses(topo.ip_device) if topo.active else [],
        "lag_members": lag_members,
        "lag_active_ports": sum(1 for m in lag_members if m["carrier"]),
        "lag_theoretical_mbps": sum(active_speeds),
        "lag_mixed_speeds": len(set(active_speeds)) > 1,
        "passthrough_members": [_port_status(p) for p in topo.passthrough_ports],
    }
