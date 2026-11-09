"""Live scenario for router mode on a real PPPoE line: `nmb-selftest scenario pppoe`.

The box's Ethernet port is already on the ONT or modem (the PPPoE line), a PPPoE login is saved, and USB
tethering (phone, hotspot, modem) keeps the box reachable over Tailscale while the port is the WAN. Built
for the first real-line test (2026-11-09, DIGI), where the owner watched from another network.

Steps:
  pppoe-up     Automatic mode: a PPPoE server answers and a login is saved, so router mode must dial PPPoE
               (the owner's rule in nmb/netd/auto_mode.py). Then: ppp0 has an address and the default route,
               NAT and MSS clamping on ppp0, the box's own internet and DNS over ppp0, the access point and
               DHCP run, a simulated LAN client reaches the internet, Tailscale stays online.
  pppoe-speed  The speed tests over ppp0: Cloudflare, Fast.com, RTR, iPerf3, and Ookla when none ran in the
               last hour (the hourly rule).
  pppoe-redial The line drops (pppd is told to hang up): pppd dials again by itself. Then pppd is stopped:
               nmb-netd notices and starts it again after its pause. No crash in nmb-netd.
  pppoe-groups Every self-test group in router mode on PPPoE (services, mode, internet, config, web, cli,
               usb, router, dhcp-probe, wifi-ap, telegram, the simulated PPPoE, dyndns, ipv6).
  pppoe-dyndns DynDNS follows the new public address of the PPPoE line (waits for the next update).
  wifi-client  (needs a phone or PC at the box) A device joins the box's Wi-Fi, gets a fresh lease, and its
               packets leave through ppp0.
  web-ui       That device opens the box's Web UI.
  restore      The mode and every other setting back as they were (standalone); the box's own internet
               comes back (over USB when the Wi-Fi network it returns to has no internet).

Settings are saved first and put back at the end, after a crash or stop (SIGTERM), or by a separate
restore service after 45 minutes. Tailscale offline for 2 minutes stops the scenario and restores.
"""
from __future__ import annotations

import os
import re
import time
from typing import List

from nmb.selftest import live, scenario as S
from nmb.selftest.live import FAIL, PASS, SKIP, WARN

STEPS = ["pppoe-up", "pppoe-speed", "pppoe-redial", "pppoe-groups", "pppoe-dyndns", "wifi-client", "web-ui", "restore"]
CHANGES = {"pppoe-up", "pppoe-speed", "pppoe-redial", "pppoe-groups", "pppoe-dyndns", "wifi-client", "web-ui"}
LAN_NET = "192.168.100.0/24"
SPEED_ENGINES = ["cloudflare", "fastcom", "rtr", "iperf3", "ookla"]


def _state() -> dict:
    return live._netd_state()


def _mode() -> str:
    return str(_state().get("active_mode") or "")


def _ppp_v4() -> List[str]:
    from nmb.netd import interfaces
    return [a for a in interfaces.get_ip_addresses("ppp0") if ":" not in a]


def _in_pppoe_router() -> bool:
    return _mode() == "mode_a" and bool(_ppp_v4())


def p_preflight(sc: S.Scenario) -> bool:
    from nmb.netd import usb_uplink
    sc.step = "preflight"
    net = sc.cfg.network
    login = bool(getattr(net, "pppoe_user", "") and getattr(net, "pppoe_password", ""))
    sc.rep.add(sc.step, "PPPoE login saved", PASS if login else FAIL, "" if login else "Web UI > Router > PPPoE")
    ok = _mode() == "standalone" and sc.carrier("eth0")
    sc.rep.add(sc.step, "standalone, cable in the WAN port", PASS if ok else FAIL, f"mode {_mode()}, eth0 carrier {sc.carrier('eth0')}")
    usb = usb_uplink.uplink_interface(sc.cfg) if sc.cfg.usb_uplink.enabled else None
    online_usb = bool(usb and usb_uplink._address_and_gateway(usb)[0])
    allow = os.environ.get("NMB_SCENARIO_ALLOW_OFFLINE") == "1"
    sc.rep.add(sc.step, "USB tethering for remote access", PASS if online_usb else (WARN if allow else FAIL),
               f"{usb} online" if online_usb else "plug in and turn on USB tethering, or set NMB_SCENARIO_ALLOW_OFFLINE=1")
    if live.weak_psk(sc.cfg):
        sc.rep.add(sc.step, "Wi-Fi password for the access point", FAIL, "weak, empty or factory: set one in Settings > Wi-Fi")
        return False
    return login and ok and (online_usb or allow)


def p_up(sc: S.Scenario) -> None:
    sc.step = "pppoe-up"
    from nmb.db import database as db
    conn = db.connect()
    with db.tx(conn):
        conn.execute("DELETE FROM kv WHERE k = 'override_mode'")   # an override would hide the automatic choice
    conn.close()
    t0 = time.time()
    res = sc.api("POST", "/api/config", {"network_mode": "auto", "wifi_enabled": True})
    sc.rep.add(sc.step, "mode set to auto", PASS if res.get("status") != "error" else FAIL, str(res.get("message", ""))[:100])
    sc.say("Automatic mode on: with the cable on the PPPoE line it must start router mode and dial PPPoE "
           "(the box's Wi-Fi network appears).", waiting=False)
    from nmb.netd.auto_mode import PPPOE_PROBE_EVERY_SEC
    took = sc.wait("router mode with PPPoE", lambda: _mode() == "mode_a" and
                   bool((_state().get("auto_decision") or {}).get("pppoe")), PPPOE_PROBE_EVERY_SEC + 240, every=3)
    if took is None:
        sc.rep.add(sc.step, "automatic decision", FAIL, (_state().get("auto_decision") or {}).get("reason", "none"))
        return
    sc.rep.add(sc.step, "automatic mode chose router mode with PPPoE", PASS,
               f"after {took:.0f} s: {(_state().get('auto_decision') or {}).get('reason', '')[:120]}")
    up = sc.wait("ppp0 with an address", lambda: bool(_ppp_v4()), 120)
    if up is None:
        sc.rep.add(sc.step, "ppp0 address", FAIL, "pppd did not connect: " + str((_state().get("details") or {}).get("pppoe_error") or ""))
        return
    sc.rep.add(sc.step, "PPPoE connected", PASS, f"{time.time() - t0:.0f} s after the mode change")
    time.sleep(8)   # the ISP may drop the first packets of a new session
    routes = live._default_routes()
    first = live._route_dev(routes[0]) if routes else ""
    sc.rep.add(sc.step, "default route via ppp0", PASS if first == "ppp0" else FAIL,
               " | ".join(" ".join(r) for r in routes[:3]) or "no default route")
    nat = live.run(["nft", "list", "table", "inet", "nmb_nat"]).stdout
    sc.rep.add(sc.step, "NAT on ppp0", PASS if re.search(r'oifname "ppp0".*masquerade', nat) else FAIL, "")
    sc.rep.add(sc.step, "MSS clamping", PASS if "maxseg size set rt mtu" in nat else FAIL, "")
    sc.rep.add(sc.step, "box's own internet over ppp0", PASS if sc.internet("ppp0") else FAIL, "HTTPS from ppp0's address")
    dns = live.run(["getent", "hosts", "www.cloudflare.com"], timeout=15).returncode == 0
    sc.rep.add(sc.step, "box's DNS", PASS if dns else FAIL, "www.cloudflare.com resolves")
    for name, pat in (("access point", ["pgrep", "-x", "hostapd"]),
                      ("DHCP for the LAN", ["pgrep", "-f", "dnsmasq --conf-file=/run/nmb/dnsmasq.conf"])):
        sc.rep.add(sc.step, name, PASS if live.run(pat).returncode == 0 else FAIL, "")
    ts = live.tailscale_online()
    sc.rep.add(sc.step, "Tailscale online", PASS if ts else FAIL, "")
    live.g_router(sc.rep, sc.cfg)
    live.g_wifi_ap(sc.rep, sc.cfg)


def p_speed(sc: S.Scenario) -> None:
    sc.step = "pppoe-speed"
    if not _in_pppoe_router():
        sc.rep.add(sc.step, "PPPoE router mode", SKIP, f"mode {_mode()}")
        return
    for engine in SPEED_ENGINES:
        if engine == "ookla" and S._ookla_recent():
            sc.rep.add(sc.step, "ookla over ppp0", SKIP, "an Ookla test ran in the last hour (hourly rule)")
            continue
        sc.say(f"Speed test {engine} over ppp0.", waiting=False)
        r = S._speed(sc, engine, "ppp0")
        if r is None:
            sc.rep.add(sc.step, f"{engine} over ppp0", FAIL, "no result stored")
            continue
        good = r["status"] == "ok" and r["iface"] in ("ppp0", None, "") and r["down"] > 0
        sc.rep.add(sc.step, f"{engine} over ppp0", PASS if good else (WARN if r["status"].startswith("skipped") else FAIL),
                   f"{r['status']}, down {r['down'] / 1e6:.0f} Mbit/s, up {r['up'] / 1e6:.0f} Mbit/s, iface {r['iface']}"
                   + (f", {r['error'][:80]}" if r["error"] else ""))


def _pppd_pid() -> int:
    out = live.run(["pgrep", "-f", "pppd plugin .*linkname nmb-pppoe|pppd .*linkname nmb-pppoe"]).stdout.split()
    return int(out[0]) if out else 0


def p_redial(sc: S.Scenario) -> None:
    sc.step = "pppoe-redial"
    if not _in_pppoe_router():
        sc.rep.add(sc.step, "PPPoE router mode", SKIP, f"mode {_mode()}")
        return
    t0 = time.time()
    pid = _pppd_pid()
    if not pid:
        sc.rep.add(sc.step, "pppd process", FAIL, "not found")
        return
    sc.say("Line drop: pppd hangs up and must dial again by itself.", waiting=False)
    live.run(["kill", "-HUP", str(pid)])
    sc.watch(lambda: not _ppp_v4(), 20, every=1)
    took = sc.wait("ppp0 back after the hang-up", lambda: bool(_ppp_v4()), 120, every=2)
    if took is not None:
        sc.rep.add(sc.step, "pppd dials again after a line drop", PASS, f"after {took:.0f} s, same pppd {_pppd_pid() == pid}")
        time.sleep(8)
        sc.rep.add(sc.step, "internet after the redial", PASS if sc.internet("ppp0") else FAIL, "HTTPS over ppp0")
    pid = _pppd_pid()
    sc.say("pppd stops: nmb-netd must notice and start it again after its pause.", waiting=False)
    live.run(["kill", "-TERM", str(pid)])
    took = sc.wait("nmb-netd starts pppd again", lambda: _pppd_pid() not in (0, pid), 120, every=2)
    if took is not None:
        sc.rep.add(sc.step, "nmb-netd restarts a stopped pppd", PASS, f"after {took:.0f} s")
        up = sc.wait("ppp0 back", lambda: bool(_ppp_v4()), 90, every=2)
        if up is not None:
            time.sleep(8)
            sc.rep.add(sc.step, "internet after the restart", PASS if sc.internet("ppp0") else FAIL, "HTTPS over ppp0")
    tb = live.run(["journalctl", "-u", "nmb-netd", "--since", f"@{int(t0)}", "--no-pager", "-o", "cat"]).stdout.count("Traceback")
    sc.rep.add(sc.step, "no crash in nmb-netd", PASS if not tb else FAIL, f"{tb} traceback(s)")
    sc.rep.add(sc.step, "Tailscale online", PASS if live.tailscale_online() else FAIL, "")


def p_groups(sc: S.Scenario) -> None:
    sc.step = "pppoe-groups"
    if not _in_pppoe_router():
        sc.rep.add(sc.step, "PPPoE router mode", SKIP, f"mode {_mode()}")
        return
    for name, fn in live.GROUPS.items():
        if name in ("speed", "collector"):
            continue   # speed has its own step; the collector needs a URL and a token (run it separately)
        sc.say(f"Self-test group {name}.", waiting=False)
        try:
            fn(sc.rep, sc.cfg)
        except Exception as e:
            sc.rep.add(name, "group crashed", FAIL, f"{type(e).__name__}: {str(e)[:160]}")
        if not _in_pppoe_router():
            sc.rep.add(sc.step, f"still in PPPoE router mode after {name}", FAIL, f"mode {_mode()}")
            return


def p_dyndns(sc: S.Scenario) -> None:
    sc.step = "pppoe-dyndns"
    d = getattr(sc.cfg, "duckdns", None)   # the DynDNS settings (DuckDNS or dynv6)
    if not (d and getattr(d, "enabled", False)):
        sc.rep.add(sc.step, "DynDNS", SKIP, "turned off")
        return
    if not _in_pppoe_router():
        sc.rep.add(sc.step, "PPPoE router mode", SKIP, f"mode {_mode()}")
        return
    interval = int(getattr(d, "update_interval_min", 10) or 10)
    sc.say(f"Waiting for the next DynDNS update (every {interval} min).", waiting=False)

    def points_here() -> bool:
        probe = live.Report()
        live.g_dyndns(probe, sc.cfg)
        return any(r["check"].startswith("name points") and r["status"] == PASS for r in probe.rows)

    took = sc.wait("the DynDNS name points at the PPPoE line", points_here, interval * 60 + 300, every=60)
    live.g_dyndns(sc.rep, sc.cfg)
    if took is not None:
        sc.rep.add(sc.step, "DynDNS follows the PPPoE address", PASS, f"after {took:.0f} s")


def p_wifi_client(sc: S.Scenario) -> None:
    sc.step = "wifi-client"
    if not _in_pppoe_router():
        sc.rep.add(sc.step, "PPPoE router mode", SKIP, f"mode {_mode()}")
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
    sc.client_traffic(LAN_NET, "ppp0", "device on the box's Wi-Fi")


def p_web_ui(sc: S.Scenario) -> None:
    from nmb.selftest import scenario_router
    if not _in_pppoe_router():
        sc.step = "web-ui"
        sc.rep.add(sc.step, "PPPoE router mode", SKIP, f"mode {_mode()}")
        return
    if "Station" not in live.run(["/usr/sbin/iw", "dev", "wlan0", "station", "dump"]).stdout:
        sc.step = "web-ui"
        sc.rep.add(sc.step, "a device on the box's Wi-Fi", SKIP, "none connected")
        return
    scenario_router.r_web_ui(sc)


def p_restore(sc: S.Scenario) -> None:
    from nmb.netd import usb_uplink
    sc.step = "restore"
    sc.say("Putting the settings back (about a minute).", waiting=False)
    S.restore(verbose=False)
    live.run(["systemctl", "stop", S.WATCHDOG_UNIT])
    took = sc.wait("standalone mode", lambda: _mode() == "standalone", 180)
    if took is not None:
        sc.rep.add(sc.step, "back in standalone mode", PASS, f"after {took:.0f} s")
    sc.rep.add(sc.step, "pppd stopped", PASS if not _pppd_pid() else FAIL, "")
    sc.rep.add(sc.step, "no access point outside router mode", PASS if live.run(["pgrep", "-x", "hostapd"]).returncode != 0 else FAIL, "")
    # With the cable still on the PPPoE line the box has no wired network; the home Wi-Fi it returns to
    # may have no internet either (its router's cable is on the line now), so USB has to carry it.
    took = sc.wait("the box's own internet", sc.internet, 240, every=5)
    if took is not None:
        via = "USB (the other routes have no internet)" if usb_uplink.rescue_active() else \
              "USB (no other route)" if usb_uplink.fallback_active() else "Ethernet or Wi-Fi"
        sc.rep.add(sc.step, "box's own internet after the restore", PASS, f"after {took:.0f} s, via {via}")
    sc.rep.add(sc.step, "Tailscale online", PASS if live.tailscale_online() else FAIL, "")
    live.g_services(sc.rep, sc.cfg)


FUNCS = {"pppoe-up": p_up, "pppoe-speed": p_speed, "pppoe-redial": p_redial, "pppoe-groups": p_groups,
         "pppoe-dyndns": p_dyndns, "wifi-client": p_wifi_client, "web-ui": p_web_ui, "restore": p_restore}


def run_pppoe(steps: List[str], wait_scale: float = 1.0) -> int:
    return S.run_steps(steps, FUNCS, p_preflight, CHANGES, wait_scale, name="pppoe")


def plan(steps: List[str]) -> str:
    doc = __doc__ or ""
    lines = [ln for ln in doc.splitlines() if any(ln.strip().startswith(s) for s in steps)]
    return "Steps: " + ", ".join(steps) + "\n" + "\n".join(lines)
