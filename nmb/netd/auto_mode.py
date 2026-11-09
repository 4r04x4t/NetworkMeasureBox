"""Automatic network mode (`[network] mode = auto`): standalone behind a router, router mode without one.

The owner's rule (2026-11-09):

* The box gets an address from a router (DHCP) on its WAN port: **standalone**. On a box with several
  wired ports, the other ports are bridged to the WAN port (LAN passthrough, transparent bridge): the box
  behaves almost like a switch, devices behind it get their addresses from the same router.
* The box gets neither internet nor an address from a router (cable on an ONT or modem, on a PC, or no
  cable at all): **router mode** (Mode A), until a router shows up again. With PPPoE credentials saved and
  a PPPoE server answering on the WAN port, router mode dials PPPoE; with USB tethering it uses that; in any
  case the Wi-Fi access point and the LAN ports serve their own network, so the box can be reached and
  configured.
* A router appearing on the WAN port while in router mode: back to standalone at once (the box must
  never hand out addresses into someone else's network).

Timing: the switch to router mode waits until the router has been missing for ROUTER_MISSING_SEC
(a router that reboots does not knock the box out of standalone); the switch back needs one clear answer
from a DHCP server.
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

log = logging.getLogger("nmb.netd.auto")

ROUTER_MISSING_SEC = 90.0      # no lease, no DHCP answer and no internet for this long -> router mode
PROBE_EVERY_SEC = 30.0         # DHCP probe on the WAN port while it matters
PPPOE_PROBE_EVERY_SEC = 120.0  # PPPoE discovery while in router mode without PPPoE


@dataclass
class Observation:
    """What the box sees on its WAN side at one moment."""
    carrier: bool = False
    lease: bool = False            # an IPv4 address from a router and a default route through it
    dhcp_servers: List[str] = field(default_factory=list)   # foreign DHCP servers that answered a probe
    probed: bool = False           # dhcp_servers is fresh
    internet: bool = False
    pppoe_server: Optional[bool] = None   # None: not checked
    wired_ports: List[str] = field(default_factory=list)


@dataclass
class Decision:
    mode: str
    reason: str
    passthrough_ports: List[str] = field(default_factory=list)   # standalone: bridge these to the WAN port
    pppoe: bool = False                                          # router mode: dial PPPoE on the WAN port


class AutoPolicy:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.missing_since: Optional[float] = None
        self.last: Optional[Decision] = None

    def decide(self, cfg, obs: Observation, current: Optional[str]) -> Decision:
        now = self.clock()
        wan = getattr(cfg, "wan_interface", "eth0") or "eth0"
        others = [p for p in obs.wired_ports if p != wan]
        router = obs.lease or bool(obs.dhcp_servers)

        if router:
            self.missing_since = None
            if others:
                d = Decision("standalone", f"a router gives addresses on {wan}; the other wired ports "
                             f"({', '.join(others)}) are bridged to it (LAN passthrough)", passthrough_ports=others)
            else:
                d = Decision("standalone", f"a router gives addresses on {wan}")
            self.last = d
            return d

        # No router seen right now.
        if self.missing_since is None:
            self.missing_since = now
        missing_for = now - self.missing_since
        pppoe = bool(obs.pppoe_server) and _pppoe_credentials(cfg)

        if current == "mode_a":
            d = Decision("mode_a", "still no router on " + wan, pppoe=pppoe or bool(self.last and self.last.pppoe))
        elif obs.internet and current == "standalone":
            # Internet without a lease: a static address or another way out; nothing to rescue.
            d = Decision("standalone", "internet works without a router lease")
            self.missing_since = None
        elif missing_for < ROUTER_MISSING_SEC and current is not None:
            d = Decision(current, f"no router on {wan} for {int(missing_for)} s; waiting "
                                  f"{int(ROUTER_MISSING_SEC)} s before router mode")
        else:
            why = "no cable" if not obs.carrier else "no internet and no router answering DHCP"
            d = Decision("mode_a", f"{why} on {wan}: router mode" + (" with PPPoE" if pppoe else ""), pppoe=pppoe)
        self.last = d
        return d


def _pppoe_credentials(cfg) -> bool:
    return bool(getattr(cfg, "pppoe_user", "") and getattr(cfg, "pppoe_password", ""))


# ---------------------------------------------------------------------------------------------
# Observing the real system (root, nmb-netd)
# ---------------------------------------------------------------------------------------------

def _has_lease(dev: str) -> bool:
    """An IPv4 address on dev (not link-local) and a default route through dev."""
    from nmb.netd import interfaces
    addrs = [a for a in interfaces.get_ip_addresses(dev) if ":" not in a and not a.startswith("169.254.")]
    if not addrs:
        return False
    res = interfaces.run_cmd(["ip", "-4", "route", "show", "default", "dev", dev], check=False)
    return bool((getattr(res, "stdout", "") or "").strip())


def _internet(timeout: float = 2.0) -> bool:
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _pppoe_discovery(dev: str) -> bool:
    import shutil
    import subprocess
    exe = shutil.which("pppoe-discovery") or ("/usr/sbin/pppoe-discovery" if Path("/usr/sbin/pppoe-discovery").exists() else "")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "-I", dev, "-t", "3", "-a", "2"], capture_output=True, text=True, timeout=15)
        return "Access-Concentrator" in out.stdout
    except Exception:
        return False


class Observer:
    """Collects an Observation, probing only when it matters (DHCP probes cost up to 8 s)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.last_probe = 0.0
        self.last_servers: List[str] = []   # valid until the next probe, so every loop sees the same answer
        self.last_carrier: Optional[bool] = None
        self.last_pppoe = 0.0
        self.pppoe_cache: Optional[bool] = None

    def observe(self, cfg, current: Optional[str], ip_device: Optional[str] = None, own_gateway: str = "") -> Observation:
        from nmb.netd import interfaces
        from nmb.netd.wifi_share import probe_dhcp_servers, wired_ports
        wan = getattr(cfg, "wan_interface", "eth0") or "eth0"
        obs = Observation(carrier=interfaces.get_carrier(wan), wired_ports=wired_ports())
        dev = ip_device or wan
        obs.lease = current != "mode_a" and _has_lease(dev)
        obs.internet = _internet()
        now = self.clock()
        plugged_in = obs.carrier and self.last_carrier is False   # a cable just went in: ask at once
        self.last_carrier = obs.carrier
        if not obs.carrier or obs.lease:
            self.last_servers = []          # no cable: nobody answers; a lease: no need to ask
        elif plugged_in or now - self.last_probe >= PROBE_EVERY_SEC:
            self.last_probe = now
            try:
                self.last_servers = [s for s in probe_dhcp_servers(wan, timeout=6.0) if s != own_gateway]
            except Exception as e:
                log.debug("auto mode: DHCP probe failed: %s", e)
                self.last_servers = []
            obs.probed = True
        obs.dhcp_servers = list(self.last_servers)
        if current == "mode_a" and obs.carrier and not obs.dhcp_servers and _pppoe_credentials(cfg):
            if now - self.last_pppoe >= PPPOE_PROBE_EVERY_SEC or self.pppoe_cache is None:
                self.last_pppoe = now
                self.pppoe_cache = _pppoe_discovery(wan)
            obs.pppoe_server = self.pppoe_cache
        elif current != "mode_a" and obs.carrier and not obs.lease and _pppoe_credentials(cfg):
            obs.pppoe_server = _pppoe_discovery(wan)
        return obs


def describe() -> Tuple[str, ...]:
    """The rules in one line each, for logs and the Web UI."""
    return (
        "Router answers DHCP on the WAN port: standalone (several wired ports: LAN passthrough bridge).",
        f"No router and no internet for {int(ROUTER_MISSING_SEC)} s: router mode (PPPoE when saved and answered, "
        "USB tethering when present; Wi-Fi access point and LAN ports for setup).",
        "A router appears on the WAN port in router mode: standalone at once.",
    )
