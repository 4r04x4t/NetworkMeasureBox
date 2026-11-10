"""A change to the access point's own settings restarts hostapd only (nmb/netd/daemon.py, ModeA.reapply_wifi).

2026-11-10, real PPPoE line: switching the band from 2.4 to 5 GHz rebuilt the whole router, so the PPPoE
session dialled again and the LAN lost the internet for about 40 s.
"""
import dataclasses
import unittest
from unittest import mock

from nmb.config import Config
from nmb.netd import daemon as netd_daemon
from nmb.netd.modes import ModeA, ModeB, ModeStandalone


class _Svc:
    def __init__(self, cfg):
        self.cfg = cfg
        self.hostapd = mock.Mock()
        self.processes = {"hostapd": self.hostapd, "pppd": mock.Mock()}
        self.started = []

    def start_hostapd(self, iface, bridge=None):
        self.started.append((iface, bridge, self.cfg.wifi_band))
        self.processes["hostapd"] = mock.Mock()
        return True


def _daemon(mode_cls, new_cfg: Config, old_cfg: Config):
    d = netd_daemon.NetworkDaemon.__new__(netd_daemon.NetworkDaemon)
    d.cfg = old_cfg
    d.svc_mgr = _Svc(old_cfg.network)
    d.modes = {"mode_a": ModeA.__new__(ModeA), "mode_b": ModeB.__new__(ModeB),
               "standalone": ModeStandalone.__new__(ModeStandalone)}
    for m in d.modes.values():
        m.cfg = old_cfg.network
        m.svc_mgr = d.svc_mgr
        m.wlan_active = False
    d.detector = mock.Mock(cfg=old_cfg.network)
    d.detector.evaluate_target_mode.return_value = ("mode_a", "test")
    d.current_mode_name = {"ModeA": "mode_a", "ModeB": "mode_b", "ModeStandalone": "standalone"}[mode_cls.__name__]
    d.current_mode_inst = d.modes[d.current_mode_name]
    d.switch_mode = mock.Mock()
    d._build_modes = mock.Mock()
    d._get_override_mode = mock.Mock(return_value=None)
    d._kernel_sig = "same"
    return d


class WifiOnlyReloadTest(unittest.TestCase):
    def _reload(self, mode_cls, **changes):
        old = Config()
        old.network.wifi_band = "2.4ghz"
        new = Config()
        new.network = dataclasses.replace(old.network, **changes)
        d = _daemon(mode_cls, new, old)
        with mock.patch.object(netd_daemon, "load_config", return_value=new), \
             mock.patch.object(netd_daemon, "_kernel_tuning_signature", return_value="same"), \
             mock.patch("nmb.netd.interfaces.interface_exists", return_value=True), \
             mock.patch("nmb.netd.interfaces.set_link_up"), \
             mock.patch("nmb.netd.wifi.unblock_wifi"), \
             mock.patch.object(ModeB, "teardown"), \
             mock.patch.object(ModeA, "teardown") as teardown:
            d._apply_reload()
        return d, teardown

    def test_band_change_restarts_only_the_access_point(self):
        d, teardown = self._reload(ModeA, wifi_band="5ghz", wifi_standard="auto")
        teardown.assert_not_called()
        d.switch_mode.assert_not_called()
        self.assertEqual(d.svc_mgr.started, [("wlan0", "br-lan", "5ghz")])
        d.svc_mgr.hostapd.stop.assert_called_once()
        self.assertIn("pppd", d.svc_mgr.processes)          # the PPPoE session is left alone
        self.assertEqual(d.modes["mode_a"].cfg.wifi_band, "5ghz")
        self.assertEqual(d.detector.cfg.wifi_band, "5ghz")

    def test_other_network_changes_still_rebuild(self):
        d, teardown = self._reload(ModeA, wifi_band="5ghz", gateway_ip="192.168.55.1")
        teardown.assert_called_once()
        d.switch_mode.assert_called_once()
        self.assertEqual(d.svc_mgr.started, [])

    def test_turning_the_access_point_off_rebuilds(self):
        d, teardown = self._reload(ModeA, wifi_enabled=False)
        teardown.assert_called_once()

    def test_standalone_only_keeps_the_settings(self):
        d, _ = self._reload(ModeStandalone, wifi_ssid="Other")
        d.switch_mode.assert_not_called()
        self.assertEqual(d.svc_mgr.started, [])
        self.assertEqual(d.modes["standalone"].cfg.wifi_ssid, "Other")

    def test_bridge_mode_rebuilds(self):
        d, _ = self._reload(ModeB, wifi_channel=36)
        d.switch_mode.assert_called_once()


if __name__ == "__main__":
    unittest.main()
