"""mode = auto (owner's rule, 2026-11-09): standalone behind a router, router mode without one."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.config import NetworkConfig
from nmb.netd import auto_mode as A
from nmb.netd.detector import NetworkDetector


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def obs(**kw):
    base = dict(carrier=True, lease=False, dhcp_servers=[], internet=False, wired_ports=["eth0"])
    base.update(kw)
    return A.Observation(**base)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.p = A.AutoPolicy(self.clock)
        self.cfg = NetworkConfig(mode="auto")

    def test_router_lease_means_standalone(self):
        d = self.p.decide(self.cfg, obs(lease=True, internet=True), "standalone")
        self.assertEqual((d.mode, d.passthrough_ports), ("standalone", []))

    def test_several_ports_behind_a_router_are_bridged(self):
        d = self.p.decide(self.cfg, obs(lease=True, wired_ports=["eth0", "eth1", "eth2"]), "standalone")
        self.assertEqual(d.mode, "standalone")
        self.assertEqual(d.passthrough_ports, ["eth1", "eth2"])

    def test_router_gone_waits_then_router_mode(self):
        self.assertEqual(self.p.decide(self.cfg, obs(), "standalone").mode, "standalone")   # a router reboot
        self.clock.t += A.ROUTER_MISSING_SEC - 1
        self.assertEqual(self.p.decide(self.cfg, obs(), "standalone").mode, "standalone")
        self.clock.t += 2
        self.assertEqual(self.p.decide(self.cfg, obs(), "standalone").mode, "mode_a")

    def test_no_cable_at_start_is_router_mode_at_once(self):
        self.assertEqual(self.p.decide(self.cfg, obs(carrier=False), None).mode, "mode_a")

    def test_router_back_means_standalone_at_once(self):
        self.assertEqual(self.p.decide(self.cfg, obs(), "mode_a").mode, "mode_a")
        d = self.p.decide(self.cfg, obs(dhcp_servers=["192.168.8.1"]), "mode_a")
        self.assertEqual(d.mode, "standalone")

    def test_pppoe_only_with_credentials_and_a_server(self):
        cfg = NetworkConfig(mode="auto", pppoe_user="u", pppoe_password="p")
        self.assertTrue(self.p.decide(cfg, obs(carrier=True, pppoe_server=True), None).pppoe)
        self.assertFalse(self.p.decide(NetworkConfig(mode="auto"), obs(pppoe_server=True), None).pppoe)
        self.assertFalse(self.p.decide(cfg, obs(pppoe_server=False), None).pppoe)

    def test_pppoe_answer_on_the_ont_is_router_mode_at_once(self):
        cfg = NetworkConfig(mode="auto", pppoe_user="u", pppoe_password="p")
        d = self.p.decide(cfg, obs(pppoe_server=True, internet=False), "standalone")
        self.assertEqual((d.mode, d.pppoe), ("mode_a", True))   # no 90 s wait: a home router never answers PPPoE

    def test_internet_without_lease_stays_standalone(self):
        self.clock.t += 1000
        self.assertEqual(self.p.decide(self.cfg, obs(internet=True), "standalone").mode, "standalone")


class ObserverTest(unittest.TestCase):
    def _observe(self, ob, current="mode_a", servers=None):
        with patch.object(A, "_has_lease", return_value=False), patch.object(A, "_internet", return_value=False), \
             patch("nmb.netd.interfaces.get_carrier", return_value=True), \
             patch("nmb.netd.wifi_share.wired_ports", return_value=["eth0"]), \
             patch("nmb.netd.wifi_share.probe_dhcp_servers", return_value=servers or []) as probe:
            return ob.observe(NetworkConfig(), current, own_gateway="192.168.100.1"), probe

    def test_probe_answer_is_kept_until_the_next_probe(self):
        clock = Clock()
        ob = A.Observer(clock)
        o1, p1 = self._observe(ob, servers=["192.168.8.1", "192.168.100.1"])
        self.assertEqual(o1.dhcp_servers, ["192.168.8.1"])          # its own DHCP server never counts
        clock.t += 5
        o2, p2 = self._observe(ob, servers=[])
        p2.assert_not_called()
        self.assertEqual(o2.dhcp_servers, ["192.168.8.1"])          # same answer every loop: debounce can pass


class ObserverInternetTest(unittest.TestCase):
    def test_wifi_or_usb_internet_does_not_count_for_the_wan_port(self):
        ob = A.Observer(Clock())
        with patch.object(A, "_has_lease", return_value=False), patch.object(A, "_ipv4_of", return_value=None), \
             patch.object(A, "_internet", return_value=True) as net, \
             patch("nmb.netd.interfaces.get_carrier", return_value=True), \
             patch("nmb.netd.wifi_share.wired_ports", return_value=["eth0"]), \
             patch("nmb.netd.wifi_share.probe_dhcp_servers", return_value=[]):
            o = ob.observe(NetworkConfig(), "standalone")
        self.assertFalse(o.internet)          # eth0 has no address: whatever Wi-Fi does, the WAN port has no internet
        net.assert_not_called()

    def test_pppoe_discovery_is_throttled(self):
        clock = Clock()
        ob = A.Observer(clock)
        cfg = NetworkConfig(pppoe_user="u", pppoe_password="p")
        with patch.object(A, "_has_lease", return_value=False), patch.object(A, "_ipv4_of", return_value=None), \
             patch("nmb.netd.interfaces.get_carrier", return_value=True), \
             patch("nmb.netd.wifi_share.wired_ports", return_value=["eth0"]), \
             patch("nmb.netd.wifi_share.probe_dhcp_servers", return_value=[]), \
             patch.object(A, "_pppoe_discovery", return_value=True) as disc:
            for _ in range(10):
                ob.observe(cfg, "standalone")
                clock.t += 5
        self.assertEqual(disc.call_count, 1)  # 50 s with an answer: asked once, not every loop


class DetectorAutoTest(unittest.TestCase):
    def test_detector_uses_the_policy_in_auto_mode(self):
        det = NetworkDetector(NetworkConfig(mode="auto"))
        det.observer = MagicMock()
        det.observer.observe.return_value = obs(carrier=False)
        self.assertEqual(det.evaluate_target_mode()[0], "mode_a")
        det.observer.observe.return_value = obs(lease=True)
        self.assertEqual(det.evaluate_target_mode()[0], "standalone")

    def test_static_mode_and_override_are_untouched(self):
        self.assertEqual(NetworkDetector(NetworkConfig(mode="standalone")).evaluate_target_mode()[0], "standalone")
        self.assertEqual(NetworkDetector(NetworkConfig(mode="auto")).evaluate_target_mode("mode_b")[0], "mode_b")


if __name__ == "__main__":
    unittest.main()


class ModeDetailsTest(unittest.TestCase):
    def test_standalone_bridges_the_auto_ports(self):
        from nmb.netd import modes
        mode = modes.ModeStandalone(NetworkConfig(mode="auto"), MagicMock())
        mode.auto_passthrough = ["eth1", "eth2"]
        ifs = MagicMock()
        ifs.get_default_gateway_iface.return_value = "eth0"
        ifs.interface_exists.return_value = True
        with patch.object(modes, "interfaces", ifs), patch.object(modes, "firewall", MagicMock()), \
             patch.object(modes.lan_topology, "apply_topology", return_value=None) as topo:
            mode.setup()
        used = topo.call_args[0][0]
        self.assertTrue(used.lan_passthrough_enabled)
        self.assertEqual(used.passthrough_ports, ["eth1", "eth2"])

    def test_user_topology_is_not_overridden(self):
        from nmb.netd import modes
        mode = modes.ModeStandalone(NetworkConfig(mode="auto", lag_enabled=True, lag_ports=["eth0", "eth1"]), MagicMock())
        mode.auto_passthrough = ["eth2"]
        ifs = MagicMock()
        ifs.get_default_gateway_iface.return_value = "eth0"
        with patch.object(modes, "interfaces", ifs), patch.object(modes, "firewall", MagicMock()), \
             patch.object(modes.lan_topology, "apply_topology", return_value=None) as topo:
            mode.setup()
        self.assertFalse(topo.call_args[0][0].lan_passthrough_enabled)
