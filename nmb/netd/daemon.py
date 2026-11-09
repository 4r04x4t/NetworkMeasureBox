"""Network Measure Box dual-mode network daemon (nmb-netd).

Supervises network mode switching between Mode A (Active Gateway/PPPoE/NAT/AP)
and Mode B (Passive Inline Bridge), with auto-failover and SQLite logging.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from nmb.config import Config, load_config
from nmb.db import database as db
from nmb.netd.detector import NetworkDetector
from nmb.netd.modes import ModeA, ModeB, ModeStandalone, NetworkMode
from nmb.netd.services import ServiceManager

log = logging.getLogger("nmb.netd")

STATE_FILE = Path("/run/nmb/netd_state.json")


class NetworkDaemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.running = False
        self.current_mode_name: Optional[str] = None
        self.current_mode_inst: Optional[NetworkMode] = None
        self.state_file = cfg.system.run_dir / "netd_state.json"
        self.reload_requested = False
        self._build_modes()

    def _build_modes(self) -> None:
        network = self.cfg.network
        self.svc_mgr = ServiceManager(self.cfg.system.run_dir, network)
        self.modes = {
            "mode_a": ModeA(network, self.svc_mgr),
            "mode_b": ModeB(network, self.svc_mgr),
            "standalone": ModeStandalone(network, self.svc_mgr),
        }
        self.modes["mode_a"].full_cfg = self.cfg
        self.detector = NetworkDetector(network)

    def _apply_reload(self) -> None:
        """Reload config; rebuild the network only when its settings actually changed."""
        self.reload_requested = False
        _apply_kernel_tuning()
        old_network = self.cfg.network
        self.cfg = load_config()
        if self.cfg.network == old_network:
            return
        log.info("network configuration changed; re-applying active mode")
        active_mode = self.current_mode_name
        if self.current_mode_inst:
            try:
                self.current_mode_inst.teardown()
            except Exception as e:
                log.error("error during %s teardown: %s", active_mode, e)
        self.current_mode_name = None
        self.current_mode_inst = None
        self._build_modes()
        target_mode, reason = self.detector.evaluate_target_mode(self._get_override_mode())
        self.switch_mode(target_mode, f"configuration reload ({reason})")

    def _get_override_mode(self) -> Optional[str]:
        """Fetch manual override if set in DB kv table."""
        try:
            conn = db.connect(readonly=True)
            row = conn.execute("SELECT v FROM kv WHERE k = 'override_mode'").fetchone()
            conn.close()
            if row and row["v"] in ("mode_a", "mode_b", "standalone", "auto"):
                return None if row["v"] == "auto" else row["v"]
        except Exception as e:
            log.debug("could not query override_mode from db: %s", e)
        return None

    def _record_event(self, severity: str, kind: str, detail: str) -> None:
        try:
            conn = db.connect()
            with db.tx(conn):
                now = db.now_ms()
                conn.execute(
                    "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, ?, 'netd', ?, ?)",
                    (now, severity, kind, detail)
                )
                if kind == "mode_change":
                    conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('active_mode', ?, ?)",
                                 (self.current_mode_name or "", now))
                    wan = getattr(self.current_mode_inst, "active_wan", self.cfg.network.wan_interface)
                    conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('active_wan_iface', ?, ?)",
                                 (wan, now))
            conn.close()
        except Exception as e:
            log.warning("failed to write event to db: %s", e)

    def _dump_state(self) -> None:
        """Write atomic state snapshot to state_file."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            mode_status = self.current_mode_inst.get_status() if self.current_mode_inst else {}
            d = getattr(self.detector, "last_decision", None) if self.cfg.network.mode == "auto" else None
            state_data = {
                "active_mode": self.current_mode_name,
                "configured_mode": self.cfg.network.mode,
                "auto_decision": ({"mode": d.mode, "reason": d.reason, "passthrough_ports": d.passthrough_ports,
                                   "pppoe": d.pppoe} if d else None),
                "timestamp_ms": db.now_ms(),
                "details": mode_status,
            }
            tmp_file = self.state_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(state_data, indent=2))
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            log.warning("could not write state file: %s", e)

    def switch_mode(self, new_mode: str, reason: str) -> bool:
        if new_mode == self.current_mode_name and self.current_mode_inst:
            return True

        log.info("SWITCHING MODE: %s -> %s (reason: %s)", self.current_mode_name, new_mode, reason)
        old_mode = self.current_mode_name

        if self.current_mode_inst:
            try:
                self.current_mode_inst.teardown()
            except Exception as e:
                log.error("error during %s teardown: %s", self.current_mode_name, e)

        target_inst = self.modes.get(new_mode)
        if not target_inst:
            log.error("unknown network mode: %s", new_mode)
            return False

        try:
            target_inst.setup()
            self.current_mode_name = new_mode
            self.current_mode_inst = target_inst
            self._record_event("info", "mode_change", f"Switched from {old_mode} to {new_mode}: {reason}")
            self._dump_state()
            return True
        except Exception as e:
            log.critical("failed to setup %s: %s", new_mode, e)
            self._record_event("crit", "mode_change_failed", f"Failed switching to {new_mode}: {e}")
            return False

    def _apply_auto_details(self, override: Optional[str]) -> None:
        """mode = auto: pass the decision's details to the modes (LAN passthrough ports, PPPoE)."""
        d = self.detector.last_decision if (self.cfg.network.mode == "auto" and not override) else None
        std, ma = self.modes["standalone"], self.modes["mode_a"]
        want_pt = list(d.passthrough_ports) if d and d.mode == "standalone" else []
        want_ppp = bool(d and d.mode == "mode_a" and d.pppoe)
        if want_pt != getattr(std, "auto_passthrough", []):
            std.auto_passthrough = want_pt
            if self.current_mode_name == "standalone" and self.current_mode_inst is std:
                log.info("auto mode: LAN passthrough ports now %s; rebuilding standalone", want_pt or "none")
                std.teardown()
                std.setup()
        if want_ppp != getattr(ma, "auto_pppoe", False):
            ma.auto_pppoe = want_ppp
            if self.current_mode_name == "mode_a" and self.current_mode_inst is ma:
                log.info("auto mode: PPPoE %s; rebuilding router mode", "on" if want_ppp else "off")
                ma.teardown()
                ma.setup()

    def handle_signal(self, signum: int, frame) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            log.info("received termination signal (%d), stopping netd...", signum)
            self.running = False
        elif signum == signal.SIGHUP:
            log.info("received SIGHUP, scheduling configuration reload")
            self.reload_requested = True

    def _timed(self, name: str, fn, *args) -> None:
        """Run one part of the loop; a slow part is logged, since the loop also keeps the box online."""
        t0 = time.monotonic()
        try:
            fn(*args)
        except Exception as e:
            log.debug("%s: %s", name, e)
        took = time.monotonic() - t0
        if took > 15:
            log.warning("netd loop: %s took %.0f s (the network is not supervised meanwhile)", name, took)

    def run(self) -> None:
        self.running = True
        import faulthandler
        faulthandler.register(signal.SIGUSR1, all_threads=True)  # `kill -USR1 <pid>`: stacks to the journal
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self.handle_signal)

        log.info("starting nmb-netd daemon (box_id=%s, mode=%s)",
                 self.cfg.system.box_id, self.cfg.network.mode)

        # Write PID file for process supervision & reloading
        pid_file = self.cfg.system.run_dir / "netd.pid"
        try:
            self.cfg.system.run_dir.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()))
        except Exception as e:
            log.debug("could not write pidfile: %s", e)

        _apply_kernel_tuning()

        # Initial assessment
        override = self._get_override_mode()
        initial_mode, reason = self.detector.evaluate_target_mode(override)
        self.switch_mode(initial_mode, f"initial startup ({reason})")

        while self.running:
            try:
                time.sleep(self.cfg.network.check_interval_sec)
                if self.reload_requested:
                    self._apply_reload()
                loop_t0 = time.monotonic()
                override = self._get_override_mode()
                self.detector.current_mode = self.current_mode_name
                self.detector.ip_device = getattr(self.current_mode_inst, "active_wan", None)
                target_mode, reason, is_ready = self.detector.get_debounced_mode(override)
                self._apply_auto_details(override)

                if isinstance(self.current_mode_inst, ModeA):
                    self.current_mode_inst.check_wan_failover()
                    self._timed("pppd watch", self.current_mode_inst.check_pppd)
                    # USB tethering as the WAN when nothing upstream answers on the WAN port, and back.
                    self.current_mode_inst.full_cfg = self.cfg
                    self.current_mode_inst.check_usb_wan()
                    if self.current_mode_inst.needs_resetup:
                        log.info("Mode A: WAN source changed; rebuilding the router setup")
                        self.current_mode_inst.teardown()
                        self.current_mode_inst.setup()
                # A default route through a port with no cable or no address leads nowhere but still wins.
                from nmb.netd import interfaces as _ifs
                self._timed("dead route reaper", _ifs.reap_dead_default_routes)
                # IPv4 DNS before IPv6 DNS (checked every 10 minutes; a no-op once set).
                if time.monotonic() - getattr(self, "_dns_prio_ts", -1e9) > 600:
                    self._dns_prio_ts = time.monotonic()
                    self._timed("dns priority", _ifs.prefer_ipv4_dns)
                # Keep a root-only copy of the secrets the owner typed, to restore them if a bug wipes them.
                from nmb.common import secret_keep
                self._timed("secret keep", secret_keep.update)
                # Tests bound to the Wi-Fi address must leave over Wi-Fi, even with a cable in.
                from nmb.netd import usb_uplink
                from nmb.netd.wifi_uplink import sync_source_routing
                from nmb.netd.wifi_share import sync as wifi_share_sync
                from nmb.common.storage_guard import run as storage_guard_run
                self._timed("wifi uplink routing", sync_source_routing, self.cfg)
                # A phone, hotspot or modem on USB: its own profile, never the default route.
                self._timed("usb keep_up", usb_uplink.keep_up, self.cfg)
                self._timed("usb source routing", usb_uplink.sync_source_routing, self.cfg)
                # Router mode picks its own WAN (check_usb_wan); elsewhere USB may also replace a dead route.
                self._timed("usb default fallback", usb_uplink.sync_default_fallback, self.cfg,
                            not isinstance(self.current_mode_inst, ModeA))
                # The Wi-Fi internet on the LAN port, only while that port has no upstream.
                self._timed("wifi share", wifi_share_sync, self.cfg)
                # Free space before the disk fills up (checks every 10 minutes).
                self._timed("storage guard", storage_guard_run, self.cfg)

                if is_ready and target_mode != self.current_mode_name:
                    self.switch_mode(target_mode, reason)
                else:
                    self._dump_state()
                if time.monotonic() - loop_t0 > 30:
                    log.warning("netd loop took %.0f s", time.monotonic() - loop_t0)
            except Exception as e:
                log.error("unexpected error in netd loop: %s", e, exc_info=True)

        # Teardown on exit
        log.info("cleaning up network interfaces before exit")
        if self.current_mode_inst:
            self.current_mode_inst.teardown()
        STATE_FILE.unlink(missing_ok=True)
        pid_file.unlink(missing_ok=True)
        log.info("nmb-netd shutdown complete")


def _apply_kernel_tuning() -> None:
    """Kernel tuning needs root, so netd owns it; the unprivileged web server asks via reload."""
    try:
        from nmb.netd.kernel import apply_kernel_network_tuning
        apply_kernel_network_tuning()
    except Exception as e:
        log.warning("kernel network tuning failed: %s", e)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-netd", description="NetworkMeasureBox network daemon")
    parser.add_argument("--config", "-c", type=Path, help="Path to nmb.conf")
    parser.add_argument("--status", action="store_true", help="Print current network status JSON and exit")
    parser.add_argument("--switch", choices=["auto", "standalone", "mode_a", "mode_b"], help="Set mode override in DB and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    if args.status:
        if STATE_FILE.exists():
            print(STATE_FILE.read_text())
            return 0
        print(json.dumps({"status": "inactive", "message": "nmb-netd is not running or state file missing"}))
        return 1

    if args.switch:
        conn = db.connect()
        with db.tx(conn):
            conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('override_mode', ?, ?)",
                         (args.switch, db.now_ms()))
        conn.close()
        print(f"Override mode set to '{args.switch}'. Daemon will transition shortly.")
        return 0

    cfg = load_config(args.config)
    daemon = NetworkDaemon(cfg)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
