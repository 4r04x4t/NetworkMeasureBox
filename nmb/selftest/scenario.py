"""Guided live scenario with USB tethering: the parts that need a person moving cables.

`nmb-selftest scenario usb` runs as a service on the box (the box's link changes during the run,
so it must not depend on an SSH session). Each step either checks by itself, or tells the person
what to do and waits until the box sees it happen (a cable out, a cable in, a client on Wi-Fi).
The current instruction is in /run/nmb/scenario.json and in the log.

Steps (all with a USB phone, hotspot or modem plugged in and turned on):
  usb-speed   Speed tests bound to USB: every engine stores bound_iface = USB, the bytes really
              crossed the USB interface, and the USB data counter grew.
  wifi-share  The box's cable moves from the home router to a laptop: the laptop gets an address
              from the box (Wi-Fi shared on the LAN port) and its traffic leaves over Wi-Fi.
  usb-fallback The box leaves its Wi-Fi network: USB becomes the internet (metric 900, event),
              the laptop on the port now gets the USB internet, and an automatic speed test
              goes over USB.
  router      Router mode with USB as the WAN: the port and the Wi-Fi access point share the USB
              internet; a simulated client, the laptop on the cable and a device on the box's
              Wi-Fi all reach the internet.
  guard       The cable moves from the laptop to the home router: the box must stop its DHCP within
              90 seconds and take the port as its WAN again.
  restore     Everything back as it was; the USB fallback ends when the box's own internet returns.
  unplug      (optional) The USB device is unplugged: no USB route or rule is left behind.

Safety: the settings changed here are written down first, a separate restore service puts them back
after 45 minutes whatever happens, and the scenario restores them itself at the end or on an error.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nmb.selftest import live
from nmb.selftest.live import FAIL, PASS, SKIP, WARN, Report

STATUS_FILE = Path("/run/nmb/scenario.json")
SNAPSHOT = Path("/var/lib/nmb/scenario-restore.json")
LOG = live.LOG_DIR / "scenario-usb.log"
COUNT_TABLE = "nmbst_count"
WATCHDOG_UNIT = "nmb-scenario-restore"
STEPS = ["usb-speed", "wifi-share", "usb-fallback", "router", "guard", "restore", "unplug"]
SPEED_ENGINES = ["cloudflare", "fastcom", "rtr", "iperf3", "ookla"]


def _now_ms() -> int:
    return int(time.time() * 1000)


class Scenario:
    def __init__(self, rep: Report, cfg, wait_scale: float = 1.0) -> None:
        self.rep = rep
        self.cfg = cfg
        self.scale = wait_scale
        self.usb: Optional[str] = None
        self.step = ""
        self.shared = False   # the laptop got an address from Wi-Fi sharing

    # ---- status for the person (and for whoever relays the instructions) ----
    def say(self, instruction: str, waiting: bool = True) -> None:
        line = f"{time.strftime('%H:%M:%S')} [{self.step}] {'>>> ' if waiting else ''}{instruction}"
        print(line, flush=True)
        try:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(json.dumps({"step": self.step, "instruction": instruction if waiting else "",
                                               "note": "" if waiting else instruction, "since": int(time.time()),
                                               "results": self.rep.counts()}))
        except OSError:
            pass

    def wait(self, what: str, cond: Callable[[], bool], timeout: float, every: float = 2.0) -> Optional[float]:
        """Seconds until cond() held, or None after the timeout."""
        t0 = time.monotonic()
        limit = timeout * self.scale
        while time.monotonic() - t0 < limit:
            try:
                if cond():
                    return time.monotonic() - t0
            except Exception:
                pass
            time.sleep(every)
        self.rep.add(self.step, f"waited for: {what}", FAIL, f"not within {int(limit)} s")
        return None

    # ---- system helpers ----
    @staticmethod
    def carrier(iface: str) -> bool:
        try:
            return Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
        except OSError:
            return False

    @staticmethod
    def counter(iface: str, which: str) -> int:
        try:
            return int(Path(f"/sys/class/net/{iface}/statistics/{which}_bytes").read_text())
        except (OSError, ValueError):
            return 0

    @staticmethod
    def netd_log_since(ts: float, pattern: str) -> bool:
        out = live.run(["journalctl", "-u", "nmb-netd", "--since", f"@{int(ts)}", "--no-pager", "-o", "cat"], timeout=20).stdout
        return re.search(pattern, out) is not None

    @staticmethod
    def event_since(kind: str, ts_ms: int) -> bool:
        conn = live._db()
        try:
            return conn.execute("SELECT COUNT(*) FROM event WHERE kind = ? AND ts >= ?", (kind, ts_ms)).fetchone()[0] > 0
        finally:
            conn.close()

    @staticmethod
    def api(method: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        res = live._cli("api", method, path, json.dumps(body), timeout=60)
        try:
            return json.loads(res.stdout)
        except Exception:
            return {"status": "error", "message": (res.stderr or res.stdout)[:200]}

    @staticmethod
    def internet(src_dev: str = "") -> bool:
        """HTTPS works (from src_dev's address when given); three tries, as a link may just be settling."""
        cmd = ["curl", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}"]
        if src_dev:
            from nmb.netd import interfaces
            addrs = [a.split("/")[0] for a in interfaces.get_ip_addresses(src_dev) if ":" not in a]
            if not addrs:
                return False
            cmd += ["--interface", addrs[0]]   # by source address: the policy rules route it out of src_dev
        for _ in range(3):
            if live.run(cmd + ["https://www.cloudflare.com/cdn-cgi/trace"], timeout=15).stdout.strip() == "200":
                return True
            time.sleep(3)
        return False

    # forwarded traffic of the clients, counted in a throwaway nftables table
    def count_start(self, saddr: str, oif: str) -> None:
        live.run(["nft", "delete", "table", "inet", COUNT_TABLE])
        live.run(["nft", "add", "table", "inet", COUNT_TABLE], check=True)
        live.run(["nft", "add", "chain", "inet", COUNT_TABLE, "cnt",
                  "{ type filter hook forward priority -5; policy accept; }"], check=True)
        live.run(["nft", "add", "rule", "inet", COUNT_TABLE, "cnt", "ip", "saddr", saddr, "oifname", oif, "counter"], check=True)

    def count_start_input(self, saddr: str, dport: int) -> None:
        """Count packets from saddr to the box itself on TCP dport (for example the Web UI)."""
        live.run(["nft", "delete", "table", "inet", COUNT_TABLE])
        live.run(["nft", "add", "table", "inet", COUNT_TABLE], check=True)
        live.run(["nft", "add", "chain", "inet", COUNT_TABLE, "cnt",
                  "{ type filter hook input priority -5; policy accept; }"], check=True)
        live.run(["nft", "add", "rule", "inet", COUNT_TABLE, "cnt", "ip", "saddr", saddr, "tcp", "dport", str(dport), "counter"],
                 check=True)

    @staticmethod
    def count_packets() -> int:
        out = live.run(["nft", "list", "table", "inet", COUNT_TABLE]).stdout
        m = re.search(r"counter packets (\d+)", out)
        return int(m.group(1)) if m else 0

    @staticmethod
    def count_stop() -> None:
        live.run(["nft", "delete", "table", "inet", COUNT_TABLE])

    @staticmethod
    def acks_since(ts: float, iface: str, prefix: str) -> List[str]:
        """Addresses dnsmasq handed out (DHCPACK) on iface since ts: a fresh lease, not an old one in a file."""
        out = live.run(["journalctl", "--since", f"@{int(ts)}", "-t", "dnsmasq-dhcp", "--no-pager", "-o", "cat"], timeout=20).stdout
        # The simulated client of `nmb-selftest router` is not a real device (phones use random MACs too,
        # so only its own fixed MAC is left out).
        return sorted(set(m.group(1) for m in re.finditer(rf"DHCPACK\({re.escape(iface)}\) ({re.escape(prefix)}\S+) ([0-9a-f:]+)", out)
                          if m.group(2) != live.SIM_CLIENT_MAC))

    def client_traffic(self, saddr: str, oif: str, what: str, timeout: float = 180) -> None:
        self.count_start(saddr, oif)
        try:
            self.say(f"Open a web page on the {what} (any site); the box counts the client's packets to the internet.")
            took = self.wait(f"internet traffic from the {what} out of {oif}", lambda: self.count_packets() >= 200, timeout)
            if took is not None:
                self.rep.add(self.step, f"{what} reaches the internet via {oif}", PASS,
                             f"{self.count_packets()} packets forwarded in {took:.0f} s")
        finally:
            self.count_stop()

    # ---- snapshot and restore ----
    def snapshot(self) -> None:
        try:
            from nmb.common import secret_keep
            secret_keep.update()   # the secrets as they are now, before anything changes
        except Exception:
            pass
        if SNAPSHOT.exists():
            return  # an earlier run did not finish: keep the original settings
        conn = live._db()
        row = conn.execute("SELECT v FROM kv WHERE k = 'override_mode'").fetchone()
        conn.close()
        wlan = live.run(["nmcli", "-g", "GENERAL.STATE", "device", "show", "wlan0"]).stdout.strip()
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps({
            "override_mode": row[0] if row else None,
            "wifi_enabled": bool(self.cfg.network.wifi_enabled),
            "wifi_share_enabled": bool(self.cfg.wifi_share.enabled),
            "wifi_share_lan": self.cfg.wifi_share.lan_interface,
            "wlan0_connected": wlan.startswith("100"),
            "ts": int(time.time()),
        }))
        SNAPSHOT.chmod(0o600)
        live.run(["systemctl", "stop", WATCHDOG_UNIT])
        live.run(["systemd-run", f"--unit={WATCHDOG_UNIT}", "--collect", "/bin/sh", "-c",
                  "sleep 2700; /usr/local/bin/nmb-selftest restore"], check=True)
        self.say("Settings saved; a restore service puts them back in 45 minutes whatever happens.", waiting=False)


def restore(verbose: bool = True) -> bool:
    """Put back what the scenario changed (also the 45-minute safety restore)."""
    if not SNAPSHOT.exists():
        if verbose:
            print("nothing to restore")
        return False
    snap = json.loads(SNAPSHOT.read_text())
    from nmb.db import database as db
    conn = db.connect()
    with db.tx(conn):
        if snap.get("override_mode"):
            conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES ('override_mode', ?, ?)", (snap["override_mode"], db.now_ms()))
        else:
            conn.execute("DELETE FROM kv WHERE k = 'override_mode'")
    conn.close()
    Scenario.api("POST", "/api/config", {"wifi_enabled": bool(snap.get("wifi_enabled"))})
    Scenario.api("POST", "/api/wifi-share/save", {"enabled": bool(snap.get("wifi_share_enabled")),
                                                 "lan_interface": snap.get("wifi_share_lan") or "eth0"})
    live.run(["nft", "delete", "table", "inet", COUNT_TABLE])
    time.sleep(20)  # netd leaves router mode and hands the ports back
    for dev in ("eth0", "wlan0"):
        live.run(["nmcli", "device", "set", dev, "managed", "yes"])
    if snap.get("wlan0_connected"):
        time.sleep(5)
        live.run(["nmcli", "device", "connect", "wlan0"], timeout=60)
    SNAPSHOT.unlink(missing_ok=True)
    # A secret wiped during the run (a bug, not the owner) comes back too.
    try:
        from nmb.common import secret_keep
        if secret_keep.lost():
            live._secrets_restore()
    except Exception as e:
        print(f"secrets: {e}")
    live.run(["logger", "-t", "nmb-selftest", "scenario: settings restored"])
    if verbose:
        print("restored: mode override, access point, Wi-Fi sharing, NetworkManager devices, Wi-Fi client")
    return True


# --------------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------------

def s_preflight(sc: Scenario) -> bool:
    from nmb.netd import usb_uplink
    sc.step = "preflight"
    if not sc.cfg.usb_uplink.enabled:
        sc.rep.add("preflight", "USB uplink enabled", FAIL, "turn it on first: nmb-cli run usb.uplink enabled=true")
        return False
    if not usb_uplink.uplink_interface(sc.cfg):
        sc.say("Plug in the USB phone, hotspot or modem and turn on USB tethering on it.")
    if sc.wait("a USB device with an address", lambda: bool(usb_uplink._address_and_gateway(usb_uplink.uplink_interface(sc.cfg) or "")[0]), 300) is None:
        return False
    sc.usb = usb_uplink.uplink_interface(sc.cfg)
    sc.rep.add("preflight", "USB device", PASS, f"{sc.usb}, kind {live.interfaces_kind(sc.usb)}")
    state = live._netd_state()
    ok = state.get("active_mode") == "standalone" and sc.carrier("eth0")
    sc.rep.add("preflight", "box in standalone mode, cable in", PASS if ok else FAIL,
               f"mode {state.get('active_mode')}, eth0 carrier {sc.carrier('eth0')}")
    if not ok:
        sc.say("Plug the box's Ethernet cable into the home router (the box must be in standalone mode).")
        if sc.wait("standalone mode with the cable in", lambda: live._netd_state().get("active_mode") == "standalone" and sc.carrier("eth0"), 300) is None:
            return False
    live.g_usb(sc.rep, sc.cfg)
    return True


def _speed(sc: Scenario, engine: str, iface: Optional[str]) -> Optional[Dict[str, Any]]:
    t0 = _now_ms()
    exe = "/usr/local/bin/nmb-speed"
    cmd = [exe, "-e", engine, "--force", "--no-port-check", "--trigger", "manual"] + (["-i", iface] if iface else [])
    live.run(cmd, timeout=360)
    conn = live._db()
    try:
        r = conn.execute("SELECT status, bound_iface, down_bps, up_bps, connection_type, error FROM speedtest "
                         "WHERE ts >= ? AND engine = ? ORDER BY id DESC LIMIT 1", (t0 - 5000, engine)).fetchone()
    finally:
        conn.close()
    return None if r is None else {"status": r[0], "iface": r[1], "down": r[2] or 0, "up": r[3] or 0, "type": r[4], "error": r[5] or ""}


def _ookla_recent() -> bool:
    conn = live._db()
    try:
        r = conn.execute("SELECT MAX(ts) FROM speedtest WHERE engine = 'ookla'").fetchone()
    finally:
        conn.close()
    return bool(r and r[0] and time.time() * 1000 - r[0] < 65 * 60 * 1000)


def s_usb_speed(sc: Scenario) -> None:
    from nmb.netd import usb_uplink
    sc.step = "usb-speed"
    sc.say("Speed tests bound to USB, one per engine (a few minutes). Nothing to do.", waiting=False)
    used0 = usb_uplink.usage_today_mb()
    for engine in SPEED_ENGINES:
        if engine == "ookla" and _ookla_recent():
            sc.rep.add(sc.step, "ookla over USB", SKIP, "Ookla ran within the last hour (at most one test per hour)")
            continue
        rx0 = sc.counter(sc.usb, "rx")
        r = _speed(sc, engine, sc.usb)
        rx_mb = (sc.counter(sc.usb, "rx") - rx0) / 1e6
        if r is None:
            sc.rep.add(sc.step, f"{engine} over USB", FAIL, "no result stored")
        elif r["status"] != "ok":
            sc.rep.add(sc.step, f"{engine} over USB", FAIL, r["error"][:120])
        else:
            ok = r["iface"] == sc.usb and r["type"] == "fwa" and rx_mb > 5
            sc.rep.add(sc.step, f"{engine} over USB", PASS if ok else FAIL,
                       f"{r['down']/1e6:.0f}/{r['up']/1e6:.0f} Mbit/s, stored as {r['iface']}/{r['type']}, {rx_mb:.0f} MB received on {sc.usb}")
    used1 = usb_uplink.usage_today_mb()
    sc.rep.add(sc.step, "USB data counter", PASS if used1 > used0 else FAIL, f"{used0:.0f} -> {used1:.0f} MB today")


def s_wifi_share(sc: Scenario) -> None:
    sc.step = "wifi-share"
    if not sc.internet("wlan0"):
        sc.rep.add(sc.step, "box on Wi-Fi", SKIP, "wlan0 has no internet; Wi-Fi sharing needs the box on a Wi-Fi network")
        return
    res = sc.api("POST", "/api/wifi-share/save", {"enabled": True, "lan_interface": "eth0"})
    sc.rep.add(sc.step, "turn on Wi-Fi sharing on eth0", PASS if res.get("status") == "ok" else FAIL, res.get("message", "")[:100])
    sc.say("Pull the box's Ethernet cable out of the home router.")
    if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 300) is None:
        return
    sc.say("Plug that cable into the laptop (the laptop set to get its address automatically).")
    if sc.wait("eth0 cable in", lambda: sc.carrier("eth0"), 300) is None:
        return
    t_in = time.time() - 5
    took = sc.wait("a lease for the laptop (192.168.77.x)", lambda: bool(sc.acks_since(t_in, "eth0", "192.168.77.")), 180)
    if took is not None:
        sc.rep.add(sc.step, "laptop gets an address from the box", PASS,
                   f"{', '.join(sc.acks_since(t_in, 'eth0', '192.168.77.'))} after {took:.0f} s")
        sc.shared = True
        sc.client_traffic("192.168.77.0/24", "wlan0", "laptop")


def s_usb_fallback(sc: Scenario) -> None:
    sc.step = "usb-fallback"
    if any(live._route_dev(r) == "eth0" for r in live._default_routes()) and sc.carrier("eth0"):
        # The cable must leave the home router first, or the box rightly keeps its wired internet.
        sc.say("Pull the box's Ethernet cable out of the home router and plug it into the laptop.")
        if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 300) is None:
            return
        sc.wait("eth0 cable in (laptop)", lambda: sc.carrier("eth0"), 300)
        time.sleep(10)
        dead = [r for r in live._default_routes() if live._route_dev(r) == "eth0"]
        sc.rep.add(sc.step, "no default route left on eth0", PASS if not dead else FAIL,
                   "removed" if not dead else " | ".join(" ".join(r) for r in dead))
    t0 = time.time()
    sc.say("The box leaves its Wi-Fi network now (on purpose); USB must become its internet.", waiting=False)
    live.run(["nmcli", "device", "disconnect", "wlan0"], timeout=30)
    took = sc.wait("the USB default route (metric 900)",
                   lambda: any(live._route_dev(r) == sc.usb and live._metric(r) == 900 for r in live._default_routes()), 150)
    if took is not None:
        sc.rep.add(sc.step, "USB becomes the internet", PASS, f"after {took:.0f} s")
    sc.rep.add(sc.step, "fallback event", PASS if sc.event_since("uplink_usb_fallback", int(t0 * 1000)) else FAIL, "uplink_usb_fallback")
    sc.rep.add(sc.step, "box internet over USB", PASS if sc.internet() else FAIL, "HTTPS")
    if sc.shared and sc.carrier("eth0"):
        sc.client_traffic("192.168.77.0/24", sc.usb, "laptop (now over USB)")
    rx0 = sc.counter(sc.usb, "rx")
    r = _speed(sc, "cloudflare", None)
    rx_mb = (sc.counter(sc.usb, "rx") - rx0) / 1e6
    ok = bool(r) and r["status"] == "ok" and r["iface"] == sc.usb
    sc.rep.add(sc.step, "automatic speed test goes over USB", PASS if ok else FAIL,
               f"stored as {r and r['iface']}, {rx_mb:.0f} MB on {sc.usb}" if r else "no result")


def s_router(sc: Scenario) -> None:
    sc.step = "router"
    t0 = time.time()
    sc.api("POST", "/api/wifi-share/save", {"enabled": False, "lan_interface": "eth0"})
    if live.weak_psk(sc.cfg):
        sc.rep.add(sc.step, "Wi-Fi password for the access point", FAIL, "weak or not set: the access point cannot start")
    sc.api("POST", "/api/config", {"wifi_enabled": True})
    live.run(["/usr/local/bin/nmb-netd", "--switch", "mode_a"], timeout=30)
    took = sc.wait("router mode on USB", lambda: sc.netd_log_since(t0, r"Mode A on USB tethering"), 150)
    if took is None:
        return
    sc.rep.add(sc.step, "router mode takes USB as the WAN", PASS, f"after {took:.0f} s")
    time.sleep(10)
    sc.rep.add(sc.step, "box internet in router mode", PASS if sc.internet() else FAIL, "HTTPS")
    live.g_router(sc.rep, sc.cfg)
    live.g_wifi_ap(sc.rep, sc.cfg)
    t_ask = time.time() - 5
    sc.say("Unplug the laptop's cable for 5 seconds and plug it back (so it asks for a new address).")
    took = sc.wait("a router-mode lease for the laptop (192.168.100.x)", lambda: bool(sc.acks_since(t_ask, "br-lan", "192.168.100.")), 240)
    if took is not None:
        sc.rep.add(sc.step, "laptop on the cable gets an address", PASS, f"after {took:.0f} s")
        sc.client_traffic("192.168.100.0/24", sc.usb, "laptop on the cable")
    sc.say(f"Connect a phone or PC to the box's Wi-Fi ({sc.cfg.network.wifi_ssid or 'NMB-Diagnostic'}); "
           "if it is already connected, turn its Wi-Fi off and on.")
    took = sc.wait("a device on the box's Wi-Fi",
                   lambda: "Station" in live.run(["/usr/sbin/iw", "dev", "wlan0", "station", "dump"]).stdout, 300)
    if took is not None:
        sc.rep.add(sc.step, "device joins the access point", PASS, f"after {took:.0f} s")
        sc.client_traffic("192.168.100.0/24", sc.usb, "device on the box's Wi-Fi")


def s_guard(sc: Scenario) -> None:
    sc.step = "guard"
    if live._netd_state().get("active_mode") != "mode_a":
        sc.rep.add(sc.step, "router mode", SKIP, "not in router mode")
        return
    sc.say("Move the box's cable from the laptop to the home router.")
    if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 300) is None:
        return
    if sc.wait("eth0 cable in", lambda: sc.carrier("eth0"), 300) is None:
        return
    t_in = time.time()
    took = sc.wait("the DHCP guard sees the home router", lambda: sc.netd_log_since(t_in - 2, r"leaving USB WAN: a DHCP server answers"), 150)
    if took is not None:
        sc.rep.add(sc.step, "box stops its DHCP on the router's network", PASS if took <= 90 else WARN, f"after {took:.0f} s (limit 90 s)")
    took = sc.wait("eth0 back as the WAN", lambda: any(live._route_dev(r) == "eth0" for r in live._default_routes()), 120)
    if took is not None:
        sc.rep.add(sc.step, "eth0 is the WAN again", PASS, f"after {took:.0f} s")
    sc.rep.add(sc.step, "box internet", PASS if sc.internet() else FAIL, "HTTPS")


def s_restore(sc: Scenario) -> None:
    sc.step = "restore"
    t0 = time.time()
    sc.say("Putting the settings back (about a minute).", waiting=False)
    restore(verbose=False)
    live.run(["systemctl", "stop", WATCHDOG_UNIT])
    took = sc.wait("standalone mode with eth0 internet",
                   lambda: live._netd_state().get("active_mode") == "standalone" and
                   any(live._route_dev(r) == "eth0" for r in live._default_routes()), 180)
    if took is not None:
        sc.rep.add(sc.step, "back in standalone mode", PASS, f"after {took:.0f} s")
    took = sc.wait("the USB fallback route gone",
                   lambda: not any(live._route_dev(r) == sc.usb and live._metric(r) == 900 for r in live._default_routes()), 150)
    if took is not None:
        sc.rep.add(sc.step, "USB is a side link again", PASS,
                   "event uplink_usb_fallback_end" if sc.event_since("uplink_usb_fallback_end", int(t0 * 1000)) else "no end event")
    sc.wait("wlan0 back on its Wi-Fi network", lambda: sc.internet("wlan0"), 120)
    live.g_services(sc.rep, sc.cfg)
    live.g_internet(sc.rep, sc.cfg)


def s_unplug(sc: Scenario) -> None:
    from nmb.netd import usb_uplink
    sc.step = "unplug"
    sc.say("Unplug the USB device (or say skip: this step gives up after 3 minutes).")
    took = sc.wait("the USB device gone", lambda: not Path(f"/sys/class/net/{sc.usb}").exists() or not sc.carrier(sc.usb), 180)
    if took is None:
        sc.rep.rows[-1]["status"] = SKIP
        return
    time.sleep(70)  # one netd loop
    left = [r for r in live._default_routes() if live._route_dev(r) == sc.usb]
    rules = [ln for ln in live.run(["ip", "-4", "rule", "show"]).stdout.splitlines() if "lookup 152" in ln]
    sc.rep.add(sc.step, "no USB route or rule left", PASS if not left and not rules else FAIL,
               f"{len(left)} route(s), {len(rules)} rule(s)")
    st = usb_uplink.status(sc.cfg)
    sc.rep.add(sc.step, "status says no device", PASS if not st.get("connected") else FAIL, str(st.get("interface")))
    sc.rep.add(sc.step, "box internet", PASS if sc.internet() else FAIL, "HTTPS")


STEP_FUNCS = {"usb-speed": s_usb_speed, "wifi-share": s_wifi_share, "usb-fallback": s_usb_fallback,
              "router": s_router, "guard": s_guard, "restore": s_restore, "unplug": s_unplug}


def run_steps(steps: List[str], funcs: Dict[str, Callable], preflight: Callable, changes: set,
              wait_scale: float = 1.0) -> int:
    """Run the steps; settings changed by them are always put back, also after a crash or a stop."""
    import signal

    def _stop(signum, frame):
        raise SystemExit(f"stopped by signal {signum}")

    signal.signal(signal.SIGTERM, _stop)   # `systemctl stop nmb-scenario` restores too
    rep = Report()
    cfg = live._cfg()
    sc = Scenario(rep, cfg, wait_scale)
    try:
        if not preflight(sc):
            sc.say("Preflight failed; nothing was changed.", waiting=False)
            return _finish(rep, sc)
        if changes & set(steps):
            sc.snapshot()
        for name in steps:
            try:
                funcs[name](sc)
            except SystemExit:
                rep.add(name, "stopped", WARN, "the scenario was stopped; restoring")
                break
            except Exception as e:
                rep.add(name, "step crashed", FAIL, f"{type(e).__name__}: {str(e)[:160]}")
            sc.cfg = live._cfg()
    finally:
        if SNAPSHOT.exists():   # a step crashed, it was stopped, or no restore step was asked for
            sc.step = "restore"
            restore(verbose=False)
            live.run(["systemctl", "stop", WATCHDOG_UNIT])
    return _finish(rep, sc)


def run_usb(steps: List[str], wait_scale: float = 1.0) -> int:
    return run_steps(steps, STEP_FUNCS, s_preflight, {"wifi-share", "usb-fallback", "router", "guard"}, wait_scale)


def _finish(rep: Report, sc: Scenario) -> int:
    c = rep.counts()
    sc.step = "done"
    sc.say(f"Finished: {c[PASS]} passed, {c[WARN]} warnings, {c[FAIL]} failed, {c[SKIP]} skipped.", waiting=False)
    out = live.LOG_DIR / time.strftime("scenario-usb-%Y%m%d-%H%M%S.json")
    try:
        out.write_text(json.dumps({"ts": int(time.time()), "counts": c, "results": rep.rows}, indent=1))
        print(f"report: {out}", flush=True)
    except OSError:
        pass
    return 1 if c[FAIL] else 0


def plan(steps: List[str]) -> str:
    doc = __doc__ or ""
    lines = [ln for ln in doc.splitlines() if any(ln.strip().startswith(s) for s in steps)]
    return "Steps: " + ", ".join(steps) + "\n" + "\n".join(lines)


if __name__ == "__main__":
    sys.exit(run_usb(STEPS))
