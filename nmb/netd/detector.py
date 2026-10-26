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

        # 3. Dynamic Auto-detection
        wan_carrier = interfaces.get_carrier(self.cfg.wan_interface)
        lan_carrier = interfaces.get_carrier(self.cfg.lan_interface)

        log.debug("detector scan: wan(%s)=%s, lan(%s)=%s",
                  self.cfg.wan_interface, wan_carrier,
                  self.cfg.lan_interface, lan_carrier)

        # Both ports connected: ideal inline deployment -> Mode B
        if wan_carrier and lan_carrier:
            return "mode_b", "both WAN and LAN links active; transparent inline bridge selected"

        # Only WAN has carrier: either standalone probe or PPPoE direct-to-ONT
        if wan_carrier and not lan_carrier:
            if self.cfg.pppoe_enabled:
                return "mode_a", "WAN active with PPPoE configured; active gateway selected"
            return "mode_b", "WAN active without LAN clients; bridging enabled for upstream probe"

        # Only LAN has carrier: user plugged laptop/switch directly into LAN port for diagnostics
        if not wan_carrier and lan_carrier:
            return "mode_a", "LAN active without WAN link; starting gateway & DHCP for diagnostics"

        # Neither link has carrier: default to Mode B to minimize startup friction
        return "mode_b", "no physical links detected; standing by in bridge mode"

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
