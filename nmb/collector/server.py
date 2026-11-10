"""nmb-collector: the central collector that measurement boxes send their results to.

An ISP or a specialist runs it on their own server. Boxes whose owner turned on
``[collector]`` send their speed tests and hourly ping summaries to ``/api/ingest``
with an ingest token. The web pages, behind the admin password, find boxes by their
unique ID, name, case number, customer number or ISP, and export their results.

Standard library only. Data lives in one SQLite file under the data directory, next
to ``collector.json`` (tokens and the admin password, both stored as hashes).
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import html
import io
import json
import logging
import os
import secrets
import sqlite3
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

log = logging.getLogger("nmb.collector.server")

MAX_BODY = 8 * 1024 * 1024
DIAG_KEEP = 72  # diagnostics reports kept per box (three days at one an hour)
SPEED_COLS = (
    "src_id", "ts", "trigger", "status", "engine", "server_id", "server_name", "server_host",
    "server_location", "down_bps", "up_bps", "ping_us", "jitter_us", "loss_pct",
    "down_loaded_lat_ms", "up_loaded_lat_ms", "bufferbloat_grade", "connection_type",
    "client_ip", "client_ipv6", "result_url", "error", "bound_iface",
    "cycle_ts", "duration_ms", "nmb_version", "box_mode", "client_ip_source",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS box (
    box_uid TEXT PRIMARY KEY, box_name TEXT, case_id TEXT, isp_name TEXT, account_id TEXT,
    contract_down_mbps REAL, contract_up_mbps REAL, connection_type TEXT, app_version TEXT,
    token_name TEXT, source_ip TEXT, first_seen INTEGER, last_seen INTEGER, diagnostics_shared INTEGER DEFAULT 0,
    remote_allowed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS box_case (
    box_uid TEXT NOT NULL, case_id TEXT NOT NULL, first_seen INTEGER, last_seen INTEGER,
    PRIMARY KEY (box_uid, case_id)
);
CREATE TABLE IF NOT EXISTS speedtest (
    box_uid TEXT NOT NULL, src_id INTEGER NOT NULL, ts INTEGER, trigger TEXT, status TEXT, engine TEXT,
    server_id INTEGER, server_name TEXT, server_host TEXT, server_location TEXT,
    down_bps INTEGER, up_bps INTEGER, ping_us INTEGER, jitter_us INTEGER, loss_pct REAL,
    down_loaded_lat_ms REAL, up_loaded_lat_ms REAL, bufferbloat_grade TEXT, connection_type TEXT,
    client_ip TEXT, client_ipv6 TEXT, result_url TEXT, error TEXT, bound_iface TEXT,
    cycle_ts INTEGER, duration_ms INTEGER, nmb_version TEXT, box_mode TEXT, client_ip_source TEXT,
    PRIMARY KEY (box_uid, src_id)
);
CREATE INDEX IF NOT EXISTS ix_speed_ts ON speedtest(box_uid, ts);
CREATE TABLE IF NOT EXISTS event (
    box_uid TEXT NOT NULL, src_id INTEGER NOT NULL, ts INTEGER, severity TEXT, source TEXT, kind TEXT, detail TEXT,
    PRIMARY KEY (box_uid, src_id)
);
CREATE INDEX IF NOT EXISTS ix_event_ts ON event(box_uid, ts);
CREATE TABLE IF NOT EXISTS command (
    id INTEGER PRIMARY KEY, box_uid TEXT NOT NULL, created INTEGER, kind TEXT, args TEXT,
    state TEXT DEFAULT 'queued', sent INTEGER, done INTEGER, ok INTEGER, result TEXT
);
CREATE INDEX IF NOT EXISTS ix_command_box ON command(box_uid, state);
CREATE TABLE IF NOT EXISTS diagnostics (
    box_uid TEXT NOT NULL, ts INTEGER NOT NULL, markdown TEXT, PRIMARY KEY (box_uid, ts)
);
CREATE TABLE IF NOT EXISTS ping_hour (
    box_uid TEXT NOT NULL, hour INTEGER NOT NULL, target TEXT NOT NULL, label TEXT,
    sent INTEGER, lost INTEGER, rtt_min_us INTEGER, rtt_avg_us INTEGER, rtt_max_us INTEGER, jitter_us INTEGER,
    PRIMARY KEY (box_uid, hour, target)
);
"""


# ------------------------------------------------------------------------------
# Settings: tokens and admin password, stored as hashes
# ------------------------------------------------------------------------------

def _hash_secret(secret: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 200_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def _check_secret(secret: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_secret(secret, salt), stored)


def _token_digest(token: str) -> str:
    # Tokens are long random values, so a plain hash is enough and keeps every upload cheap.
    return hashlib.sha256(token.encode()).hexdigest()


class Settings:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "collector.json"
        self.lock = threading.Lock()
        self.data: Dict[str, Any] = {"admin_password": "", "tokens": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def set_password(self, password: str) -> None:
        self.data["admin_password"] = _hash_secret(password)
        self.save()

    def check_password(self, password: str) -> bool:
        stored = self.data.get("admin_password", "")
        return bool(stored) and _check_secret(password, stored)

    def add_token(self, name: str) -> str:
        token = "nmbc_" + secrets.token_urlsafe(24)
        with self.lock:
            self.data["tokens"][name] = {"digest": _token_digest(token), "created": int(time.time())}
            self.save()
        return token

    def revoke_token(self, name: str) -> bool:
        with self.lock:
            found = self.data["tokens"].pop(name, None) is not None
            if found:
                self.save()
        return found

    def token_name(self, token: str) -> Optional[str]:
        digest = _token_digest(token)
        for name, info in self.data.get("tokens", {}).items():
            if hmac.compare_digest(info.get("digest", ""), digest):
                return name
        return None


# ------------------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------------------

def connect(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "collector.db", timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(box)")}
    if "diagnostics_shared" not in cols:
        conn.execute("ALTER TABLE box ADD COLUMN diagnostics_shared INTEGER DEFAULT 0")
    if "remote_allowed" not in cols:
        conn.execute("ALTER TABLE box ADD COLUMN remote_allowed INTEGER DEFAULT 0")
    speed_cols = {r[1] for r in conn.execute("PRAGMA table_info(speedtest)")}
    for col, typ in (("cycle_ts", "INTEGER"), ("duration_ms", "INTEGER"), ("nmb_version", "TEXT"),
                     ("box_mode", "TEXT"), ("client_ip_source", "TEXT")):
        if col not in speed_cols:
            conn.execute(f"ALTER TABLE speedtest ADD COLUMN {col} {typ}")
    return conn


def _text(v: Any, limit: int = 256) -> Optional[str]:
    if v is None:
        return None
    return str(v)[:limit]


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


CORRECTABLE = tuple(c for c in SPEED_COLS if c not in ("src_id", "ts"))
_INT_COLS = ("ts", "server_id", "down_bps", "up_bps", "ping_us", "jitter_us", "cycle_ts", "duration_ms")
_NUM_COLS = ("loss_pct", "down_loaded_lat_ms", "up_loaded_lat_ms")


def _speed_value(col: str, v: Any) -> Any:
    if col in _INT_COLS:
        return _int(v)
    if col in _NUM_COLS:
        return _num(v)
    return _text(v, 512)


def check_owner(conn: sqlite3.Connection, uid: str, token_name: Optional[str], active_tokens: Optional[set]) -> None:
    """A box belongs to the token it first uploaded with: another token that is still valid may not write
    into it, take its commands or report results for it (PermissionError -> 403)."""
    owner = conn.execute("SELECT token_name FROM box WHERE box_uid = ?", (uid,)).fetchone()
    if owner and owner[0] and token_name is not None and owner[0] != token_name \
            and (active_tokens is None or owner[0] in active_tokens):
        raise PermissionError("this box uploads with another token")


def ingest(conn: sqlite3.Connection, payload: Dict[str, Any], token_name: str, source_ip: str,
           active_tokens: Optional[set] = None) -> Dict[str, int]:
    """Store one upload; repeated uploads of the same rows are ignored.

    A box belongs to the token it first uploaded with: another token cannot write into it while that
    token is still valid (it could before: any token could write into any box, audit H3). Only then
    are the box's own corrections of rows it sent earlier applied ("corrections": values that NMB had
    filled in instead of measuring, cleared on the box on 2026-11-10)."""
    uid = str(payload.get("box_uid", ""))
    if not uid.startswith("nmb-") or not 10 <= len(uid) <= 40 or not all(c.isalnum() or c == "-" for c in uid):
        raise ValueError("invalid box_uid")
    check_owner(conn, uid, token_name, active_tokens)
    now = int(time.time() * 1000)
    isp = payload.get("isp") if isinstance(payload.get("isp"), dict) else {}
    case_id = _text(payload.get("case_id"), 80) or ""
    speed = payload.get("speedtests") if isinstance(payload.get("speedtests"), list) else []
    ping = payload.get("ping_hours") if isinstance(payload.get("ping_hours"), list) else []
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    diag = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else None
    shared = 1 if payload.get("share_diagnostics") else 0
    corrections = payload.get("corrections") if isinstance(payload.get("corrections"), list) else []
    if len(speed) > 2000 or len(ping) > 5000 or len(events) > 2000 or len(corrections) > 20000:
        raise ValueError("too many rows in one upload")
    added_speed = added_ping = added_events = corrected = 0
    with conn:
        conn.execute(
            """INSERT INTO box (box_uid, box_name, case_id, isp_name, account_id, contract_down_mbps,
                                contract_up_mbps, connection_type, app_version, token_name, source_ip, first_seen, last_seen,
                                diagnostics_shared, remote_allowed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(box_uid) DO UPDATE SET box_name=excluded.box_name, case_id=excluded.case_id,
                 isp_name=excluded.isp_name, account_id=excluded.account_id,
                 contract_down_mbps=excluded.contract_down_mbps, contract_up_mbps=excluded.contract_up_mbps,
                 connection_type=excluded.connection_type, app_version=excluded.app_version,
                 token_name=excluded.token_name, source_ip=excluded.source_ip, last_seen=excluded.last_seen,
                 diagnostics_shared=excluded.diagnostics_shared, remote_allowed=excluded.remote_allowed""",
            (uid, _text(payload.get("box_name"), 80), case_id, _text(isp.get("name"), 120), _text(isp.get("account_id"), 80),
             _num(isp.get("contract_down_mbps")), _num(isp.get("contract_up_mbps")), _text(isp.get("connection_type"), 40),
             _text(payload.get("app_version"), 40), token_name, source_ip, now, now, shared,
             1 if payload.get("allow_remote_control") else 0),
        )
        if case_id:
            conn.execute(
                """INSERT INTO box_case (box_uid, case_id, first_seen, last_seen) VALUES (?,?,?,?)
                   ON CONFLICT(box_uid, case_id) DO UPDATE SET last_seen=excluded.last_seen""",
                (uid, case_id, now, now),
            )
        for row in speed:
            if not isinstance(row, dict) or _int(row.get("id")) is None:
                continue
            vals = [uid, _int(row.get("id"))]
            for col in SPEED_COLS[1:]:
                vals.append(_speed_value(col, row.get(col)))
            cur = conn.execute(
                f"INSERT OR IGNORE INTO speedtest (box_uid, {', '.join(SPEED_COLS)}) VALUES ({', '.join('?' * (len(SPEED_COLS) + 1))})",
                vals,
            )
            added_speed += cur.rowcount
        for row in ping:
            if not isinstance(row, dict) or _int(row.get("hour")) is None or not row.get("target"):
                continue
            cur = conn.execute(
                """INSERT OR REPLACE INTO ping_hour (box_uid, hour, target, label, sent, lost, rtt_min_us,
                                                     rtt_avg_us, rtt_max_us, jitter_us) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (uid, _int(row["hour"]), _text(row["target"], 120), _text(row.get("label"), 120), _int(row.get("sent")),
                 _int(row.get("lost")), _int(row.get("rtt_min_us")), _int(row.get("rtt_avg_us")),
                 _int(row.get("rtt_max_us")), _int(row.get("jitter_us"))),
            )
            added_ping += cur.rowcount
        for row in events:
            if not isinstance(row, dict) or _int(row.get("id")) is None:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO event (box_uid, src_id, ts, severity, source, kind, detail) VALUES (?,?,?,?,?,?,?)",
                (uid, _int(row["id"]), _int(row.get("ts")), _text(row.get("severity"), 10), _text(row.get("source"), 40),
                 _text(row.get("kind"), 80), _text(row.get("detail"), 2000)),
            )
            added_events += cur.rowcount
        for fix in corrections:
            if not isinstance(fix, dict) or fix.get("field") not in CORRECTABLE or _int(fix.get("id")) is None:
                continue
            col = fix["field"]
            cur = conn.execute(f"UPDATE speedtest SET {col} = ? WHERE box_uid = ? AND src_id = ?",
                               (_speed_value(col, fix.get("value")), uid, _int(fix["id"])))
            corrected += cur.rowcount
        if diag and isinstance(diag.get("markdown"), str) and _int(diag.get("ts")) is not None:
            conn.execute("INSERT OR REPLACE INTO diagnostics (box_uid, ts, markdown) VALUES (?,?,?)",
                         (uid, _int(diag["ts"]), diag["markdown"][:2_000_000]))
            conn.execute(
                """DELETE FROM diagnostics WHERE box_uid = ? AND ts NOT IN
                   (SELECT ts FROM diagnostics WHERE box_uid = ? ORDER BY ts DESC LIMIT ?)""", (uid, uid, DIAG_KEEP))
    return {"speedtests": added_speed, "ping_hours": added_ping, "events": added_events,
            "diagnostics": 1 if diag else 0, "corrected": corrected}


# Remote control: the box asks for work (no connection into the box), and runs only these.
COMMANDS = {
    "speedtest": "Run a speed test",
    "diagnostics": "Send fresh network diagnostics",
    "upload": "Upload now",
}
ENGINES = ("ookla", "rtr", "cloudflare", "fastcom", "all")


def queue_command(conn: sqlite3.Connection, uid: str, kind: str, args: Dict[str, Any]) -> int:
    if kind not in COMMANDS:
        raise ValueError("unknown command")
    clean: Dict[str, Any] = {}
    if kind == "speedtest":
        engine = str(args.get("engine", "rtr"))
        if engine not in ENGINES:
            raise ValueError("unknown engine")
        clean["engine"] = engine
        sid = str(args.get("server_id", "")).strip()
        if sid:
            if not sid.isdigit() or len(sid) > 7:
                raise ValueError("invalid server ID")
            clean["server_id"] = int(sid)
    with conn:
        cur = conn.execute("INSERT INTO command (box_uid, created, kind, args) VALUES (?,?,?,?)",
                           (uid, int(time.time() * 1000), kind, json.dumps(clean)))
    return int(cur.lastrowid)


def poll(conn: sqlite3.Connection, payload: Dict[str, Any], token_name: Optional[str] = None,
         active_tokens: Optional[set] = None) -> List[Dict[str, Any]]:
    """Store the box's command results and hand it the queued commands (only to the box's own token)."""
    uid = str(payload.get("box_uid", ""))
    check_owner(conn, uid, token_name, active_tokens)
    allowed = 1 if payload.get("allow_remote_control") else 0
    now = int(time.time() * 1000)
    with conn:
        conn.execute("UPDATE box SET remote_allowed = ?, last_seen = ? WHERE box_uid = ?", (allowed, now, uid))
        for r in payload.get("results") or []:
            if isinstance(r, dict) and _int(r.get("id")) is not None:
                conn.execute("UPDATE command SET state='done', done=?, ok=?, result=? WHERE id=? AND box_uid=?",
                             (now, 1 if r.get("ok") else 0, _text(r.get("message"), 2000), _int(r["id"]), uid))
        if not allowed:
            conn.execute("UPDATE command SET state='refused', done=?, result=? WHERE box_uid=? AND state IN ('queued','sent')",
                         (now, "Remote control is off on this box.", uid))
            return []
        rows = conn.execute("SELECT id, kind, args FROM command WHERE box_uid=? AND state='queued' ORDER BY id LIMIT 5", (uid,)).fetchall()
        for r in rows:
            conn.execute("UPDATE command SET state='sent', sent=? WHERE id=?", (now, r["id"]))
    return [{"id": r["id"], "kind": r["kind"], "args": json.loads(r["args"] or "{}")} for r in rows]


def search(conn: sqlite3.Connection, q: str, limit: int = 200) -> List[sqlite3.Row]:
    """Boxes whose ID, name, current or earlier case number, customer number or ISP match."""
    q = q.strip()
    if not q:
        return conn.execute("SELECT * FROM box ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()
    like = f"%{q}%"
    return conn.execute(
        """SELECT * FROM box WHERE box_uid LIKE ? OR box_name LIKE ? OR case_id LIKE ? OR account_id LIKE ?
                  OR isp_name LIKE ? OR box_uid IN (SELECT box_uid FROM box_case WHERE case_id LIKE ?)
           ORDER BY last_seen DESC LIMIT ?""",
        (like, like, like, like, like, like, limit),
    ).fetchall()


def box_summary(conn: sqlite3.Connection, uid: str, days: int = 30) -> Dict[str, Any]:
    since = int((time.time() - days * 86400) * 1000)
    box = conn.execute("SELECT * FROM box WHERE box_uid = ?", (uid,)).fetchone()
    if box is None:
        return {}
    stats = conn.execute(
        """SELECT COUNT(*), AVG(down_bps), AVG(up_bps), AVG(ping_us), MIN(down_bps), MAX(down_bps)
             FROM speedtest WHERE box_uid = ? AND status = 'ok' AND ts >= ? AND COALESCE(client_ip_source, '') != 'local'""",
        (uid, since)).fetchone()
    failed = conn.execute("SELECT COUNT(*) FROM speedtest WHERE box_uid = ? AND status != 'ok' AND ts >= ?", (uid, since)).fetchone()[0]
    below = None
    if box["contract_down_mbps"]:
        below = conn.execute(
            "SELECT COUNT(*) FROM speedtest WHERE box_uid = ? AND status = 'ok' AND ts >= ? AND down_bps < ? "
            "AND COALESCE(client_ip_source, '') != 'local'",
            (uid, since, box["contract_down_mbps"] * 1e6 * 0.8)).fetchone()[0]
    per_engine = conn.execute(
        """SELECT engine, COUNT(*), AVG(down_bps), AVG(up_bps) FROM speedtest
            WHERE box_uid = ? AND status = 'ok' AND ts >= ? AND COALESCE(client_ip_source, '') != 'local'
            GROUP BY engine ORDER BY engine""", (uid, since)).fetchall()
    ping = conn.execute(
        """SELECT target, label, SUM(sent), SUM(lost), AVG(rtt_avg_us), MAX(rtt_max_us) FROM ping_hour
            WHERE box_uid = ? AND hour >= ? GROUP BY target ORDER BY target""", (uid, since)).fetchall()
    cases = conn.execute("SELECT case_id, first_seen, last_seen FROM box_case WHERE box_uid = ? ORDER BY first_seen", (uid,)).fetchall()
    return {"box": dict(box), "days": days, "ok_tests": stats[0], "failed_tests": failed,
            "avg_down_bps": stats[1], "avg_up_bps": stats[2], "avg_ping_us": stats[3],
            "min_down_bps": stats[4], "max_down_bps": stats[5], "below_80pct": below,
            "per_engine": [dict(zip(("engine", "count", "avg_down_bps", "avg_up_bps"), r)) for r in per_engine],
            "ping": [dict(zip(("target", "label", "sent", "lost", "avg_rtt_us", "max_rtt_us"), r)) for r in ping],
            "cases": [dict(r) for r in cases]}


def render_diagnostics(conn: sqlite3.Connection, uid: str, lang: str, ts: Optional[int]) -> Optional[str]:
    t = TEXT[lang]
    e = html.escape
    all_ts = [r[0] for r in conn.execute("SELECT ts FROM diagnostics WHERE box_uid = ? ORDER BY ts DESC", (uid,))]
    if not all_ts:
        return None
    pick = ts if ts in all_ts else all_ts[0]
    md = conn.execute("SELECT markdown FROM diagnostics WHERE box_uid = ? AND ts = ?", (uid, pick)).fetchone()[0] or ""
    older = " · ".join(
        f'<a href="/box/{quote(uid)}/diagnostics?ts={x}&lang={lang}">{_when(x)}</a>' if x != pick else f"<b>{_when(x)}</b>"
        for x in all_ts[:24])
    body = (f'<p><a href="/box/{quote(uid)}?lang={lang}">← {t["box"]} {e(uid)}</a></p>'
            f'<h1>{t["diag"]} · {_when(pick)}</h1><p class="muted">{older}</p><pre>{e(md)}</pre>')
    return _page(lang, f'{t["diag"]} {uid}', body)


def speed_csv(conn: sqlite3.Connection, uid: str) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(("box_uid",) + SPEED_COLS)
    for r in conn.execute(f"SELECT box_uid, {', '.join(SPEED_COLS)} FROM speedtest WHERE box_uid = ? ORDER BY ts", (uid,)):
        w.writerow(tuple(r))
    return out.getvalue()


# ------------------------------------------------------------------------------
# Web pages
# ------------------------------------------------------------------------------

TEXT = {
    "en": {"title": "Measurement collector", "search": "Search", "placeholder": "Box ID, name, case number, customer number or ISP",
           "box": "Box", "name": "Name", "case": "Case", "isp": "ISP", "customer": "Customer no.", "last_seen": "Last upload",
           "version": "Version", "none": "No box found.", "back": "All boxes", "days": "Last {days} days",
           "ok_tests": "Speed tests", "failed": "Without result", "avg_down": "Average download", "avg_up": "Average upload",
           "avg_ping": "Average ping", "contract": "Subscribed", "below": "Below 80% of the subscribed download",
           "engines": "By engine", "ping": "Ping per target", "loss": "Loss", "cases": "Case numbers",
           "recent": "Latest speed tests", "csv": "Download all speed tests (CSV)", "time": "Time", "engine": "Engine",
           "down": "Download", "up": "Upload", "server": "Server", "status": "Status",
           "events": "Events (outages, link changes, warnings)", "diag": "Network diagnostics",
           "diag_off": "The owner of this box has not shared the network diagnostics.", "diag_none": "No diagnostics received yet.",
           "diag_from": "Report from", "diag_older": "Earlier reports", "severity": "Level", "kind": "Event", "detail": "Detail",
           "remote": "Remote control", "remote_off": "The owner of this box has not allowed remote control.",
           "remote_hint": "The box picks up commands within about a minute.", "send": "Send",
           "cmd_speedtest": "Run a speed test", "cmd_diagnostics": "Send fresh network diagnostics", "cmd_upload": "Upload now",
           "engine_any": "Engine", "server_id": "Ookla server ID (optional)", "commands": "Commands", "result": "Result"},
    "hu": {"title": "Mérésgyűjtő", "search": "Keresés", "placeholder": "Doboz-ID, név, ügyszám, ügyfélszám vagy szolgáltató",
           "box": "Doboz", "name": "Név", "case": "Ügyszám", "isp": "Szolgáltató", "customer": "Ügyfélszám", "last_seen": "Utolsó küldés",
           "version": "Verzió", "none": "Nincs találat.", "back": "Minden doboz", "days": "Utolsó {days} nap",
           "ok_tests": "Sebességmérés", "failed": "Eredmény nélkül", "avg_down": "Átlagos letöltés", "avg_up": "Átlagos feltöltés",
           "avg_ping": "Átlagos ping", "contract": "Előfizetett", "below": "Az előfizetett letöltés 80%-a alatt",
           "engines": "Motoronként", "ping": "Ping célonként", "loss": "Csomagvesztés", "cases": "Ügyszámok",
           "recent": "Legutóbbi sebességmérések", "csv": "Az összes sebességmérés letöltése (CSV)", "time": "Idő", "engine": "Motor",
           "down": "Letöltés", "up": "Feltöltés", "server": "Szerver", "status": "Állapot",
           "events": "Események (kimaradások, link-változások, figyelmeztetések)", "diag": "Hálózati diagnosztika",
           "diag_off": "A doboz gazdája nem osztotta meg a hálózati diagnosztikát.", "diag_none": "Még nem érkezett diagnosztika.",
           "diag_from": "Jelentés ideje", "diag_older": "Korábbi jelentések", "severity": "Szint", "kind": "Esemény", "detail": "Részletek",
           "remote": "Távoli irányítás", "remote_off": "A doboz gazdája nem engedélyezte a távoli irányítást.",
           "remote_hint": "A doboz körülbelül egy percen belül átveszi a parancsot.", "send": "Küldés",
           "cmd_speedtest": "Sebességmérés indítása", "cmd_diagnostics": "Friss hálózati diagnosztika küldése", "cmd_upload": "Azonnali feltöltés",
           "engine_any": "Motor", "server_id": "Ookla szerver-ID (nem kötelező)", "commands": "Parancsok", "result": "Eredmény"},
}

CSS = """body{font-family:system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
main{max-width:1100px;margin:0 auto;padding:16px}a{color:#38bdf8}h1{font-size:1.3rem}h2{font-size:1.05rem;margin-top:24px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #1e293b;padding:6px 8px;text-align:left}
th{color:#94a3b8;font-weight:600}.wrap{overflow-x:auto}form{display:flex;gap:8px;flex-wrap:wrap}
input{flex:1;min-width:220px;padding:8px;border-radius:6px;border:1px solid #334155;background:#020617;color:#e2e8f0}
select{padding:8px;border-radius:6px;border:1px solid #334155;background:#020617;color:#e2e8f0}
button{padding:8px 14px;border-radius:6px;border:0;background:#0284c7;color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.card{background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px}
pre{white-space:pre-wrap;word-break:break-word;background:#020617;border:1px solid #1e293b;border-radius:8px;padding:12px;font-size:12px;max-height:70vh;overflow:auto}.card b{display:block;font-size:1.2rem;margin-top:4px}.muted{color:#94a3b8}"""


def _ms(us) -> str:
    """Microseconds as milliseconds, or "--" when not measured (never 0.0 ms)."""
    return f"{us / 1000:.1f} ms" if us is not None else "--"


def _pct(lost, sent) -> str:
    return f"{100.0 * (lost or 0) / sent:.2f}%" if sent else "--"


def _mbps(bps: Any) -> str:
    return f"{bps / 1e6:.1f} Mbps" if bps else "--"


def _when(ms: Any) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000)) if ms else "--"


def _page(lang: str, title: str, body: str) -> str:
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>'
            f"<style>{CSS}</style></head><body><main>{body}</main></body></html>")


def render_search(conn: sqlite3.Connection, q: str, lang: str) -> str:
    t = TEXT[lang]
    e = html.escape
    rows = search(conn, q)
    lines = "".join(
        f'<tr><td><a href="/box/{quote(r["box_uid"])}?lang={lang}"><code>{e(r["box_uid"])}</code></a></td><td>{e(r["box_name"] or "")}</td>'
        f'<td>{e(r["case_id"] or "")}</td><td>{e(r["account_id"] or "")}</td><td>{e(r["isp_name"] or "")}</td>'
        f'<td>{_when(r["last_seen"])}</td><td>{e(r["app_version"] or "")}</td></tr>'
        for r in rows)
    table = (f'<div class="wrap"><table><tr><th>{t["box"]}</th><th>{t["name"]}</th><th>{t["case"]}</th><th>{t["customer"]}</th>'
             f'<th>{t["isp"]}</th><th>{t["last_seen"]}</th><th>{t["version"]}</th></tr>{lines}</table></div>') if rows else f'<p class="muted">{t["none"]}</p>'
    body = (f'<h1>{t["title"]}</h1><form method="get" action="/"><input type="hidden" name="lang" value="{lang}">'
            f'<input name="q" value="{e(q)}" placeholder="{e(t["placeholder"])}" aria-label="{e(t["search"])}"><button>{t["search"]}</button></form>'
            f"<h2>{len(rows)}</h2>{table}")
    return _page(lang, t["title"], body)


def render_box(conn: sqlite3.Connection, uid: str, lang: str) -> Optional[str]:
    t = TEXT[lang]
    e = html.escape
    s = box_summary(conn, uid)
    if not s:
        return None
    b = s["box"]
    contract = f'{b["contract_down_mbps"] or "--"} / {b["contract_up_mbps"] or "--"} Mbps'
    cards = [(t["ok_tests"], s["ok_tests"]), (t["failed"], s["failed_tests"]), (t["avg_down"], _mbps(s["avg_down_bps"])),
             (t["avg_up"], _mbps(s["avg_up_bps"])), (t["avg_ping"], f'{s["avg_ping_us"] / 1000:.1f} ms' if s["avg_ping_us"] else "--"),
             (t["contract"], contract)]
    if s["below_80pct"] is not None:
        cards.append((t["below"], f'{s["below_80pct"]} / {s["ok_tests"]}'))
    grid = "".join(f'<div class="card"><span class="muted">{e(k)}</span><b>{e(str(v))}</b></div>' for k, v in cards)
    eng = "".join(f'<tr><td>{e(r["engine"] or "")}</td><td>{r["count"]}</td><td>{_mbps(r["avg_down_bps"])}</td><td>{_mbps(r["avg_up_bps"])}</td></tr>' for r in s["per_engine"])
    ping = "".join(
        f'<tr><td>{e(r["label"] or "")} <span class="muted">{e(r["target"])}</span></td>'
        f'<td>{_ms(r["avg_rtt_us"])}</td><td>{_pct(r["lost"], r["sent"])}</td></tr>'
        for r in s["ping"])
    cases = ", ".join(e(c["case_id"]) for c in s["cases"]) or "--"
    recent = conn.execute(
        "SELECT ts, engine, status, down_bps, up_bps, ping_us, server_name, error FROM speedtest WHERE box_uid = ? ORDER BY ts DESC LIMIT 50",
        (uid,)).fetchall()
    rec = "".join(
        f'<tr><td>{_when(r["ts"])}</td><td>{e(r["engine"] or "")}</td><td>{e(r["status"] or "")}</td><td>{_mbps(r["down_bps"])}</td>'
        f'<td>{_mbps(r["up_bps"])}</td><td>{_ms(r["ping_us"])}</td><td>{e(r["server_name"] or r["error"] or "")}</td></tr>'
        for r in recent)
    events = conn.execute(
        "SELECT ts, severity, source, kind, detail FROM event WHERE box_uid = ? ORDER BY ts DESC LIMIT 100", (uid,)).fetchall()
    ev = "".join(
        f'<tr><td>{_when(r["ts"])}</td><td>{e(r["severity"] or "")}</td><td>{e((r["source"] or "") + " / " + (r["kind"] or ""))}</td>'
        f'<td>{e(r["detail"] or "")}</td></tr>' for r in events)
    diag_ts = [r[0] for r in conn.execute("SELECT ts FROM diagnostics WHERE box_uid = ? ORDER BY ts DESC", (uid,))]
    if diag_ts:
        diag_html = (f'<p><a href="/box/{quote(uid)}/diagnostics?lang={lang}">{t["diag_from"]} {_when(diag_ts[0])}</a> · '
                     f'{t["diag_older"]}: {len(diag_ts) - 1}</p>')
    else:
        diag_html = f'<p class="muted">{t["diag_none"] if b["diagnostics_shared"] else t["diag_off"]}</p>'
    cmds = conn.execute("SELECT * FROM command WHERE box_uid = ? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
    cmd_rows = "".join(
        f'<tr><td>{_when(c["created"])}</td><td>{e(t.get("cmd_" + (c["kind"] or ""), c["kind"] or ""))} <span class="muted">{e(c["args"] or "")}</span></td>'
        f'<td>{e(c["state"] or "")}</td><td>{e(c["result"] or "")}</td></tr>' for c in cmds)
    if b["remote_allowed"]:
        act = f"/box/{quote(uid)}/command?lang={lang}"
        engines = "".join(f'<option value="{x}">{x}</option>' for x in ENGINES)
        remote_html = (
            f'<p class="muted">{t["remote_hint"]}</p>'
            f'<form method="post" action="{act}"><input type="hidden" name="kind" value="speedtest">'
            f'<select name="engine" aria-label="{t["engine_any"]}">{engines}</select>'
            f'<input name="server_id" placeholder="{e(t["server_id"])}" inputmode="numeric" style="max-width:220px">'
            f'<button>{t["cmd_speedtest"]}</button></form>'
            f'<form method="post" action="{act}" style="margin-top:8px"><input type="hidden" name="kind" value="diagnostics"><button>{t["cmd_diagnostics"]}</button></form>'
            f'<form method="post" action="{act}" style="margin-top:8px"><input type="hidden" name="kind" value="upload"><button>{t["cmd_upload"]}</button></form>')
    else:
        remote_html = f'<p class="muted">{t["remote_off"]}</p>'
    if cmd_rows:
        remote_html += (f'<h3>{t["commands"]}</h3><div class="wrap"><table><tr><th>{t["time"]}</th><th></th><th>{t["status"]}</th>'
                        f'<th>{t["result"]}</th></tr>{cmd_rows}</table></div>')
    body = (f'<p><a href="/?lang={lang}">← {t["back"]}</a></p><h1>{t["box"]} <code>{e(uid)}</code> · {e(b["box_name"] or "")}</h1>'
            f'<p class="muted">{t["isp"]}: {e(b["isp_name"] or "--")} · {t["customer"]}: {e(b["account_id"] or "--")} · '
            f'{t["case"]}: {e(b["case_id"] or "--")} · {t["last_seen"]}: {_when(b["last_seen"])} · {t["version"]}: {e(b["app_version"] or "")}</p>'
            f'<h2>{t["days"].format(days=s["days"])}</h2><div class="grid">{grid}</div>'
            f'<h2>{t["engines"]}</h2><div class="wrap"><table><tr><th>{t["engine"]}</th><th>#</th><th>{t["down"]}</th><th>{t["up"]}</th></tr>{eng}</table></div>'
            f'<h2>{t["ping"]}</h2><div class="wrap"><table><tr><th></th><th>{t["avg_ping"]}</th><th>{t["loss"]}</th></tr>{ping}</table></div>'
            f'<h2>{t["cases"]}</h2><p>{cases}</p>'
            f'<h2>{t["remote"]}</h2>{remote_html}'
            f'<h2>{t["diag"]}</h2>{diag_html}'
            + (f'<h2>{t["events"]}</h2><div class="wrap"><table><tr><th>{t["time"]}</th><th>{t["severity"]}</th><th>{t["kind"]}</th>'
               f'<th>{t["detail"]}</th></tr>{ev}</table></div>' if ev else "")
            + f'<h2>{t["recent"]}</h2><p><a href="/box/{quote(uid)}/speedtests.csv">{t["csv"]}</a></p>'
            f'<div class="wrap"><table><tr><th>{t["time"]}</th><th>{t["engine"]}</th><th>{t["status"]}</th><th>{t["down"]}</th>'
            f'<th>{t["up"]}</th><th>Ping</th><th>{t["server"]}</th></tr>{rec}</table></div>')
    return _page(lang, f'{t["box"]} {uid}', body)


# ------------------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "nmb-collector"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s %s", self.client_address[0], fmt % args)

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: Dict[str, Any]) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _admin_ok(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            if user == "admin" and self.server.settings.check_password(pw):  # type: ignore[attr-defined]
                return True
        self._send(401, b"Login required", "text/plain", {"WWW-Authenticate": 'Basic realm="nmb-collector"'})
        return False

    def _same_origin(self) -> bool:
        """Admin forms must come from these pages (Basic auth alone would allow cross-site posts)."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        return bool(host) and urlparse(origin).netloc == host

    def _admin_post(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        if not (len(parts) == 3 and parts[0] == "box" and parts[2] == "command"):
            self._send(404, b"Not found", "text/plain")
            return
        if not self._admin_ok():
            return
        if not self._same_origin():
            self._send(403, b"Cross-site request refused", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(min(length, 4096)).decode("utf-8", "replace")).items()}
        uid = parts[1]
        lang = parse_qs(urlparse(self.path).query).get("lang", ["en"])[0]
        try:
            with self.server.db_lock:  # type: ignore[attr-defined]
                box = self.server.conn.execute("SELECT remote_allowed FROM box WHERE box_uid = ?", (uid,)).fetchone()  # type: ignore[attr-defined]
                if not box or not box[0]:
                    raise ValueError("remote control is off on this box")
                queue_command(self.server.conn, uid, form.get("kind", ""), form)  # type: ignore[attr-defined]
        except ValueError as e:
            self._send(400, str(e).encode(), "text/plain")
            return
        self._send(303, b"", "text/plain", {"Location": f"/box/{quote(uid)}?lang={quote(lang)}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/ingest", "/api/poll"):
            self._admin_post(path)
            return
        auth = self.headers.get("Authorization", "")
        name = self.server.settings.token_name(auth[7:]) if auth.startswith("Bearer ") else None  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        if not name:
            # Read the upload first: answering before it is read resets the connection, and the box then
            # reports "Broken pipe" instead of the refused token (seen box -> collector, 2026-11-08).
            if 0 < length <= MAX_BODY:
                self.rfile.read(length)
            self._json(401, {"ok": False, "error": "invalid token"})
            return
        if not 0 < length <= MAX_BODY:
            self._json(413, {"ok": False, "error": "body too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
            with self.server.db_lock:  # type: ignore[attr-defined]
                active = set((self.server.settings.data.get("tokens") or {}).keys())  # type: ignore[attr-defined]
                if path == "/api/poll":
                    self._json(200, {"ok": True, "commands": poll(self.server.conn, payload, name, active)})  # type: ignore[attr-defined]
                    return
                added = ingest(self.server.conn, payload, name, self.client_address[0], active_tokens=active)  # type: ignore[attr-defined]
        except PermissionError as e:
            self._json(403, {"ok": False, "error": str(e)})
            return
        except (ValueError, json.JSONDecodeError) as e:
            self._json(400, {"ok": False, "error": str(e)})
            return
        self._json(200, {"ok": True, "added": added})

    def do_GET(self) -> None:
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        lang = qs.get("lang", [""])[0]
        if lang not in TEXT:
            lang = "hu" if self.headers.get("Accept-Language", "").lower().startswith("hu") else "en"
        if url.path == "/health":
            self._json(200, {"ok": True})
            return
        if not self._admin_ok():
            return
        conn = self.server.conn  # type: ignore[attr-defined]
        parts = [p for p in url.path.split("/") if p]
        with self.server.db_lock:  # type: ignore[attr-defined]
            if url.path == "/":
                self._send(200, render_search(conn, qs.get("q", [""])[0], lang).encode(), "text/html; charset=utf-8")
            elif url.path == "/api/boxes":
                self._json(200, {"boxes": [dict(r) for r in search(conn, qs.get("q", [""])[0])]})
            elif len(parts) == 3 and parts[0] == "api" and parts[1] == "box":
                s = box_summary(conn, parts[2])
                self._json(200 if s else 404, s or {"error": "not found"})
            elif len(parts) == 2 and parts[0] == "box":
                page = render_box(conn, parts[1], lang)
                if page is None:
                    self._send(404, b"Not found", "text/plain")
                else:
                    self._send(200, page.encode(), "text/html; charset=utf-8")
            elif len(parts) == 3 and parts[0] == "box" and parts[2] == "diagnostics":
                try:
                    ts = int(qs.get("ts", [""])[0])
                except ValueError:
                    ts = None
                page = render_diagnostics(conn, parts[1], lang, ts)
                if page is None:
                    self._send(404, b"Not found", "text/plain")
                else:
                    self._send(200, page.encode(), "text/html; charset=utf-8")
            elif len(parts) == 3 and parts[0] == "box" and parts[2] == "speedtests.csv":
                self._send(200, speed_csv(conn, parts[1]).encode(), "text/csv; charset=utf-8",
                           {"Content-Disposition": f'attachment; filename="{parts[1]}-speedtests.csv"'})
            else:
                self._send(404, b"Not found", "text/plain")


def make_server(data_dir: Path, host: str, port: int, cert: str = "", key: str = "") -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.settings = Settings(data_dir)  # type: ignore[attr-defined]
    httpd.conn = connect(data_dir)  # type: ignore[attr-defined]
    httpd.db_lock = threading.Lock()  # type: ignore[attr-defined]
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key or None)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="nmb-collector", description="Central collector for NetworkMeasureBox measurements.")
    p.add_argument("--data", default=os.environ.get("NMB_COLLECTOR_DATA", "/var/lib/nmb-collector"), help="Data directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="Run the collector")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8600)
    sv.add_argument("--cert", default="", help="TLS certificate (PEM); without it, run behind an HTTPS proxy")
    sv.add_argument("--key", default="", help="TLS private key (PEM)")
    pw = sub.add_parser("set-password", help="Set the admin password of the web pages (user: admin)")
    pw.add_argument("--password", help="Read from stdin when omitted")
    ta = sub.add_parser("token-add", help="Create an ingest token for boxes (printed once)")
    ta.add_argument("name", help="Who the token is for, e.g. support-team")
    sub.add_parser("token-list", help="List ingest tokens")
    tr = sub.add_parser("token-revoke", help="Revoke an ingest token")
    tr.add_argument("name")
    args = p.parse_args(argv)

    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = Settings(data)
    if args.cmd == "set-password":
        password = args.password or sys.stdin.readline().rstrip("\n")
        if len(password) < 10:
            print("Use at least 10 characters.", file=sys.stderr)
            return 1
        settings.set_password(password)
        print("Admin password set. Log in as: admin")
        return 0
    if args.cmd == "token-add":
        print(settings.add_token(args.name))
        print("Give this token to the box owner: Web UI > System > Central collector. It is not shown again.", file=sys.stderr)
        return 0
    if args.cmd == "token-list":
        for name, info in settings.data.get("tokens", {}).items():
            print(f"{name}\tcreated {time.strftime('%Y-%m-%d', time.localtime(info.get('created', 0)))}")
        return 0
    if args.cmd == "token-revoke":
        ok = settings.revoke_token(args.name)
        print("Revoked." if ok else "No such token.")
        return 0 if ok else 1
    if not settings.data.get("admin_password"):
        print("Set the admin password first: nmb-collector set-password", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    httpd = make_server(data, args.host, args.port, args.cert, args.key)
    scheme = "https" if args.cert else "http"
    log.info("nmb-collector listening on %s://%s:%d (data: %s)", scheme, args.host, args.port, data)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
