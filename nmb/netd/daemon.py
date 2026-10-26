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

        self.svc_mgr = ServiceManager(cfg.system.run_dir, cfg.network)
        self.modes = {
            "mode_a": ModeA(cfg.network, self.svc_mgr),
            "mode_b": ModeB(cfg.network, self.svc_mgr),
            "standalone": ModeStandalone(cfg.network, self.svc_mgr),
        }
        self.detector = NetworkDetector(cfg.network)

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
            state_data = {
                "active_mode": self.current_mode_name,
                "configured_mode": self.cfg.network.mode,
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

    def handle_signal(self, signum: int, frame) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            log.info("received termination signal (%d), stopping netd...", signum)
            self.running = False
        elif signum == signal.SIGHUP:
            log.info("received SIGHUP, reloading configuration")
            self.cfg = load_config()

    def run(self) -> None:
        self.running = True
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

        # Initial assessment
        override = self._get_override_mode()
        initial_mode, reason = self.detector.evaluate_target_mode(override)
        self.switch_mode(initial_mode, f"initial startup ({reason})")

        while self.running:
            try:
                time.sleep(self.cfg.network.check_interval_sec)
                override = self._get_override_mode()
                target_mode, reason, is_ready = self.detector.get_debounced_mode(override)

                if is_ready and target_mode != self.current_mode_name:
                    self.switch_mode(target_mode, reason)
                else:
                    self._dump_state()
            except Exception as e:
                log.error("unexpected error in netd loop: %s", e, exc_info=True)

        # Teardown on exit
        log.info("cleaning up network interfaces before exit")
        if self.current_mode_inst:
            self.current_mode_inst.teardown()
        STATE_FILE.unlink(missing_ok=True)
        pid_file.unlink(missing_ok=True)
        log.info("nmb-netd shutdown complete")


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
