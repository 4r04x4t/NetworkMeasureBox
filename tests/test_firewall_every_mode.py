"""The box has a firewall in every mode, set up before the WAN comes up (audit netd H1-H3, M9)."""
import unittest
from unittest.mock import MagicMock, call, patch

from nmb.config import Config
from nmb.netd import firewall, modes


class RuleTest(unittest.TestCase):
    def test_host_guard_drops_the_internet_but_not_the_lan_or_vpn(self):
        rules = firewall.host_guard_rules([("udp", 41641), ("udp", 51820)])
        self.assertEqual(rules[-1], "drop")
        self.assertIn('iifname { "lo", "tailscale0", "wg0", "tun0" } accept', rules)
        self.assertTrue(any(r.startswith("ip saddr { 10.0.0.0/8") for r in rules))
        self.assertIn("ip6 saddr @onlink6 accept", rules)
        self.assertIn("udp dport { 41641, 51820 } accept", rules)
        # no port for SSH, DNS, the Web UI or iperf3 from the internet
        self.assertFalse(any("22" in r.split() or "53" in r.split() or "5201" in r for r in rules))
        # 100.64.0.0/10 is other ISP customers on CGNAT, not Tailscale (that comes in on tailscale0)
        self.assertFalse(any("100.64" in r for r in rules))

    def test_bad_ports_ignored(self):
        self.assertEqual(firewall._port_rules("", [("udp", "x"), ("icmp", 1), ("tcp", 0), ("tcp", 70000)]), [])

    def test_wan_guard_covers_each_wan(self):
        with patch.object(firewall, "apply_guard", return_value=True) as ag:
            firewall.apply_wan_guard(["ppp0", "eth3", "ppp0", ""], [("udp", 41641)])
        rules = ag.call_args[0][0]
        self.assertIn('iifname "ppp0" drop', rules)
        self.assertIn('iifname "eth3" drop', rules)
        self.assertEqual(sum(r == 'iifname "ppp0" drop' for r in rules), 1)

    def test_guard_is_its_own_table_not_the_boot_one(self):
        text = firewall.guard_ruleset(firewall.host_guard_rules([]), [])
        self.assertIn("table inet nmb_host {", text)
        self.assertIn("delete table inet nmb_host", text)     # replaced in one transaction
        self.assertNotIn("nmb_guard", text)

    def test_onlink_prefixes_from_routes(self):
        out = ("2a01:36d:1200:5a00::/64 dev eth0 proto ra metric 100 pref medium\n"
               "fd42:42:42::/64 dev wg0 proto kernel metric 256\n"
               "fe80::/64 dev eth0 proto kernel metric 256\n"
               "default via fe80::1 dev eth0 proto ra metric 100\n"
               "2001:db8:5::/48 via fe80::1 dev eth0\n"
               "2a02:ab8:1::/64 dev wg0 proto kernel\n")
        with patch.object(firewall.subprocess, "run", return_value=MagicMock(stdout=out)):
            self.assertEqual(firewall.onlink_ipv6_prefixes(), ["2a01:36d:1200:5a00::/64"])

    def test_refresh_only_when_something_changed(self):
        firewall._guard_state.update(rules=firewall.host_guard_rules([("udp", 41641)]), onlink6=["2a01::/64"])
        with patch.object(firewall, "onlink_ipv6_prefixes", return_value=["2a01::/64"]), \
                patch.object(firewall, "apply_guard") as ag:
            firewall.refresh_host_guard([("udp", 41641)])
            ag.assert_not_called()
            firewall.refresh_host_guard([("udp", 41641), ("udp", 51820)])    # WireGuard switched on
            ag.assert_called_once()

    def test_refresh_does_nothing_in_router_mode(self):
        firewall._guard_state.update(rules=firewall.wan_input_rules("ppp0", []), onlink6=[])
        with patch.object(firewall, "apply_guard") as ag:
            firewall.refresh_host_guard([("udp", 41641)])
        ag.assert_not_called()


class NatTest(unittest.TestCase):
    def _nft(self, ok=True, **kw):
        res = MagicMock(returncode=0 if ok else 1, stderr="boom")
        with patch.object(firewall.shutil, "which", side_effect=lambda b: "/usr/sbin/nft" if b == "nft" else None), \
                patch.object(firewall, "_set_sysctl_forward") as fwd, \
                patch.object(firewall.subprocess, "run", return_value=res) as run:
            r = firewall.enable_nat_mode_a("ppp0", ["br-lan"], **kw)
        return r, fwd, run

    def test_forwarding_only_after_the_rules(self):
        r, fwd, _ = self._nft(ok=True)
        self.assertTrue(r)
        fwd.assert_called_once_with(True)

    def test_failure_returns_false_and_leaves_forwarding_alone(self):
        r, fwd, _ = self._nft(ok=False)
        self.assertFalse(r)
        fwd.assert_not_called()

    def test_wan2_gets_nat_and_protection(self):
        _, _, run = self._nft(extra_wans=["eth3"])
        text = run.call_args.kwargs["input"]
        self.assertIn('oifname {"ppp0", "eth3"} masquerade', text)
        self.assertIn('iifname "eth3" drop', text)
        self.assertIn('iifname {"br-lan"} oifname {"ppp0", "eth3"} accept', text)

    def test_iptables_fallback_covers_ipv6_and_never_flushes(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=1 if "-C" in cmd else 0, stdout="", stderr="")

        bins = {"iptables": "/usr/sbin/iptables", "ip6tables": "/usr/sbin/ip6tables"}
        with patch.object(firewall.shutil, "which", side_effect=bins.get), \
                patch.object(firewall, "_set_sysctl_forward"), \
                patch.object(firewall.subprocess, "run", side_effect=run):
            self.assertTrue(firewall.enable_nat_mode_a("ppp0", ["br-lan"], open_ports=[("udp", 41641)]))
            firewall.disable_nat()
        v6 = [c for c in calls if c[0].endswith("ip6tables")]
        self.assertTrue(any("NMB-HOST" in c and "DROP" in c and "ppp0" in c for c in v6))
        self.assertTrue(any("FORWARD" in c and "ppp0" in c and "DROP" in c for c in v6))
        self.assertFalse(any("-F" in c and "nat" in c for c in calls), "never flush the whole nat table")
        self.assertTrue(any("-D" in c and "MASQUERADE" in c for c in calls), "our own rule is removed")

    def test_no_ip6tables_turns_ipv6_forwarding_off(self):
        with patch.object(firewall.shutil, "which", side_effect={"iptables": "/usr/sbin/iptables"}.get), \
                patch.object(firewall, "_set_sysctl_forward"), \
                patch.object(firewall, "_set_ipv6_forward") as v6, \
                patch.object(firewall.subprocess, "run", return_value=MagicMock(returncode=0)):
            firewall.enable_nat_mode_a("ppp0", ["br-lan"])
        v6.assert_called_with(False)


class ModeOrderTest(unittest.TestCase):
    def _mode_a(self):
        cfg = Config()
        cfg.network.pppoe_enabled = True
        cfg.network.pppoe_user = "user@isp"
        cfg.network.wan_interface = "eth0"
        cfg.network.lan_ports = ["eth1"]
        cfg.network.wifi_enabled = False
        order = MagicMock()
        svc = order.svc
        mode = modes.ModeA(cfg.network, svc)
        mode.full_cfg = cfg
        ifs = MagicMock()
        ifs.interface_exists.side_effect = lambda n: n in ("eth0", "eth1")
        ifs.usb_tether_kind.return_value = None
        fw = order.fw
        fw.enable_nat_mode_a.return_value = True
        return mode, order, ifs, fw

    def test_guard_before_pppd_and_pppd_stopped_before_rules_removed(self):
        mode, order, ifs, fw = self._mode_a()
        with patch.object(modes, "interfaces", ifs), patch.object(modes, "firewall", fw), \
                patch.object(mode, "_start_ra_watch"), patch.object(mode, "_renew_lan_clients"), \
                patch.object(mode, "_usb_wan_candidate", return_value=None):
            mode.setup()
            names = [c[0] for c in order.mock_calls]
            self.assertLess(names.index("fw.apply_wan_guard"), names.index("svc.start_pppd"))
            self.assertEqual(order.fw.apply_wan_guard.call_args_list[0][0][0], ["ppp0"])
            order.reset_mock()
            mode.teardown()
            names = [c[0] for c in order.mock_calls]
            self.assertLess(names.index("svc.stop_all"), names.index("fw.disable_nat"))

    def test_failed_rules_switch_forwarding_off(self):
        mode, order, ifs, fw = self._mode_a()
        fw.enable_nat_mode_a.return_value = False
        with patch.object(modes, "interfaces", ifs), patch.object(modes, "firewall", fw), \
                patch.object(mode, "_start_ra_watch"), patch.object(mode, "_renew_lan_clients"), \
                patch.object(mode, "_usb_wan_candidate", return_value=None):
            mode.setup()
        fw._set_sysctl_forward.assert_called_with(False)
        self.assertTrue(mode.firewall_error)

    def test_standalone_and_bridge_put_the_host_guard_up_first(self):
        cfg = Config()
        for cls in (modes.ModeStandalone, modes.ModeB):
            order = MagicMock()
            mode = cls(cfg.network, order.svc)
            ifs = MagicMock()
            ifs.interface_exists.return_value = False
            ifs.get_default_gateway_iface.return_value = "eth0"
            with patch.object(modes, "interfaces", ifs), patch.object(modes, "firewall", order.fw), \
                    patch.object(modes.lan_topology, "apply_topology", return_value=None), \
                    patch.object(modes, "_box_open_ports", return_value=[("udp", 41641)]), \
                    patch.object(modes.ModeB, "_request_management_ip"):
                mode.setup()
            names = [c[0] for c in order.mock_calls]
            self.assertEqual(names[0], "fw.apply_host_guard", cls.__name__)
            order.fw.apply_host_guard.assert_called_once_with([("udp", 41641)])



class RunningVpnPortTest(unittest.TestCase):
    def test_running_server_keeps_its_port_open_even_if_disabled_in_config(self):
        from nmb.netd import port_forward
        cfg = Config()
        cfg.openvpn.enabled = False
        cfg.wireguard.enabled = False
        with patch.object(port_forward.Path, "exists", lambda self: str(self) == "/sys/class/net/tun0"):
            ports = port_forward.box_open_ports(cfg)
        self.assertIn(("udp", 1194), ports)
        self.assertNotIn(("udp", 51820), ports)


if __name__ == "__main__":
    unittest.main()
