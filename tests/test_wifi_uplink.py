"""Where speed tests run (Ethernet, Wi-Fi or automatic) and the Wi-Fi uplink routing."""
import unittest
from types import SimpleNamespace
from unittest import mock

from nmb.netd import interfaces, wifi_uplink


def _cfg(link, enabled=True):
    return SimpleNamespace(
        network=SimpleNamespace(measurement_link=link, measurement_interface="wan", wan_interface="eth0", wan2_interface=""),
        wifi_uplink=SimpleNamespace(enabled=enabled, interface="wlan0", ssid="Home", password="pw", hidden=False),
    )


class MeasurementLinkTest(unittest.TestCase):
    def _pick(self, link, wired):
        with mock.patch.object(interfaces, "find_active_wired_interface", return_value=wired), \
             mock.patch.object(interfaces, "interface_exists", return_value=True), \
             mock.patch.object(interfaces, "get_ip_addresses", side_effect=lambda i: ["192.168.1.30/24"] if i == "wlan0" else ["192.168.1.20/24"]):
            return interfaces.find_preferred_measurement_interface(_cfg(link))

    def test_auto_prefers_a_cable(self):
        self.assertEqual(self._pick("auto", ("eth0", "192.168.1.20")), ("eth0", "192.168.1.20", True))

    def test_wifi_only_uses_wifi_even_with_a_cable(self):
        self.assertEqual(self._pick("wifi", ("eth0", "192.168.1.20")), ("wlan0", "192.168.1.30", False))

    def test_ethernet_only_never_uses_wifi(self):
        iface, ip, wired = self._pick("ethernet", None)
        self.assertEqual((iface, ip, wired), ("eth0", None, True))


class SourceRoutingTest(unittest.TestCase):
    def test_rule_and_table_for_the_wifi_address(self):
        calls = []

        def run(cmd, timeout=15.0):
            calls.append(cmd)
            if cmd[:4] == ["ip", "-4", "-o", "addr"]:
                return 0, "3: wlan0    inet 192.168.1.30/24 brd 192.168.1.255 scope global wlan0", ""
            if cmd[:4] == ["ip", "-4", "route", "show"]:
                return 0, "default via 192.168.1.1 dev wlan0 proto dhcp metric 700", ""
            return 0, "", ""

        with mock.patch.object(wifi_uplink, "_run", side_effect=run):
            self.assertTrue(wifi_uplink.sync_source_routing(_cfg("wifi")))
        self.assertIn(["ip", "-4", "route", "replace", "default", "via", "192.168.1.1", "dev", "wlan0", "table", "150"], calls)
        self.assertIn(["ip", "-4", "rule", "add", "priority", "150", "from", "192.168.1.30", "lookup", "150"], calls)

    def test_rule_removed_when_off(self):
        calls = []
        with mock.patch.object(wifi_uplink, "_run", side_effect=lambda cmd, timeout=15.0: calls.append(cmd) or (0, "", "")):
            self.assertFalse(wifi_uplink.sync_source_routing(_cfg("ethernet", enabled=False)))
        self.assertIn(["ip", "-4", "rule", "del", "priority", "150"], calls)

    def test_wifi_joined_outside_nmb_still_gets_the_rule(self):
        calls = []

        def run(cmd, timeout=15.0):
            calls.append(cmd)
            if cmd[:4] == ["ip", "-4", "-o", "addr"]:
                return 0, "3: wlan0    inet 192.168.8.219/24 scope global wlan0", ""
            if cmd[:4] == ["ip", "-4", "route", "show"]:
                return 0, "default via 192.168.8.1 dev wlan0 proto dhcp metric 600", ""
            return 0, "", ""

        with mock.patch.object(wifi_uplink, "_run", side_effect=run):
            self.assertTrue(wifi_uplink.sync_source_routing(_cfg("auto", enabled=False)))
        self.assertIn(["ip", "-4", "rule", "add", "priority", "150", "from", "192.168.8.219", "lookup", "150"], calls)

    def test_iw_found_outside_the_path(self):
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(wifi_uplink.Path, "exists", lambda self: str(self) == "/usr/sbin/iw"):
            self.assertEqual(wifi_uplink._iw(), "/usr/sbin/iw")

    def test_connect_needs_an_ssid(self):
        cfg = _cfg("auto")
        cfg.wifi_uplink.ssid = ""
        self.assertFalse(wifi_uplink.connect(cfg)[0])


if __name__ == "__main__":
    unittest.main()
