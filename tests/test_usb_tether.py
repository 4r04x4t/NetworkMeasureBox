"""USB phones, hotspots and modems are never treated as the wired line."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.netd import interfaces


class UsbTetherTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.net = self.root / "class" / "net"
        self.net.mkdir(parents=True)
        self.patch = patch.object(interfaces, "SYS_CLASS_NET", self.net)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def _iface(self, name, driver=None, vendor=None, devtype=None):
        d = self.net / name
        d.mkdir()
        (d / "uevent").write_text(f"INTERFACE={name}\n" + (f"DEVTYPE={devtype}\n" if devtype else ""))
        if driver:
            usbdev = self.root / "usb" / name
            intf = usbdev / "1-1:1.0"
            intf.mkdir(parents=True)
            if vendor:
                (usbdev / "idVendor").write_text(vendor + "\n")
            drv = self.root / "drivers" / driver
            drv.mkdir(parents=True, exist_ok=True)
            os.symlink(drv, intf / "driver")
            os.symlink(intf, d / "device")

    def test_phones_hotspots_and_modems_are_not_wired(self):
        self._iface("usb0", "rndis_host", "18d1")            # Android
        self._iface("eth1", "ipheth", "05ac")                # iPhone
        self._iface("enx9c3dcf000001", "cdc_ncm", "0846")    # Netgear Nighthawk
        self._iface("wwan0", "qmi_wwan", "2c7c", "wwan")     # cellular modem
        for name in ("usb0", "eth1", "enx9c3dcf000001", "wwan0"):
            self.assertFalse(interfaces.is_wired_interface(name), name)
        self.assertEqual(interfaces.usb_tether_kind("enx9c3dcf000001"), "tether")
        self.assertEqual(interfaces.usb_tether_kind("wwan0"), "modem")

    def test_real_ethernet_stays_wired(self):
        self._iface("eth0")                                       # on-board, no USB driver link
        self._iface("enx00e04c680001", "cdc_ether", "0bda")       # Realtek USB dongle on the CDC driver
        self._iface("enx00e04c680002", "r8152", "0bda")           # Realtek USB dongle, own driver
        for name in ("eth0", "enx00e04c680001", "enx00e04c680002"):
            self.assertTrue(interfaces.is_wired_interface(name), name)
            self.assertIsNone(interfaces.usb_tether_kind(name), name)


if __name__ == "__main__":
    unittest.main()


class SpeedCliInterfaceTest(unittest.TestCase):
    def test_interface_option_reaches_the_runner(self):
        # 2026-11-08: `nmb-speed -i eth1` measured on eth0; the option was never passed on.
        from unittest.mock import patch
        from nmb.speed import runner
        with patch.object(runner, "run_measurement_cycle", return_value=True) as cyc, \
             patch.object(runner, "load_config", create=True), patch("nmb.devlog.setup_dev_logging"):
            runner.main(["-e", "cloudflare", "-i", "eth1", "--force"])
        self.assertEqual(cyc.call_args.kwargs["target_iface"], "eth1")
