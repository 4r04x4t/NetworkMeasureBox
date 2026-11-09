"""The access point never starts with the shared factory password or an invalid one."""
import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.config import NetworkConfig
from nmb.netd.services import ServiceManager
from nmb.netd.wifi import SHARED_FACTORY_PSK, weak_wifi_password


class WifiPskTest(unittest.TestCase):
    def test_weak_passwords(self):
        for psk in ("", "short", SHARED_FACTORY_PSK, "x" * 64):
            self.assertTrue(weak_wifi_password(psk), psk)
        self.assertFalse(weak_wifi_password("Tq8vLm2pXe4R"))

    def test_code_default_is_not_the_factory_password(self):
        self.assertNotEqual(NetworkConfig().wifi_psk, SHARED_FACTORY_PSK)

    def _start(self, psk, security="wpa2"):
        cfg = dataclasses.replace(NetworkConfig(), wifi_psk=psk, wifi_security=security)
        mgr = ServiceManager(Path(tempfile.mkdtemp()), cfg)
        with patch("nmb.netd.services.shutil.which", return_value="/usr/sbin/hostapd"), \
             patch("nmb.netd.services.ManagedProcess") as proc, \
             patch.object(ServiceManager, "_release_from_network_manager"):
            proc.return_value.start.return_value = True
            return mgr.start_hostapd("wlan0"), proc.called

    def test_ap_refuses_factory_and_empty_password(self):
        for psk in (SHARED_FACTORY_PSK, ""):
            started, launched = self._start(psk)
            self.assertFalse(started)
            self.assertFalse(launched)

    def test_ap_starts_with_unique_password(self):
        started, launched = self._start("Tq8vLm2pXe4R")
        self.assertTrue(started)
        self.assertTrue(launched)

    def test_radio_loses_its_client_address_before_the_ap_starts(self):
        cfg = dataclasses.replace(NetworkConfig(), wifi_psk="Tq8vLm2pXe4R", wifi_security="wpa2")
        mgr = ServiceManager(Path(tempfile.mkdtemp()), cfg)
        with patch("nmb.netd.services.shutil.which", side_effect=lambda b: f"/usr/sbin/{b}"), \
             patch("nmb.netd.services.subprocess.run") as run, \
             patch("nmb.netd.services.ManagedProcess") as proc:
            proc.return_value.start.return_value = True
            self.assertTrue(mgr.start_hostapd("wlan0"))
        cmds = [c[0][0] for c in run.call_args_list]
        self.assertIn(["/usr/sbin/ip", "-4", "addr", "flush", "dev", "wlan0", "dynamic"], cmds)
        self.assertIn(["/usr/sbin/ip", "-4", "route", "flush", "dev", "wlan0", "proto", "dhcp"], cmds)
        # Never a full flush: standalone mode puts the access point's own address on the radio first.
        self.assertNotIn(["/usr/sbin/ip", "addr", "flush", "dev", "wlan0"], cmds)


if __name__ == "__main__":
    unittest.main()
