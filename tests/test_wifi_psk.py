"""The access point never starts with the shared factory password or an invalid one."""
import dataclasses
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.config import NetworkConfig
from nmb.netd.services import ServiceManager
from nmb.netd.wifi import SHARED_FACTORY_PSK, weak_wifi_password


# What the Raspberry Pi 4's radio reports, so the tests never ask the PC they run on (a PC without hostapd or
# iw, such as WSL2, failed them on 2026-11-10; a PC with them would have run real commands on its own Wi-Fi).
PI4_CAPS = {
    "interface": "wlan0", "phy_name": "phy0", "driver": "brcmfmac",
    "ap_mode_supported": True, "wpa3_supported": True,
    "supported_bands": ["2.4ghz", "5ghz"], "supported_standards": ["b", "g", "a", "n", "ac"],
    "supported_widths": ["20", "40", "80"], "ht40_bands": ["5ghz"], "band_flags": {},
    "highest_standard": "ac",
    "channels": {"2.4ghz": list(range(1, 14)), "5ghz": [36, 40, 44, 48, 149, 153, 157, 161], "6ghz": []},
    "current_status": {},
}


def _no_host_commands():
    """Patches that keep start_hostapd away from the machine running the test: no binary lookup, no command,
    no radio detection and no internet lookup reaches the host. subprocess.run and shutil.which are replaced on
    their modules, so every caller in the process is covered while the patches are active. The country stays
    "auto" (the default) but comes from a fake regulatory domain: otherwise "auto" asked a public GeoIP
    service over the internet and left a background thread behind (found on 2026-11-10)."""
    run = patch("nmb.netd.services.subprocess.run",
                side_effect=lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0, "", ""))
    which = patch("nmb.netd.services.shutil.which", side_effect=lambda b: f"/usr/sbin/{b}")
    caps = patch("nmb.netd.wifi.detect_wifi_capabilities", return_value=PI4_CAPS)
    reg = patch("nmb.netd.geoip.get_wifi_regulatory_domain", return_value={"country_code": "HU", "is_unset": False})
    geo = patch("nmb.netd.geoip.get_public_geoip", side_effect=AssertionError("no internet lookup in a unit test"))
    set_reg = patch("nmb.netd.geoip.set_wifi_regulatory_domain", return_value=True)
    return run, which, caps, reg, geo, set_reg


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
        run, which, caps, reg, geo, set_reg = _no_host_commands()
        with run, which, caps, reg, geo, set_reg, \
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
        run_patch, which, caps, reg, geo, set_reg = _no_host_commands()
        with run_patch as run, which, caps, reg, geo, set_reg as set_reg_mock, \
             patch("nmb.netd.services.ManagedProcess") as proc:
            proc.return_value.start.return_value = True
            self.assertTrue(mgr.start_hostapd("wlan0"))
        cmds = [c[0][0] for c in run.call_args_list]
        self.assertIn(["/usr/sbin/ip", "-4", "addr", "flush", "dev", "wlan0", "dynamic"], cmds)
        self.assertIn(["/usr/sbin/ip", "-4", "route", "flush", "dev", "wlan0", "proto", "dhcp"], cmds)
        # Never a full flush: standalone mode puts the access point's own address on the radio first. Every
        # address flush, in whatever spelling, must be limited to the DHCP client's dynamic addresses.
        addr_flushes = [c for c in cmds if "addr" in c and "flush" in c]
        self.assertTrue(addr_flushes)
        self.assertTrue(all("dynamic" in c for c in addr_flushes), addr_flushes)
        set_reg_mock.assert_called_with("HU")       # "auto" took the radio's own regulatory domain


if __name__ == "__main__":
    unittest.main()
