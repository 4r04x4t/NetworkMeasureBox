"""Settings from a USB stick: only the keys in the file change, secrets are never wiped, applied once."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.common import usb_import as U

CURRENT = """[network]
mode = standalone
wifi_psk = old-password1
pppoe_user =
pppoe_password =

[telegram]
enabled = false
token = 111:old
"""


class ApplyPartialTest(unittest.TestCase):
    def test_only_given_keys_change_and_secrets_are_kept(self):
        upd = "[telegram]\nenabled = true\ntoken =\n[network]\npppoe_user = alice@isp\npppoe_password = s3cret\nwifi_psk = __KEEP_CURRENT__\n[newsec]\nx = 1\n"
        text, applied, skipped = U.apply_partial(CURRENT, upd)
        self.assertIn("enabled = true", text)
        self.assertIn("token = 111:old", text)            # empty secret on the stick: kept
        self.assertIn("wifi_psk = old-password1", text)   # marked: kept
        self.assertIn("pppoe_user = alice@isp", text)
        self.assertIn("pppoe_password = s3cret", text)
        self.assertIn("mode = standalone", text)
        self.assertIn("[newsec]\nx = 1", text)
        self.assertEqual(sorted(skipped), ["network.wifi_psk", "telegram.token"])
        self.assertIn("network.pppoe_password", applied)


class ImportTextTest(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.cfg = d / "nmb.conf"
        self.cfg.write_text(CURRENT)
        for name, val in (("CONFIG", self.cfg), ("BACKUP_DIR", d / "bk"), ("STATE", d / "state.json")):
            p = patch.object(U, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_applied_once_with_a_backup(self):
        upd = "[telegram]\ntoken = 222:new\n"
        res = U.import_text(upd, now=1000)
        self.assertEqual(res["status"], "applied")
        self.assertIn("token = 222:new", self.cfg.read_text())
        self.assertEqual(Path(res["backup"]).read_text(), CURRENT)
        self.assertEqual(oct(Path(res["backup"]).stat().st_mode & 0o777), "0o600")
        self.assertEqual(U.import_text(upd, now=2000)["status"], "already")

    def test_disabled_or_broken_file_changes_nothing(self):
        self.cfg.write_text(CURRENT + "\n[usb_import]\nenabled = false\n")
        self.assertEqual(U.import_text("[telegram]\ntoken = 3:x\n")["status"], "disabled")
        self.cfg.write_text(CURRENT)
        res = U.import_text("this is not ini\n")
        self.assertFalse(res["ok"])
        self.assertEqual(self.cfg.read_text(), CURRENT)

    def test_device_name_is_checked(self):
        self.assertEqual(U.import_from_device("../sda1"), 2)


if __name__ == "__main__":
    unittest.main()
