"""Guided live scenario for the automatic mode: `nmb-selftest scenario auto`.

Checks the owner's rule (nmb/netd/auto_mode.py) with real cables:

  auto-on      The box is switched to `mode = auto` with the cable in the home router: it must stay
               standalone (no switch for a minute), and say why ("a router gives addresses").
  auto-router  The cable is pulled out of the home router and left out: router mode must start, not before
               the 90-second grace (a rebooting router must not knock the box over) and not much after;
               the access point and its DHCP run, the box keeps its internet over USB tethering and
               Tailscale stays online.
  auto-back    The cable goes back into the home router: standalone again within about a minute, the
               box's own address from the router, the access point gone, the radio back on the home Wi-Fi.
  auto-pppoe   (only with a saved PPPoE login) The cable goes onto the ONT or modem: router mode dials
               PPPoE and has internet over it; then the cable back into the home router, standalone again.
  restore      The mode and every other setting back as they were.

A single-port box loses its home network in router mode, so this scenario needs USB tethering (phone,
hotspot, modem) for Tailscale; without it, the Tailscale guard would stop the test after 2 minutes. Set
NMB_SCENARIO_ALLOW_OFFLINE=1 to run anyway (then nobody can watch it remotely).
"""
from __future__ import annotations

import os
import time
from typing import List

from nmb.selftest import live, scenario as S
from nmb.selftest.live import FAIL, PASS, SKIP, WARN

STEPS = ["auto-on", "auto-router", "auto-back", "auto-pppoe", "restore"]


def _state() -> dict:
    return live._netd_state()


def _mode() -> str:
    return str(_state().get("active_mode") or "")


def _reason() -> str:
    d = _state().get("auto_decision") or {}
    return str(d.get("reason") or "")


def a_preflight(sc: S.Scenario) -> bool:
    from nmb.netd import usb_uplink
    sc.step = "preflight"
    ok = _mode() == "standalone" and sc.carrier("eth0") and sc.internet()
    sc.rep.add(sc.step, "standalone, cable in the home router, internet", PASS if ok else FAIL, f"mode {_mode()}")
    if not ok:
        return False
    usb = usb_uplink.uplink_interface(sc.cfg) if sc.cfg.usb_uplink.enabled else None
    online_usb = bool(usb and usb_uplink._address_and_gateway(usb)[0])
    if not online_usb and os.environ.get("NMB_SCENARIO_ALLOW_OFFLINE") != "1":
        sc.rep.add(sc.step, "USB tethering for remote access", FAIL,
                   "plug in and turn on USB tethering (keeps Tailscale up in router mode), "
                   "or set NMB_SCENARIO_ALLOW_OFFLINE=1")
        return False
    sc.rep.add(sc.step, "USB tethering for remote access", PASS if online_usb else WARN,
               f"{usb} online" if online_usb else "none: remote access drops in router mode")
    if live.weak_psk(sc.cfg):
        sc.rep.add(sc.step, "Wi-Fi password for the access point", WARN, "weak or not set: router mode runs without access point")
    return True


def a_on(sc: S.Scenario) -> None:
    sc.step = "auto-on"
    from nmb.db import database as db
    conn = db.connect()
    with db.tx(conn):
        conn.execute("DELETE FROM kv WHERE k = 'override_mode'")   # an override would hide the automatic choice
    conn.close()
    res = sc.api("POST", "/api/config", {"network_mode": "auto", "wifi_enabled": True})
    sc.rep.add(sc.step, "mode set to auto", PASS if res.get("status") != "error" else FAIL, str(res.get("message", ""))[:100])
    took = sc.wait("the automatic decision", lambda: _state().get("configured_mode") == "auto" and bool(_reason()), 90)
    if took is None:
        return
    t0 = time.time()
    switched = sc.watch(lambda: _mode() != "standalone", 60, every=3)   # no change is the expected outcome
    sc.rep.add(sc.step, "stays standalone behind the router", PASS if switched is None else FAIL,
               f"reason: {_reason()}" if switched is None else f"switched to {_mode()} after {time.time() - t0:.0f} s")


def a_router(sc: S.Scenario) -> None:
    sc.step = "auto-router"
    if _mode() != "standalone":
        sc.rep.add(sc.step, "starts in standalone", SKIP, f"mode {_mode()}")
        return
    sc.say("Pull the box's cable out of the home router and leave it out (about 3 minutes).")
    if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 300) is None:
        return
    t_out = time.time()
    from nmb.netd.auto_mode import ROUTER_MISSING_SEC
    took = sc.wait("router mode", lambda: _mode() == "mode_a", ROUTER_MISSING_SEC + 90, every=3)
    if took is None:
        return
    elapsed = time.time() - t_out
    sc.rep.add(sc.step, "router mode after the grace time", PASS if elapsed >= ROUTER_MISSING_SEC - 5 else FAIL,
               f"after {elapsed:.0f} s (grace {int(ROUTER_MISSING_SEC)} s): {_reason()}")
    time.sleep(15)
    ap = live.run(["pgrep", "-x", "hostapd"]).returncode == 0
    dhcp = live.run(["pgrep", "-f", "dnsmasq --conf-file=/run/nmb/dnsmasq.conf"]).returncode == 0
    sc.rep.add(sc.step, "access point and DHCP for setup", PASS if ap and dhcp else (WARN if dhcp else FAIL),
               f"hostapd {'running' if ap else 'not running'}, DHCP {'running' if dhcp else 'not running'}")
    sc.rep.add(sc.step, "box internet (USB)", PASS if sc.internet() else FAIL, "HTTPS")
    ts = live.tailscale_online()
    sc.rep.add(sc.step, "Tailscale online", SKIP if ts is None else (PASS if ts else FAIL), "")


def a_back(sc: S.Scenario) -> None:
    sc.step = "auto-back"
    if _mode() != "mode_a":
        sc.rep.add(sc.step, "starts in router mode", SKIP, f"mode {_mode()}")
        return
    sc.say("Plug the box's cable back into the home router.")
    if sc.wait("eth0 cable in", lambda: sc.carrier("eth0"), 300) is None:
        return
    t_in = time.time()
    took = sc.wait("standalone again", lambda: _mode() == "standalone", 120, every=2)
    if took is None:
        return
    sc.rep.add(sc.step, "standalone after the router answers", PASS if took <= 75 else WARN, f"after {time.time() - t_in:.0f} s")
    sc.wait("the box's own address from the router", lambda: sc.internet("eth0"), 120)
    sc.rep.add(sc.step, "address from the router on eth0", PASS if sc.internet("eth0") else FAIL, "HTTPS from eth0's address")
    sc.rep.add(sc.step, "no access point in standalone", PASS if live.run(["pgrep", "-x", "hostapd"]).returncode != 0 else FAIL, "")
    sc.wait("the radio back on the home Wi-Fi", lambda: sc.internet("wlan0"), 120)
    sc.rep.add(sc.step, "radio back on the home Wi-Fi", PASS if sc.internet("wlan0") else WARN, "HTTPS from wlan0's address")


def a_pppoe(sc: S.Scenario) -> None:
    sc.step = "auto-pppoe"
    net = sc.cfg.network
    if not (getattr(net, "pppoe_user", "") and getattr(net, "pppoe_password", "")):
        sc.rep.add(sc.step, "PPPoE login", SKIP, "no PPPoE login saved")
        return
    if _mode() != "standalone":
        sc.rep.add(sc.step, "starts in standalone", SKIP, f"mode {_mode()}")
        return
    sc.say("Move the box's cable from the home router to the ONT or modem (the PPPoE line). If the ISP allows "
           "only one session, stop the home router's PPPoE first.")
    if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 600) is None:
        return
    if sc.wait("eth0 cable in (ONT)", lambda: sc.carrier("eth0"), 600) is None:
        return
    took = sc.wait("router mode with PPPoE", lambda: _mode() == "mode_a" and bool((_state().get("auto_decision") or {}).get("pppoe")), 420, every=3)
    if took is None:
        return
    sc.rep.add(sc.step, "router mode dials PPPoE", PASS, f"after {took:.0f} s")
    from nmb.netd import interfaces
    up = sc.wait("ppp0 with an address", lambda: any(":" not in a for a in interfaces.get_ip_addresses("ppp0")), 120)
    if up is not None:
        p = live.run(["ping", "-c", "3", "-W", "3", "-I", "ppp0", "1.1.1.1"], timeout=20)
        sc.rep.add(sc.step, "internet over PPPoE", PASS if p.returncode == 0 else FAIL, "ping 1.1.1.1 over ppp0")
    sc.say("Move the cable back from the ONT to the home router (and turn the router's PPPoE on again).")
    if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 600) is None:
        return
    if sc.wait("eth0 cable in (router)", lambda: sc.carrier("eth0"), 600) is None:
        return
    took = sc.wait("standalone again", lambda: _mode() == "standalone", 180, every=2)
    if took is not None:
        sc.rep.add(sc.step, "standalone behind the router again", PASS, f"after {took:.0f} s")


def a_restore(sc: S.Scenario) -> None:
    sc.step = "restore"
    sc.say("Putting the settings back (about a minute).", waiting=False)
    S.restore(verbose=False)
    live.run(["systemctl", "stop", S.WATCHDOG_UNIT])
    took = sc.wait("the original mode with internet", lambda: sc.internet() and bool(_mode()), 180)
    if took is not None:
        sc.rep.add(sc.step, "settings back", PASS, f"mode {_mode()}, configured {_state().get('configured_mode')}")
    live.g_services(sc.rep, sc.cfg)
    live.g_internet(sc.rep, sc.cfg)


FUNCS = {"auto-on": a_on, "auto-router": a_router, "auto-back": a_back, "auto-pppoe": a_pppoe, "restore": a_restore}


def run_auto(steps: List[str], wait_scale: float = 1.0) -> int:
    return S.run_steps(steps, FUNCS, a_preflight, {"auto-on", "auto-router", "auto-back", "auto-pppoe"},
                       wait_scale, name="auto")


def plan(steps: List[str]) -> str:
    lines = [ln for ln in (__doc__ or "").splitlines() if ln.startswith("  ") and any(ln.strip().startswith(s) for s in steps)]
    return "Steps: " + ", ".join(steps) + "\n" + "\n".join(lines)
