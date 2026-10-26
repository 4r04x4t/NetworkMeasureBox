"""Traffic gate monitoring for idle-only measurement enforcement.

Samples interface byte counters from /proc/net/dev to calculate bandwidth
consumption (rx_bps, tx_bps) and determine if network activity is below threshold.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from nmb.db import database as db

log = logging.getLogger("nmb.probe.gate")

PROC_NET_DEV = Path("/proc/net/dev")


class InterfaceCounter:
    def __init__(self, rx_bytes: int, tx_bytes: int, timestamp: float):
        self.rx_bytes = rx_bytes
        self.tx_bytes = tx_bytes
        self.timestamp = timestamp


class IdleCheckResult:
    """Rich result object that evaluates as bool and provides detailed bandwidth metrics."""
    def __init__(
        self,
        cleared: bool,
        rate_kbps: float,
        load_percent: float,
        threshold_kbps: float,
        capacity_mbps: float,
    ):
        self.cleared = bool(cleared)
        self.rate_kbps = float(rate_kbps)
        self.load_percent = float(load_percent)
        self.threshold_kbps = float(threshold_kbps)
        self.capacity_mbps = float(capacity_mbps)

    def __bool__(self) -> bool:
        return self.cleared

    def __iter__(self):
        return iter((self.cleared, self.rate_kbps, self.load_percent, self.threshold_kbps))

    def __repr__(self) -> str:
        return (f"<IdleCheckResult cleared={self.cleared} rate={self.rate_kbps:.1f}kbps "
                f"load={self.load_percent:.2f}% threshold={self.threshold_kbps:.1f}kbps cap={self.capacity_mbps:.0f}Mbps>")


def get_interface_capacity_mbps(iface: Optional[str] = None, contract_down_mbps: float = 0.0) -> float:
    """Determine effective network capacity in Mbps.
    Prioritizes contract_down_mbps if set (>0), otherwise checks /sys/class/net/<iface>/speed,
    falling back to 1000.0 Mbps.
    """
    if contract_down_mbps and float(contract_down_mbps) > 0:
        return float(contract_down_mbps)
    if iface:
        speed_file = Path(f"/sys/class/net/{iface}/speed")
        if speed_file.exists():
            try:
                val = int(speed_file.read_text().strip())
                if val > 0:
                    return float(val)
            except Exception:
                pass
    return 1000.0


def calculate_load_percent(current_kbps: float, capacity_mbps: float) -> float:
    """Calculate current network traffic utilization percentage relative to capacity."""
    if capacity_mbps <= 0:
        return 0.0
    capacity_kbps = capacity_mbps * 1000.0
    return (current_kbps / capacity_kbps) * 100.0


def get_effective_threshold_kbps(
    capacity_mbps: float,
    threshold_percent: float = 2.0,
    threshold_mode: str = "percent",
    fixed_kbps: float = 500.0,
) -> float:
    """Calculate effective threshold in Kbps."""
    if threshold_mode == "fixed":
        return float(max(100.0, fixed_kbps))
    # Percentage mode (default 2.0%)
    capacity_kbps = max(10.0, capacity_mbps) * 1000.0
    thresh_kbps = capacity_kbps * (max(0.1, threshold_percent) / 100.0)
    # Floor at 200 Kbps (to accommodate harmless OS background traffic like NTP/DNS/mDNS)
    return max(200.0, thresh_kbps)


class TrafficGate:
    def __init__(self, monitored_iface: Optional[str] = None):
        self.monitored_iface = monitored_iface
        self.last_counters: Dict[str, InterfaceCounter] = {}
        self.current_rates: Dict[str, Tuple[int, int]] = {}  # iface -> (rx_bps, tx_bps)

    def get_interface_capacity_mbps(self, iface: Optional[str] = None, contract_down_mbps: float = 0.0) -> float:
        target = iface or self.monitored_iface
        return get_interface_capacity_mbps(target, contract_down_mbps=contract_down_mbps)

    def get_effective_threshold_kbps(
        self,
        capacity_mbps: float,
        threshold_percent: float = 2.0,
        threshold_mode: str = "percent",
        fixed_kbps: float = 500.0,
    ) -> float:
        return get_effective_threshold_kbps(capacity_mbps, threshold_percent, threshold_mode, fixed_kbps)

    def _read_proc_net_dev(self) -> Dict[str, Tuple[int, int]]:
        """Read cumulative (rx_bytes, tx_bytes) for each interface in /proc/net/dev."""
        counters = {}
        if not PROC_NET_DEV.exists():
            return counters

        try:
            lines = PROC_NET_DEV.read_text().splitlines()
            for line in lines[2:]:  # skip header lines
                if ":" not in line:
                    continue
                iface, data = line.split(":", 1)
                iface = iface.strip()
                if iface == "lo":
                    continue
                fields = data.split()
                if len(fields) >= 9:
                    rx_bytes = int(fields[0])
                    tx_bytes = int(fields[8])
                    counters[iface] = (rx_bytes, tx_bytes)
        except Exception as e:
            log.warning("failed to read %s: %s", PROC_NET_DEV, e)

        return counters

    def sample(self) -> Dict[str, Tuple[int, int]]:
        """Sample counters and compute rate in bits per second (bps) since last sample."""
        now = time.monotonic()
        raw = self._read_proc_net_dev()
        new_rates: Dict[str, Tuple[int, int]] = {}

        for iface, (rx_b, tx_b) in raw.items():
            if iface in self.last_counters:
                prev = self.last_counters[iface]
                dt = now - prev.timestamp
                if dt > 0.05:
                    delta_rx = max(0, rx_b - prev.rx_bytes)
                    delta_tx = max(0, tx_b - prev.tx_bytes)
                    rx_bps = int((delta_rx * 8) / dt)
                    tx_bps = int((delta_tx * 8) / dt)
                    new_rates[iface] = (rx_bps, tx_bps)

            self.last_counters[iface] = InterfaceCounter(rx_b, tx_b, now)

        self.current_rates = new_rates
        return new_rates

    def get_rate(self, iface: Optional[str] = None) -> Tuple[int, int]:
        target = iface or self.monitored_iface
        if target and target in self.current_rates:
            return self.current_rates[target]
        # If no specific interface, sum across all active interfaces
        total_rx = sum(r[0] for r in self.current_rates.values())
        total_tx = sum(r[1] for r in self.current_rates.values())
        return total_rx, total_tx

    def is_idle(
        self,
        threshold_kbps: float = 500.0,
        iface: Optional[str] = None,
        capacity_mbps: Optional[float] = None,
        threshold_percent: float = 2.0,
        mode: str = "percent",
    ) -> IdleCheckResult:
        """Check if current combined rx + tx rate is below threshold (< 2% or fixed)."""
        rx_bps, tx_bps = self.get_rate(iface)
        current_kbps = (rx_bps + tx_bps) / 1000.0
        cap_mbps = float(capacity_mbps) if (capacity_mbps and capacity_mbps > 0) else self.get_interface_capacity_mbps(iface)
        load_pct = calculate_load_percent(current_kbps, cap_mbps)

        if mode == "percent":
            effective_thresh = get_effective_threshold_kbps(cap_mbps, threshold_percent=threshold_percent, threshold_mode="percent")
            idle = (load_pct < threshold_percent)
        else:
            effective_thresh = float(threshold_kbps)
            idle = (current_kbps < effective_thresh)

        return IdleCheckResult(
            cleared=idle,
            rate_kbps=current_kbps,
            load_percent=load_pct,
            threshold_kbps=effective_thresh,
            capacity_mbps=cap_mbps,
        )

    def wait_for_idle(
        self,
        threshold_kbps: float = 500.0,
        max_wait_sec: float = 30.0,
        consecutive_idle_sec: float = 3.0,
        iface: Optional[str] = None,
        capacity_mbps: Optional[float] = None,
        threshold_percent: float = 2.0,
        mode: str = "percent",
    ) -> IdleCheckResult:
        """Block until traffic is consistently below threshold for consecutive_idle_sec.

        Returns IdleCheckResult (evaluates to True/False in bool context).
        """
        start = time.monotonic()
        idle_streak_start: Optional[float] = None

        cap_mbps = float(capacity_mbps) if (capacity_mbps and capacity_mbps > 0) else self.get_interface_capacity_mbps(iface)
        effective_thresh = get_effective_threshold_kbps(
            capacity_mbps=cap_mbps,
            threshold_percent=threshold_percent,
            threshold_mode=mode,
            fixed_kbps=threshold_kbps,
        )

        log.info(
            "traffic gate: waiting for idle (mode=%s, limit=%.1f kbps / <%.1f%% of %.0f Mbps) on %s (max wait: %.1fs)",
            mode, effective_thresh, threshold_percent, cap_mbps, iface or "all interfaces", max_wait_sec
        )

        # Baseline sample
        self.sample()
        time.sleep(1.0)

        last_kbps = 0.0
        last_pct = 0.0

        while (time.monotonic() - start) < max_wait_sec:
            self.sample()
            rx_bps, tx_bps = self.get_rate(iface)
            total_kbps = (rx_bps + tx_bps) / 1000.0
            load_pct = calculate_load_percent(total_kbps, cap_mbps)
            last_kbps = total_kbps
            last_pct = load_pct

            is_below = (load_pct < threshold_percent) if mode == "percent" else (total_kbps < effective_thresh)

            if is_below:
                if idle_streak_start is None:
                    idle_streak_start = time.monotonic()
                elif (time.monotonic() - idle_streak_start) >= consecutive_idle_sec:
                    log.info(
                        "traffic gate clear: rate %.1f kbps (%.2f%% load) is below threshold (%.1f kbps / <%.1f%%)",
                        total_kbps, load_pct, effective_thresh, threshold_percent
                    )
                    return IdleCheckResult(True, total_kbps, load_pct, effective_thresh, cap_mbps)
            else:
                if idle_streak_start is not None:
                    log.debug("traffic gate busy: rate %.1f kbps (%.2f%% load); resetting streak", total_kbps, load_pct)
                idle_streak_start = None

            time.sleep(1.0)

        log.warning(
            "traffic gate timeout: network remained busy (%.1f kbps / %.2f%% load, limit: %.1f kbps) after %.1fs",
            last_kbps, last_pct, effective_thresh, max_wait_sec
        )
        return IdleCheckResult(False, last_kbps, last_pct, effective_thresh, cap_mbps)

    def record_stats(self, conn: sqlite3.Connection, iface: Optional[str] = None) -> None:
        """Record current throughput snapshot to SQLite iface_stat table."""
        now_ms = db.now_ms()
        target = iface or self.monitored_iface
        entries = []

        if target and target in self.current_rates:
            rx, tx = self.current_rates[target]
            entries.append((now_ms, target, rx, tx))
        else:
            for dev, (rx, tx) in self.current_rates.items():
                entries.append((now_ms, dev, rx, tx))

        if entries:
            try:
                with db.tx(conn):
                    conn.executemany(
                        "INSERT OR REPLACE INTO iface_stat (ts, iface, rx_bps, tx_bps) VALUES (?, ?, ?, ?)",
                        entries
                    )
            except Exception as e:
                log.warning("failed to insert iface_stat: %s", e)
