"""NetworkMeasureBox Autonomous In-Process Precision Scheduler.

Supports standard 5-part cron expressions, interval shorthands (e.g. 5m, 15m, 30m),
and integrates with TrafficGate to ensure automated speedtests execute only
when network load is below threshold (< 2.0% of capacity).
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Optional, Set, Tuple

from nmb.config import Config

log = logging.getLogger("nmb.speed.scheduler")


def parse_cron_field(field_expr: str, min_val: int, max_val: int) -> Set[int]:
    """Parse a single cron field (supports *, */N, A-B, A,B,C, N)."""
    field_expr = field_expr.strip()
    if not field_expr or field_expr == "*":
        return set(range(min_val, max_val + 1))

    results: Set[int] = set()
    parts = field_expr.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
                if step > 0:
                    for val in range(min_val, max_val + 1):
                        if (val - min_val) % step == 0:
                            results.add(val)
            except ValueError:
                pass
        elif "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start = max(min_val, int(start_s))
                end = min(max_val, int(end_s))
                if start <= end:
                    results.update(range(start, end + 1))
            except ValueError:
                pass
        else:
            try:
                val = int(part)
                if min_val <= val <= max_val:
                    results.add(val)
            except ValueError:
                pass

    return results if results else set(range(min_val, max_val + 1))


def normalize_cron_expression(expr: str) -> str:
    """Normalize user input (shorthand seconds, minutes, or 5/6-part cron)."""
    s = str(expr).strip().lower()
    if not s:
        return "0 */6 * * *"

    # 1. Check seconds shorthands, e.g. "10s", "30 sec", "15 mp", "every 20s"
    is_sec = False
    for suffix in ("sec", "secs", "second", "seconds", "mp", "masodperc", "másodperc", "másodpercenként", "masodpercenkent"):
        if s.endswith(suffix):
            is_sec = True
            break
    if not is_sec and s.endswith("s") and not s.endswith("mins") and not s.endswith("ms"):
        is_sec = True

    if is_sec:
        digits = "".join(c for c in s if c.isdigit())
        if digits:
            val = int(digits)
            if val < 60:
                val = max(1, val)
                return f"*/{val} * * * * *"
            else:
                mins = max(1, val // 60)
                if mins <= 59:
                    return f"*/{mins} * * * *"
                else:
                    hrs = max(1, min(23, mins // 60))
                    return f"0 */{hrs} * * *"

    # 2. Check minutes shorthands, e.g. "5m", "15 min", "*/10", "perc", "percenként"
    is_min = False
    for suffix in ("min", "mins", "minute", "minutes", "perc", "percenként", "percenkent"):
        if s.endswith(suffix):
            is_min = True
            break
    if not is_min and s.endswith("m"):
        is_min = True

    if is_min:
        digits = "".join(c for c in s if c.isdigit())
        if digits:
            val = int(digits)
            if val <= 59:
                return f"*/{val} * * * *"
            else:
                hours = max(1, min(23, val // 60))
                return f"0 */{hours} * * *"

    # 3. Numeric string only (e.g. "10") -> default to minutes if <= 59, else hours
    if s.isdigit():
        val = int(s)
        if val <= 59:
            return f"*/{val} * * * *"
        else:
            hours = max(1, min(23, val // 60))
            return f"0 */{hours} * * *"

    parts = s.split()
    # If 1 part like "*/10" or "*/30s"
    if len(parts) == 1 and parts[0].startswith("*/"):
        num_part = "".join(c for c in parts[0] if c.isdigit())
        if parts[0].endswith("s"):
            return f"*/{num_part} * * * * *"
        return f"{parts[0]} * * * *"

    # If 6 parts: second minute hour dom month dow
    if len(parts) == 6:
        return " ".join(parts)

    # If 5 parts: minute hour dom month dow
    if len(parts) == 5:
        return " ".join(parts)

    return "0 */6 * * *"


def is_second_cron(expr: str) -> bool:
    """Return True if cron expression specifies a second-level interval (6-part cron)."""
    norm = normalize_cron_expression(expr)
    return len(norm.split()) == 6


def get_cron_interval_seconds(expr: str) -> Optional[float]:
    """Calculate the interval duration in seconds if the expression represents a repeating period."""
    norm = normalize_cron_expression(expr)
    parts = norm.split()
    if len(parts) == 6:
        # e.g. */10 * * * * *
        if parts[0].startswith("*/") and parts[1:] == ["*", "*", "*", "*", "*"]:
            try:
                return float(parts[0][2:])
            except ValueError:
                pass
        elif parts[0] == "*" and parts[1:] == ["*", "*", "*", "*", "*"]:
            return 1.0
    elif len(parts) == 5:
        # e.g. */5 * * * *
        if parts[0].startswith("*/") and parts[1:] == ["*", "*", "*", "*"]:
            try:
                return float(parts[0][2:]) * 60.0
            except ValueError:
                pass
        elif parts[0] == "*" and parts[1:] == ["*", "*", "*", "*"]:
            return 60.0
        elif parts[0] == "0" and parts[1].startswith("*/") and parts[2:] == ["*", "*", "*"]:
            try:
                return float(parts[1][2:]) * 3600.0
            except ValueError:
                pass
        elif parts[0] == "0" and parts[1] == "*" and parts[2:] == ["*", "*", "*"]:
            return 3600.0
    return None


def matches_cron(cron_expr: str, dt: Optional[datetime.datetime] = None) -> bool:
    """Return True if datetime matches 5-part or 6-part cron expression."""
    dt = dt or datetime.datetime.now()
    normalized = normalize_cron_expression(cron_expr)
    parts = normalized.split()

    if len(parts) == 6:
        sec_expr, min_expr, hour_expr, dom_expr, month_expr, dow_expr = parts
        # Second (0-59)
        if dt.second not in parse_cron_field(sec_expr, 0, 59):
            return False
    elif len(parts) == 5:
        min_expr, hour_expr, dom_expr, month_expr, dow_expr = parts
    else:
        return False

    # Minute (0-59)
    if dt.minute not in parse_cron_field(min_expr, 0, 59):
        return False

    # Hour (0-23)
    if dt.hour not in parse_cron_field(hour_expr, 0, 23):
        return False

    # Day of month (1-31)
    if dt.day not in parse_cron_field(dom_expr, 1, 31):
        return False

    # Month (1-12)
    if dt.month not in parse_cron_field(month_expr, 1, 12):
        return False

    # Day of week (0-6, Sunday=0 or 7)
    dow = dt.isoweekday() % 7
    dow_set = parse_cron_field(dow_expr, 0, 7)
    if 7 in dow_set:
        dow_set.add(0)
    if 0 in dow_set:
        dow_set.add(7)

    if dow not in dow_set:
        return False

    return True


def get_cron_description(cron_expr: str, lang: str = "en") -> str:
    """Provide a friendly description of the cron interval in given language."""
    norm = normalize_cron_expression(cron_expr)
    is_hu = (lang == "hu")

    shorthands = {
        "*/5 * * * * *": ("5 másodpercenként (Ultra gyors)", "Every 5 seconds (Ultra rapid)"),
        "*/10 * * * * *": ("10 másodpercenként (Gyakori tesztelés)", "Every 10 seconds (Frequent)"),
        "*/15 * * * * *": ("15 másodpercenként", "Every 15 seconds"),
        "*/20 * * * * *": ("20 másodpercenként", "Every 20 seconds"),
        "*/30 * * * * *": ("30 másodpercenként (Gyakori)", "Every 30 seconds (Frequent)"),
        "*/45 * * * * *": ("45 másodpercenként", "Every 45 seconds"),
        "* * * * *": ("1 percenként (60s)", "Every 1 minute (60s)"),
        "0 * * * * *": ("1 percenként (60s)", "Every 1 minute (60s)"),
        "*/5 * * * *": ("5 percenként (Gyakori)", "Every 5 minutes (Frequent)"),
        "*/10 * * * *": ("10 percenként", "Every 10 minutes"),
        "*/15 * * * *": ("15 percenként", "Every 15 minutes"),
        "*/30 * * * *": ("30 percenként", "Every 30 minutes"),
        "0 * * * *": ("1 óránként", "Every 1 hour"),
        "0 */2 * * *": ("2 óránként", "Every 2 hours"),
        "0 */4 * * *": ("4 óránként", "Every 4 hours"),
        "0 */6 * * *": ("6 óránként (Ajánlott)", "Every 6 hours (Recommended)"),
        "0 */12 * * *": ("12 óránként", "Every 12 hours"),
        "0 3 * * *": ("24 óránként (Hajnali 3:00)", "Every 24 hours (3:00 AM)"),
    }

    if norm in shorthands:
        return shorthands[norm][0] if is_hu else shorthands[norm][1]

    # Custom description for 6-part cron
    parts = norm.split()
    if len(parts) == 6 and parts[0].startswith("*/") and parts[1:] == ["*", "*", "*", "*", "*"]:
        secs = parts[0][2:]
        return f"{secs} másodpercenként (Egyedi)" if is_hu else f"Every {secs} seconds (Custom)"

    # Custom description for 5-part cron
    if len(parts) == 5 and parts[0].startswith("*/") and parts[1:] == ["*", "*", "*", "*"]:
        mins = parts[0][2:]
        return f"{mins} percenként (Egyedi)" if is_hu else f"Every {mins} minutes (Custom)"

    return f"Egyedi időzítés ({norm})" if is_hu else f"Custom schedule ({norm})"


def estimate_next_run(cron_expr: str, start_dt: Optional[datetime.datetime] = None) -> datetime.datetime:
    """Find next matching time up to 48 hours in the future."""
    dt = start_dt or datetime.datetime.now()
    if is_second_cron(cron_expr):
        cur = dt.replace(microsecond=0) + datetime.timedelta(seconds=1)
        for _ in range(7200):  # up to 2 hours
            if matches_cron(cron_expr, cur):
                return cur
            cur += datetime.timedelta(seconds=1)
        return cur
    else:
        cur = dt.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        for _ in range(2880):  # 48 hours
            if matches_cron(cron_expr, cur):
                return cur
            cur += datetime.timedelta(minutes=1)
        return cur


class AutonomousScheduler(threading.Thread):
    """Background daemon thread that continuously monitors cron schedule.

    Triggers automated speedtest measurements with strict Traffic Gate idle checking
    (< 2% network load condition) to ensure measurements are genuinely accurate and do
    not disrupt client traffic. Supports both second-level (6-part cron / seconds interval)
    and minute/hour-level scheduling.
    """

    def __init__(self, cfg: Config):
        super().__init__(name="nmb-autonomous-scheduler", daemon=True)
        self.cfg = cfg
        self.running = False
        self._stop_event = threading.Event()
        self.last_triggered_key: Tuple[int, ...] = ()
        self.last_run_timestamp: float = 0.0
        self.last_outcome: str = "idle"  # idle, running, completed, skipped_busy, error
        self.last_detail: str = ""
        self.last_checked_time: float = 0.0
        self._cycle_running = False

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()

    def run(self) -> None:
        self.running = True
        self._stop_event.clear()
        sched_cron = getattr(self.cfg.speedtest, "schedule_cron", "0 */6 * * *")
        log.info("AutonomousScheduler thread started. Schedule mode: %s, Cron: %s (Seconds-level: %s)",
                 getattr(self.cfg.speedtest, "schedule_mode", "scheduled"),
                 sched_cron,
                 is_second_cron(sched_cron))

        # Initial wait
        self._stop_event.wait(3.0)

        while self.running and not self._stop_event.is_set():
            try:
                now = datetime.datetime.now()
                self.last_checked_time = time.time()
                sched_mode = getattr(self.cfg.speedtest, "schedule_mode", "scheduled")
                sched_cron = getattr(self.cfg.speedtest, "schedule_cron", "0 */6 * * *")

                if sched_mode == "scheduled":
                    is_sec = is_second_cron(sched_cron)
                    current_key = (now.year, now.month, now.day, now.hour, now.minute, now.second) if is_sec else (now.year, now.month, now.day, now.hour, now.minute)

                    if current_key != self.last_triggered_key:
                        if matches_cron(sched_cron, now):
                            self.last_triggered_key = current_key

                            # Prevent overlapping cycles if previous test is still active
                            from nmb.speed.runner import is_speedtest_running
                            if is_speedtest_running() or self._cycle_running:
                                log.debug("AutonomousScheduler: previous measurement cycle still running at %s, skipping tick", now.strftime("%Y-%m-%d %H:%M:%S"))
                            else:
                                log.info("AutonomousScheduler: scheduled interval triggered (%s). Initiating cycle with Traffic Gate...", sched_cron)
                                self._execute_cycle()
                    else:
                        log.debug("AutonomousScheduler already triggered for %s", current_key)
                else:
                    log.debug("AutonomousScheduler idle: mode is %s (not scheduled)", sched_mode)

            except Exception as e:
                log.error("AutonomousScheduler loop exception: %s", e)

            # High precision 1s tick for second-level cron, or 3s tick for minute-level
            sleep_duration = 1.0 if is_second_cron(getattr(self.cfg.speedtest, "schedule_cron", "")) else 3.0
            self._stop_event.wait(sleep_duration)

        log.info("AutonomousScheduler thread stopped.")

    def _execute_cycle(self) -> None:
        """Run measurement cycle in a non-blocking worker thread."""
        def _worker():
            from nmb.speed.runner import run_measurement_cycle
            self._cycle_running = True
            self.last_outcome = "running"
            self.last_detail = "Measurement cycle in progress..."
            try:
                engine = getattr(self.cfg.speedtest, "automated_engine", "ookla")
                server_id = getattr(self.cfg.speedtest, "server_id", None)
                log.debug("AutonomousScheduler worker starting run_measurement_cycle (engine=%s, server_id=%s)", engine, server_id)
                ok = run_measurement_cycle(
                    self.cfg,
                    trigger="schedule",
                    force=False,
                    run_port_check=True,
                    server_id=server_id,
                    engine=engine,
                )
                self.last_run_timestamp = time.time()
                if ok:
                    self.last_outcome = "completed"
                    self.last_detail = f"Mérés sikeresen lefutott ({engine})"
                else:
                    self.last_outcome = "skipped_busy"
                    self.last_detail = "Mérés elhalasztva: hálózati terhelés meghaladta a pontossági küszöböt (<2%)"
                log.debug("AutonomousScheduler worker finished: outcome=%s, detail=%s", self.last_outcome, self.last_detail)
            except Exception as ex:
                log.error("AutonomousScheduler worker error: %s", ex)
                self.last_outcome = "error"
                self.last_detail = str(ex)
            finally:
                self._cycle_running = False

        t = threading.Thread(target=_worker, daemon=True, name="nmb-sched-runner")
        t.start()

    def get_status(self) -> dict:
        """Return full diagnostics on the scheduler and traffic gate."""
        now = datetime.datetime.now()
        sched_cron = getattr(self.cfg.speedtest, "schedule_cron", "0 */6 * * *")
        sched_mode = getattr(self.cfg.speedtest, "schedule_mode", "scheduled")
        thresh_pct = getattr(self.cfg.speedtest, "idle_threshold_percent", 2.0)
        thresh_mode = getattr(self.cfg.speedtest, "idle_threshold_mode", "percent")
        contract_down = getattr(self.cfg.isp, "contract_down_mbps", 1000.0)

        from nmb.probe.traffic_gate import TrafficGate
        gate = TrafficGate(self.cfg.network.wan_interface)
        cap_mbps = gate.get_interface_capacity_mbps(self.cfg.network.wan_interface, contract_down_mbps=contract_down)
        eff_thresh_kbps = gate.get_effective_threshold_kbps(
            capacity_mbps=cap_mbps,
            threshold_percent=thresh_pct,
            threshold_mode=thresh_mode,
            fixed_kbps=getattr(self.cfg.speedtest, "idle_threshold_kbps", 500)
        )
        gate_res = gate.is_idle(
            threshold_kbps=eff_thresh_kbps,
            iface=self.cfg.network.wan_interface,
            capacity_mbps=cap_mbps,
            threshold_percent=thresh_pct,
            mode=thresh_mode,
        )
        idle = gate_res.cleared
        cur_kbps = gate_res.rate_kbps
        load_pct = gate_res.load_percent

        next_dt = estimate_next_run(sched_cron, now) if sched_mode == "scheduled" else None

        return {
            "status": "active" if self.running else "stopped",
            "schedule_mode": sched_mode,
            "schedule_cron": sched_cron,
            "normalized_cron": normalize_cron_expression(sched_cron),
            "description_hu": get_cron_description(sched_cron, "hu"),
            "description_en": get_cron_description(sched_cron, "en"),
            "next_run_iso": next_dt.strftime("%Y-%m-%d %H:%M:%S") if next_dt else None,
            "last_run_timestamp": self.last_run_timestamp,
            "last_outcome": self.last_outcome,
            "last_detail": self.last_detail,
            "traffic_gate": {
                "mode": thresh_mode,
                "threshold_percent": thresh_pct,
                "effective_threshold_kbps": eff_thresh_kbps,
                "effective_threshold_mbps": round(eff_thresh_kbps / 1000.0, 2),
                "capacity_mbps": cap_mbps,
                "current_traffic_kbps": round(cur_kbps, 1),
                "current_load_percent": round(load_pct, 2),
                "is_gate_clear": idle,
            }
        }
