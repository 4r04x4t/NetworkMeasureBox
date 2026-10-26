"""High-performance native latency and jitter measurement engine (nmb-probe).

Sends sub-second ICMP Echo Requests across configured targets using a single
non-blocking socket, tracks lost packets, calculates RFC 3550 jitter, detects outages,
and flushes batched samples to SQLite in low-frequency transactions.
"""
from __future__ import annotations

import argparse
import collections
import logging
import os
import select
import signal
import sys
import time
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from nmb.config import Config, load_config
from nmb.db import database as db
from nmb.probe.icmp import build_echo_request, create_icmp_socket, extract_kernel_timestamp_ns, parse_echo_reply
from nmb.probe.traffic_gate import TrafficGate

log = logging.getLogger("nmb.probe.engine")


@dataclass
class PendingPing:
    target_id: int
    addr: str
    seq: int
    send_ns: int
    deadline_sec: float


@dataclass
class TargetState:
    id: int
    addr: str
    label: str
    role: str = "Public DNS"
    last_rtt_us: Optional[int] = None
    jitter_us: int = 0
    consecutive_loss: int = 0


class ProbeEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.running = False
        self.ident = os.getpid() & 0xFFFF
        self.seq = 0
        bind_dev = cfg.network.wan_interface if cfg.network.wan_interface else None
        self.sock, self.is_raw = create_icmp_socket(bind_iface=bind_dev)

        # High-performance kernel epoll event loop
        self.epoll: Optional[select.epoll] = None
        if hasattr(select, "epoll"):
            try:
                self.epoll = select.epoll()
                self.epoll.register(self.sock.fileno(), select.EPOLLIN | select.EPOLLERR | select.EPOLLHUP)
                log.debug("Kernel epoll event polling initialized for ICMP socket")
            except Exception as e:
                log.debug("epoll init fallback: %s", e)

        self.targets: Dict[int, TargetState] = {}
        self.addr_to_target_id: Dict[str, int] = {}
        self.pending_pings: Dict[Tuple[int, int], PendingPing] = {}  # (target_id, seq) -> PendingPing
        self.sample_queue: Deque[Tuple[int, int, Optional[int]]] = collections.deque()

        self.interval_sec = cfg.probe.ping_interval_ms / 1000.0
        self.batch_flush_sec = cfg.probe.batch_flush_sec
        self.timeout_sec = 1.5
        # Calculate consecutive failure threshold to declare outage (e.g. 15s / 0.5s = 30 ticks)
        self.outage_loss_ticks = max(3, int(cfg.probe.outage_loss_seconds / max(0.05, self.interval_sec)))

        self.traffic_gate = TrafficGate(cfg.network.wan_interface)
        self.active_outage_id: Optional[int] = None
        self.last_flush_time = time.monotonic()
        self.last_gate_sample_time = time.monotonic()
        self.last_gw_sync_time = time.monotonic()

    def _load_targets(self) -> None:
        """Load target list from SQLite database, enrolling dynamic gateway targets."""
        try:
            from nmb.netd.interfaces import sync_gateway_ping_targets
            try:
                sync_conn = db.connect()
                with db.tx(sync_conn):
                    sync_gateway_ping_targets(sync_conn, self.cfg.network.wan_interface)
                sync_conn.close()
            except Exception as e:
                log.debug("gateway sync error: %s", e)

            conn = db.connect(readonly=True)
            rows = conn.execute("SELECT id, addr, label, role FROM target WHERE enabled = 1").fetchall()
            conn.close()
            new_targets: Dict[int, TargetState] = {}
            new_addr_map: Dict[str, int] = {}
            for r in rows:
                tid = r["id"]
                addr = r["addr"]
                role = r["role"] if "role" in r.keys() and r["role"] else "Public DNS"
                existing = self.targets.get(tid)
                if existing:
                    existing.addr = addr
                    existing.label = r["label"]
                    existing.role = role
                    new_targets[tid] = existing
                else:
                    new_targets[tid] = TargetState(id=tid, addr=addr, label=r["label"], role=role)
                new_addr_map[addr] = tid

            self.targets = new_targets
            self.addr_to_target_id = new_addr_map
            log.info("loaded %d probe targets from DB: %s",
                     len(self.targets), ", ".join(f"{t.addr} ({t.role})" for t in self.targets.values()))
        except Exception as e:
            log.error("failed loading targets from db: %s; using defaults", e)
            defaults = [
                (1, "1.1.1.1", "Cloudflare", "Public DNS"),
                (2, "8.8.8.8", "Google", "Public DNS"),
                (3, "9.9.9.9", "Quad9", "Public DNS"),
                (4, "185.222.222.222", "DNS.SB", "Public DNS"),
            ]
            for tid, addr, label, role in defaults:
                self.targets[tid] = TargetState(id=tid, addr=addr, label=label, role=role)
                self.addr_to_target_id[addr] = tid

    def _send_probes(self) -> None:
        now_ns = time.time_ns()
        now_mono = time.monotonic()

        for tid, target in self.targets.items():
            self.seq = (self.seq + 1) & 0xFFFF
            packet = build_echo_request(self.ident, self.seq)
            try:
                # SOCK_DGRAM requires port 0 in address tuple
                dest = (target.addr, 0) if not self.is_raw else (target.addr, 1)
                self.sock.sendto(packet, dest)
                self.pending_pings[(tid, self.seq)] = PendingPing(
                    target_id=tid,
                    addr=target.addr,
                    seq=self.seq,
                    send_ns=now_ns,
                    deadline_sec=now_mono + self.timeout_sec
                )
            except OSError as e:
                log.debug("sendto error for %s: %s", target.addr, e)
                # Enqueue immediate lost sample
                self.sample_queue.append((db.now_ms(), tid, None))

    def _process_replies(self, timeout_sec: float) -> None:
        """Read incoming ICMP packets using kernel timestamps and epoll/select."""
        end_time = time.monotonic() + timeout_sec
        while time.monotonic() < end_time:
            remaining = max(0.0, end_time - time.monotonic())
            if self.epoll is not None:
                events = self.epoll.poll(timeout=remaining)
                if not events:
                    break
            else:
                r, _, _ = select.select([self.sock], [], [], remaining)
                if not r:
                    break

            try:
                # recvmsg enables receiving socket control messages (ancdata) with kernel timestamp
                data, ancdata, flags, src = self.sock.recvmsg(2048, 1024)
            except OSError:
                break

            parsed = parse_echo_reply(data, self.is_raw)
            if not parsed:
                continue

            _, ident, seq, send_ns_payload = parsed
            src_ip = src[0]
            tid = self.addr_to_target_id.get(src_ip)

            # Match pending request
            key = (tid, seq) if tid else None
            pending = self.pending_pings.pop(key, None) if key else None

            if not pending and not tid:
                continue

            # Extract hardware/kernel receive timestamp from ancdata (eliminates userspace scheduling jitter)
            kernel_recv_ns = extract_kernel_timestamp_ns(ancdata)
            now_ns = kernel_recv_ns if kernel_recv_ns is not None else time.time_ns()

            # Calculate RTT in microseconds
            orig_send_ns = pending.send_ns if pending else send_ns_payload
            rtt_us = max(1, (now_ns - orig_send_ns) // 1000) if orig_send_ns > 0 else 1000

            target = self.targets.get(tid or 0)
            if target:
                # RFC 3550 jitter calculation: J = J + (|D| - J) / 16
                if target.last_rtt_us is not None:
                    d = abs(rtt_us - target.last_rtt_us)
                    target.jitter_us = int(target.jitter_us + (d - target.jitter_us) / 16.0)
                target.last_rtt_us = rtt_us
                target.consecutive_loss = 0

            ts_ms = db.now_ms()
            self.sample_queue.append((ts_ms, tid or 1, rtt_us))

    def _check_timeouts(self) -> None:
        """Expire pending requests past deadline as lost packets."""
        now_mono = time.monotonic()
        expired_keys = [k for k, p in self.pending_pings.items() if p.deadline_sec <= now_mono]

        for k in expired_keys:
            pending = self.pending_pings.pop(k)
            target = self.targets.get(pending.target_id)
            if target:
                target.consecutive_loss += 1

            ts_ms = db.now_ms()
            self.sample_queue.append((ts_ms, pending.target_id, None))

    def _evaluate_outage(self, conn: db.sqlite3.Connection) -> None:
        """Detect and log network-wide outages when all targets drop packets."""
        now_ms = db.now_ms()
        all_down = len(self.targets) > 0 and all(t.consecutive_loss >= self.outage_loss_ticks for t in self.targets.values())

        if all_down and self.active_outage_id is None:
            # Outage started
            log.warning("OUTAGE DETECTED: all targets unreachable")
            with db.tx(conn):
                cur = conn.execute(
                    "INSERT INTO outage (start_ts, cause) VALUES (?, 'all probe targets unreachable')",
                    (now_ms,)
                )
                self.active_outage_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'crit', 'probe', 'outage_start', 'Total connectivity loss detected')",
                    (now_ms,)
                )

        elif not all_down and self.active_outage_id is not None:
            # Outage recovered
            log.info("OUTAGE RECOVERED: reachability restored")
            with db.tx(conn):
                conn.execute(
                    "UPDATE outage SET end_ts = ? WHERE id = ?",
                    (now_ms, self.active_outage_id)
                )
                conn.execute(
                    "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'probe', 'outage_end', 'Connectivity restored across probe targets')",
                    (now_ms,)
                )
            self.active_outage_id = None

    def _flush_samples(self) -> None:
        """Flush batched samples to SQLite ping_sample table in a single atomic transaction."""
        if not self.sample_queue:
            return

        batch: List[Tuple[int, int, Optional[int]]] = []
        while self.sample_queue and len(batch) < 5000:
            batch.append(self.sample_queue.popleft())

        try:
            conn = db.connect()
            with db.tx(conn):
                conn.executemany("INSERT OR REPLACE INTO ping_sample (ts, target_id, rtt_us) VALUES (?, ?, ?)", batch)

            self._evaluate_outage(conn)

            # Record traffic gate throughput
            now = time.monotonic()
            if now - self.last_gate_sample_time >= 5.0:
                self.traffic_gate.sample()
                self.traffic_gate.record_stats(conn)
                self.last_gate_sample_time = now

            conn.close()
            log.debug("flushed %d ping samples to database", len(batch))
        except Exception as e:
            log.error("failed flushing samples to db: %s", e)

    def handle_signal(self, signum: int, frame) -> None:
        log.info("received signal %d, stopping probe engine...", signum)
        self.running = False

    def run(self) -> None:
        self.running = True
        import threading
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.handle_signal)
            signal.signal(signal.SIGINT, self.handle_signal)

        self._load_targets()
        log.info("starting nmb-probe latency & jitter polling loop (interval=%.2fs)", self.interval_sec)

        while self.running:
            loop_start = time.monotonic()

            self._send_probes()
            # Wait for replies within probe interval
            self._process_replies(self.interval_sec)
            self._check_timeouts()

            # Flush periodically
            now = time.monotonic()
            if now - self.last_flush_time >= self.batch_flush_sec:
                self._flush_samples()
                self.last_flush_time = now

            # Periodically re-sync gateway targets (every 1 hour)
            if now - self.last_gw_sync_time >= 3600.0:
                self._load_targets()
                self.last_gw_sync_time = now

            # Throttle loop to maintain consistent interval
            elapsed = time.monotonic() - loop_start
            sleep_needed = self.interval_sec - elapsed
            if sleep_needed > 0.005:
                time.sleep(sleep_needed)

        # Final drain flush on exit
        log.info("draining final %d samples to database before exit...", len(self.sample_queue))
        self._flush_samples()
        self.sock.close()
        log.info("nmb-probe engine shutdown complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-probe", description="NetworkMeasureBox latency/jitter probe engine")
    parser.add_argument("--config", "-c", help="Path to nmb.conf")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    cfg = load_config(args.config)
    engine = ProbeEngine(cfg)
    engine.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
