"""Wi-Fi shared on the LAN port: DHCP probe packets and when sharing may run."""
import socket
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from nmb.netd import wifi_share


def _offer(xid, server="192.168.8.1", msg=2):
    pkt = bytearray(240)
    pkt[0] = 2
    pkt[4:8] = struct.pack("!I", xid)
    pkt[236:240] = b"\x63\x82\x53\x63"
    return bytes(pkt) + bytes([53, 1, msg, 54, 4]) + socket.inet_aton(server) + b"\xff"


def _cfg(enabled=True):
    return SimpleNamespace(wifi_share=SimpleNamespace(enabled=enabled, lan_interface="eth0", address="192.168.77.1/24"),
                           wifi_uplink=SimpleNamespace(interface="wlan0"), guest_wifi=SimpleNamespace(enabled=False, interface=""))


class DhcpPacketTest(unittest.TestCase):
    def test_discover_is_a_broadcast_request(self):
        pkt = wifi_share.build_discover(b"\x02\x00\x00\x00\x00\x01", 0x1234)
        self.assertEqual(pkt[0], 1)
        self.assertEqual(struct.unpack("!I", pkt[4:8])[0], 0x1234)
        self.assertEqual(struct.unpack("!H", pkt[10:12])[0], 0x8000)
        self.assertIn(b"\x35\x01\x01", pkt[240:])

    def test_offer_names_its_server_and_others_are_ignored(self):
        self.assertEqual(wifi_share.parse_offer_server(_offer(7), 7), "192.168.8.1")
        self.assertIsNone(wifi_share.parse_offer_server(_offer(7), 8))          # other transaction
        self.assertIsNone(wifi_share.parse_offer_server(_offer(7, msg=5), 7))   # an ACK, not an offer
        self.assertIsNone(wifi_share.parse_offer_server(b"short", 7))


class SyncTest(unittest.TestCase):
    def setUp(self):
        wifi_share._last_probe = 0.0
        wifi_share._last_probe_servers = []
        wifi_share._last_carrier = None
        self.states = []
        p = [mock.patch.object(wifi_share, "_write_state", side_effect=lambda **kw: self.states.append(kw)),
             mock.patch.object(wifi_share, "_state", return_value={}),
             mock.patch("nmb.netd.wifi_uplink.uplink_interface", return_value="wlan0"),
             mock.patch("nmb.netd.wifi_uplink._ipv4_and_gateway", return_value=("192.168.8.219", "192.168.8.1")),
             mock.patch.object(wifi_share.Path, "exists", return_value=True),
             mock.patch.object(wifi_share, "_has_carrier", return_value=True),
             mock.patch.object(wifi_share, "_dnsmasq_running", return_value=False)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def test_never_serves_where_another_dhcp_server_answers(self):
        with mock.patch.object(wifi_share, "_default_route_dev", return_value=False), \
             mock.patch.object(wifi_share, "probe_dhcp_servers", return_value=["192.168.8.1"]), \
             mock.patch.object(wifi_share, "_start_dnsmasq") as start:
            res = wifi_share.sync(_cfg())
        self.assertEqual((res["active"], res["code"]), (False, "other_dhcp"))
        start.assert_not_called()

    def test_port_with_its_own_internet_is_left_alone(self):
        with mock.patch.object(wifi_share, "_default_route_dev", return_value=True), \
             mock.patch.object(wifi_share, "probe_dhcp_servers") as probe:
            res = wifi_share.sync(_cfg())
        self.assertEqual(res["code"], "own_internet")
        probe.assert_not_called()

    def test_shares_when_the_port_is_empty(self):
        with mock.patch.object(wifi_share, "_default_route_dev", return_value=False), \
             mock.patch.object(wifi_share, "probe_dhcp_servers", return_value=["192.168.77.1"]), \
             mock.patch.object(wifi_share, "_addresses", return_value=[]), \
             mock.patch.object(wifi_share, "_run", return_value=(1, "", "")), \
             mock.patch.object(wifi_share, "_apply_nat", return_value=True) as nat, \
             mock.patch.object(wifi_share, "_start_dnsmasq", return_value=True) as start:
            res = wifi_share.sync(_cfg())
        self.assertTrue(res["active"])          # its own offer does not count as another server
        nat.assert_called_once()
        start.assert_called_once()
        self.assertTrue(self.states[-1]["active"])

    def test_off_when_disabled(self):
        self.assertEqual(wifi_share.sync(_cfg(enabled=False))["code"], "off")

    def test_cable_plugged_in_stops_dhcp_before_probing(self):
        wifi_share._last_carrier = False
        order = []
        with mock.patch.object(wifi_share, "_default_route_dev", return_value=False), \
             mock.patch.object(wifi_share, "_stop_dnsmasq", side_effect=lambda: order.append("stop")), \
             mock.patch.object(wifi_share, "probe_dhcp_servers", side_effect=lambda i: order.append("probe") or ["10.0.0.1"]):
            wifi_share.sync(_cfg())
        self.assertEqual(order[:2], ["stop", "probe"])

    def test_nat_rules_only_masquerade_the_shared_subnet(self):
        rules = wifi_share.nft_ruleset("192.168.77.0/24", "eth0", "wlan0")
        self.assertIn('ip saddr 192.168.77.0/24 oifname "wlan0" masquerade', rules)
        self.assertIn('iifname "wlan0" oifname "eth0" drop', rules)


if __name__ == "__main__":
    unittest.main()
