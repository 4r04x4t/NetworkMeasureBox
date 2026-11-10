"""network-online.target must not wait for NetworkManager's whole startup (router mode, 2026-11-10)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DROPIN = ROOT / "os" / "nmb-wait-online.conf"


class WaitOnlineDropInTest(unittest.TestCase):
    def test_drop_in_waits_for_a_connection_not_for_startup(self):
        lines = [l.strip() for l in DROPIN.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(lines[0], "[Service]")
        execs = [l for l in lines if l.startswith("ExecStart=")]
        # The stock ExecStart must be cleared first, or systemd refuses a second one for a oneshot unit.
        self.assertEqual(execs[0], "ExecStart=")
        self.assertEqual(len(execs), 2)
        cmd = execs[1].split("=", 1)[1].split()
        self.assertEqual(cmd[0], "/usr/bin/nm-online")
        self.assertNotIn("-s", cmd)
        self.assertNotIn("--wait-for-startup", cmd)

    def test_setup_installs_it_as_a_drop_in(self):
        setup = (ROOT / "setup.sh").read_text()
        self.assertIn('"$SCRIPT_DIR/os/nmb-wait-online.conf" /etc/systemd/system/NetworkManager-wait-online.service.d/50-nmb.conf', setup)
        # installed before the daemon-reload that follows the unit copy
        self.assertLess(setup.index("nmb-wait-online.conf"), setup.index("systemctl daemon-reload", setup.index('cp "$SCRIPT_DIR/systemd/"*')))


if __name__ == "__main__":
    unittest.main()
