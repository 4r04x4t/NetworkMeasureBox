"""The OONI add-on is off by default and persists its switch."""
import tempfile
import unittest
from pathlib import Path

from nmb.config import Config, load_config, save_config


class OoniToggleTests(unittest.TestCase):
    def test_default_off_and_round_trip(self):
        self.assertFalse(Config().ooni.enabled)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nmb.conf"
            path.write_text("[network]\nwan_interface = eth0\n")
            cfg = load_config(path)
            self.assertFalse(cfg.ooni.enabled)
            cfg.ooni.enabled = True
            save_config(cfg, path)
            self.assertTrue(load_config(path).ooni.enabled)


if __name__ == "__main__":
    unittest.main()
