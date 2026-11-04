"""Unit tests for NetworkMeasureBox Network Hardware Drivers & Firmware Subsystem."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from nmb.netd.drivers import (
    get_full_driver_status,
    detect_all_physical_interfaces,
    detect_hardware_controllers,
    detect_missing_firmware,
    get_recommended_driver_packages,
)


class TestDrivers(unittest.TestCase):
    def test_full_driver_status(self):
        status = get_full_driver_status()
        self.assertEqual(status.get("status"), "ok")
        self.assertIn("interfaces", status)
        self.assertIn("controllers", status)
        self.assertIn("missing_firmware", status)
        self.assertIn("recommended_packages", status)
        self.assertIn("all_drivers_ready", status)

    def test_detect_interfaces(self):
        ifaces = detect_all_physical_interfaces()
        self.assertIsInstance(ifaces, list)
        for iface in ifaces:
            self.assertIn("name", iface)
            self.assertIn("driver", iface)
            self.assertIn("mac", iface)

    def test_recommended_packages(self):
        pkgs = get_recommended_driver_packages()
        self.assertIsInstance(pkgs, list)
        for p in pkgs:
            self.assertIn("package", p)
            self.assertIn("description", p)

    def test_nmb_driver_cli(self):
        repo_root = Path(__file__).resolve().parent.parent
        cli_bin = repo_root / "bin" / "nmb-driver"
        self.assertTrue(cli_bin.exists())

        # Test CLI scan --json
        r = subprocess.run([str(cli_bin), "scan", "--json"], stdout=subprocess.PIPE, text=True, timeout=10.0)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("interfaces", data)


if __name__ == "__main__":
    unittest.main()

