"""One status code for a speed test row, the same in the detailed CSV and the SLA dossier.

The numbers follow the legend printed in the dossier (nmb/report/dossier.py, status_codes_text).
Only codes the box can actually decide are produced: 1, 6, 7, 9, 10, 12 and 14.

Rules (2026-11-10, no invented values):
- "below the guaranteed speed" (6) only against a guaranteed speed the owner set, download AND upload;
- "far below the offered speed" (6) only against an offered (contract) speed that is set: below 40 %
  in either direction (NMB's own rule, written in the description);
- nothing is judged against a speed that was never set (the detailed CSV used to fill in 1000/200 and
  300/50 Mbit/s and judged every unconfigured box against 300 Mbit/s);
- Wi-Fi (14) comes from the interface the test really ran on, not from the configured line type;
- a skipped test is 9 only when other traffic was the reason, otherwise 10 (nothing could run: manual
  mode, data cap, rate limit, interval not over).
"""
from __future__ import annotations

from typing import Optional, Tuple

FAR_BELOW_OFFERED = 0.40

WIFI_PREFIXES = ("wlan", "wlp", "wl", "ath", "ra", "mlan")


def is_wifi_iface(name: Optional[str]) -> bool:
    n = (name or "").strip().lower()
    return bool(n) and n.startswith(WIFI_PREFIXES) and not n.startswith("wwan")


def classify(status: str, error: Optional[str], down_mbps: Optional[float], up_mbps: Optional[float],
             bound_iface: Optional[str] = None, connection_type: Optional[str] = None,
             contract_down: float = 0.0, contract_up: float = 0.0,
             guaranteed_down: float = 0.0, guaranteed_up: float = 0.0) -> Tuple[int, str]:
    if status == "ok":
        if is_wifi_iface(bound_iface) or (connection_type or "").lower() in ("wifi", "wlan", "guest_wifi"):
            return 14, "Wi-Fi measurement"
        below_guaranteed = [
            label for label, got, need in (("download", down_mbps, guaranteed_down), ("upload", up_mbps, guaranteed_up))
            if need and need > 0 and got is not None and got < need
        ]
        if below_guaranteed:
            return 6, "below the guaranteed speed (" + ", ".join(below_guaranteed) + ")"
        far_below = [
            label for label, got, offered in (("download", down_mbps, contract_down), ("upload", up_mbps, contract_up))
            if offered and offered > 0 and got is not None and got < offered * FAR_BELOW_OFFERED
        ]
        if far_below:
            return 6, f"below {FAR_BELOW_OFFERED:.0%} of the offered speed (" + ", ".join(far_below) + ")"
        return 1, "valid measurement"
    err = str(error or "").lower()
    if status == "skipped_busy":
        if "traffic" in err or "busy" in err or "in use" in err:
            return 9, "skipped: other traffic on the line"
        return 10, "skipped: no test could run" + (f" ({str(error)[:80]})" if error else "")
    if status == "error":
        if "timeout" in err or "timed out" in err:
            return 7, "invalid: timeout"
        return 12, "error"
    return 12, f"unknown status {status!r}"
