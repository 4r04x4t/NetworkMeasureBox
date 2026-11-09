"""PPPoE dialing without hammering the ISP, and USB taking over a default route that leads nowhere.

Both came from the real PPPoE test of 2026-11-09: a wrong login was sent 5 times in 40 s (pppd with
`maxfail 0`), after which the ISP did not answer for a while; and the box stayed on the home router's
Wi-Fi after the router's internet cable was pulled, while the hotspot on USB worked.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.config import Config
from nmb.netd import firewall, modes, services, usb_uplink


class PppdCommandTest(unittest.TestCase):
    def _cmd(self, **kw):
        cfg = SimpleNamespace(pppoe_user="u", pppoe_password="p", pppoe_service_name="")
        with TemporaryDirectory() as d, patch.object(services, "kernel_pppoe_plugin", return_value="pppoe.so"):
            return services.build_pppd_cmd("/usr/sbin/pppd", cfg, "eth0", Path(d) / "o", **kw)

    def test_pppd_gives_up_after_a_few_failures(self):
        cmd = self._cmd()
        self.assertEqual(cmd[cmd.index("maxfail") + 1], "3")
        self.assertIn("persist", cmd)

    def test_selftest_dials_once(self):
        cmd = self._cmd(maxfail=1)
        self.assertEqual(cmd[cmd.index("maxfail") + 1], "1")


class PppdWatchTest(unittest.TestCase):
    def setUp(self):
        self.svc = MagicMock()
        self.mode = modes.ModeA(Config().network, self.svc)
        self.mode.pppoe_iface = "eth0"
        self.mode.active_wan = "ppp0"
        self.ifs = patch.object(modes, "interfaces", MagicMock())
        self.ifs.start().get_ip_addresses.return_value = []
        self.addCleanup(self.ifs.stop)
        self.events = patch("nmb.netd.usb_uplink._log_event")
        self.logged = self.events.start()
        self.addCleanup(self.events.stop)

    def test_refused_login_waits_longer_each_time(self):
        self.svc.pppd_exit_code.return_value = services.PPPD_EXIT_AUTH
        self.mode.check_pppd(now=1000)
        self.assertIn("refused", self.mode.pppoe_error)
        self.assertEqual(self.mode._pppd_retry_at, 1000 + 600)
        self.svc.start_pppd.assert_not_called()
        self.mode.check_pppd(now=1599)
        self.svc.start_pppd.assert_not_called()      # still pausing
        self.mode.check_pppd(now=1600)
        self.svc.start_pppd.assert_called_once_with("eth0")
        self.mode.check_pppd(now=1700)                  # refused again
        self.assertEqual(self.mode._pppd_retry_at, 1700 + 1200)
        self.assertEqual(self.logged.call_count, 2)

    def test_pause_is_capped(self):
        self.svc.pppd_exit_code.return_value = services.PPPD_EXIT_AUTH
        self.mode.pppoe_auth_fails = 10
        self.mode.check_pppd(now=0)
        self.assertEqual(self.mode._pppd_retry_at, 1800)

    def test_line_problem_retries_soon(self):
        self.svc.pppd_exit_code.return_value = 8
        self.mode.check_pppd(now=50)
        self.assertEqual(self.mode._pppd_retry_at, 80)
        self.assertIn("no PPPoE server", self.mode.pppoe_error)
        self.logged.assert_not_called()

    def test_link_up_clears_the_error(self):
        self.mode.pppoe_error, self.mode.pppoe_auth_fails = "the ISP refused", 2
        self.svc.pppd_exit_code.return_value = None
        modes.interfaces.get_ip_addresses.return_value = ["100.64.1.2/32"]
        self.mode.check_pppd(now=10)
        self.assertEqual((self.mode.pppoe_error, self.mode.pppoe_auth_fails), ("", 0))

    def test_nothing_to_do_without_pppoe(self):
        self.mode.active_wan, self.mode.pppoe_iface = "eth0", ""
        self.svc.pppd_exit_code.return_value = services.PPPD_EXIT_AUTH
        self.mode.check_pppd(now=0)
        self.assertEqual(self.mode.pppoe_error, "")


class UsbRescueRouteTest(unittest.TestCase):
    """Wi-Fi default route present (home router without internet), hotspot on USB works."""

    def setUp(self):
        self.cfg = Config()
        self.cfg.usb_uplink.enabled = True
        usb_uplink._fallback_active = None
        usb_uplink._rescue.update(active=False, fails=0, oks=0, ts=-1e9)
        self.addCleanup(usb_uplink._rescue.update, active=False, fails=0, oks=0, ts=-1e9)
        self.calls = []
        self.wifi_ok = False
        self.rescue_route = ""

    def run_cmd(self, cmd, timeout=15.0):
        line = " ".join(cmd)
        self.calls.append(line)
        if cmd[:5] == ["ip", "-4", "route", "show", "default"]:
            if len(cmd) == 5:
                return 0, "default via 192.168.8.1 dev wlan0 proto dhcp src 192.168.8.219 metric 600\n" + self.rescue_route, ""
            if cmd[5:] == ["metric", "40"]:
                return 0, self.rescue_route, ""
            return 0, "", ""
        if "route replace default" in line and "metric 40" in line:
            self.rescue_route = "default via 192.168.1.1 dev eth1 metric 40\n"
        if "route del default metric 40" in line:
            self.rescue_route = ""
        if cmd[0] == "ping":
            dev = cmd[cmd.index("-I") + 1]
            return (0 if dev == "eth1" or self.wifi_ok else 1), "", ""
        return 0, "", ""

    def sync(self, now, allow=True):
        with patch.object(usb_uplink, "uplink_interface", return_value="eth1"), \
             patch.object(usb_uplink, "_address_and_gateway", return_value=("192.168.1.4", "192.168.1.1")), \
             patch.object(usb_uplink, "_is_bridge_port", return_value=False), \
             patch.object(usb_uplink, "_log_event") as ev, \
             patch.object(usb_uplink, "_run", side_effect=self.run_cmd):
            usb_uplink.sync_default_fallback(self.cfg, allow_rescue=allow, now=now)
            return ev

    def test_usb_takes_over_a_dead_wifi_route_and_gives_it_back(self):
        self.sync(0)
        self.sync(30)
        self.assertFalse(usb_uplink.rescue_active())       # two failed probes: not yet
        ev = self.sync(60)
        self.assertTrue(usb_uplink.rescue_active())
        self.assertTrue(any("route replace default via 192.168.1.1 dev eth1 metric 40" in c for c in self.calls))
        self.assertEqual(ev.call_args[0][0], "uplink_usb_rescue")
        self.wifi_ok = True
        self.sync(90)
        self.assertTrue(usb_uplink.rescue_active())        # one good probe: keep USB
        ev = self.sync(120)
        self.assertFalse(usb_uplink.rescue_active())
        self.assertTrue(any("route del default metric 40" in c for c in self.calls))
        self.assertEqual(ev.call_args[0][0], "uplink_usb_rescue_end")

    def test_probes_at_most_every_30_seconds(self):
        self.sync(0)
        pings = sum(c.startswith("ping") for c in self.calls)
        self.sync(10)
        self.sync(20)
        self.assertEqual(sum(c.startswith("ping") for c in self.calls), pings)

    def test_working_wifi_keeps_its_route(self):
        self.wifi_ok = True
        for t in (0, 30, 60, 90):
            self.sync(t)
        self.assertFalse(usb_uplink.rescue_active())
        self.assertFalse(any("metric 40" in c and "replace" in c for c in self.calls))

    def test_router_mode_never_rescues(self):
        for t in (0, 30, 60, 90):
            self.sync(t, allow=False)
        self.assertFalse(usb_uplink.rescue_active())
        self.assertFalse(any(c.startswith("ping") for c in self.calls))


class WanFirewallTest(unittest.TestCase):
    """A public address on ppp0 (2026-11-09): only answers, ICMP and the VPN ports from the internet."""

    def _rules(self, **kw):
        with patch.object(firewall.shutil, "which", side_effect=lambda b: "/usr/sbin/nft" if b == "nft" else None), \
             patch.object(firewall, "_set_sysctl_forward"), \
             patch.object(firewall.subprocess, "run") as run:
            run.return_value.returncode = 0
            firewall.enable_nat_mode_a("ppp0", ["br-lan"], **kw)
        return run.call_args.kwargs["input"]

    def test_everything_else_is_dropped_on_the_wan(self):
        rules = self._rules(open_ports=[("udp", 41641), ("udp", 51820), ("tcp", 1194)])
        self.assertIn('iifname "ppp0" ct state established,related accept', rules)
        self.assertIn('iifname "ppp0" udp dport { 41641, 51820 } accept', rules)
        self.assertIn('iifname "ppp0" tcp dport { 1194 } accept', rules)
        self.assertIn('iifname "ppp0" meta l4proto ipv6-icmp accept', rules)
        self.assertTrue(rules.index('iifname "ppp0" drop') > rules.index('udp dport { 41641, 51820 }'))
        self.assertNotIn("dport 22", rules)
        self.assertNotIn("100.64.0.0/10", rules)       # CGNAT neighbours of the ISP are the internet too

    def test_private_sources_keep_full_access(self):
        rules = self._rules()
        self.assertIn('iifname "ppp0" ip saddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 } accept', rules)
        self.assertLess(rules.index("192.168.0.0/16"), rules.index('iifname "ppp0" drop'))

    def test_sharing_without_protection_has_no_drop(self):
        rules = self._rules(block_public_wan=False)
        self.assertNotIn('iifname "ppp0" drop', rules)

    def test_router_opens_only_the_vpns_that_are_on(self):
        cfg = Config()
        cfg.wireguard.enabled, cfg.openvpn.enabled, cfg.openvpn.proto, cfg.openvpn.port = True, True, "tcp", 443
        mode = modes.ModeA(cfg.network, MagicMock())
        mode.full_cfg = cfg
        self.assertEqual(mode._wan_open_ports(), [("udp", 41641), ("udp", 51820), ("tcp", 443)])
        cfg.wireguard.enabled = cfg.openvpn.enabled = False
        self.assertEqual(mode._wan_open_ports(), [("udp", 41641)])

    def test_rules_load_in_nft(self):
        import shutil, subprocess
        nft = shutil.which("nft")
        if not nft:
            self.skipTest("nft not installed")
        rules = self._rules(open_ports=[("udp", 41641)], dmz_iface="eth2")
        res = subprocess.run([nft, "-c", "-f", "-"], input=rules, text=True, capture_output=True)
        if "Operation not permitted" in res.stderr or "Permission denied" in res.stderr:
            self.skipTest("nft -c needs root here")
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()


class PppdOptionsFileTest(unittest.TestCase):
    """2026-11-09: after an update the old options file belonged to nmb; nmb-netd (no CAP_FOWNER) could not
    chmod it and router mode on PPPoE did not start. The file is now written new and moved over."""

    def test_old_file_is_replaced_not_edited(self):
        import os
        cfg = SimpleNamespace(pppoe_user="u", pppoe_password="p", pppoe_service_name="")
        with TemporaryDirectory() as d, patch.object(services, "kernel_pppoe_plugin", return_value="pppoe.so"):
            path = Path(d) / "ppp-options"
            path.write_text("old")
            os.chmod(path, 0o660)
            ino = path.stat().st_ino
            with patch.object(services.os, "chmod", side_effect=PermissionError(1, "Operation not permitted")):
                services.build_pppd_cmd("/usr/sbin/pppd", cfg, "eth0", path)
            self.assertNotEqual(path.stat().st_ino, ino)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('password "p"', path.read_text())
            self.assertEqual([p.name for p in Path(d).iterdir()], ["ppp-options"])

    def test_installer_does_not_chown_run_files(self):
        text = (Path(__file__).resolve().parent.parent / "setup.sh").read_text()
        self.assertNotRegex(text, r"chown -R [^\n]*/run/nmb")
