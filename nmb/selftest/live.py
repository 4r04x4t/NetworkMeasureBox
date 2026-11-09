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
    def __init__(self, quiet: bool = False) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.quiet = quiet   # a probe report used only to poll a condition prints nothing

    def add(self, group: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append({"group": group, "check": name, "status": status, "detail": detail})
        if self.quiet:
            return
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
    ip -4 addr flush dev "$interface"   # IPv4 only: a full flush also took the IPv6 link-local address (no SLAAC then)
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
    wan = details.get("wan_interface") or details.get("active_wan") or details.get("wan") or ""
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
        _router_ipv6(rep, cfg, ns, details)
        if wan:
            rep.add("router", "WAN in the state file", PASS, wan)
    except Exception as e:
        rep.add("router", "LAN client simulation", FAIL, str(e)[:160])
    finally:
        _cleanup_ns(ns)
        shutil.rmtree(tmp, ignore_errors=True)


def _router_ipv6(rep: Report, cfg, ns: str, details: Dict[str, Any]) -> None:
    """IPv6 for the LAN (nmb/netd/ipv6_lan.py): the delegated prefix on br-lan, a SLAAC address on the
    simulated client from the box's router advert, and HTTPS over IPv6 from it. No address is printed."""
    v6 = details.get("ipv6_lan") or {}
    if not getattr(cfg.network, "lan_ipv6", True):
        rep.add("router", "IPv6 for the LAN", SKIP, "turned off ([network] lan_ipv6)")
        return
    wan = details.get("wan_interface") or ""
    wan_v6 = [a for a in __import__("nmb.netd.interfaces", fromlist=["x"]).get_ip_addresses(wan)
              if ":" in a and not a.lower().startswith(("fe80", "fd", "fc"))] if wan else []
    if wan != "ppp0":
        rep.add("router", "IPv6 for the LAN", SKIP, f"only on a PPPoE WAN (WAN is {wan or 'none'})")
        return
    rep.add("router", "box's own IPv6 on the WAN", PASS if wan_v6 else FAIL,
            "public address from the ISP's router advert" if wan_v6 else "none (accept_ra on ppp0?)")
    rep.add("router", "delegated prefix on the LAN", PASS if v6.get("prefixes") else FAIL,
            f"{v6.get('prefixes', 0)} prefix(es); dhcpcd {'running' if v6.get('dhcpcd_running') else 'not running'}")
    if not v6.get("prefixes"):
        return
    run(["sysctl", "-w", "net.ipv6.conf.all.accept_ra=1"], ns=ns)
    addr = ""
    for _ in range(20):
        out = run(["ip", "-6", "-o", "addr", "show", "scope", "global"], ns=ns).stdout
        # usable only once DAD is over and the advert's default route is in
        ready = [l for l in out.splitlines() if "tentative" not in l]
        if ready and "default" in run(["ip", "-6", "route", "show", "default"], ns=ns).stdout:
            addr = "\n".join(ready)
            break
        time.sleep(1)
    rep.add("router", "LAN client gets IPv6 (SLAAC)", PASS if addr else FAIL,
            "address from the box's router advert" if addr else "no address in 20 s")
    if not addr:
        return
    c6 = run(["curl", "-6", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}",
              "https://www.cloudflare.com/cdn-cgi/trace"], ns=ns, timeout=15).stdout.strip()
    rep.add("router", "LAN client HTTPS over IPv6", PASS if c6 == "200" else FAIL, f"HTTP {c6 or 'none'}")


_NATPMP_CLIENT = r"""
import socket, struct, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
gw, inner, ext, life = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
try:
    s.sendto(struct.pack("!BBHHHI", 0, 2, 0, inner, ext, life), (gw, 5351))
    d = s.recvfrom(64)[0]
    print(struct.unpack("!BBHIHHI", d[:16])[2], struct.unpack("!BBHIHHI", d[:16])[5])
except socket.timeout:
    print("timeout")
"""


_TEST_WEB_SERVER = (
    "import functools, http.server, socketserver, sys\n"
    "socketserver.TCPServer.allow_reuse_address = True\n"
    "h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=sys.argv[2])\n"
    "socketserver.TCPServer((sys.argv[1], 8000), h).serve_forever()\n"
)


def _api_json(method: str, path: str, body: Optional[dict] = None) -> Dict[str, Any]:
    res = _cli("api", method, path, *( [json.dumps(body)] if body is not None else []), timeout=60)
    try:
        return json.loads(res.stdout)
    except ValueError:
        return {"status": "error", "message": (res.stderr or res.stdout)[:200]}


def g_portfwd(rep: Report, cfg) -> None:
    """Port forwarding and UPnP in router mode, on the box itself: a LAN device in a namespace with a small web
    server, a temporary rule, the DNAT and hairpin path from a second LAN device, and a NAT-PMP mapping.
    The owner's settings are put back at the end. Reaching the port from the internet needs a host outside
    (see docs/TESTING.md, done by hand on 2026-11-09)."""
    state = _netd_state()
    if state.get("active_mode") != "mode_a":
        rep.add("portfwd", "router mode", SKIP, f"the box is in {state.get('active_mode')} mode")
        return
    wan = (state.get("details") or {}).get("wan_interface") or ""
    from nmb.netd import interfaces
    wan_ip = next((a.split("/")[0] for a in interfaces.get_ip_addresses(wan) if ":" not in a), "")
    if not wan_ip:
        rep.add("portfwd", "WAN address", FAIL, f"{wan or 'no WAN'} has no IPv4 address")
        return
    before = _api_json("GET", "/api/port-forward")
    if "rules" not in before:
        rep.add("portfwd", "settings", FAIL, before.get("message", "no answer from the Web API"))
        return
    gw = str(cfg.network.gateway_ip)
    lan_net = before.get("lan", "192.168.100.0/24")
    import ipaddress
    hosts = list(ipaddress.IPv4Network(lan_net).hosts())
    dev_ip, peer_ip = str(hosts[-4]), str(hosts[-3])            # .250 and .251 on a /24, outside the DHCP range
    used = {int(p) for r in before["rules"] for p in str(r.get("ext", "")).split("-") if p.isdigit()}
    ext = next(p for p in range(18081, 18100) if p not in used)
    token = f"nmb-portfwd-{os.getpid()}"
    dev, peer = f"{NS_PREFIX}pf", f"{NS_PREFIX}pp"
    tmp = Path(tempfile.mkdtemp(prefix="nmbst"))
    server = None
    try:
        for ns, ip in ((dev, dev_ip), (peer, peer_ip)):
            _cleanup_ns(ns)
            run(["ip", "netns", "add", ns], check=True)
            run(["ip", "link", "add", f"{ns}a", "type", "veth", "peer", "name", f"{ns}b"], check=True)
            run(["ip", "link", "set", f"{ns}a", "master", "br-lan"], check=True)
            run(["ip", "link", "set", f"{ns}a", "up"], check=True)
            run(["ip", "link", "set", f"{ns}b", "netns", ns], check=True)
            run(["ip", "link", "set", "lo", "up"], ns=ns)
            run(["ip", "link", "set", f"{ns}b", "up"], ns=ns, check=True)
            run(["ip", "addr", "add", f"{ip}/{ipaddress.IPv4Network(lan_net).prefixlen}", "dev", f"{ns}b"], ns=ns, check=True)
            run(["ip", "route", "add", "default", "via", gw], ns=ns, check=True)
        reach = all(run(["ping", "-c", "1", "-W", "2", gw], ns=ns, timeout=5).returncode == 0 for ns in (dev, peer))
        rep.add("portfwd", "test LAN devices reach the box", PASS if reach else FAIL,
                "on br-lan" if reach else "no answer from the gateway (router mode still starting?)")
        if not reach:
            return
        (tmp / "index.html").write_text(token)
        # socketserver, not http.server: HTTPServer looks up its own name (reverse DNS of a private address),
        # which took 5-30 s from the namespace (2026-11-09) and made the test fail.
        server = subprocess.Popen(["ip", "netns", "exec", dev, "python3", "-c", _TEST_WEB_SERVER, dev_ip, str(tmp)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        up = False
        for _ in range(20):
            if run(["curl", "-s", "-m", "2", f"http://{dev_ip}:8000/"], ns=peer, timeout=5).stdout.strip() == token:
                up = True
                break
            time.sleep(0.5)
        rep.add("portfwd", "test web server on the LAN device", PASS if up else FAIL, "answers on the LAN" if up else "did not start")
        if not up:
            return
        test_rule = {"name": "nmb-selftest", "proto": "tcp", "ext": str(ext), "ip": dev_ip, "port": 8000, "on": True}
        res = _api_json("POST", "/api/port-forward/save", {"enabled": True, "rules": before["rules"] + [test_rule]})
        rep.add("portfwd", "temporary rule saved", PASS if res.get("status") == "ok" else FAIL, res.get("message", "")[:120])
        dnat = f"dport {ext} dnat ip to {dev_ip}:8000"
        ok = False
        for _ in range(20):
            if dnat in run(["nft", "list", "table", "inet", "nmb_nat"]).stdout:
                ok = True
                break
            time.sleep(1)
        rep.add("portfwd", "DNAT rule in the router firewall", PASS if ok else FAIL, f"TCP {ext} on {wan}" if ok else "not applied in 20 s")
        got = run(["curl", "-s", "-m", "8", f"http://{wan_ip}:{ext}/"], ns=peer, timeout=12).stdout.strip()
        rep.add("portfwd", "hairpin: a LAN device reaches the forwarded port", PASS if got == token else FAIL,
                "via the line's own address" if got == token else "no answer")
        if before.get("upnp_installed"):
            _api_json("POST", "/api/port-forward/save", {"upnp": True})
            running = False
            for _ in range(25):
                if run(["pgrep", "-x", "miniupnpd"]).returncode == 0:
                    running = True
                    break
                time.sleep(1)
            rep.add("portfwd", "UPnP service starts", PASS if running else FAIL, "miniupnpd" if running else "not running in 25 s")
            if running:
                time.sleep(2)
                script = tmp / "natpmp.py"
                script.write_text(_NATPMP_CLIENT)
                out = run(["python3", str(script), gw, "8000", str(ext + 10), "120"], ns=dev, timeout=10).stdout.split()
                mapped = bool(out) and out[0] == "0"
                rep.add("portfwd", "NAT-PMP mapping from a LAN device", PASS if mapped else FAIL,
                        f"TCP {ext + 10}" if mapped else f"answer {' '.join(out) or 'none'}")
                low = run(["python3", str(script), gw, "22", "22", "120"], ns=dev, timeout=10).stdout.split()
                refused = bool(low) and low[0].isdigit() and low[0] != "0"   # an answer, and not "success"
                rep.add("portfwd", "UPnP refuses ports below 1024", PASS if refused else FAIL,
                        f"result {low[0] if low else 'none'}")
                if mapped:
                    run(["python3", str(script), gw, "8000", "0", "0"], ns=dev, timeout=10)
        else:
            rep.add("portfwd", "UPnP service", SKIP, "miniupnpd is not installed")
    except Exception as e:
        rep.add("portfwd", "port forwarding test", FAIL, f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        back = _api_json("POST", "/api/port-forward/save",
                         {"enabled": before.get("enabled", False), "upnp": before.get("upnp", False), "rules": before.get("rules", [])})
        if server is not None:
            server.terminate()
        for ns in (dev, peer):
            _cleanup_ns(ns)
        shutil.rmtree(tmp, ignore_errors=True)
        rep.add("portfwd", "owner's settings put back", PASS if back.get("status") == "ok" else FAIL,
                f"forwarding {'on' if before.get('enabled') else 'off'}, UPnP {'on' if before.get('upnp') else 'off'}, "
                f"{len(before.get('rules', []))} rule(s)")


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


def _pppd_remote_message(since: float) -> str:
    """The last message the PPP peer sent with a refusal ("Remote message: ..." in pppd's log)."""
    out = run(["journalctl", "-t", "pppd", "--since", f"@{int(since)}", "-o", "cat", "--no-pager"], timeout=10).stdout
    msgs = re.findall(r"Remote message:\s*(.*)", out)
    return msgs[-1].replace("^J", " ").strip()[:120] if msgs else ""


def _pppd_in_ns(ns: str, iface: str, user: str, password: str, linkname: str, timeout: float = 25.0,
                while_up: Optional[Callable[[], None]] = None, service: str = "",
                info: Optional[dict] = None) -> Tuple[bool, str]:
    """Dial PPPoE with NMB's own pppd command inside a namespace; True when ppp got an address.

    One attempt only (maxfail 1): a wrong password is not sent again and again, since an ISP may stop
    answering a port after several refused logins (2026-11-09: 5 in 40 s, then no PADO for a minute).
    info, when given, gets pppd's exit code as "rc" (None while it was still dialing)."""
    import types
    from nmb.netd.services import PPPD_EXIT_TEXT, build_pppd_cmd
    pppd = shutil.which("pppd") or "/usr/sbin/pppd"
    opts = Path(tempfile.mkdtemp(prefix="nmbst-ppp")) / "options"
    cfg = types.SimpleNamespace(pppoe_user=user, pppoe_password=password, pppoe_service_name=service)
    # No usepeerdns: Debian's hook would put the ISP's DNS into the box's own /etc/resolv.conf for as long
    # as the test link is up (seen 2026-11-09), and from outside the namespace those servers are unreachable.
    cmd = ["ip", "netns", "exec", ns] + build_pppd_cmd(pppd, cfg, iface, opts, linkname=linkname, maxfail=1,
                                                        peer_dns=False)
    started = time.time()
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
        if addr and while_up:
            while_up()   # checks that need the link, before it is hung up
        rc = proc.poll()
        if info is not None:
            info["rc"] = rc
        if addr:
            return True, addr
        detail = "no PPP address"
        if rc is not None and rc in PPPD_EXIT_TEXT:
            detail += f": {PPPD_EXIT_TEXT[rc]}"
        msg = _pppd_remote_message(started)
        if msg:
            detail += f"; the ISP said '{msg}'"
        return False, detail
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
            pinged = []
            ok, detail = _pppd_in_ns(cli, f"{NS_PREFIX}pb", "nmbtest", "Right-Pass-77", "nmbst-ok",
                                     while_up=lambda: pinged.append(run(["ping", "-c", "2", "-W", "2", "10.77.0.1"], ns=cli, timeout=10).returncode == 0))
            rep.add("pppoe", "dial with the right password (simulated line)", PASS if ok else FAIL, detail)
            if ok:
                rep.add("pppoe", "traffic over the PPP link", PASS if pinged and pinged[0] else FAIL, "ping to the server")
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
        disc = run(["pppoe-discovery", "-I", mv, "-a", "3", "-t", "3"], ns=ns, timeout=25)
        acs = re.findall(r"Access-Concentrator:\s*(.+)", disc.stdout)
        services = sorted(set(s.strip() for s in re.findall(r"Service-Name:\s*(.*)", disc.stdout)))
        found = bool(acs)
        rep.add("pppoe", f"PPPoE server answers on {wan}", PASS if found else FAIL,
                f"concentrator {', '.join(a.strip() for a in acs[:2])}; service names {services or ['(none)']}" if found
                else "none: the WAN port must be on the ONT or modem, not behind a router")
        want = str(getattr(net, "pppoe_service_name", "") or "").strip()
        if found and want:
            ok_name = want in services or not services or services == [""]
            rep.add("pppoe", "saved service name is offered", PASS if ok_name else WARN,
                    f"'{want}'" + ("" if ok_name else f" not among {services}: dialing would fail; clear it or use one of these"))
        if found:
            from nmb.netd.services import kernel_pppoe_plugin
            rep.add("pppoe", "kernel PPPoE", PASS if kernel_pppoe_plugin() else WARN,
                    kernel_pppoe_plugin() or "user-space pppoe only: slower than the line on a Pi")
            pinged = []

            def check() -> None:
                # pppd sets the default route just after the address, and the ISP may drop the first
                # packets of a new session (2026-11-09: 3 pings in the first 3 s went unanswered).
                t_up = time.time()
                for _ in range(10):
                    if "default" in run(["ip", "-4", "route", "show", "default"], ns=ns).stdout:
                        break
                    time.sleep(0.5)
                first = None
                while time.time() - t_up < 20:
                    if run(["ping", "-n", "-c", "1", "-W", "2", "1.1.1.1"], ns=ns, timeout=5).returncode == 0:
                        first = time.time() - t_up
                        break
                    time.sleep(1)
                pinged.append(first)
                pinged.append(run(["cat", "/sys/class/net/ppp0/mtu"], ns=ns).stdout.strip())
                # HTTPS through the line: a full-size TLS handshake also shows MTU trouble.
                web = run(["curl", "-4", "-s", "-o", "/dev/null", "-m", "10", "-w", "%{http_code}",
                           "https://1.1.1.1/cdn-cgi/trace"], ns=ns, timeout=15).stdout.strip()
                pinged.append(web)
                # IPv6 from the ISP: a global address from a router advertisement on the PPP link.
                v6 = ""
                for _ in range(8):
                    v6 = run(["ip", "-6", "-o", "addr", "show", "dev", "ppp0", "scope", "global"], ns=ns).stdout
                    if v6.strip():
                        break
                    time.sleep(1)
                pinged.append(bool(v6.strip()))
            from nmb.netd.services import PPPD_EXIT_AUTH
            info: dict = {}
            ok, detail = _pppd_in_ns(ns, mv, net.pppoe_user, net.pppoe_password, "nmbst-real", timeout=45,
                                     while_up=check, service=want, info=info)
            refused = info.get("rc") == PPPD_EXIT_AUTH
            # A refused login means the service name was accepted: dialing again would only send the
            # wrong password once more.
            if not ok and want and not refused:
                ok, detail = _pppd_in_ns(ns, mv, net.pppoe_user, net.pppoe_password, "nmbst-real2", timeout=45,
                                         while_up=check, service="", info=info)
                refused = info.get("rc") == PPPD_EXIT_AUTH
                if ok:
                    rep.add("pppoe", "dial with the saved service name", WARN, f"failed with '{want}', works without it")
            hint = (" (retype the user name and password exactly as the ISP gave them, e.g. from the old router)"
                    if refused else " (check the user name and password, or the ISP's session limit)")
            rep.add("pppoe", "dial the real line with the saved credentials", PASS if ok else FAIL,
                    "connected" if ok else detail + hint)
            if ok and len(pinged) >= 4:   # the address is the public one: never printed
                first, mtu, web, v6 = pinged[:4]
                rep.add("pppoe", "internet over PPPoE", PASS if first is not None else FAIL,
                        (f"ping 1.1.1.1 answered {first:.1f} s after the link came up" if first is not None
                         else "no ping answer in 20 s") + f"; ppp MTU {mtu}")
                rep.add("pppoe", "HTTPS over PPPoE", PASS if web == "200" else FAIL, f"https://1.1.1.1 HTTP {web or 'none'}")
                rep.add("pppoe", "IPv6 from the ISP on PPPoE", PASS if v6 else WARN,
                        "global address from a router advertisement" if v6 else
                        "no global address from an RA in 8 s (the ISP may hand out IPv6 only by DHCPv6-PD)")
    except Exception as e:
        rep.add("pppoe", "real line", FAIL, f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        run(["ip", "netns", "del", ns])


def g_dyndns(rep: Report, cfg) -> None:
    """DynDNS (DuckDNS, dynv6): set up, updated recently, and the name points at this line (no address printed)."""
    d = getattr(cfg, "duckdns", None)
    if not d or not d.enabled:
        rep.add("dyndns", "DynDNS", SKIP, "turned off")
        return
    rep.add("dyndns", "domain and token set", PASS if d.domain and d.token else FAIL,
            "set" if d.domain and d.token else "missing: " + " and ".join(n for n, v in (("domain", d.domain), ("token", d.token)) if not v))
    res = _cli("api", "GET", "/api/dyndns/status")
    try:
        st = json.loads(res.stdout)
    except Exception:
        rep.add("dyndns", "status", FAIL, (res.stderr or res.stdout)[:100])
        return
    age = time.time() - float(st.get("last_update_ts") or 0)
    limit = 2 * 60 * int(getattr(d, "update_interval_min", 10) or 10) + 120
    ok = st.get("last_status") == "OK" and age < limit
    rep.add("dyndns", "updated recently", PASS if ok else FAIL,
            f"last {st.get('last_status')} {int(age // 60)} min ago" if st.get("last_update_ts") else f"never: {st.get('last_message') or st.get('last_status')}")
    fqdn = st.get("fqdn") or d.domain

    def doh(rtype: str) -> List[str]:
        # Public DNS over HTTPS: the home router's resolver may cache an old answer (2026-11-09: it did).
        out = run(["curl", "-s", "-m", "8", "-H", "accept: application/dns-json",
                   f"https://dns.google/resolve?name={fqdn}&type={rtype}"], timeout=12).stdout
        try:
            return [a["data"] for a in json.loads(out).get("Answer", []) if a.get("type") in (1, 28)]
        except Exception:
            return []
    trace = run(["curl", "-4", "-s", "-m", "10", "https://www.cloudflare.com/cdn-cgi/trace"], timeout=15).stdout
    mine = next((ln[3:] for ln in trace.splitlines() if ln.startswith("ip=")), "")
    a = doh("A")
    rep.add("dyndns", "name points at this line (IPv4, public DNS)", PASS if mine and mine in a else FAIL,
            "matches the current public address" if mine in a else ("no A record" if not a else "points elsewhere"))
    aaaa = doh("AAAA")
    has_v6 = run(["curl", "-6", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
                  "https://www.cloudflare.com/cdn-cgi/trace"], timeout=12).stdout.strip() == "200"
    if aaaa and not has_v6:
        rep.add("dyndns", "IPv6 record", WARN, "the name has an AAAA record, but this line has no IPv6: clients trying IPv6 first fail")
    else:
        rep.add("dyndns", "IPv6 record", PASS, "line has IPv6" if has_v6 else "no IPv6 on this line and no AAAA record")


def router_advert(iface: str, wait: float = 12.0) -> Optional[Dict[str, Any]]:
    """Ask the LAN's IPv6 router (router solicitation) and read its advertisement (root).

    Returns {"lifetime": s, "managed": bool, "other": bool, "prefixes": [(len, autonomous)]}, or None
    when no router answered. 2026-11-09: the home router answered with lifetime 0 and no prefix, so no
    device on the LAN could get IPv6 although the line has it.
    """
    import socket
    import struct
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6)
    except OSError:
        return None
    try:
        s.setsockopt(socket.SOL_SOCKET, 25, iface.encode())   # SO_BINDTODEVICE
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 255)
        s.sendto(bytes([133, 0, 0, 0, 0, 0, 0, 0]), ("ff02::2", 0, 0, socket.if_nametoindex(iface)))
        s.settimeout(1)
        t0 = time.time()
        while time.time() - t0 < wait:
            try:
                data, _ = s.recvfrom(2048)
            except socket.timeout:
                continue
            if not data or data[0] != 134 or len(data) < 16:
                continue
            opts, prefixes = data[16:], []
            while len(opts) >= 8 and opts[1]:
                if opts[0] == 3 and len(opts) >= 32:
                    prefixes.append((opts[2], bool(opts[3] & 0x40)))
                opts = opts[opts[1] * 8:]
            return {"lifetime": struct.unpack("!H", data[6:8])[0], "managed": bool(data[5] & 0x80),
                    "other": bool(data[5] & 0x40), "prefixes": prefixes}
        return None
    except OSError:
        return None
    finally:
        s.close()


def g_ipv6(rep: Report, cfg) -> None:
    """IPv6 on the line: the LAN router's advertisement, the box's address and route, and real traffic."""
    details = _netd_state().get("details", {}) or {}
    # Router mode names its WAN (ppp0 on PPPoE); the other modes the port the box measures on.
    wan = details.get("wan_interface") or details.get("interface") or getattr(cfg.network, "wan_interface", "eth0")
    ra = router_advert(wan)
    learned = run(["ip", "-6", "route", "show", "default", "dev", wan, "proto", "ra"]).stdout.strip()
    if ra is None and learned:
        # A PPPoE concentrator may advertise only when the session starts and ignore a solicitation later
        # (DIGI, 2026-11-09): the route it advertised then is the proof.
        rep.add("ipv6", f"IPv6 router on {wan}", PASS, "no answer to a solicitation now; the default route came from its advert")
    elif ra is None:
        rep.add("ipv6", f"IPv6 router on {wan}", WARN, "no router advertisement: the network has no IPv6")
    else:
        usable = ra["lifetime"] > 0 and any(a for _, a in ra["prefixes"])
        detail = (f"router lifetime {ra['lifetime']} s, prefixes {[f'/{l}' for l, _ in ra['prefixes']] or 'none'}, "
                  f"DHCPv6 {'yes' if ra['managed'] else 'no'}")
        if not usable:
            detail += (": the router gives the LAN no IPv6 (no prefix or not a default router); "
                       "turn on IPv6 for the LAN on the router (SLAAC or DHCPv6, with prefix delegation from the ISP)")
        rep.add("ipv6", f"IPv6 router on {wan}", PASS if usable else FAIL, detail)
    from nmb.netd import interfaces
    glob = [a for a in interfaces.get_ip_addresses(wan) if ":" in a and not a.lower().startswith(("fe80", "fd", "fc"))]
    rep.add("ipv6", f"public IPv6 address on {wan}", PASS if glob else FAIL, f"{len(glob)} address(es)")
    route = run(["ip", "-6", "route", "show", "default"]).stdout.strip()
    rep.add("ipv6", "IPv6 default route", PASS if route else FAIL, "present" if route else "none")
    ok = run(["curl", "-6", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
              "https://www.cloudflare.com/cdn-cgi/trace"], timeout=12).stdout.strip() == "200"
    rep.add("ipv6", "HTTPS over IPv6", PASS if ok else FAIL, "works" if ok else "no IPv6 internet")


def g_mode(rep: Report, cfg) -> None:
    """The running network mode fits the setting and the network (automatic mode included)."""
    st = _netd_state()
    active, configured = st.get("active_mode"), st.get("configured_mode") or cfg.network.mode
    try:
        conn = _db()
        row = conn.execute("SELECT v FROM kv WHERE k = 'override_mode'").fetchone()
        conn.close()
        override = row[0] if row else None
    except Exception:
        override = None
    rep.add("mode", "network mode", PASS if active else FAIL,
            f"running {active}, configured {configured}" + (f", override {override}" if override and override != "auto" else ""))
    wanted = override if override in ("mode_a", "mode_b", "standalone") else (configured if configured != "auto" else None)
    d = st.get("auto_decision") or {}
    if wanted:
        rep.add("mode", "running mode is the set one", PASS if active == wanted else WARN,
                "" if active == wanted else f"set {wanted}, running {active} (a switch may be pending)")
    elif configured == "auto":
        rep.add("mode", "automatic decision", PASS if d.get("mode") == active else WARN,
                f"{d.get('mode')}: {d.get('reason') or 'no decision yet'}")
    ap = run(["pgrep", "-x", "hostapd"]).returncode == 0
    if active != "mode_a":
        rep.add("mode", "no access point outside router mode", PASS if not ap else FAIL,
                "" if not ap else "hostapd runs: the radio should be a Wi-Fi client here")
        dev = (st.get("details") or {}).get("interface") or cfg.network.wan_interface
        from nmb.netd import interfaces
        lease = [a for a in interfaces.get_ip_addresses(dev) if ":" not in a and not a.startswith("169.254.")]
        if interfaces.get_carrier(cfg.network.wan_interface):
            rep.add("mode", f"address from the router on {dev}", PASS if lease else FAIL, "yes" if lease else "none")
    else:
        dhcp = run(["pgrep", "-f", "dnsmasq --conf-file=/run/nmb/dnsmasq.conf"]).returncode == 0
        rep.add("mode", "router mode serves its LAN", PASS if dhcp else FAIL, "DHCP running" if dhcp else "no DHCP server")
        if configured == "auto" and not override:
            from nmb.netd.wifi_share import probe_dhcp_servers
            from nmb.netd import interfaces
            wan = cfg.network.wan_interface
            if interfaces.get_carrier(wan):
                found = [s for s in probe_dhcp_servers(wan, timeout=5) if s != cfg.network.gateway_ip]
                rep.add("mode", "no router on the WAN port in automatic router mode", PASS if not found else FAIL,
                        "none answered" if not found else f"{', '.join(found)} answers: should be standalone")


SPEED_HOURS = 24


def g_speed(rep: Report, cfg, hours: Optional[int] = None) -> None:
    hours = hours or SPEED_HOURS
    conn = _db()
    since = int((time.time() - hours * 3600) * 1000)
    rep.add("speed", "window", PASS, f"tests of the last {hours} h (--speed-hours)")
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
        vht = {"1": "80", "2": "160", "3": "80+80"}.get(conf.get("vht_oper_chwidth", ""), "")
        width = vht or ("40" if wide else "20")
        std = "802.11ac" if conf.get("ieee80211ac") == "1" else ("802.11n" if conf.get("ieee80211n") == "1" else "")
        rep.add("wifi-ap", "channel width fits the radio", PASS, f"{band}, {width} MHz{', ' + std if std else ''}")
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
    "services": g_services, "mode": g_mode, "internet": g_internet, "config": g_config, "web": g_web, "cli": g_cli,
    "usb": g_usb, "router": g_router, "dhcp-probe": g_dhcp_probe, "speed": g_speed, "wifi-ap": g_wifi_ap,
    "collector": g_collector, "telegram": g_telegram, "pppoe": g_pppoe, "dyndns": g_dyndns, "ipv6": g_ipv6,
    "portfwd": g_portfwd,
}
QUICK = [g for g in GROUPS if g not in ("telegram", "portfwd")]   # portfwd changes settings for a minute: --full or by name


def prune_reports(keep: int = 30, folder: Optional[Path] = None) -> int:
    """Keep the newest `keep` self-test and scenario reports of each kind; older ones are deleted."""
    folder = folder or LOG_DIR
    removed = 0
    for pattern in ("selftest-2*.json", "scenario-*-2*.json"):
        files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def to_markdown(rep: Report, groups: List[str]) -> str:
    """The report as a Markdown table. Details never hold secrets or public addresses (see the checks)."""
    c = rep.counts()
    head = (f"# nmb-selftest {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Groups: {', '.join(groups)}. **{c[PASS]} passed, {c[WARN]} warnings, {c[FAIL]} failed, {c[SKIP]} skipped.**\n\n"
            "| | Group | Check | Detail |\n|---|---|---|---|\n")
    icon = {PASS: "✅", WARN: "⚠️", FAIL: "❌", SKIP: "—"}
    esc = lambda t: str(t).replace("|", "\\|").replace("\n", " ")
    return head + "".join(f"| {icon[r['status']]} | {r['group']} | {esc(r['check'])} | {esc(r['detail'])} |\n" for r in rep.rows)


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
    from nmb.selftest import scenario_auto, scenario_pppoe, scenario_router
    p.add_argument("name", choices=["usb", "router", "auto", "pppoe"])
    p.add_argument("--steps", default=None, help="Comma-separated. usb: " + ", ".join(scenario.STEPS)
                   + "; router: " + ", ".join(scenario_router.STEPS)
                   + "; auto: " + ", ".join(scenario_auto.STEPS)
                   + "; pppoe: " + ", ".join(scenario_pppoe.STEPS))
    p.add_argument("--plan", action="store_true", help="Only print the steps")
    args = p.parse_args(argv)
    mod = {"router": scenario_router, "auto": scenario_auto, "pppoe": scenario_pppoe}.get(args.name, scenario)
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
    if args.name == "auto":
        return scenario_auto.run_auto(steps)
    if args.name == "pppoe":
        return scenario_pppoe.run_pppoe(steps)
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
    p.add_argument("--speed-hours", type=int, default=24, help="speed group: look at this many hours (default 24)")
    p.add_argument("--md", default="", help="Also write a Markdown report here (to paste into an issue or a chat)")
    p.add_argument("--json", default="", help="Write the report here (default: /var/log/nmb/selftest-<time>.json)")
    args = p.parse_args(argv)
    unknown = [g for g in args.groups if g not in GROUPS]
    if unknown:
        p.error("unknown group(s): " + ", ".join(unknown))
    groups = args.groups or (list(GROUPS) if args.full else QUICK)
    if os.geteuid() != 0:
        print("Run as root: the checks build throwaway network namespaces.", file=sys.stderr)
        return 2
    global SPEED_HOURS
    SPEED_HOURS = max(1, args.speed_hours)
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
    bad = [r for r in rep.rows if r["status"] in (FAIL, WARN)]
    if bad:
        print("\nTo look at:")
        for r in bad:
            print(f"  {r['status']:<4} {r['group']}/{r['check']}: {r['detail']}")
    print(f"\n{c[PASS]} passed, {c[WARN]} warnings, {c[FAIL]} failed, {c[SKIP]} skipped")
    if args.md:
        try:
            Path(args.md).write_text(to_markdown(rep, groups), encoding="utf-8")
            print(f"markdown: {args.md}")
        except OSError as e:
            print(f"could not write the markdown report: {e}", file=sys.stderr)
    out = Path(args.json) if args.json else LOG_DIR / time.strftime("selftest-%Y%m%d-%H%M%S.json")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"ts": int(time.time()), "groups": groups, "counts": c, "results": rep.rows}, indent=1))
        print(f"report: {out}")
        prune_reports()
    except OSError as e:
        print(f"could not write the report: {e}", file=sys.stderr)
    return 1 if c[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
