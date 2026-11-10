"""Data caps for automatic speed tests: per link (Ethernet/PPPoE, Wi-Fi, USB, link aggregation) and per
connection type (fiber, cable, DSL, mobile, satellite ...), counted from the data the tests themselves use.

On a 1000/300 line the owner's schedule (every engine every 2-5 minutes) moved about 800 GB in 4 hours
(2026-11-09 night, real PPPoE line). A cap stops the *automatic* tests on that link once the data used by
tests in the current period reaches it; manual, Web UI and Telegram tests still run (and still count).

Settings (`[data_cap]`):
  period      day or month
  reset_day   for month: the day of the month the count starts again (1-28)
  wired_mb    Ethernet or PPPoE (also a bridge on the WAN port), 0 = no cap
  wifi_mb     Wi-Fi
  usb_mb      USB tethering (phone, hotspot, modem); [usb_uplink] daily_limit_mb stays a separate daily cap
  lag_mb      link aggregation (bond)
  by_type     JSON {"fwa": 20000, "satellite": 5000}: a cap per connection type ([isp] connection_type; a
              USB link counts as fwa, mobile); for each test the stricter of the link cap and the type cap holds

Usage is the bytes the measured interface moved while a test cycle ran (so traffic of other devices in
that time counts too: an upper bound). It is kept per link and per type in the kv table of the live
database, with the start of the period it belongs to.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nmb.config import DataCapConfig
from nmb.db import database as db

log = logging.getLogger("nmb.speed.data_cap")

LINKS = ("wired", "wifi", "usb", "lag")
CONNECTION_TYPES = ("fiber", "docsis", "xdsl", "fwa", "dialup", "satellite", "ethernet", "other")
USB_CONNECTION_TYPE = "fwa"           # a hotspot or modem on USB is a mobile line
WARN_AT = 0.8
MAX_MB = 100_000_000                  # 100 TB: a typing error, not a cap
LINK_KEY = "data_cap_used:{}"
TYPE_KEY = "data_cap_type_used:{}"
NOTE_KEY = "data_cap_note:{}"
NOTE_EVERY_MS = 3600 * 1000


class CapError(ValueError):
    pass


def _int_mb(value: Any, name: str) -> int:
    try:
        mb = int(float(value))
    except (TypeError, ValueError):
        raise CapError(f"{name}: a whole number of MB (0 = no cap)")
    if mb < 0 or mb > MAX_MB:
        raise CapError(f"{name}: 0 to {MAX_MB} MB")
    return mb


def clean(body: Dict[str, Any], current: DataCapConfig) -> DataCapConfig:
    """New settings from an API body, checked; keys left out keep their value."""
    out = DataCapConfig(**{k: getattr(current, k) for k in ("period", "reset_day", "wired_mb", "wifi_mb", "usb_mb", "lag_mb")},
                        by_type=dict(current.by_type))
    if "period" in body:
        period = str(body["period"]).strip().lower()
        if period not in ("day", "month"):
            raise CapError("period: day or month")
        out.period = period
    if "reset_day" in body:
        day = _int_mb(body["reset_day"], "reset_day")
        if not 1 <= day <= 28:
            raise CapError("reset_day: 1-28 (every month has these days)")
        out.reset_day = day
    for link in LINKS:
        key = f"{link}_mb"
        if key in body:
            setattr(out, key, _int_mb(body[key], key))
    if "by_type" in body:
        raw = body["by_type"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "{}")
            except ValueError:
                raise CapError("by_type: a JSON object such as {\"fwa\": 20000}")
        if not isinstance(raw, dict):
            raise CapError("by_type: a JSON object such as {\"fwa\": 20000}")
        caps = {}
        for ctype, mb in raw.items():
            if ctype not in CONNECTION_TYPES:
                raise CapError(f"by_type: unknown connection type '{str(ctype)[:20]}' ({', '.join(CONNECTION_TYPES)})")
            value = _int_mb(mb, f"by_type.{ctype}")
            if value:
                caps[ctype] = value
        out.by_type = caps
    return out


def parse_by_type(text: str) -> Dict[str, int]:
    try:
        raw = json.loads(text or "{}")
    except ValueError:
        log.warning("[data_cap] by_type in nmb.conf is not valid JSON; no caps per connection type")
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        try:
            mb = int(float(v))
        except (TypeError, ValueError):
            continue
        if k in CONNECTION_TYPES and 0 < mb <= MAX_MB:
            out[k] = mb
    return out


# ---- which link and type a test uses ----

def link_class(iface: Optional[str]) -> str:
    """wired, wifi, usb or lag for the interface a test is bound to."""
    if not iface:
        return "wired"
    try:
        from nmb.netd.interfaces import usb_tether_kind
        if usb_tether_kind(iface):
            return "usb"
    except Exception:
        pass
    base = Path("/sys/class/net") / iface
    if (base / "bonding").exists() or re.match(r"^(bond|team)\d*", iface):
        return "lag"
    if (base / "wireless").exists() or (base / "phy80211").exists() or iface.startswith("wl"):
        return "wifi"
    return "wired"


def connection_type(cfg: Any, link: str) -> str:
    if link == "usb":
        return USB_CONNECTION_TYPE
    ctype = str(getattr(getattr(cfg, "isp", None), "connection_type", "fiber") or "fiber")
    return ctype if ctype in CONNECTION_TYPES else "other"


# ---- periods ----

def period_start(caps: DataCapConfig, today: Optional[datetime.date] = None) -> datetime.date:
    today = today or datetime.date.today()
    if caps.period == "day":
        return today
    day = min(max(int(caps.reset_day or 1), 1), 28)
    if today.day >= day:
        return today.replace(day=day)
    first = today.replace(day=1)
    prev = first - datetime.timedelta(days=1)
    return prev.replace(day=day)


def next_reset(caps: DataCapConfig, today: Optional[datetime.date] = None) -> datetime.date:
    start = period_start(caps, today)
    if caps.period == "day":
        return start + datetime.timedelta(days=1)
    month = start.month % 12 + 1
    year = start.year + (1 if start.month == 12 else 0)
    return start.replace(year=year, month=month)


def _used(conn, key: str, start: str) -> float:
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    if not row:
        return 0.0
    when, _, used = str(row[0]).partition("|")
    try:
        return float(used) if when == start else 0.0
    except ValueError:
        return 0.0


def _set(conn, key: str, start: str, mb: float) -> None:
    with db.tx(conn):
        conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (key, f"{start}|{mb:.1f}", db.now_ms()))


def usage(conn, cfg: Any, caps: Optional[DataCapConfig] = None) -> Dict[str, Any]:
    """Per link and per connection type: cap, used and whether automatic tests stop (for the API and the bot)."""
    caps = caps or getattr(cfg, "data_cap", None) or DataCapConfig()
    start = period_start(caps).isoformat()
    links = []
    for link in LINKS:
        ctype = connection_type(cfg, link)
        cap, used = caps.link_cap(link), _used(conn, LINK_KEY.format(link), start)
        tcap, tused = int(caps.by_type.get(ctype, 0) or 0), _used(conn, TYPE_KEY.format(ctype), start)
        links.append({"link": link, "cap_mb": cap, "used_mb": round(used, 1), "type": ctype, "type_cap_mb": tcap,
                      "type_used_mb": round(tused, 1),
                      "reached": bool((cap and used >= cap) or (tcap and tused >= tcap))})
    return {"period": caps.period, "reset_day": caps.reset_day, "period_start": start,
            "next_reset": next_reset(caps).isoformat(), "links": links, "by_type": dict(caps.by_type),
            "types": list(CONNECTION_TYPES)}


def check(conn, cfg: Any, iface: Optional[str]) -> Tuple[bool, str]:
    """Whether automatic tests on iface must stop now, with the reason (names the cap that was reached)."""
    caps = getattr(cfg, "data_cap", None)
    if caps is None:
        return False, ""
    link = link_class(iface)
    ctype = connection_type(cfg, link)
    start = period_start(caps).isoformat()
    span = "today" if caps.period == "day" else f"since {start}"
    cap = caps.link_cap(link)
    if cap:
        used = _used(conn, LINK_KEY.format(link), start)
        if used >= cap:
            return True, f"data cap for {link} reached ({used:.0f} of {cap} MB used by tests {span})"
    tcap = int(caps.by_type.get(ctype, 0) or 0)
    if tcap:
        used = _used(conn, TYPE_KEY.format(ctype), start)
        if used >= tcap:
            return True, f"data cap for {ctype} connections reached ({used:.0f} of {tcap} MB used by tests {span})"
    return False, ""


def add(conn, cfg: Any, iface: Optional[str], megabytes: float) -> List[str]:
    """Count a cycle's data against its link and type; returns the events written (warning, reached)."""
    caps = getattr(cfg, "data_cap", None)
    if caps is None or megabytes <= 0:
        return []
    link = link_class(iface)
    ctype = connection_type(cfg, link)
    start = period_start(caps).isoformat()
    events = []
    for key, cap, label in ((LINK_KEY.format(link), caps.link_cap(link), link),
                            (TYPE_KEY.format(ctype), int(caps.by_type.get(ctype, 0) or 0), f"{ctype} connections")):
        before = _used(conn, key, start)
        after = before + megabytes
        _set(conn, key, start, after)
        if not cap:
            continue
        if before < cap <= after:
            events.append(("data_cap_reached", "warn",
                           f"Data cap for {label} reached: {after:.0f} of {cap} MB used by tests; automatic tests stop "
                           f"until {next_reset(caps).isoformat()} (manual tests still run)"))
        elif before < cap * WARN_AT <= after:
            events.append(("data_cap_warning", "info",
                           f"Tests used {after:.0f} of the {cap} MB data cap for {label} ({after / cap:.0%})"))
    for kind, severity, detail in events:
        try:
            with db.tx(conn):
                conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, ?, 'speed', ?, ?)",
                             (db.now_ms(), severity, kind, detail))
        except Exception:
            log.debug("data cap event not written", exc_info=True)
        log.warning(detail) if kind == "data_cap_reached" else log.info(detail)
    return [k for k, _, _ in events]


def note_skip_due(conn, iface: Optional[str]) -> bool:
    """A skipped row at most once an hour per link: with a schedule every minute the table would fill up."""
    key = NOTE_KEY.format(link_class(iface))
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    now = db.now_ms()
    try:
        last = int(row[0]) if row else 0
    except ValueError:
        last = 0
    if now - last < NOTE_EVERY_MS:
        return False
    with db.tx(conn):
        conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (key, str(now), now))
    return True
