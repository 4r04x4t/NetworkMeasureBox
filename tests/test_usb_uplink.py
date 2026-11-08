"""USB tethering link: own profile without the default route, link selection, limit, routing."""
import unittest
from unittest.mock import patch

from nmb.config import Config
from nmb.netd import usb_uplink


class UsbUplinkTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.cfg.usb_uplink.enabled = True

    def test_profile_never_takes_the_default_route(self):
        calls = []

        def run(cmd, timeout=15.0):
            calls.append(cmd)
            return 0, "", ""

        with patch.object(usb_uplink, "uplink_interface", return_value="eth1"), \
             patch.object(usb_uplink, "_address_and_gateway", return_value=("192.168.1.4", "192.168.1.1")), \
             patch("nmb.netd.usb_uplink.shutil.which", return_value="/usr/bin/nmcli"), \
             patch.object(usb_uplink, "_run", side_effect=run):
            ok, msg = usb_uplink.connect(self.cfg)
        self.assertTrue(ok, msg)
        add = next(c for c in calls if "add" in c)
        self.assertIn("ipv4.never-default", add)
        self.assertEqual(add[add.index("ipv4.never-default") + 1], "yes")
        self.assertEqual(add[add.index("ifname") + 1], "eth1")

    def test_no_device_gives_a_clear_message(self):
        with patch.object(usb_uplink, "uplink_interface", return_value=None):
            ok, msg = usb_uplink.connect(self.cfg)
        self.assertFalse(ok)
        self.assertIn("USB", msg)

    def test_source_rule_added_and_removed(self):
        calls = []

        def run(cmd, timeout=15.0):
            calls.append(" ".join(cmd))
            return 0, ("152: from 192.168.1.4 lookup 152" if "show" in cmd and calls[-1].startswith("ip -4 rule") and len(calls) > 3 else ""), ""

        with patch.object(usb_uplink, "uplink_interface", return_value="eth1"), \
             patch.object(usb_uplink, "_address_and_gateway", return_value=("192.168.1.4", "192.168.1.1")), \
             patch.object(usb_uplink, "_run", side_effect=run):
            self.assertTrue(usb_uplink.sync_source_routing(self.cfg))
        self.assertTrue(any("route replace default via 192.168.1.1 dev eth1 table 152" in c for c in calls))
        self.assertTrue(any("rule add priority 152 from 192.168.1.4 lookup 152" in c for c in calls))

        calls.clear()
        self.cfg.usb_uplink.enabled = False
        with patch.object(usb_uplink, "_run", side_effect=lambda cmd, timeout=15.0: (calls.append(" ".join(cmd)) or (0, "152: from 192.168.1.4 lookup 152", ""))):
            self.assertFalse(usb_uplink.sync_source_routing(self.cfg))
        self.assertTrue(any("rule del priority 152" in c for c in calls))

    def test_measurement_link_usb_picks_the_usb_interface(self):
        from nmb.netd import interfaces
        self.cfg.network.measurement_link = "usb"
        with patch("nmb.netd.usb_uplink.uplink_interface", return_value="eth1"), \
             patch.object(interfaces, "interface_exists", return_value=True), \
             patch.object(interfaces, "get_ip_addresses", return_value=["192.168.1.4/24", "fe80::1/64"]):
            iface, ip, wired = interfaces.find_preferred_measurement_interface(self.cfg)
        self.assertEqual((iface, ip, wired), ("eth1", "192.168.1.4", False))

    def test_config_round_trip(self):
        import tempfile
        from pathlib import Path
        from nmb.config import load_config, save_config
        path = Path(tempfile.mkdtemp()) / "nmb.conf"
        self.cfg.usb_uplink.daily_limit_mb = 0
        self.cfg.network.measurement_link = "usb"
        self.assertTrue(save_config(self.cfg, path))
        back = load_config(path)
        self.assertTrue(back.usb_uplink.enabled)
        self.assertEqual(back.usb_uplink.daily_limit_mb, 0)
        self.assertEqual(back.network.measurement_link, "usb")


if __name__ == "__main__":
    unittest.main()
