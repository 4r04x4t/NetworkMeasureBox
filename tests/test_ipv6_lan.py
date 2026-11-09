"""IPv6 for the LAN in router mode: prefix delegation on the PPPoE WAN and router adverts on the LAN.

2026-11-09, DIGI PPPoE: ppp0 gets its own address by a router advert, and DHCPv6-PD hands out a /64 for
the LAN (seen with dhcpcd on the box). Before this, LAN and Wi-Fi clients of router mode had no IPv6.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nmb.config import Config, load_config, save_config
from nmb.netd import ipv6_lan, modes, services


class Ipv6LanConfigTest(unittest.TestCase):
    def test_dhcpcd_asks_only_for_a_prefix(self):
        conf = ipv6_lan.dhcpcd_conf("ppp0", "br-lan")
        self.assertIn("allowinterfaces ppp0", conf)
        self.assertIn("ipv6only", conf)
        self.assertIn("noipv6rs", conf)               # the kernel takes ppp0's own router advert
        self.assertIn("nohook resolv.conf", conf)
        self.assertIn("ia_pd 1 br-lan/0/64", conf)
        self.assertNotIn("ia_na", conf)

    def test_dnsmasq_advertises_the_prefix(self):
        lines = ipv6_lan.dnsmasq_ra_lines(["br-lan"])
        self.assertIn("enable-ra", lines)
        self.assertIn("dhcp-range=::,constructor:br-lan,ra-stateless,ra-names,64,12h", lines)
        self.assertIn("dhcp-option=option6:dns-server,[::]", lines)
        self.assertEqual(ipv6_lan.dnsmasq_ra_lines([]), "")

    def _dnsmasq_conf(self, lan_ipv6):
        cfg = Config()
        cfg.network.lan_ipv6 = lan_ipv6
        with tempfile.TemporaryDirectory() as d:
            mgr = services.ServiceManager.__new__(services.ServiceManager)
            mgr.cfg, mgr.run_dir, mgr.processes = cfg.network, Path(d), {}
            with patch.object(services.shutil, "which", return_value="/usr/sbin/dnsmasq"), \
                 patch.object(services, "_service_active", return_value=False), \
                 patch.object(services.ManagedProcess, "start", return_value=True):
                mgr.start_dnsmasq(["br-lan"])
            return (Path(d) / "dnsmasq.conf").read_text()

    def test_router_dnsmasq_has_ra_only_when_on(self):
        self.assertIn("enable-ra", self._dnsmasq_conf(True))
        self.assertNotIn("enable-ra", self._dnsmasq_conf(False))

    def test_setting_round_trip_default_on(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nmb.conf"
            cfg = load_config(path)
            self.assertTrue(cfg.network.lan_ipv6)
            cfg.network.lan_ipv6 = False
            save_config(cfg, path)
            self.assertFalse(load_config(path).network.lan_ipv6)


class Ipv6LanWatchTest(unittest.TestCase):
    def setUp(self):
        self.svc = MagicMock()
        self.svc.processes = {}
        self.mode = modes.ModeA(Config().network, self.svc)
        self.mode.active_wan, self.mode.lan_ifaces = "ppp0", ["br-lan"]

    def _check(self, idx):
        real = Path.read_text

        def fake(self_path, *a, **k):
            if str(self_path) == "/sys/class/net/ppp0/ifindex":
                if idx is None:
                    raise FileNotFoundError(self_path)
                return idx + "\n"
            return real(self_path, *a, **k)
        with patch.object(Path, "read_text", fake):
            self.mode.check_ipv6_lan()

    def test_waits_for_ppp0_then_follows_redials(self):
        self._check(None)
        self.svc.start_dhcpcd_pd.assert_not_called()
        self._check("41")
        self.svc.start_dhcpcd_pd.assert_called_once_with("ppp0", "br-lan")
        running = MagicMock()
        running.is_running.return_value = True
        self.svc.processes = {"dhcpcd-pd": running}
        self._check("41")
        self.assertEqual(self.svc.start_dhcpcd_pd.call_count, 1)    # same ppp0: left alone
        self._check("57")                                          # redial: a new ppp0
        self.assertEqual(self.svc.start_dhcpcd_pd.call_count, 2)

    def test_not_without_pppoe_or_when_off(self):
        self.mode.active_wan = "eth1"
        self._check("41")
        self.mode.active_wan = "ppp0"
        self.mode.cfg.lan_ipv6 = False
        self._check("41")
        self.svc.start_dhcpcd_pd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
