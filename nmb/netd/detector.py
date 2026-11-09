"""Auto-detection and failover engine.

Evaluates physical carrier status, upstream connectivity, and database overrides
to determine whether Mode A or Mode B should be active, with hysteresis/debouncing.
"""
from __future__ import annotations

import logging
import socket
import time
from typing import List, Optional, Tuple

from nmb.config import NetworkConfig
from nmb.netd import interfaces

log = logging.getLogger("nmb.netd.detector")


class NetworkDetector:
    def __init__(self, cfg: NetworkConfig):
        self.cfg = cfg
        self.last_candidate_mode: Optional[str] = None
        self.candidate_since: float = 0.0
        self.debounce_sec: float = 4.0
        # mode = auto: the owner's rule (nmb/netd/auto_mode.py); the daemon fills these in each loop.
        from nmb.netd.auto_mode import AutoPolicy, Observer
        self.auto = AutoPolicy()
        self.observer = Observer()
        self.current_mode: Optional[str] = None
        self.ip_device: Optional[str] = None
        self.last_decision = None

    def check_reachability(self, targets: List[str], timeout: float = 1.0) -> bool:
        """Quick TCP probe to known external targets (port 53 DNS or 80 HTTP)."""
        for target in targets:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    s.connect((target, 53))
                    return True
            except OSError:
                continue
        return False

    def evaluate_target_mode(self, override_mode: Optional[str] = None) -> Tuple[str, str]:
        """Determine what mode should be active and the rationale.

        Returns:
            (target_mode, reason) where target_mode is 'mode_a' or 'mode_b'.
        """
        # 1. Manual override takes highest priority
        if override_mode in ("mode_a", "mode_b", "standalone"):
            return override_mode, f"manual override set to {override_mode}"

        # 2. Configured static mode
        if self.cfg.mode in ("mode_a", "mode_b", "standalone"):
            return self.cfg.mode, f"static configuration mode={self.cfg.mode}"

        # 3. LAN passthrough / link aggregation only make sense behind a router
        if getattr(self.cfg, "lan_passthrough_enabled", False) or getattr(self.cfg, "lag_enabled", False):
            return "standalone", "LAN passthrough or link aggregation enabled"

        # 4. Automatic: standalone behind a router, router mode without one (auto_mode.py)
        try:
            obs = self.observer.observe(self.cfg, self.current_mode, self.ip_device, own_gateway=self.cfg.gateway_ip)
            decision = self.auto.decide(self.cfg, obs, self.current_mode)
        except Exception as e:
            log.warning("auto mode: could not decide (%s); keeping %s", e, self.current_mode or "standalone")
            return (self.current_mode or "standalone"), "auto mode could not observe the network"
        self.last_decision = decision
        return decision.mode, decision.reason

    def get_debounced_mode(self, override_mode: Optional[str] = None) -> Tuple[str, str, bool]:
        """Evaluate mode with debouncing to prevent flapping during link negotiation.

        Returns:
            (mode, reason, is_ready_to_switch)
        """
        raw_mode, reason = self.evaluate_target_mode(override_mode)
        now = time.time()

        if raw_mode != self.last_candidate_mode:
            self.last_candidate_mode = raw_mode
            self.candidate_since = now
            log.info("mode candidate changed to %s (reason: %s); starting debounce (%.1fs)",
                     raw_mode, reason, self.debounce_sec)
            return raw_mode, reason, False

        elapsed = now - self.candidate_since
        is_ready = elapsed >= self.debounce_sec
        return raw_mode, reason, is_ready
