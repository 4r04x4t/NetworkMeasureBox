"""Live checks on a running box (nmb-selftest): what the unit tests cannot see.

Each check looks at the real system: services, routes, the USB uplink, router mode with a simulated
client, the DHCP guard against a throwaway DHCP server, the speed test engines against each other,
the Wi-Fi access point, the web and terminal interfaces, the Telegram bot and the central collector.

Rules the checks keep:
- They never print or store secrets (tokens, passwords, keys) or the box's public addresses;
  only whether something is set.
- They only touch throwaway objects (network namespaces, veth pairs, a test bridge, a copy of
  the database) and remove them again, also after an error.
- They never change the mode, the configuration or the uplinks.

Run as root on the box:  nmb-selftest            (all quick groups)
                         nmb-selftest --full     (also the Telegram bot, a few minutes)
                         nmb-selftest router usb (only these groups)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
LOG_DIR = Path("/var/log/nmb")
NS_PREFIX = "nmbst"
SIM_CLIENT_MAC = "02:4e:4d:42:53:54"   # the simulated LAN client, so lease checks can tell it apart          # every throwaway object starts with this
HU_LEAK = re.compile(r"[őűŐŰ]")


class Report:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def add(self, group: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append({"group": group, "check": name, "status": status, "detail": detail})
        mark = {"PASS": "ok  ", "WARN": "warn", "FAIL": "FAIL", "SKIP": "skip"}[status]
        print(f"[{mark}] {group:<10} {name:<38} {detail}", flush=True)

    def counts(self) -> Dict[str, int]:
        out = {s: 0 for s in (PASS, WARN, FAIL, SKIP)}
        for r in self.rows:
            out[r["status"]] += 1
        return out


def run(cmd: List[str], timeout: float = 30.0, ns: Optional[str] = None, check: bool = False) -> subprocess.CompletedProcess:
    if ns:
        cmd = ["ip", "netns", "exec", ns] + cmd
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {(res.stderr or res.stdout).strip()[:200]}")
    return res


def _cfg():
    from nmb.config import load_config
    return load_config()


def _db(readonly: bool = True) -> sqlite3.Connection:
    from nmb.db import database as db
    return db.connect(readonly=readonly)


def _netd_state() -> Dict[str, Any]:
    for p in (Path("/run/nmb/netd_state.json"),):
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _default_routes() -> List[List[str]]:
    out = run(["ip", "-4", "route", "show", "default"]).stdout
    return [line.split() for line in out.splitlines() if line.strip()]


def _route_dev(parts: List[str]) -> str:
    return parts[parts.index("dev") + 1] if "dev" in parts else ""


def _metric(parts: List[str]) -> int:
    return int(parts[parts.index("metric") + 1]) if "metric" in parts else 0


def tailscale_online() -> Optional[bool]:
    """True/False when Tailscale runs, None when it is not installed or not logged in."""
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        d = json.loads(run([exe, "status", "--json"], timeout=10).stdout or "{}")
    except Exception:
        return False
    if d.get("BackendState") not in ("Running",):
        return None if d.get("BackendState") in ("NeedsLogin", "Stopped", None) else False
    return bool((d.get("Self") or {}).get("Online"))


def interfaces_kind(iface: Optional[str]) -> str:
    from nmb.netd import interfaces
    return str(interfaces.usb_tether_kind(iface)) if iface else "none"


def weak_psk(cfg) -> bool:
    from nmb.netd.wifi import weak_wifi_password
    return weak_wifi_password(getattr(cfg.network, "wifi_psk", ""))


# --------------------------------------------------------------------------------------------
# Pure evaluation helpers (unit tested in tests/test_selftest.py)
# --------------------------------------------------------------------------------------------

def evaluate_engines(rows: List[Dict[str, Any]], min_rows: int = 5, ratio_hi: float = 1.35,
                     ratio_lo: float = 0.65, ip_missing_max: float = 0.2) -> List[Tuple[str, str, str]]:
    """rows: ok speed tests with engine, iface, down_bps, up_bps, client_ip, ping_min, ping_median.

    Returns (name, status, detail): per engine and link the share without a client IP, and each
    engine's median download compared with the reference engines (Ookla and Cloudflare) on the same link.
    """
    out: List[Tuple[str, str, str]] = []
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r.get("iface") or "?", r["engine"]), []).append(r)
    for (iface, engine), rs in sorted(groups.items()):
        missing = sum(1 for r in rs if not r.get("client_ip"))
        share = missing / len(rs)
        st = FAIL if share > ip_missing_max and len(rs) >= min_rows else (WARN if missing else PASS)
        out.append((f"client IP {engine}@{iface}", st, f"{missing}/{len(rs)} rows without the client IP"))
        single = [r for r in rs if r.get("ping_min") is not None and r.get("ping_min") == r.get("ping_median")]
        if engine == "rtr" and len(rs) >= min_rows and len(single) == len(rs):
            out.append((f"ping samples {engine}@{iface}", WARN,
                        "minimum ping always equals the median: only one ping sample is kept"))
    links = {k[0] for k in groups}
    for iface in sorted(links):
        ref = [r["down_bps"] for (i, e), rs in groups.items() if i == iface and e in ("ookla", "cloudflare")
               for r in rs if r.get("down_bps")]
        if len(ref) < min_rows:
            continue
        ref_med = statistics.median(ref)
        for (i, engine), rs in sorted(groups.items()):
            if i != iface or engine in ("ookla", "cloudflare"):
                continue
            vals = [r["down_bps"] for r in rs if r.get("down_bps")]
            if len(vals) < min_rows:
                continue
            ratio = statistics.median(vals) / ref_med if ref_med else 0
            st = PASS if ratio_lo <= ratio <= ratio_hi else WARN
            out.append((f"download {engine}@{iface} vs reference", st,
                        f"median {statistics.median(vals)/1e6:.0f} vs {ref_med/1e6:.0f} Mbit/s (x{ratio:.2f}, n={len(vals)})"))
    return out


def parse_iw_phy(text: str) -> Dict[str, Dict[str, bool]]:
    """Per band of `iw phy`: whether it supports HT40 and VHT (80 MHz)."""
    bands: Dict[str, Dict[str, bool]] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"\s*Band (\d+):", line)
        if m:
            cur = {"1": "2.4ghz", "2": "5ghz", "4": "6ghz"}.get(m.group(1), m.group(1))
            bands[cur] = {"ht40": False, "vht": False}
            continue
        if cur is None:
            continue
        if "HT20/HT40" in line:
            bands[cur]["ht40"] = True
        if "VHT Capabilities" in line:
            bands[cur]["vht"] = True
    return bands


def parse_hostapd(text: str) -> Dict[str, str]:
    conf: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if "pass" in k or "psk" in k or k.startswith("wpa_"):
                continue  # never keep the Wi-Fi password
            conf[k.strip()] = v.strip()
    return conf


def i18n_problems(tables: Dict[str, Dict[str, str]], base: str = "en") -> Dict[str, List[str]]:
    """Per language: keys missing against the base, and Hungarian letters outside Hungarian."""
    out: Dict[str, List[str]] = {}
    ref = tables.get(base, {})
    for lang, t in tables.items():
        probs = [f"missing {k}" for k in ref if k not in t]
        if lang != "hu":
            probs += [f"hungarian in {k}" for k, v in t.items() if isinstance(v, str) and HU_LEAK.search(v)]
        out[lang] = probs
    return out


# --------------------------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------------------------

def g_services(rep: Report, cfg) -> None:
    units = ["nmb-netd", "nmb-web", "nmb-probe", "nmb-db", "nmb-guard"]
    if getattr(cfg.telegram, "token", ""):
        units.append("nmb-telegram")
    for u in units:
        st = run(["systemctl", "is-active", u]).stdout.strip()
        rep.add("services", u, PASS if st == "active" else FAIL, st)
    res = run(["journalctl", "-u", "nmb-netd", "-u", "nmb-web", "-u", "nmb-telegram", "--since", "-1h",
               "--no-pager", "-o", "cat"], timeout=30)
    tb = res.stdout.count("Traceback")
    rep.add("services", "no tracebacks in the last hour", PASS if tb == 0 else WARN, f"{tb} traceback(s)")
    state = _netd_state()
    rep.add("services", "netd state file", PASS if state.get("active_mode") else FAIL,
            f"active mode {state.get('active_mode')}")


def g_internet(rep: Report, cfg) -> None:
    routes = _default_routes()
    rep.add("internet", "default route", PASS if routes else FAIL,
            ", ".join(f"{_route_dev(r)} metric {_metric(r)}" for r in routes) or "none")
    from nmb.netd import interfaces
    dead = interfaces.dead_default_routes("\n".join(" ".join(r) for r in routes),
                                          lambda d: any(":" not in a for a in interfaces.get_ip_addresses(d)))
    rep.add("internet", "no dead default route", PASS if not dead else FAIL,
            "" if not dead else "through a port with no link or no address: " + ", ".join(_route_dev(r) for r in dead))
    ping = run(["ping", "-c", "3", "-W", "2", "1.1.1.1"], timeout=15)
    m = re.search(r"= [\d.]+/([\d.]+)/", ping.stdout)
    rep.add("internet", "ping 1.1.1.1", PASS if ping.returncode == 0 else FAIL,
            f"avg {m.group(1)} ms" if m else (ping.stdout.strip().splitlines() or ["no answer"])[-1])
    import socket
    try:
        socket.getaddrinfo("www.netztest.at", 443)
        rep.add("internet", "DNS", PASS, "www.netztest.at resolves")
    except OSError as e:
        rep.add("internet", "DNS", FAIL, str(e))
    ts = tailscale_online()
    rep.add("internet", "Tailscale online", SKIP if ts is None else (PASS if ts else FAIL),
            "not installed or not logged in" if ts is None else ("connected" if ts else "offline: remote access is gone"))
    res = run(["curl", "-s", "-m", "10", "https://www.cloudflare.com/cdn-cgi/trace"], timeout=15)
    rep.add("internet", "HTTPS", PASS if "ip=" in res.stdout else FAIL,
            "Cloudflare answered" if "ip=" in res.stdout else (res.stderr.strip() or "no answer"))


def g_config(rep: Report, cfg) -> None:
    from nmb.netd.wifi import weak_wifi_password
    weak = weak_wifi_password(getattr(cfg.network, "wifi_psk", ""))
    # A weak or factory password is a failure even with the access point off: it could not be turned on.
    rep.add("config", "Wi-Fi password", FAIL if weak else PASS,
            "weak, empty or the factory one: the access point cannot start; set one in Settings > Wi-Fi" if weak
            else "set, not the factory one")
    rep.add("config", "Telegram token", PASS if getattr(cfg.telegram, "token", "") else
            (FAIL if getattr(cfg.telegram, "enabled", False) else WARN),
            "set" if getattr(cfg.telegram, "token", "") else "not set: the bot stays off")
    from nmb.common import secret_keep
    gone = secret_keep.lost() if secret_keep.KEEP_FILE.exists() else []
    rep.add("config", "no secret lost", PASS if not gone else FAIL,
            "kept copies match" if gone == [] else
            "empty or factory now, set before: " + ", ".join(f"{n} (seen {time.strftime('%m-%d %H:%M', time.localtime(t))})" for n, t in gone)
            + "; restore with: sudo nmb-selftest secrets-restore")
    p = Path("/etc/nmb/nmb.conf")
    if p.exists():
        mode = p.stat().st_mode & 0o777
        rep.add("config", "nmb.conf permissions", PASS if not mode & 0o007 else FAIL, oct(mode))
    try:
        conn = _db()
        bad = conn.execute("SELECT COUNT(*) FROM event WHERE severity NOT IN ('debug','info','warn','crit')").fetchone()[0]
        conn.close()
        rep.add("config", "event severities", PASS if not bad else FAIL, f"{bad} rows outside the schema")
    except Exception as e:
        rep.add("config", "event severities", WARN, str(e))


def _cli(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    exe = shutil.which("nmb-cli") or "/opt/nmb/bin/nmb-cli"
    return run([exe, *args], timeout=timeout)


def g_web(rep: Report, cfg) -> None:
    import urllib.request
    from nmb.web.i18n import SUPPORTED_LANGUAGES
    tables: Dict[str, Dict[str, str]] = {}
    port = getattr(cfg.web, "port", 80) or 80
    for lang in SUPPORTED_LANGUAGES:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/i18n?lang={lang}", timeout=10) as r:
                tables[lang] = json.loads(r.read()).get("translations", {})
        except Exception as e:
            rep.add("web", f"i18n {lang}", FAIL, str(e))
    for lang, probs in i18n_problems(tables).items():
        rep.add("web", f"i18n {lang}", PASS if not probs else FAIL,
                f"{len(tables[lang])} texts" if not probs else f"{len(probs)}: {', '.join(probs[:4])}")
    for path in ("/api/status", "/api/usb-uplink/status", "/api/storage/status", "/api/config"):
        res = _cli("api", "GET", path)
        ok = res.returncode == 0
        detail = "answered" if ok else (res.stderr or res.stdout).strip()[:120]
        if ok and path == "/api/config":
            body = res.stdout
            leaked = [k for k in ('"wifi_psk"', '"token"', '"password"') if re.search(k + r'\s*:\s*"[^"]+', body)]
            if leaked:
                ok, detail = False, "returns secrets: " + ", ".join(leaked)
        rep.add("web", f"GET {path}", PASS if ok else FAIL, detail)


def g_cli(rep: Report, cfg) -> None:
    res = _cli("menu")
    try:
        menu = json.loads(res.stdout)
        rep.add("cli", "nmb-cli menu", PASS, f"{len(json.dumps(menu))} bytes of menu")
    except Exception:
        rep.add("cli", "nmb-cli menu", FAIL, (res.stderr or res.stdout)[:120])
        return
    screens = [s.get("id") for s in menu if isinstance(s, dict) and s.get("id")]
    failed = []
    for key in sorted(set(screens)):
        r = _cli("show", key, timeout=60)
        if r.returncode not in (0,) and "Unknown screen" not in r.stderr:
            failed.append(key)
    rep.add("cli", "every screen loads", PASS if not failed else FAIL,
            f"{len(set(screens))} screens" if not failed else "failed: " + ", ".join(failed[:6]))
    for eng in ("all", "ookla", "cloudflare", "fastcom", "rtr", "iperf3"):
        r = _cli("latest", eng, "--json")
        rep.add("cli", f"latest {eng}", PASS if r.returncode == 0 else WARN, (r.stderr.strip() or "ok")[:100])


def g_telegram(rep: Report, cfg) -> None:
    """Every menu button and command in every language, through a fake Telegram client."""
    import logging
    import signal
    import traceback
    logging.disable(logging.CRITICAL)
    from nmb.bot import i18n as B
    from nmb.bot.commands import CommandHandler
    from nmb.bot.i18n import set_chat_lang

    class Fake:
        def __init__(self) -> None:
            self.out: List[str] = []
            self.cb: set = set()

        def _m(self, rm) -> None:
            for row in (rm or {}).get("inline_keyboard", []):
                for b in row:
                    if b.get("callback_data"):
                        self.cb.add(b["callback_data"])

        def send_message(self, chat_id, text, parse_mode="HTML", reply_markup=None):
            self.out.append(text)
            self._m(reply_markup)
            return True

        def send_document(self, chat_id, filename, content, caption=""):
            self.out.append(f"[doc {filename}]")
            return True

        def send_photo(self, chat_id, photo_bytes, caption="", filename=""):
            self.out.append("[photo]")
            return True

        def __getattr__(self, n):
            return lambda *a, **k: True

    class _TO(Exception):
        pass

    def _alarm(*_a):
        raise _TO()

    signal.signal(signal.SIGALRM, _alarm)
    # Anything that changes the box, measures, or talks to the outside is left out.
    skip = re.compile(r"^/(reboot now|kill \d|purge \S+ confirm|heal (fix|apply)|vpn (add|del|delete|rm|on|off|start|stop|enable|disable)|"
                      r"wifi connect|mode \S|adblock (on|off|enable|disable|update)|dyndns (on|off|update|set)|backup (create|send)|"
                      r"test|speed|speedtest|lang \S|ai)")
    bad = re.compile(r"Traceback|object has no attribute|cannot import|unexpected keyword|positional argument|"
                     r"not enough values|\{[a-z_]+\}")
    base = ["/help", "/status", "/ping", "/sla", "/purge", "/lang", "/tailscale", "/mode", "/vpn", "/vpn clients",
            "/dyndns", "/adblock", "/heal", "/tasks", "/kill", "/wifi", "/wifi saved", "/backup", "/backup list",
            "/drivers", "/reboot", "/foo"]
    f = Fake()
    h = CommandHandler(cfg, f)
    for i, lang in enumerate(B.SUPPORTED_LANGUAGES):
        chat = 990000100 + i
        set_chat_lang(chat, lang)
        labels = [b["text"] for row in B.get_main_keyboard(lang)["keyboard"] for b in row]
        todo, seen, fails, ran = labels + base, set(), [], 0
        while todo:
            c = todo.pop(0)
            cmd = B.get_menu_aliases().get(c.lower(), c)
            if c in seen or skip.match(cmd):
                continue
            seen.add(c)
            f.out.clear()
            f.cb.clear()
            ran += 1
            signal.alarm(45)
            try:
                h.handle_command(chat, c)
                err = ""
            except _TO:
                err = "no answer within 45 s"
            except Exception:
                err = traceback.format_exc(limit=1).strip().splitlines()[-1]
            finally:
                signal.alarm(0)
            txt = " | ".join(f.out)
            problem = err or ("no reply" if not f.out else "") or ("error text" if bad.search(txt) else "") or \
                ("Hungarian text" if lang != "hu" and HU_LEAK.search(txt) else "")
            if problem:
                fails.append(f"{c}: {problem}")
            todo += [x for x in f.cb if x not in seen]
        rep.add("telegram", f"bot {lang}", PASS if not fails else FAIL,
                f"{ran} commands and buttons" if not fails else f"{len(fails)}/{ran}: " + "; ".join(fails[:3]))
    logging.disable(logging.NOTSET)


def g_usb(rep: Report, cfg) -> None:
    from nmb.netd import interfaces, usb_uplink
    tethers = usb_uplink.tether_interfaces()
    if not tethers:
        rep.add("usb", "device on USB", SKIP, "no phone, hotspot or modem plugged in")
        return
    for t in tethers:
        rep.add("usb", f"{t} kind", PASS, str(interfaces.usb_tether_kind(t)))
    if not cfg.usb_uplink.enabled:
        rep.add("usb", "USB uplink", SKIP, "turned off in the settings")
        return
    iface = usb_uplink.uplink_interface(cfg)
    ip, gw = usb_uplink._address_and_gateway(iface) if iface else (None, None)
    rep.add("usb", "address and gateway", PASS if ip and gw else FAIL, f"{iface}: {'ok' if ip else 'no address'}")
    if not ip:
        return
    nd = run(["nmcli", "-g", "ipv4.never-default", "connection", "show", usb_uplink.PROFILE]).stdout.strip()
    rep.add("usb", "profile never takes the default route", PASS if nd == "yes" else FAIL, nd or "profile missing")
    rules = run(["ip", "-4", "rule", "show"]).stdout
    rep.add("usb", "source rule to table 152", PASS if f"from {ip} lookup 152" in rules else FAIL, "")
    routes = _default_routes()
    others = [r for r in routes if _route_dev(r) != iface and "linkdown" not in r]
    usb_def = [r for r in routes if _route_dev(r) == iface]
    router_wan = _netd_state().get("active_mode") == "mode_a"   # router mode may use USB as its WAN
    if others and usb_def and not router_wan:
        rep.add("usb", "fallback route only without other internet", FAIL,
                "USB default route although " + _route_dev(others[0]) + " has one")
    elif not others and not usb_def:
        rep.add("usb", "fallback route only without other internet", FAIL, "no internet route at all")
    else:
        rep.add("usb", "fallback route only without other internet", PASS,
                "USB is the internet" if usb_def and not others else "USB stays a side link")
    p = run(["ping", "-c", "3", "-W", "3", "-I", ip, "1.1.1.1"], timeout=20)
    m = re.search(r"= [\d.]+/([\d.]+)/", p.stdout)
    rep.add("usb", "ping over USB", PASS if p.returncode == 0 else FAIL, f"avg {m.group(1)} ms" if m else "no answer")
    c = run(["curl", "-s", "-m", "15", "--interface", iface, "https://www.cloudflare.com/cdn-cgi/trace"], timeout=20)
    rep.add("usb", "HTTPS over USB", PASS if "ip=" in c.stdout else FAIL, "ok" if "ip=" in c.stdout else c.stderr.strip()[:100])


_UDHCPC_SCRIPT = """#!/bin/sh
case "$1" in
  bound|renew)
    ip addr flush dev "$interface"
    ip addr add "$ip/${mask:-24}" dev "$interface"
    for r in $router; do ip route replace default via "$r" dev "$interface"; break; done
    : > "$RESOLV"; for d in $dns; do echo "nameserver $d" >> "$RESOLV"; done
    echo "$ip" > "$LEASE"
    ;;
esac
exit 0
"""


def _cleanup_ns(name: str) -> None:
    run(["ip", "netns", "del", name])
    for link in (f"{name}a", f"{name}b", f"{name}br"):
        run(["ip", "link", "del", link])
    shutil.rmtree(f"/etc/netns/{name}", ignore_errors=True)


def g_router(rep: Report, cfg) -> None:
    state = _netd_state()
    if state.get("active_mode") != "mode_a":
        rep.add("router", "router mode", SKIP, f"the box is in {state.get('active_mode')} mode")
        return
    details = state.get("details") or {}
    wan = details.get("active_wan") or details.get("wan") or ""
    br = run(["bridge", "link"]).stdout
    members = re.findall(r"\d+: (\S+?)[:@].*master br-lan", br)
    rep.add("router", "LAN bridge members", PASS if members else FAIL, ", ".join(members) or "none")
    dnsmasq = run(["pgrep", "-f", "dnsmasq --conf-file=/run/nmb/dnsmasq.conf"]).returncode == 0
    rep.add("router", "DHCP server for the LAN", PASS if dnsmasq else FAIL, "running" if dnsmasq else "not running")
    nat = run(["nft", "list", "table", "inet", "nmb_nat"]).stdout
    m = re.search(r'oifname "([^"]+)" masquerade', nat)
    rep.add("router", "NAT out of the WAN", PASS if m else FAIL, f"masquerade on {m.group(1)}" if m else "no NAT")
    routes = _default_routes()
    if m:
        wrong = [r for r in routes if _route_dev(r) != m.group(1) and "linkdown" not in r]
        best = min(routes, key=_metric) if routes else []
        rep.add("router", "box's own default route via the WAN", PASS if best and _route_dev(best) == m.group(1) else FAIL,
                f"best {_route_dev(best) if best else 'none'}; other: {', '.join(_route_dev(r) for r in wrong) or 'none'}")
    # A client on the LAN, like the laptop on the cable: a veth into br-lan, DHCP, then the internet.
    ns = f"{NS_PREFIX}c"
    _cleanup_ns(ns)
    tmp = Path(tempfile.mkdtemp(prefix="nmbst"))
    try:
        run(["ip", "netns", "add", ns], check=True)
        run(["ip", "link", "add", f"{ns}a", "type", "veth", "peer", "name", f"{ns}b"], check=True)
        run(["ip", "link", "set", f"{ns}b", "address", SIM_CLIENT_MAC], check=True)
        run(["ip", "link", "set", f"{ns}b", "netns", ns], check=True)
        run(["ip", "link", "set", f"{ns}a", "master", "br-lan"], check=True)
        run(["ip", "link", "set", f"{ns}a", "up"], check=True)
        run(["ip", "link", "set", "lo", "up"], ns=ns)
        run(["ip", "link", "set", f"{ns}b", "up"], ns=ns, check=True)
        etc = Path(f"/etc/netns/{ns}")
        etc.mkdir(parents=True, exist_ok=True)
        script = tmp / "udhcpc.sh"
        script.write_text(_UDHCPC_SCRIPT)
        script.chmod(0o700)
        env_cmd = ["env", f"RESOLV={etc / 'resolv.conf'}", f"LEASE={tmp / 'lease'}",
                   "udhcpc", "-i", f"{ns}b", "-n", "-q", "-t", "6", "-T", "2", "-s", str(script)]
        dh = run(env_cmd, ns=ns, timeout=40)
        lease = (tmp / "lease").read_text().strip() if (tmp / "lease").exists() else ""
        rep.add("router", "LAN client gets an address", PASS if lease else FAIL, lease or (dh.stderr or dh.stdout).strip()[-120:])
        if not lease:
            return
        p = run(["ping", "-c", "3", "-W", "3", "1.1.1.1"], ns=ns, timeout=20)
        mm = re.search(r"= [\d.]+/([\d.]+)/", p.stdout)
        rep.add("router", "LAN client reaches the internet", PASS if p.returncode == 0 else FAIL,
                f"avg {mm.group(1)} ms" if mm else "no answer")
        d = run(["getent", "hosts", "www.netztest.at"], ns=ns, timeout=15)
        rep.add("router", "LAN client DNS", PASS if d.returncode == 0 else FAIL, "resolves" if d.returncode == 0 else "no answer")
        gw = str(getattr(cfg.network, "gateway_ip", "192.168.100.1") or "192.168.100.1")
        port = int(getattr(cfg.web, "port", 80) or 80)
        w = run(["curl", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}", f"http://{gw}:{port}/"], ns=ns, timeout=15).stdout.strip()
        rep.add("router", "Web UI reachable from the LAN", PASS if w[:1] in ("2", "3") or w == "401" else FAIL, f"HTTP {w or 'no answer'}")
        ssh = run(["bash", "-c", f"exec 3<>/dev/tcp/{gw}/22 && head -c 7 <&3"], ns=ns, timeout=10).stdout
        rep.add("router", "SSH reachable from the LAN", PASS if ssh.startswith("SSH-") else FAIL, ssh.strip() or "no answer")
        c = run(["curl", "-s", "-m", "15", "https://www.cloudflare.com/cdn-cgi/trace"], ns=ns, timeout=20)
        rep.add("router", "LAN client HTTPS", PASS if "ip=" in c.stdout else FAIL,
                "ok" if "ip=" in c.stdout else c.stderr.strip()[:100])
        if wan:
            rep.add("router", "WAN in the state file", PASS, wan)
    except Exception as e:
        rep.add("router", "LAN client simulation", FAIL, str(e)[:160])
    finally:
        _cleanup_ns(ns)
        shutil.rmtree(tmp, ignore_errors=True)


def g_dhcp_probe(rep: Report, cfg) -> None:
    """The DHCP guard against a throwaway DHCP server, on a plain port and on a bridge port."""
    if not shutil.which("dnsmasq"):
        rep.add("dhcp-probe", "dnsmasq", SKIP, "not installed")
        return
    from nmb.netd.wifi_share import probe_dhcp_servers
    ns = f"{NS_PREFIX}d"
    pid = f"/run/{ns}.pid"
    _cleanup_ns(ns)

    def kill_srv() -> None:
        try:
            os.kill(int(Path(pid).read_text().strip()), 15)
        except Exception:
            pass
        Path(pid).unlink(missing_ok=True)

    try:
        run(["ip", "netns", "add", ns], check=True)
        run(["ip", "link", "add", f"{ns}a", "type", "veth", "peer", "name", f"{ns}b"], check=True)
        run(["ip", "link", "set", f"{ns}b", "netns", ns], check=True)
        run(["ip", "addr", "add", "10.199.0.1/24", "dev", f"{ns}b"], ns=ns, check=True)
        run(["ip", "link", "set", f"{ns}b", "up"], ns=ns, check=True)
        run(["ip", "link", "set", f"{ns}a", "up"], check=True)
        run(["dnsmasq", "--port=0", f"--interface={ns}b", "--bind-interfaces", "--dhcp-range=10.199.0.100,10.199.0.150,1h",
             f"--pid-file={pid}", f"--dhcp-leasefile=/run/{ns}.leases", "--conf-file=/dev/null"], ns=ns, check=True)
        time.sleep(1)
        got = probe_dhcp_servers(f"{ns}a", timeout=5)
        rep.add("dhcp-probe", "server on a plain port", PASS if "10.199.0.1" in got else FAIL, str(got))
        run(["ip", "link", "add", f"{ns}br", "type", "bridge"], check=True)
        run(["ip", "link", "set", f"{ns}br", "up"], check=True)
        run(["ip", "link", "set", f"{ns}a", "master", f"{ns}br"], check=True)
        time.sleep(1)
        got = probe_dhcp_servers(f"{ns}a", timeout=5)
        rep.add("dhcp-probe", "server on a bridge port", PASS if "10.199.0.1" in got else FAIL, str(got))
        kill_srv()
        time.sleep(0.5)
        got = probe_dhcp_servers(f"{ns}a", timeout=3)
        rep.add("dhcp-probe", "no server, no false alarm", PASS if not got else FAIL, str(got))
    except Exception as e:
        rep.add("dhcp-probe", "test setup", FAIL, str(e)[:160])
    finally:
        kill_srv()
        Path(f"/run/{ns}.leases").unlink(missing_ok=True)
        _cleanup_ns(ns)


def _pppd_in_ns(ns: str, iface: str, user: str, password: str, linkname: str, timeout: float = 25.0) -> Tuple[bool, str]:
    """Dial PPPoE with NMB's own pppd command inside a namespace; True when ppp got an address."""
    import types
    from nmb.netd.services import build_pppd_cmd
    pppd = shutil.which("pppd") or "/usr/sbin/pppd"
    opts = Path(tempfile.mkdtemp(prefix="nmbst-ppp")) / "options"
    cfg = types.SimpleNamespace(pppoe_user=user, pppoe_password=password, pppoe_service_name="")
    cmd = ["ip", "netns", "exec", ns] + build_pppd_cmd(pppd, cfg, iface, opts, linkname=linkname)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    addr = ""
    try:
        t0 = time.time()
        while time.time() - t0 < timeout and proc.poll() is None:
            out = run(["ip", "-4", "-o", "addr", "show"], ns=ns).stdout
            m = re.search(r"\d+: (ppp\d+)\s+inet (\S+)", out)
            if m:
                addr = f"{m.group(1)} {m.group(2)}"
                break
            time.sleep(1)
        return bool(addr), addr or "no PPP address"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(opts.parent, ignore_errors=True)


def g_pppoe(rep: Report, cfg, real: bool = False) -> None:
    """PPPoE with NMB's own pppd command: against a throwaway PPPoE server (right and wrong password), and
    with --real against the line on the WAN port, through a macvlan in a namespace (the box's routes stay)."""
    server = shutil.which("pppoe-server") or ("/usr/sbin/pppoe-server" if os.path.exists("/usr/sbin/pppoe-server") else "")
    if not real:
        if not server:
            rep.add("pppoe", "pppoe-server", SKIP, "not installed (package pppoe)")
            return
        srv, cli = f"{NS_PREFIX}ps", f"{NS_PREFIX}pc"
        etc = Path(f"/etc/netns/{srv}")
        try:
            for ns in (srv, cli):
                run(["ip", "netns", "del", ns])
            run(["ip", "netns", "add", srv], check=True)
            run(["ip", "netns", "add", cli], check=True)
            run(["ip", "link", "add", f"{NS_PREFIX}pa", "type", "veth", "peer", "name", f"{NS_PREFIX}pb"], check=True)
            run(["ip", "link", "set", f"{NS_PREFIX}pa", "netns", srv], check=True)
            run(["ip", "link", "set", f"{NS_PREFIX}pb", "netns", cli], check=True)
            run(["ip", "link", "set", f"{NS_PREFIX}pa", "up"], ns=srv, check=True)
            run(["ip", "link", "set", f"{NS_PREFIX}pb", "up"], ns=cli, check=True)
            # The server's pppd reads /etc/ppp; inside its namespace that is /etc/netns/<ns>/ppp.
            if etc.exists():
                shutil.rmtree(etc)
            shutil.copytree("/etc/ppp", etc / "ppp")
            (etc / "ppp" / "pap-secrets").write_text('"nmbtest" * "Right-Pass-77" *\n')
            (etc / "ppp" / "chap-secrets").write_text('"nmbtest" * "Right-Pass-77" *\n')
            (etc / "ppp" / "pppoe-server-options").write_text("require-pap\nlcp-echo-interval 10\nlcp-echo-failure 2\n")
            run([server, "-I", f"{NS_PREFIX}pa", "-L", "10.77.0.1", "-R", "10.77.0.100", "-N", "4"], ns=srv, check=True)
            time.sleep(1)
            ok, detail = _pppd_in_ns(cli, f"{NS_PREFIX}pb", "nmbtest", "Right-Pass-77", "nmbst-ok")
            rep.add("pppoe", "dial with the right password (simulated line)", PASS if ok else FAIL, detail)
            if ok:
                p = run(["ping", "-c", "2", "-W", "2", "10.77.0.1"], ns=cli, timeout=10)
                rep.add("pppoe", "traffic over the PPP link", PASS if p.returncode == 0 else FAIL, "ping to the server")
            bad, detail = _pppd_in_ns(cli, f"{NS_PREFIX}pb", "nmbtest", "wrong-pass", "nmbst-bad", timeout=15)
            rep.add("pppoe", "wrong password is refused", PASS if not bad else FAIL, "no link" if not bad else detail)
            leak = run(["pgrep", "-af", "pppd"]).stdout
            rep.add("pppoe", "password not on any command line", PASS if "Right-Pass-77" not in leak else FAIL, "")
        except Exception as e:
            rep.add("pppoe", "simulated line", FAIL, f"{type(e).__name__}: {str(e)[:150]}")
        finally:
            run(["pkill", "-f", f"pppoe-server -I {NS_PREFIX}pa"])
            for ns in (srv, cli):
                run(["ip", "netns", "del", ns])
            shutil.rmtree(etc, ignore_errors=True)
        return
    # The real line: the WAN port must reach the ISP's PPPoE server (the ONT or modem, not the home router).
    net = cfg.network
    if not (getattr(net, "pppoe_user", "") and getattr(net, "pppoe_password", "")):
        rep.add("pppoe", "real line", SKIP, "no PPPoE user name and password set (Web UI > Router > PPPoE)")
        return
    ns, mv = f"{NS_PREFIX}pr", f"{NS_PREFIX}mv"
    wan = getattr(net, "wan_interface", "eth0") or "eth0"
    try:
        run(["ip", "netns", "del", ns])
        run(["ip", "netns", "add", ns], check=True)
        run(["ip", "link", "add", mv, "link", wan, "type", "macvlan", "mode", "bridge"], check=True)
        run(["ip", "link", "set", mv, "netns", ns], check=True)
        run(["ip", "link", "set", mv, "up"], ns=ns, check=True)
        disc = run(["pppoe-discovery", "-I", mv], ns=ns, timeout=20)
        found = "Access-Concentrator" in disc.stdout
        rep.add("pppoe", f"PPPoE server answers on {wan}", PASS if found else FAIL,
                "found" if found else "none: the WAN port must be on the ONT or modem, not behind a router")
        if found:
            ok, detail = _pppd_in_ns(ns, mv, net.pppoe_user, net.pppoe_password, "nmbst-real", timeout=40)
            rep.add("pppoe", "dial the real line with the saved credentials", PASS if ok else FAIL,
                    "connected" if ok else detail)   # the address is the public one: not printed
            if ok:
                p = run(["ping", "-c", "3", "-W", "3", "1.1.1.1"], ns=ns, timeout=20)
                rep.add("pppoe", "internet over PPPoE", PASS if p.returncode == 0 else FAIL, "ping 1.1.1.1")
    except Exception as e:
        rep.add("pppoe", "real line", FAIL, f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        run(["ip", "netns", "del", ns])


def g_speed(rep: Report, cfg, hours: int = 48) -> None:
    conn = _db()
    since = int((time.time() - hours * 3600) * 1000)
    rows = []
    errors: Dict[str, List[int]] = {}
    messages: Dict[str, Dict[str, int]] = {}
    paused: Dict[str, int] = {}
    for r in conn.execute("SELECT engine, status, bound_iface, down_bps, up_bps, client_ip, raw_json, error FROM speedtest "
                          "WHERE ts > ?", (since,)):
        engine = r[0] or "ookla"
        if r[1] == "skipped_busy":
            continue
        errors.setdefault(engine, [0, 0])
        msg = (r[7] or "").replace("\n", " ")
        if r[1] == "error" and "rate limit" in msg.lower():
            paused[engine] = paused.get(engine, 0) + 1   # the box waits on purpose; not a failed test
            continue
        errors[engine][1] += 1
        if r[1] == "error":
            errors[engine][0] += 1
            key = re.sub(r"\[[^\]]*\]|\d{4}-\d\d-\d\dT\S+", "", msg).strip()[:70]
            messages.setdefault(engine, {})[key] = messages.setdefault(engine, {}).get(key, 0) + 1
        if r[1] != "ok":
            continue
        raw = {}
        try:
            raw = json.loads(r[6] or "{}")
        except Exception:
            pass
        rows.append({"engine": engine, "iface": r[2], "down_bps": r[3], "up_bps": r[4], "client_ip": r[5],
                     "ping_min": raw.get("ping_min_ms"), "ping_median": raw.get("ping_median_ms")})
    conn.close()
    if not rows:
        rep.add("speed", f"tests in the last {hours} h", WARN, "none")
        return
    for engine, (err, total) in sorted(errors.items()):
        share = err / total if total else 0
        top = sorted((messages.get(engine) or {}).items(), key=lambda kv: -kv[1])[:2]
        rep.add("speed", f"errors {engine}", PASS if share <= 0.1 else (WARN if share <= 0.3 else FAIL),
                f"{err}/{total}" + ("; " + "; ".join(f"{n}x {m}" for m, n in top) if top else ""))
    for engine, n in sorted(paused.items()):
        rep.add("speed", f"rate-limit pauses {engine}", WARN if n > 3 else PASS,
                f"{n} scheduled run(s) recorded as errors while the box waited out a rate limit")
    for name, st, detail in evaluate_engines(rows):
        rep.add("speed", name, st, detail)


def g_wifi_ap(rep: Report, cfg) -> None:
    iw = shutil.which("iw") or "/usr/sbin/iw"
    bands = parse_iw_phy(run([iw, "phy"]).stdout) if os.path.exists(iw) else {}
    rep.add("wifi-ap", "radio bands", PASS if bands else WARN,
            "; ".join(f"{b}: {'HT40' if v['ht40'] else 'HT20 only'}{', VHT80' if v['vht'] else ''}" for b, v in bands.items()) or "unknown")
    conf_path = Path(cfg.system.run_dir) / "hostapd.conf"
    running = run(["pgrep", "-x", "hostapd"]).returncode == 0
    if not running or not conf_path.exists():
        rep.add("wifi-ap", "access point", SKIP, "not running")
        return
    conf = parse_hostapd(conf_path.read_text())
    # An access point without DHCP lets devices join but gives them nothing (2026-11-09: dnsmasq failed
    # with "unknown interface wlan0" because the radio's own address had been flushed).
    ap_if = conf.get("bridge") or conf.get("interface") or "wlan0"
    from nmb.netd import interfaces as _ifs
    has_ip = any(":" not in a for a in _ifs.get_ip_addresses(ap_if))
    dhcp = run(["pgrep", "-f", "dnsmasq --conf-file=/run/nmb/dnsmasq.conf"]).returncode == 0
    rep.add("wifi-ap", "access point hands out addresses", PASS if has_ip and dhcp else FAIL,
            f"{ap_if}: address {'yes' if has_ip else 'none'}, DHCP {'running' if dhcp else 'not running'}")
    band = "5ghz" if conf.get("hw_mode") == "a" else "2.4ghz"
    wide = "HT40" in conf.get("ht_capab", "")
    cap = bands.get(band, {})
    if wide and not cap.get("ht40"):
        rep.add("wifi-ap", "channel width fits the radio", FAIL, f"40 MHz asked on {band}, the radio only does 20 MHz there")
    elif not wide and any(v["ht40"] for v in bands.values()):
        better = [b for b, v in bands.items() if v["ht40"]]
        rep.add("wifi-ap", "channel width fits the radio", WARN,
                f"20 MHz on {band}; this radio does 40/80 MHz on {', '.join(better)}")
    else:
        rep.add("wifi-ap", "channel width fits the radio", PASS, f"{band}, {'40' if wide else '20'} MHz")
    log = run(["journalctl", "--since", "-1h", "--no-pager", "-o", "cat", "-t", "hostapd"], timeout=20).stdout
    retries = log.count("not found from the channel list")
    rep.add("wifi-ap", "hostapd starts at the first try", PASS if not retries else WARN,
            f"{retries} start(s) refused for a channel the radio does not offer in that mode" if retries else "")


def g_collector(rep: Report, cfg, url: str = "", token: str = "") -> None:
    """Upload a copy of the box's data to a collector: a local one (default) or the one at --collector-url.

    The copy keeps the box's own upload position untouched, so a real collector still gets everything.
    """
    from nmb.collector import client, server
    tmp = Path(tempfile.mkdtemp(prefix="nmbst-coll"))
    httpd = None
    try:
        src = _db()
        copy = sqlite3.connect(tmp / "box.db")
        src.backup(copy)
        src.close()
        for k in (client.KV_LAST_SPEED, client.KV_LAST_PING, client.KV_LAST_EVENT, client.KV_LAST_DIAG):
            copy.execute("DELETE FROM kv WHERE k = ?", (k,))
        copy.commit()
        want_speed = copy.execute("SELECT COUNT(*) FROM speedtest").fetchone()[0]
        if not url:
            (tmp / "srv").mkdir(mode=0o700)
            st = server.Settings(tmp / "srv")
            st.set_password("selftest-" + os.urandom(8).hex())
            token = st.add_token("selftest")
            httpd = server.make_server(tmp / "srv", "127.0.0.1", 0)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{httpd.server_address[1]}"
            where = "local test collector"
        else:
            where = "collector at --collector-url"
        import copy as _copy
        c2 = _copy.deepcopy(cfg)
        c2.collector.url, c2.collector.token = url, token
        c2.collector.case_id = c2.collector.case_id or "SELFTEST"
        c2.collector.share_diagnostics = False
        t0 = time.time()
        total = 0
        for _ in range(10):   # send_now stops after 20 batches; a long backlog needs a few calls
            res = client.send_now(c2, copy)
            if not res.get("ok"):
                break
            total += res.get("speedtests", 0)
            if res.get("speedtests", 0) == 0:
                break
        rep.add("collector", f"upload to the {where}", PASS if res.get("ok") else FAIL,
                f"{total} speed test(s) sent" if res.get("ok") else res.get("message", "")[:140])
        rep.add("collector", "every speed test arrived", PASS if total == want_speed else FAIL,
                f"{total}/{want_speed} in {time.time() - t0:.1f} s")
        if httpd is not None:
            rows = httpd.conn.execute("SELECT COUNT(*) FROM speedtest").fetchone()[0]
            rep.add("collector", "stored once on the collector", PASS if rows == want_speed else FAIL, f"{rows} rows")
            again = client.send_now(c2, copy)
            rep.add("collector", "sending again adds nothing", PASS if again.get("speedtests") == 0 else FAIL,
                    again.get("message", "")[:100])
        copy.close()
    except Exception as e:
        rep.add("collector", "upload", FAIL, f"{type(e).__name__}: {str(e)[:140]}")
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


GROUPS: Dict[str, Callable] = {
    "services": g_services, "internet": g_internet, "config": g_config, "web": g_web, "cli": g_cli,
    "usb": g_usb, "router": g_router, "dhcp-probe": g_dhcp_probe, "speed": g_speed, "wifi-ap": g_wifi_ap,
    "collector": g_collector, "telegram": g_telegram, "pppoe": g_pppoe,
}
QUICK = [g for g in GROUPS if g not in ("telegram",)]


def _secrets_restore() -> int:
    """Put back secrets that are empty or factory now but were set before (names only are printed)."""
    if os.geteuid() != 0:
        print("Run as root.", file=sys.stderr)
        return 2
    from nmb.common import secret_keep
    text, names = secret_keep.restore()
    if not names:
        print("No lost secret to restore.")
        return 0
    path = secret_keep.CONFIG
    st = path.stat()
    tmp = path.with_suffix(".restore")
    tmp.write_text(text, encoding="utf-8")
    os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, st.st_mode & 0o777)
    os.replace(tmp, path)
    for unit in ("nmb-web", "nmb-telegram"):
        run(["systemctl", "try-restart", unit], timeout=60)
    run(["systemctl", "reload", "nmb-netd"], timeout=30)
    print("Restored: " + ", ".join(names))
    return 0


def _scenario_main(argv: List[str]) -> int:
    from nmb.selftest import scenario
    p = argparse.ArgumentParser(prog="nmb-selftest scenario", description=scenario.__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    from nmb.selftest import scenario_router
    p.add_argument("name", choices=["usb", "router"])
    p.add_argument("--steps", default=None, help="Comma-separated. usb: " + ", ".join(scenario.STEPS)
                   + "; router: " + ", ".join(scenario_router.STEPS))
    p.add_argument("--plan", action="store_true", help="Only print the steps")
    args = p.parse_args(argv)
    mod = scenario_router if args.name == "router" else scenario
    known = mod.STEPS
    steps = known if args.steps is None else [s.strip() for s in args.steps.split(",") if s.strip()]
    bad = [s for s in steps if s not in known]
    if bad:
        p.error("unknown step(s): " + ", ".join(bad))
    if args.plan:
        print(mod.plan(steps))
        return 0
    if os.geteuid() != 0:
        print("Run as root.", file=sys.stderr)
        return 2
    return scenario_router.run_router(steps) if args.name == "router" else scenario.run_usb(steps)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["scenario"]:
        return _scenario_main(argv[1:])
    if argv[:1] == ["secrets-restore"]:
        return _secrets_restore()
    if argv[:1] == ["restore"]:
        from nmb.selftest import scenario
        return 0 if scenario.restore() else 1
    p = argparse.ArgumentParser(prog="nmb-selftest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("groups", nargs="*", metavar="group",
                   help="Groups to run: " + ", ".join(GROUPS) + " (default: all but telegram)")
    p.add_argument("--full", action="store_true", help="Also run the Telegram bot through every command (minutes)")
    p.add_argument("--collector-url", default="", help="Upload a copy of the data to this collector instead of a local one; "
                                                       "the token is read from NMB_SELFTEST_COLLECTOR_TOKEN")
    p.add_argument("--pppoe-real", action="store_true", help="pppoe group: also dial the real line on the WAN port "
                   "with the saved credentials (the port must be on the ONT or modem); never changes the box's routes")
    p.add_argument("--json", default="", help="Write the report here (default: /var/log/nmb/selftest-<time>.json)")
    args = p.parse_args(argv)
    unknown = [g for g in args.groups if g not in GROUPS]
    if unknown:
        p.error("unknown group(s): " + ", ".join(unknown))
    groups = args.groups or (list(GROUPS) if args.full else QUICK)
    if os.geteuid() != 0:
        print("Run as root: the checks build throwaway network namespaces.", file=sys.stderr)
        return 2
    cfg = _cfg()
    rep = Report()
    for g in groups:
        try:
            if g == "pppoe" and args.pppoe_real:
                g_pppoe(rep, cfg, real=True)
            elif g == "collector":
                g_collector(rep, cfg, args.collector_url, os.environ.get("NMB_SELFTEST_COLLECTOR_TOKEN", ""))
            else:
                GROUPS[g](rep, cfg)
        except Exception as e:
            rep.add(g, "group crashed", FAIL, f"{type(e).__name__}: {str(e)[:160]}")
    c = rep.counts()
    print(f"\n{c[PASS]} passed, {c[WARN]} warnings, {c[FAIL]} failed, {c[SKIP]} skipped")
    out = Path(args.json) if args.json else LOG_DIR / time.strftime("selftest-%Y%m%d-%H%M%S.json")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"ts": int(time.time()), "groups": groups, "counts": c, "results": rep.rows}, indent=1))
        print(f"report: {out}")
    except OSError as e:
        print(f"could not write the report: {e}", file=sys.stderr)
    return 1 if c[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
