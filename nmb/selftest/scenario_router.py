"""Guided live scenario for router mode (Mode A) with the Ethernet port as WAN: `nmb-selftest scenario router`.

The box needs only its cable to the home router; a phone or PC joins the box's Wi-Fi. No USB device is
needed (with one plugged in and turned on, the WAN-loss step checks the USB takeover instead).

Steps:
  router-up    Router mode starts: the WAN port gets the home router's address, NAT on the WAN, the access
               point has an address and DHCP, the box's own internet works, a simulated LAN client gets an
               address and reaches the internet, DNS and HTTPS.
  wifi-client  A real device joins the box's Wi-Fi: a fresh lease from the box, and its packets to the
               internet are counted leaving the WAN port.
  web-ui       The device opens the box's Web UI (http://<gateway>): its requests to port 80 are counted.
  wan-loss     The cable is pulled from the home router for a minute: the access point and DHCP keep
               running and nothing crashes; with the cable back the WAN gets its address again and the
               device reaches the internet again (or USB takes over while the cable is out, when enabled).
  restore      Settings back as they were, standalone mode, the radio back on the home Wi-Fi.

Settings are saved first; they are put back at the end, after a crash or stop (SIGTERM), or by a separate
restore service after 45 minutes.
"""
from __future__ import annotations

import time
from typing import List

from nmb.selftest import live, scenario as S
from nmb.selftest.live import FAIL, PASS, SKIP, WARN, Report

STEPS = ["router-up", "wifi-client", "web-ui", "wan-loss", "restore"]
LAN_NET = "192.168.100.0/24"


def _lan(sc: S.Scenario) -> str:
    return str(getattr(sc.cfg.network, "gateway_ip", "192.168.100.1") or "192.168.100.1")


def r_preflight(sc: S.Scenario) -> bool:
    sc.step = "preflight"
    state = live._netd_state()
    ok = state.get("active_mode") == "standalone" and sc.carrier("eth0") and sc.internet()
    sc.rep.add(sc.step, "standalone, cable in the home router, internet", PASS if ok else FAIL,
               f"mode {state.get('active_mode')}, eth0 carrier {sc.carrier('eth0')}")
    if not ok:
        sc.say("Plug the box's cable into the home router; the box must be in standalone mode with internet.")
        if sc.wait("standalone with internet on eth0",
                   lambda: live._netd_state().get("active_mode") == "standalone" and sc.carrier("eth0") and sc.internet(), 300) is None:
            return False
    if live.weak_psk(sc.cfg):
        sc.rep.add(sc.step, "Wi-Fi password for the access point", FAIL, "weak, empty or factory: set one in Settings > Wi-Fi")
        return False
    return True


def r_router_up(sc: S.Scenario) -> None:
    sc.step = "router-up"
    t0 = time.time()
    sc.say("Switching to router mode (the box's Wi-Fi network appears; the box leaves the home Wi-Fi).", waiting=False)
    sc.api("POST", "/api/config", {"wifi_enabled": True})
    live.run(["/usr/local/bin/nmb-netd", "--switch", "mode_a"], timeout=30)
    took = sc.wait("router mode set up", lambda: live._netd_state().get("active_mode") == "mode_a" and
                   sc.netd_log_since(t0, r"applying Mode A NAT"), 150)
    if took is None:
        return
    sc.rep.add(sc.step, "router mode is up", PASS, f"after {took:.0f} s")
    time.sleep(8)
    sc.rep.add(sc.step, "WAN port has the home router's address", PASS if sc.internet("eth0") else FAIL, "HTTPS from eth0's address")
    sc.rep.add(sc.step, "box's own internet", PASS if sc.internet() else FAIL, "HTTPS")
    live.g_router(sc.rep, sc.cfg)
    live.g_wifi_ap(sc.rep, sc.cfg)


def r_wifi_client(sc: S.Scenario) -> None:
    sc.step = "wifi-client"
    if live._netd_state().get("active_mode") != "mode_a":
        sc.rep.add(sc.step, "router mode", SKIP, "not in router mode")
        return
    t_ask = time.time() - 5
    sc.say(f"Connect a phone or PC to the box's Wi-Fi ({sc.cfg.network.wifi_ssid or 'NMB-Diagnostic'}); "
           "if it is already connected, turn its Wi-Fi off and on.")
    took = sc.wait("a device on the box's Wi-Fi with a fresh address",
                   lambda: "Station" in live.run(["/usr/sbin/iw", "dev", "wlan0", "station", "dump"]).stdout
                   and bool(sc.acks_since(t_ask, "br-lan", "192.168.100.")), 300)
    if took is None:
        return
    sc.rep.add(sc.step, "device joins and gets an address", PASS,
               f"{', '.join(sc.acks_since(t_ask, 'br-lan', '192.168.100.'))} after {took:.0f} s")
    sc.client_traffic(LAN_NET, "eth0", "device on the box's Wi-Fi")


def r_web_ui(sc: S.Scenario) -> None:
    sc.step = "web-ui"
    if live._netd_state().get("active_mode") != "mode_a":
        sc.rep.add(sc.step, "router mode", SKIP, "not in router mode")
        return
    port = int(getattr(sc.cfg.web, "port", 80) or 80)
    sc.count_start_input(LAN_NET, port)
    try:
        sc.say(f"On that device open http://{_lan(sc)}/ (the box's Web UI) and log in.")
        took = sc.wait("Web UI requests from the LAN", lambda: sc.count_packets() >= 20, 240)
        if took is not None:
            sc.rep.add(sc.step, "Web UI reachable from the box's Wi-Fi", PASS, f"{sc.count_packets()} packets to port {port} in {took:.0f} s")
    finally:
        sc.count_stop()


def r_wan_loss(sc: S.Scenario) -> None:
    from nmb.netd import usb_uplink
    sc.step = "wan-loss"
    if live._netd_state().get("active_mode") != "mode_a":
        sc.rep.add(sc.step, "router mode", SKIP, "not in router mode")
        return
    usb = usb_uplink.uplink_interface(sc.cfg) if sc.cfg.usb_uplink.enabled else None
    sc.say("Pull the box's cable out of the home router and leave it out for about a minute.")
    if sc.wait("eth0 cable out", lambda: not sc.carrier("eth0"), 300) is None:
        return
    time.sleep(45)
    ap = live.run(["pgrep", "-x", "hostapd"]).returncode == 0
    dhcp = live.run(["pgrep", "-f", "dnsmasq --conf-file=/run/nmb/dnsmasq.conf"]).returncode == 0
    sc.rep.add(sc.step, "access point and DHCP stay up without WAN", PASS if ap and dhcp else FAIL,
               f"hostapd {'running' if ap else 'stopped'}, DHCP {'running' if dhcp else 'stopped'}")
    dead = [r for r in live._default_routes() if live._route_dev(r) == "eth0"]
    sc.rep.add(sc.step, "no dead default route on eth0", PASS if not dead else FAIL, " | ".join(" ".join(r) for r in dead))
    if usb:
        sc.rep.add(sc.step, "USB takes over as WAN", PASS if sc.netd_log_since(time.time() - 120, r"Mode A on USB tethering") else WARN,
                   f"{usb} enabled and present")
    sc.say("Plug the cable back into the home router.")
    if sc.wait("eth0 cable in", lambda: sc.carrier("eth0"), 300) is None:
        return
    t_in = time.time()
    took = sc.wait("the WAN port gets its address again", lambda: sc.internet("eth0"), 180)
    if took is not None:
        sc.rep.add(sc.step, "WAN back after the cable", PASS, f"after {took:.0f} s")
    sc.rep.add(sc.step, "box's own internet", PASS if sc.internet() else FAIL, "HTTPS")
    if "Station" in live.run(["/usr/sbin/iw", "dev", "wlan0", "station", "dump"]).stdout:
        sc.client_traffic(LAN_NET, "eth0", "device on the box's Wi-Fi (after the WAN came back)", timeout=120)
    tb = live.run(["journalctl", "-u", "nmb-netd", "--since", f"@{int(t_in) - 120}", "--no-pager", "-o", "cat"]).stdout.count("Traceback")
    sc.rep.add(sc.step, "no crash in nmb-netd", PASS if not tb else FAIL, f"{tb} traceback(s)")


def r_restore(sc: S.Scenario) -> None:
    sc.step = "restore"
    sc.say("Putting the settings back (about a minute).", waiting=False)
    S.restore(verbose=False)
    live.run(["systemctl", "stop", S.WATCHDOG_UNIT])
    took = sc.wait("standalone with internet", lambda: live._netd_state().get("active_mode") == "standalone" and sc.internet(), 180)
    if took is not None:
        sc.rep.add(sc.step, "back in standalone mode", PASS, f"after {took:.0f} s")
    sc.wait("wlan0 back on the home Wi-Fi", lambda: sc.internet("wlan0"), 120)
    sc.rep.add(sc.step, "radio back on the home Wi-Fi", PASS if sc.internet("wlan0") else FAIL, "HTTPS from wlan0's address")
    sc.rep.add(sc.step, "no access point outside router mode", PASS if live.run(["pgrep", "-x", "hostapd"]).returncode != 0 else FAIL, "")
    live.g_services(sc.rep, sc.cfg)
    live.g_internet(sc.rep, sc.cfg)


FUNCS = {"router-up": r_router_up, "wifi-client": r_wifi_client, "web-ui": r_web_ui, "wan-loss": r_wan_loss, "restore": r_restore}


def run_router(steps: List[str], wait_scale: float = 1.0) -> int:
    return S.run_steps(steps, FUNCS, r_preflight, {"router-up", "wifi-client", "web-ui", "wan-loss"}, wait_scale, name="router")


def plan(steps: List[str]) -> str:
    lines = [ln for ln in (__doc__ or "").splitlines() if ln.startswith("  ") and any(ln.strip().startswith(s) for s in steps)]
    return "Steps: " + ", ".join(steps) + "\n" + "\n".join(lines)
