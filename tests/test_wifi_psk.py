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


if __name__ == "__main__":
    unittest.main()
