"""Tests for LAN passthrough and link aggregation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.config import Config, NetworkConfig, load_config, save_config
from nmb.netd import lan_topology as lt
from nmb.netd.detector import NetworkDetector

WIRED = ["eth0", "eth1", "eth2", "eth3"]


def validate(**overrides):
    args = dict(
        lag_enabled=False, lag_ports=[], lag_mode="802.3ad", lag_hash_policy="layer3+4", lacp_rate="fast",
        passthrough_enabled=False, passthrough_ports=[], wan_interface="eth0", wired_ports=WIRED,
    )
    args.update(overrides)
    return lt.validate_settings(**args)


class ValidationTests(unittest.TestCase):
    def test_disabled_is_valid(self):
        self.assertEqual(validate(), [])

    def test_lag_needs_two_distinct_ports(self):
        self.assertTrue(validate(lag_enabled=True, lag_ports=["eth0", "eth0"]))
        self.assertEqual(validate(lag_enabled=True, lag_ports=["eth0", "eth1"]), [])

    def test_lag_rejects_unknown_port_and_mode(self):
        self.assertTrue(validate(lag_enabled=True, lag_ports=["eth0", "wlan0"]))
        self.assertTrue(validate(lag_enabled=True, lag_ports=["eth0", "eth1"], lag_mode="magic"))

    def test_passthrough_needs_port(self):
        self.assertTrue(validate(passthrough_enabled=True))

    def test_port_cannot_be_uplink_and_passthrough(self):
        self.assertTrue(validate(passthrough_enabled=True, passthrough_ports=["eth0"]))
        self.assertTrue(validate(
            lag_enabled=True, lag_ports=["eth0", "eth1"],
            passthrough_enabled=True, passthrough_ports=["eth1"],
        ))

    def test_wireless_uplink_cannot_be_bridged(self):
        self.assertTrue(validate(wan_interface="wlan0", passthrough_enabled=True, passthrough_ports=["eth1"]))

    def test_lag_and_passthrough_combined(self):
        self.assertEqual(validate(
            lag_enabled=True, lag_ports=["eth0", "eth1"],
            passthrough_enabled=True, passthrough_ports=["eth2", "eth3"],
        ), [])


class TopologyTests(unittest.TestCase):
    def _net(self, **kw):
        net = NetworkConfig()
        net.wan_interface = "eth0"
        for k, v in kw.items():
            setattr(net, k, v)
        return net

    def test_passthrough_without_lag(self):
        t = lt.resolve_topology(self._net(lan_passthrough_enabled=True, passthrough_ports=["eth1"]))
        self.assertEqual((t.uplink_device, t.ip_device, t.monitor_device), ("eth0", lt.BRIDGE_NAME, "eth0"))

    def test_lag_without_passthrough(self):
        t = lt.resolve_topology(self._net(lag_enabled=True, lag_ports=["eth0", "eth1"]))
        self.assertEqual((t.uplink_device, t.ip_device), (lt.BOND_NAME, lt.BOND_NAME))

    def test_lag_with_passthrough_monitors_bond_not_bridge(self):
        net = self._net(lag_enabled=True, lag_ports=["eth0", "eth1"],
                        lan_passthrough_enabled=True, passthrough_ports=["eth2"])
        self.assertEqual(lt.traffic_monitor_device(net, lt.BRIDGE_NAME), lt.BOND_NAME)

    def test_inactive_keeps_measurement_interface(self):
        self.assertEqual(lt.traffic_monitor_device(self._net(), "eth5"), "eth5")

    def test_failed_setup_rolls_back(self):
        net = self._net(lag_enabled=True, lag_ports=["eth0", "eth1"])
        with patch.object(lt, "setup_bond", return_value=False), patch.object(lt, "teardown_topology") as td:
            self.assertIsNone(lt.apply_topology(net))
        self.assertEqual(td.call_count, 2)

    def test_detector_selects_standalone_in_auto_mode(self):
        net = self._net(mode="auto", lan_passthrough_enabled=True, passthrough_ports=["eth1"])
        self.assertEqual(NetworkDetector(net).evaluate_target_mode()[0], "standalone")

    def test_manual_override_wins(self):
        net = self._net(mode="auto", lag_enabled=True, lag_ports=["eth0", "eth1"])
        self.assertEqual(NetworkDetector(net).evaluate_target_mode("mode_a")[0], "mode_a")


class ConfigTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nmb.conf"
            path.write_text("[network]\nwan_interface = eth0\n")
            cfg = load_config(path)
            cfg.network.lag_enabled = True
            cfg.network.lag_ports = ["eth0", "eth1"]
            cfg.network.lag_mode = "balance-alb"
            cfg.network.lan_passthrough_enabled = True
            cfg.network.passthrough_ports = ["eth2"]
            with patch("nmb.config.DEFAULT_CONFIG_PATH", path, create=True):
                save_config(cfg, path)
            loaded = load_config(path)
            self.assertTrue(loaded.network.lag_enabled)
            self.assertEqual(loaded.network.lag_ports, ["eth0", "eth1"])
            self.assertEqual(loaded.network.lag_mode, "balance-alb")
            self.assertEqual(loaded.network.passthrough_ports, ["eth2"])


if __name__ == "__main__":
    unittest.main()
