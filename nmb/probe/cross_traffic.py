"""Detect other devices' traffic, separated from the box's own measurement traffic."""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from nmb.netd import lan_topology, upnp_wan

log = logging.getLogger("nmb.probe.cross_traffic")

SYS_NET = Path("/sys/class/net")
PROC_NET_DEV = Path("/proc/net/dev")
INLINE_INTERVAL_SEC = 1.0
ROUTER_INTERVAL_SEC = 3.0
SUSTAINED_SAMPLES = 3
# Router and local counters are not read at the same instant, so a small share of the test leaks through.
ROUTER_NOISE_SHARE = 0.10
COUNTER_WRAP = 2 ** 32

VISIBILITY_INLINE = "inline"
VISIBILITY_ROUTER = "router"
VISIBILITY_NONE = "none"


def _is_access_point(iface: str) -> bool:
    iw = shutil.which("iw")
    if not iw or not (SYS_NET / iface / "wireless").exists():
        return False
    try:
        out = subprocess.run([iw, "dev", iface, "info"], capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "type AP" in out


def client_devices(cfg, uplink: str, active_mode: str = "") -> List[str]:
    """Return ports that carry only forwarded client traffic, never the box's own test."""
    net = cfg.network
    topo = lan_topology.resolve_topology(net)
    excluded = {uplink, net.wan_interface, getattr(net, "wan2_interface", ""), *topo.uplink_ports}
    gateway_lan = {getattr(net, "lan_interface", ""), getattr(net, "wlan_interface", "")} if active_mode == "mode_a" else set()
    devices = []
    if not SYS_NET.exists():
        return devices
    for path in sorted(SYS_NET.iterdir()):
        name = path.name
        if name in excluded or name == "lo":
            continue
        if (path / "brport").exists() or name in gateway_lan or _is_access_point(name):
            devices.append(name)
    return devices


def read_counters() -> Dict[str, Tuple[int, int]]:
    counters = {}
    try:
        for line in PROC_NET_DEV.read_text().splitlines()[2:]:
            name, _, data = line.partition(":")
            fields = data.split()
            if len(fields) >= 9:
                counters[name.strip()] = (int(fields[0]), int(fields[8]))
    except (OSError, ValueError) as e:
        log.warning("failed to read %s: %s", PROC_NET_DEV, e)
    return counters


def counter_delta(new: int, old: int) -> int:
    """Bytes between two readings; many routers keep 32-bit counters that wrap."""
    return new - old if new >= old else new + COUNTER_WRAP - old


class ForeignTrafficMonitor:
    def __init__(self, uplink: str, clients: List[str], router_url: Optional[str]):
        self.uplink = uplink
        self.clients = clients
        self.router_url = None if clients else router_url
        self._last: Optional[Tuple[float, int, int]] = None
        # Unknown counts as busy until the router has given two readings.
        self._last_kbps = float("inf")

    @classmethod
    def for_config(cls, cfg, uplink: str, active_mode: str = "") -> "ForeignTrafficMonitor":
        clients = client_devices(cfg, uplink, active_mode)
        return cls(uplink, clients, None if clients else upnp_wan.find_control_url())

    @property
    def visibility(self) -> str:
        if self.clients:
            return VISIBILITY_INLINE
        return VISIBILITY_ROUTER if self.router_url else VISIBILITY_NONE

    @property
    def interval(self) -> float:
        return ROUTER_INTERVAL_SEC if self.router_url else INLINE_INTERVAL_SEC

    def _read(self) -> Optional[Tuple[int, int]]:
        """Return (foreign byte counter, own byte counter)."""
        local = read_counters()
        own = sum(local.get(self.uplink, (0, 0)))
        if self.clients:
            return sum(sum(local.get(dev, (0, 0))) for dev in self.clients), own
        if self.router_url:
            wan = upnp_wan.read_wan_bytes(self.router_url)
            return (sum(wan), own) if wan else None
        return None

    def sample(self) -> Optional[float]:
        """Return foreign traffic in kbps since the last sample; None until two readings exist."""
        reading = self._read()
        if reading is None:
            return None
        now = time.monotonic()
        previous, self._last = self._last, (now, reading[0], reading[1])
        if previous is None or now <= previous[0]:
            return None
        elapsed = now - previous[0]
        total_kbps = counter_delta(reading[0], previous[1]) * 8 / elapsed / 1000.0
        if self.clients:
            return total_kbps
        own_kbps = max(0, reading[1] - previous[2]) * 8 / elapsed / 1000.0
        return max(0.0, total_kbps - own_kbps * (1.0 + ROUTER_NOISE_SHARE))

    def router_kbps(self) -> float:
        """Latest foreign rate for the start check; inline clients already appear on the uplink."""
        if not self.router_url:
            return 0.0
        now = time.monotonic()
        if self._last is None or now - self._last[0] >= ROUTER_INTERVAL_SEC:
            value = self.sample()
            self._last_kbps = float("inf") if value is None else value
        return self._last_kbps


def network_confirmed_idle(cfg, max_wait_sec: float = 60.0) -> bool:
    """Return True when other devices are visible and the network stays below the strict limit."""
    from nmb.netd.interfaces import find_preferred_measurement_interface
    from nmb.netd.lan_topology import traffic_monitor_device
    from nmb.probe.traffic_gate import TrafficGate

    iface = traffic_monitor_device(cfg.network, find_preferred_measurement_interface(cfg)[0])
    monitor = ForeignTrafficMonitor.for_config(cfg, iface, getattr(cfg.network, "mode", ""))
    if monitor.visibility == VISIBILITY_NONE:
        return False
    gate = TrafficGate(iface, strict=True)
    result = gate.wait_for_idle(
        threshold_kbps=cfg.speedtest.idle_threshold_kbps,
        max_wait_sec=max_wait_sec,
        iface=iface,
        capacity_mbps=gate.get_interface_capacity_mbps(iface, contract_down_mbps=cfg.isp.contract_down_mbps),
        threshold_percent=cfg.speedtest.idle_threshold_percent,
        mode=cfg.speedtest.idle_threshold_mode,
        extra_kbps=monitor.router_kbps,
    )
    return result.cleared


def watch(monitor: ForeignTrafficMonitor, threshold_kbps: float, stop: threading.Event,
          on_detect: Callable[[float], None]) -> threading.Thread:
    """Call on_detect once when foreign traffic stays above the threshold."""
    def _loop() -> None:
        streak = 0
        monitor.sample()
        while not stop.wait(monitor.interval):
            kbps = monitor.sample()
            # A failed read cannot prove the line is idle, so it counts as busy.
            streak = streak + 1 if kbps is None or kbps >= threshold_kbps else 0
            if streak >= SUSTAINED_SAMPLES:
                on_detect(kbps or 0.0)
                return

    thread = threading.Thread(target=_loop, daemon=True, name="nmb-cross-traffic")
    thread.start()
    return thread
