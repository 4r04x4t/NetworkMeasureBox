"""Port forwarding in router mode: rule checks, nftables rules, UPnP config, settings round trip."""
import ipaddress
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nmb.config import Config, load_config, save_config
from nmb.netd import firewall, modes, port_forward as pf

LAN = ipaddress.IPv4Network("192.168.100.0/24")
GW = "192.168.100.1"


def rule(**kw):
    r = {"name": "nas", "proto": "tcp", "ext": "8443", "ip": "192.168.100.20", "port": 443, "on": True}
    r.update(kw)
    return r


class RuleCheckTest(unittest.TestCase):
    def test_good_rule_is_normalised(self):
        self.assertEqual(pf.clean_rule(rule(ext=" 8443 ", port="443"), LAN, GW),
                         {"name": "nas", "proto": "tcp", "ext": "8443", "ip": "192.168.100.20", "port": 443, "on": True})

    def test_same_port_when_device_port_is_empty(self):
        self.assertEqual(pf.clean_rule(rule(port=""), LAN, GW)["port"], 8443)

    def test_range_keeps_its_ports(self):
        r = pf.clean_rule(rule(ext="6881-6889", port=0, proto="both"), LAN, GW)
        self.assertEqual((r["ext"], r["port"], r["proto"]), ("6881-6889", 0, "both"))
        with self.assertRaises(pf.RuleError):
            pf.clean_rule(rule(ext="6881-6889", port=7000), LAN, GW)

    def test_bad_rules_say_why(self):
        for bad, word in ((rule(ip="10.0.0.5"), "must be a device"), (rule(ip=GW), "not the box"),
                          (rule(ip="192.168.100.255"), "must be a device"), (rule(ext="70000"), "1-65535"),
                          (rule(ext="9-1"), "1-65535"), (rule(ext="abc"), "not a number"), (rule(proto="icmp"), "tcp, udp"),
                          (rule(ext="1-2000"), "longer than"), (rule(name="x" * 40), "at most 32"),
                          (rule(ip="nas.local"), "not an IPv4")):
            with self.assertRaises(pf.RuleError) as ctx:
                pf.clean_rule(bad, LAN, GW)
            self.assertIn(word, str(ctx.exception))

    def test_overlaps_and_box_ports_are_refused(self):
        with self.assertRaises(pf.RuleError) as ctx:
            pf.clean_rules([rule(), rule(name="b", ext="8440-8450", ip="192.168.100.21", port=0)], LAN, GW)
        self.assertIn("overlaps rule 1", str(ctx.exception))
        # different protocol: no overlap
        pf.clean_rules([rule(), rule(name="b", proto="udp", ip="192.168.100.21")], LAN, GW)
        # a switched-off rule does not block another
        pf.clean_rules([rule(on=False), rule(name="b", ip="192.168.100.21")], LAN, GW)
        with self.assertRaises(pf.RuleError) as ctx:
            pf.clean_rules([rule(proto="udp", ext="41641", port=0)], LAN, GW, reserved=[("udp", 41641)])
        self.assertIn("used by the box itself", str(ctx.exception))

    def test_unreadable_config_means_no_rules(self):
        self.assertEqual(pf.parse_config_rules("{not json"), [])
        self.assertEqual(pf.parse_config_rules('{"a": 1}'), [])
        self.assertEqual(pf.parse_config_rules(""), [])

    def test_active_rules_skip_off_and_broken_ones(self):
        cfg = Config()
        cfg.port_forward.rules = [rule(), rule(name="off", ext="9000", on=False), rule(name="bad", ip="8.8.8.8", ext="9001")]
        self.assertEqual(pf.active_rules(cfg), [])            # forwarding itself is off
        cfg.port_forward.enabled = True
        self.assertEqual([r["name"] for r in pf.active_rules(cfg)], ["nas"])


class NftRulesTest(unittest.TestCase):
    def test_dnat_and_hairpin(self):
        pre, post = pf.nat_rules("ppp0", '{"br-lan"}', GW, LAN,
                                 [pf.clean_rule(rule(), LAN, GW), pf.clean_rule(rule(name="t", proto="both", ext="6881-6889", port=0, ip="192.168.100.30"), LAN, GW)])
        self.assertIn('iifname "ppp0" tcp dport 8443 dnat ip to 192.168.100.20:443', pre)
        self.assertIn('iifname "ppp0" meta l4proto { tcp, udp } th dport 6881-6889 dnat ip to 192.168.100.30', pre)
        self.assertTrue(any("fib daddr type local ip daddr != 192.168.100.1 tcp dport 8443" in r for r in pre))
        self.assertEqual(post, ['oifname {"br-lan"} ip saddr 192.168.100.0/24 ip daddr 192.168.100.0/24 ct status dnat masquerade'])

    def _ruleset(self, forwards):
        with patch.object(firewall.shutil, "which", side_effect=lambda b: "/usr/sbin/nft" if b == "nft" else None), \
             patch.object(firewall, "_set_sysctl_forward"), patch.object(firewall.subprocess, "run") as run:
            run.return_value.returncode = 0
            firewall.enable_nat_mode_a("ppp0", ["br-lan"], open_ports=[("udp", 41641)], forwards=forwards, gateway_ip=GW)
        return run.call_args.kwargs["input"]

    def test_ruleset_replaces_the_table_atomically(self):
        rs = self._ruleset([pf.clean_rule(rule(), LAN, GW)])
        self.assertTrue(rs.lstrip().startswith("table inet nmb_nat\ndelete table inet nmb_nat\n"))
        self.assertIn("type nat hook prerouting priority dstnat", rs)
        self.assertIn('iifname "ppp0" ct status dnat accept', rs)
        self.assertLess(rs.index("ct status dnat masquerade"), rs.index('oifname "ppp0" masquerade'))

    def test_no_prerouting_chain_without_rules(self):
        self.assertNotIn("prerouting", self._ruleset([]))

    def test_wan_to_lan_is_dropped_but_answers_and_forwards_pass(self):
        rs = self._ruleset([])
        fwd = rs[rs.index("chain forward"):]
        self.assertLess(fwd.index("ct state established,related accept"), fwd.index('iifname "ppp0" drop'))
        self.assertLess(fwd.index('iifname "ppp0" ct status dnat accept'), fwd.index('iifname "ppp0" drop'))


class UpnpConfigTest(unittest.TestCase):
    def test_secure_defaults(self):
        conf = pf.miniupnpd_conf("ppp0", "br-lan", LAN, "u-u-i-d", "/run/nmb/upnp.leases")
        self.assertIn("ext_ifname=ppp0", conf)
        self.assertIn("listening_ip=br-lan", conf)
        self.assertIn("secure_mode=yes", conf)
        self.assertIn("allow 1024-65535 192.168.100.0/24 1024-65535", conf)
        self.assertTrue(conf.rstrip().splitlines()[-1].startswith("deny 0-65535 0.0.0.0/0"))
        self.assertIn(f"upnp_nat_table_name={pf.UPNP_TABLE}", conf)
        # miniupnpd 2.3.9 (Debian 13) refuses unknown options and does not start (seen on the box)
        known = {"ext_ifname", "listening_ip", "port", "enable_upnp", "enable_natpmp", "enable_pcp_pmp", "secure_mode",
                 "system_uptime", "notify_interval", "clean_ruleset_interval", "min_lifetime", "max_lifetime", "lease_file",
                 "uuid", "friendly_name", "model_name", "upnp_table_name", "upnp_nat_table_name", "upnp_forward_chain",
                 "upnp_nat_chain", "upnp_nat_postrouting_chain", "upnp_nftables_family_split"}
        for line in conf.splitlines():
            if line and not line.startswith(("allow ", "deny ")):
                self.assertIn(line.split("=")[0], known, line)

    def test_miniupnpd_raw_rule_format(self):
        # as printed on the box (Debian 13, miniupnpd 2.3.9, nft 1.1)
        chain = ('table inet nmb_upnp {\n\tchain prerouting {\n'
                 '\t\tiif "ppp0" @nh,72,8 0x6 th dport 38080 dnat ip to 192.168.100.251:8000\n'
                 '\t\tiif "ppp0" @nh,72,8 0x11 th dport 3478 dnat ip to 192.168.100.41:3478\n\t}\n}\n')
        leases = "TCP:38080:192.168.100.251:8000:1794251400:nmb-selftest\n"
        m = pf.parse_upnp_chain(chain, leases)
        self.assertEqual(m[0], {"proto": "tcp", "ext": 38080, "ip": "192.168.100.251", "port": 8000, "name": "nmb-selftest"})
        self.assertEqual((m[1]["proto"], m[1]["ext"], m[1]["name"]), ("udp", 3478, ""))

    def test_mappings_are_read_from_the_chain(self):
        out = ('table inet nmb_upnp {\n chain prerouting {\n  iifname "ppp0" tcp dport 51413 dnat ip to 192.168.100.40:51413 comment "Transmission"\n'
               '  iifname "ppp0" udp dport 3478 dnat ip to 192.168.100.41:3478\n }\n}\n')
        with patch.object(pf.shutil, "which", return_value="/usr/sbin/nft"), \
             patch("subprocess.run", return_value=MagicMock(stdout=out)):
            m = pf.upnp_mappings(lease_file="/nonexistent")
        self.assertEqual(m[0], {"proto": "tcp", "ext": 51413, "ip": "192.168.100.40", "port": 51413, "name": ""})
        self.assertEqual(m[1]["proto"], "udp")


class RouterModeTest(unittest.TestCase):
    def test_upnp_waits_for_the_wan_address_and_follows_it(self):
        cfg = Config()
        cfg.port_forward.upnp = True
        svc = MagicMock()
        svc.processes = {}
        mode = modes.ModeA(cfg.network, svc)
        mode.full_cfg, mode.active_wan, mode.lan_ifaces = cfg, "ppp0", ["br-lan"]
        addrs = {"ppp0": []}
        with patch.object(modes, "firewall"), patch.object(modes.interfaces, "get_ip_addresses", side_effect=lambda i: addrs.get(i, [])):
            mode.apply_firewall()
            svc.start_miniupnpd.assert_not_called()          # ppp0 has no address yet
            addrs["ppp0"] = ["198.51.100.7/32"]
            mode.check_upnp()
            svc.start_miniupnpd.assert_called_once()
            running = MagicMock()
            running.is_running.return_value = True
            svc.processes = {"miniupnpd": running}
            mode.check_upnp()
            svc.start_miniupnpd.assert_called_once()          # same address: left alone
            addrs["ppp0"] = ["198.51.100.8/32"]                # redial, new address
            mode.check_upnp()
            svc.stop_miniupnpd.assert_called_once_with(keep_table=True)
            self.assertEqual(svc.start_miniupnpd.call_count, 2)

    def test_router_applies_rules_and_upnp(self):
        cfg = Config()
        cfg.port_forward.enabled, cfg.port_forward.upnp = True, True
        cfg.port_forward.rules = [rule()]
        svc = MagicMock()
        svc.processes = {}
        mode = modes.ModeA(cfg.network, svc)
        mode.full_cfg, mode.active_wan, mode.lan_ifaces = cfg, "ppp0", ["br-lan"]
        with patch.object(modes, "firewall") as fw, \
             patch.object(modes.interfaces, "get_ip_addresses", return_value=["198.51.100.7/32"]):
            mode.apply_firewall()
        kw = fw.enable_nat_mode_a.call_args.kwargs
        self.assertEqual([r["name"] for r in kw["forwards"]], ["nas"])
        self.assertEqual(kw["gateway_ip"], GW)
        svc.start_miniupnpd.assert_called_once()
        cfg.port_forward.upnp = False
        with patch.object(modes, "firewall"):
            mode.apply_firewall()
        svc.stop_miniupnpd.assert_called_once()


class SettingsRoundTripTest(unittest.TestCase):
    def test_rules_survive_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nmb.conf"
            cfg = load_config(path)
            cfg.port_forward.enabled = True
            cfg.port_forward.rules = [rule(), rule(name="game", proto="udp", ext="27015", port=0, ip="192.168.100.60")]
            self.assertTrue(save_config(cfg, path))
            back = load_config(path)
        self.assertTrue(back.port_forward.enabled)
        self.assertFalse(back.port_forward.upnp)
        self.assertEqual(back.port_forward.rules, cfg.port_forward.rules)


if __name__ == "__main__":
    unittest.main()
