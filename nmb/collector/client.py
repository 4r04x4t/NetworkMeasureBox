"""Send this box's measurements to a central collector (``nmb-collector``).

Off by default. When ``[collector] enabled = true``, the box sends what is new since
the last successful upload every ``interval_min`` minutes:

* speed tests (every result, failed ones included, so the collector sees gaps too);
* one ping summary per target and hour;
* the box's identity: its permanent unique ID, its name, the case number, the ISP,
  the customer number set under ISP, and the subscribed speeds.

With ``share_diagnostics = true`` (only with the owner's consent) it also sends the
box's events and, hourly, the full network diagnostics report (``llm_bundle``):
interfaces, routes, MTU, DNS, NAT, Wi-Fi, traceroute, the devices on the LAN and the
settings with every secret masked.

Without it nothing else leaves the box: no settings, passwords or traffic data.
The collector identifies the box by ``box_uid``, a random ID made once per box,
since the box name (``box_id``) is ``nmb-01`` on every box unless changed.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nmb.db import database as db

log = logging.getLogger("nmb.collector")

UID_FILE = Path(os.environ.get("NMB_BOX_UID_FILE", "/var/lib/nmb/box_uid"))
KV_LAST_SPEED = "collector_last_speed_id"
KV_LAST_PING = "collector_last_ping_hour"
KV_STATUS = "collector_status"
KV_LAST_EVENT = "collector_last_event_id"
KV_LAST_DIAG = "collector_last_diag_ts"
DIAG_INTERVAL_SEC = 3600
BATCH = 500
PROTOCOL = 1

SPEED_FIELDS = (
    "id", "ts", "trigger", "status", "engine", "server_id", "server_name", "server_host",
    "server_location", "down_bps", "up_bps", "ping_us", "jitter_us", "loss_pct",
    "down_loaded_lat_ms", "up_loaded_lat_ms", "bufferbloat_grade", "connection_type",
    "client_ip", "client_ipv6", "result_url", "error", "bound_iface",
)

_UID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: easy to read out on the phone


def box_uid() -> str:
    """The box's permanent unique ID, e.g. ``nmb-k7q2-x9mf-3hwd``; made on first use."""
    try:
        uid = UID_FILE.read_text().strip()
        if uid.startswith("nmb-") and 10 <= len(uid) <= 40:
            return uid
    except OSError:
        pass
    raw = "".join(secrets.choice(_UID_ALPHABET) for _ in range(12))
    uid = f"nmb-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"
    try:
        UID_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = UID_FILE.with_suffix(".tmp")
        tmp.write_text(uid + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, UID_FILE)
    except OSError as e:
        log.warning("could not save the box ID: %s", e)
    return uid


def _kv_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    return str(row[0]) if row else default


def _kv_set(conn, key: str, value: str) -> None:
    with db.tx(conn):
        conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (key, value, int(time.time() * 1000)))


def build_payload(conn, cfg) -> Dict[str, Any]:
    """What would be sent now: everything new since the last successful upload."""
    last_speed = int(_kv_get(conn, KV_LAST_SPEED, "0") or 0)
    last_hour = int(_kv_get(conn, KV_LAST_PING, "0") or 0)
    cols = ", ".join(SPEED_FIELDS)
    cur = conn.execute(f"SELECT {cols} FROM speedtest WHERE id > ? ORDER BY id LIMIT ?", (last_speed, BATCH))
    speed = [dict(zip(SPEED_FIELDS, row)) for row in cur.fetchall()]

    # Whole hours only: the current hour is sent once it is over.
    this_hour = int(time.time() // 3600) * 3600 * 1000
    rows = conn.execute(
        """SELECT (p.ts / 3600000) * 3600000 AS hour, t.addr, t.label,
                  SUM(p.sent), SUM(p.lost), MIN(p.rtt_min), AVG(p.rtt_avg), MAX(p.rtt_max), AVG(p.jitter_us)
             FROM ping_minute p JOIN target t ON t.id = p.target_id
            WHERE p.ts >= ? AND p.ts < ?
            GROUP BY hour, t.id ORDER BY hour LIMIT ?""",
        (last_hour, this_hour, BATCH),
    ).fetchall()
    ping = [
        {"hour": r[0], "target": r[1], "label": r[2], "sent": r[3], "lost": r[4],
         "rtt_min_us": r[5], "rtt_avg_us": int(r[6]) if r[6] is not None else None,
         "rtt_max_us": r[7], "jitter_us": int(r[8]) if r[8] is not None else None}
        for r in rows
    ]
    from nmb.common.backup import APP_VERSION
    isp = getattr(cfg, "isp", None)
    extra: Dict[str, Any] = {}
    if cfg.collector.share_diagnostics:
        last_event = int(_kv_get(conn, KV_LAST_EVENT, "0") or 0)
        extra["events"] = [
            {"id": r[0], "ts": r[1], "severity": r[2], "source": r[3], "kind": r[4], "detail": (r[5] or "")[:2000]}
            for r in conn.execute(
                "SELECT id, ts, severity, source, kind, detail FROM event WHERE id > ? AND severity != 'debug' ORDER BY id LIMIT ?",
                (last_event, BATCH))
        ]
        last_diag = int(_kv_get(conn, KV_LAST_DIAG, "0") or 0)
        if time.time() - last_diag >= DIAG_INTERVAL_SEC:
            try:
                from nmb.report.llm_bundle import generate_llm_diagnostic_bundle
                extra["diagnostics"] = {"ts": int(time.time() * 1000), "markdown": generate_llm_diagnostic_bundle(cfg)}
            except Exception as e:
                log.warning("could not build the diagnostics for the collector: %s", e)
    return {
        "protocol": PROTOCOL,
        "box_uid": box_uid(),
        "box_name": str(getattr(cfg.system, "box_id", "")),
        "case_id": cfg.collector.case_id,
        "app_version": APP_VERSION,
        "sent_at": int(time.time() * 1000),
        "isp": {
            "name": getattr(isp, "name", "") if isp else "",
            "account_id": getattr(isp, "account_id", "") if isp else "",
            "contract_down_mbps": getattr(isp, "contract_down_mbps", None) if isp else None,
            "contract_up_mbps": getattr(isp, "contract_up_mbps", None) if isp else None,
            "connection_type": getattr(isp, "connection_type", "") if isp else "",
        },
        "speedtests": speed,
        "ping_hours": ping,
        "share_diagnostics": bool(cfg.collector.share_diagnostics),
        "allow_remote_control": bool(cfg.collector.allow_remote_control),
        **extra,
    }


def _post(url: str, token: str, payload: Dict[str, Any], timeout: float = 20.0, path: str = "/api/ingest") -> Dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url.rstrip("/") + path, data=data, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "User-Agent": "NetworkMeasureBox-collector-client"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL set by the box owner
        return json.loads(resp.read(1 << 20) or b"{}")


def send_now(cfg, conn=None) -> Dict[str, Any]:
    """Upload what is new; returns and stores the outcome."""
    co = cfg.collector
    if not (co.url and co.token):
        return {"ok": False, "message": "Set the collector address and token first."}
    if not co.url.startswith(("https://", "http://")):
        return {"ok": False, "message": "The collector address must start with https:// or http://."}
    own = conn is None
    conn = conn or db.connect()
    try:
        sent_speed = sent_ping = 0
        status: Dict[str, Any]
        for _ in range(20):  # catch up in batches after a long offline time
            payload = build_payload(conn, cfg)
            if not payload["speedtests"] and not payload["ping_hours"] and not payload.get("events") \
                    and "diagnostics" not in payload and sent_speed + sent_ping > 0:
                break
            answer = _post(co.url, co.token, payload)
            if not answer.get("ok"):
                raise ValueError(answer.get("error") or "the collector refused the upload")
            if payload["speedtests"]:
                _kv_set(conn, KV_LAST_SPEED, str(payload["speedtests"][-1]["id"]))
            if payload["ping_hours"]:
                _kv_set(conn, KV_LAST_PING, str(payload["ping_hours"][-1]["hour"] + 3600 * 1000))
            if payload.get("events"):
                _kv_set(conn, KV_LAST_EVENT, str(payload["events"][-1]["id"]))
            if "diagnostics" in payload:
                _kv_set(conn, KV_LAST_DIAG, str(int(time.time())))
            sent_speed += len(payload["speedtests"])
            sent_ping += len(payload["ping_hours"])
            if len(payload["speedtests"]) < BATCH and len(payload["ping_hours"]) < BATCH and len(payload.get("events") or []) < BATCH:
                break
        status = {"ok": True, "ts": int(time.time()), "speedtests": sent_speed, "ping_hours": sent_ping,
                  "message": f"Sent {sent_speed} speed test(s) and {sent_ping} ping hour(s)."}
    except urllib.error.HTTPError as e:
        status = {"ok": False, "ts": int(time.time()),
                  "message": "The collector refused the token." if e.code in (401, 403) else f"The collector answered HTTP {e.code}."}
    except (urllib.error.URLError, OSError, ValueError) as e:
        status = {"ok": False, "ts": int(time.time()), "message": f"Could not reach the collector: {getattr(e, 'reason', e)}"}
    finally:
        try:
            if "status" in locals():
                _kv_set(conn, KV_STATUS, json.dumps(status))
        finally:
            if own:
                conn.close()
    log.info("collector upload: %s", status["message"])
    return status


def get_status(cfg) -> Dict[str, Any]:
    conn = db.connect()
    try:
        last = json.loads(_kv_get(conn, KV_STATUS, "{}") or "{}")
        pending = conn.execute("SELECT COUNT(*) FROM speedtest WHERE id > ?",
                               (int(_kv_get(conn, KV_LAST_SPEED, "0") or 0),)).fetchone()[0]
    finally:
        conn.close()
    co = cfg.collector
    return {
        "enabled": co.enabled, "url": co.url, "token_set": bool(co.token), "case_id": co.case_id,
        "interval_min": co.interval_min, "share_diagnostics": co.share_diagnostics,
        "allow_remote_control": co.allow_remote_control, "box_uid": box_uid(), "box_name": cfg.system.box_id,
        "last": last, "pending_speedtests": pending,
    }


# ------------------------------------------------------------------------------
# Remote control (opt-in): the box asks the collector for work, so nothing connects in
# ------------------------------------------------------------------------------

POLL_SEC = 60
ENGINES = ("ookla", "rtr", "cloudflare", "fastcom", "all")
_results: List[Dict[str, Any]] = []
_results_lock = threading.Lock()


def run_command(cfg, cmd: Dict[str, Any]) -> Dict[str, Any]:
    """Run one command from the collector; only this fixed list exists."""
    kind = cmd.get("kind")
    args = cmd.get("args") if isinstance(cmd.get("args"), dict) else {}
    log.info("collector command %s %s", kind, args)
    if kind == "speedtest":
        engine = args.get("engine", "rtr")
        if engine not in ENGINES:
            return {"ok": False, "message": "unknown engine"}
        sid = args.get("server_id")
        if sid is not None and not (isinstance(sid, int) and 0 < sid < 10_000_000):
            return {"ok": False, "message": "invalid server ID"}
        from nmb.speed.runner import run_measurement_cycle
        outcome: Dict[str, Any] = {}
        ok = run_measurement_cycle(cfg, trigger="manual", force=True, run_port_check=False,
                                   server_id=sid, engine=engine, outcome=outcome)
        send_now(cfg)
        return {"ok": bool(ok), "message": f"speed test ({engine}) {'finished' if ok else 'failed'}; results uploaded"}
    if kind == "diagnostics":
        conn = db.connect()
        try:
            _kv_set(conn, KV_LAST_DIAG, "0")
        finally:
            conn.close()
        res = send_now(cfg)
        return {"ok": res.get("ok", False), "message": res.get("message", "")}
    if kind == "upload":
        res = send_now(cfg)
        return {"ok": res.get("ok", False), "message": res.get("message", "")}
    return {"ok": False, "message": "unknown command"}


def poll_once(cfg) -> int:
    """Report finished commands, fetch new ones and run them; returns how many ran."""
    co = cfg.collector
    with _results_lock:
        results = list(_results)
    answer = _post(co.url, co.token, {"box_uid": box_uid(), "allow_remote_control": bool(co.allow_remote_control),
                                      "results": results}, path="/api/poll")
    with _results_lock:
        del _results[:len(results)]
    ran = 0
    for cmd in answer.get("commands") or []:
        if not co.allow_remote_control:
            break
        try:
            res = run_command(cfg, cmd)
        except Exception as e:
            log.exception("collector command failed")
            res = {"ok": False, "message": str(e)}
        with _results_lock:
            _results.append({"id": cmd.get("id"), **res})
        ran += 1
    return ran


_thread: Optional[threading.Thread] = None
_wake = threading.Event()


def wake() -> None:
    _wake.set()


def start(cfg_getter: Callable[[], Any]) -> None:
    """Background uploader; does nothing while the collector is off."""
    global _thread
    if _thread and _thread.is_alive():
        wake()
        return

    def loop() -> None:
        time.sleep(30)
        next_upload = 0.0
        while True:
            cfg = cfg_getter()
            co = cfg.collector
            if co.enabled and co.url and co.token:
                if time.time() >= next_upload or _wake.is_set():
                    _wake.clear()
                    try:
                        send_now(cfg)
                    except Exception:
                        log.exception("collector upload failed")
                    next_upload = time.time() + max(5, co.interval_min) * 60
                if co.allow_remote_control:
                    try:
                        poll_once(cfg)
                    except (urllib.error.URLError, OSError, ValueError) as e:
                        log.debug("collector poll failed: %s", e)
            _wake.wait(POLL_SEC if (co.enabled and co.allow_remote_control) else max(5, co.interval_min) * 60)

    _thread = threading.Thread(target=loop, name="nmb-collector-client", daemon=True)
    _thread.start()

