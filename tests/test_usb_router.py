"""USB tethering as the only internet: default-route fallback, sharing on the LAN port, router mode."""
import unittest
from unittest.mock import MagicMock, patch

from nmb.config import Config
from nmb.netd import modes, usb_uplink, wifi_share


def _router(cfg, dhcp_on_wan):
    svc = MagicMock()
    mode = modes.ModeA(cfg.network, svc)
    mode.full_cfg = cfg
    ifs = MagicMock()
    ifs.interface_exists.return_value = True
    ifs.get_carrier.return_value = True
    ifs.get_ip_addresses.return_value = []
    ifs.usb_tether_kind.side_effect = lambda name: "tether" if name == "eth1" else None
    patches = [
        patch.object(modes, "interfaces", ifs),
        patch.object(modes, "firewall", MagicMock()),
        patch.object(usb_uplink, "uplink_interface", return_value="eth1"),
        patch.object(usb_uplink, "_address_and_gateway", return_value=("192.168.1.4", "192.168.1.1")),
        patch("nmb.netd.wifi_share.probe_dhcp_servers", return_value=["192.168.8.1"] if dhcp_on_wan else []),
        patch("nmb.netd.wifi.unblock_wifi", create=True),
    ]
    return mode, svc, ifs, patches


class UsbRouterModeTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.cfg.usb_uplink.enabled = True
        self.cfg.network.wan_interface = "eth0"
        self.cfg.network.lan_interface = "eth1"     # the default LAN name, which is the hotspot here
        self.cfg.network.lan_ports = ["eth1"]
        self.cfg.network.wifi_enabled = True

    def _setup(self, dhcp_on_wan):
        mode, svc, ifs, patches = _router(self.cfg, dhcp_on_wan)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        mode.setup()
        return mode, svc, ifs

    def test_nothing_upstream_on_the_port_makes_usb_the_wan(self):
        mode, svc, ifs = self._setup(dhcp_on_wan=False)
        self.assertEqual(mode.usb_wan, "eth1")
        self.assertEqual(mode.active_wan, "eth1")
        bridge_members = ifs.setup_bridge.call_args[0][1]
        self.assertIn("eth0", bridge_members)          # the single Ethernet port serves the LAN
        self.assertNotIn("eth1", bridge_members)       # the hotspot is never a LAN port
        modes.firewall.enable_nat_mode_a.assert_called_once()
        self.assertEqual(modes.firewall.enable_nat_mode_a.call_args[0][0], "eth1")
        svc.start_hostapd.assert_called_once()          # Wi-Fi clients get the USB internet too

    def test_a_dhcp_server_on_the_port_keeps_it_as_wan(self):
        mode, svc, ifs = self._setup(dhcp_on_wan=True)
        self.assertIsNone(mode.usb_wan)
        self.assertEqual(mode.active_wan, "eth0")
        for call in ifs.setup_bridge.call_args_list:
            self.assertNotIn("eth1", call[0][1])

    def test_guard_stops_serving_when_a_router_appears_on_the_port(self):
        mode, svc, ifs = self._setup(dhcp_on_wan=False)
        mode._usb_guard_ts = 0.0
        with patch("nmb.netd.wifi_share.probe_dhcp_servers", return_value=["192.168.8.1"]):
            mode.check_usb_wan()
        svc.stop_all.assert_called()
        self.assertTrue(mode.needs_resetup)


class UsbFallbackRouteTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.cfg.usb_uplink.enabled = True
        usb_uplink._fallback_active = None
        self.calls = []

    def _run(self, routes):
        def run(cmd, timeout=15.0):
            self.calls.append(" ".join(cmd))
            if cmd[:5] == ["ip", "-4", "route", "show", "default"] and len(cmd) == 5:
                return 0, routes, ""
            return 0, "", ""
        return run

    def _sync(self, routes):
        with patch.object(usb_uplink, "uplink_interface", return_value="eth1"), \
             patch.object(usb_uplink, "_address_and_gateway", return_value=("192.168.1.4", "192.168.1.1")), \
             patch.object(usb_uplink, "_log_event"), \
             patch.object(usb_uplink, "_run", side_effect=self._run(routes)):
            return usb_uplink.sync_default_fallback(self.cfg)

    def test_usb_becomes_the_internet_only_when_nothing_else_is(self):
        self.assertTrue(self._sync(""))
        self.assertTrue(any("route replace default via 192.168.1.1 dev eth1 metric 900" in c for c in self.calls))

    def test_cable_back_removes_the_fallback(self):
        self.assertFalse(self._sync("default via 192.168.8.1 dev eth0 metric 50\n"))
        self.assertFalse(any("route replace default" in c for c in self.calls))


class RouterWanRouteTest(UsbFallbackRouteTest):
    def tearDown(self):
        usb_uplink.set_router_wan(None)

    def test_router_mode_keeps_the_usb_route_despite_a_stale_lan_route(self):
        usb_uplink.set_router_wan("eth1")
        with patch.object(usb_uplink, "_is_bridge_port", return_value=False):
            self.assertTrue(self._sync("default via 192.168.8.1 dev eth0 proto dhcp metric 102\n"))
        self.assertFalse(any("route del default metric 900" in c for c in self.calls))

    def test_dead_or_bridged_routes_are_not_another_internet(self):
        with patch.object(usb_uplink, "_is_bridge_port", side_effect=lambda d: d == "eth0"):
            self.assertTrue(self._sync("default via 192.168.8.1 dev eth0 metric 102\n"))
        self.calls.clear()
        usb_uplink._fallback_active = None
        with patch.object(usb_uplink, "_is_bridge_port", return_value=False):
            self.assertTrue(self._sync("default via 192.168.8.1 dev wlan0 metric 600 linkdown\n"))


class ShareFromUsbTest(unittest.TestCase):
    def test_upstream_falls_back_to_usb(self):
        cfg = Config()
        cfg.usb_uplink.enabled = True
        with patch("nmb.netd.wifi_uplink.uplink_interface", return_value=None), \
             patch.object(usb_uplink, "uplink_interface", return_value="eth1"), \
             patch.object(usb_uplink, "_address_and_gateway", return_value=("192.168.1.4", "192.168.1.1")):
            self.assertEqual(wifi_share.upstream(cfg), ("eth1", "192.168.1.4", "192.168.1.1", "usb"))



class FallbackEventSchemaTest(unittest.TestCase):
    def test_event_fits_the_real_schema(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        schema = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()
        path = Path(tempfile.mkdtemp()) / "t.db"
        init = sqlite3.connect(path)
        init.executescript(schema)
        init.close()
        with patch("nmb.db.database.connect", lambda *a, **k: sqlite3.connect(path)), \
             patch.object(usb_uplink.log, "warning") as warned:
            usb_uplink._log_event("uplink_usb_fallback", "test")
        warned.assert_not_called()
        rows = sqlite3.connect(path).execute("SELECT kind, severity FROM event").fetchall()
        self.assertEqual(rows, [("uplink_usb_fallback", "warn")])


if __name__ == "__main__":
    unittest.main()
