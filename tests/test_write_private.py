"""Generated configs replace the old file (a new inode with the wanted mode), never edit it in place."""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from nmb.netd.services import _write_private


class WritePrivateTest(unittest.TestCase):
    def test_replaces_the_file_and_sets_the_mode(self):
        path = Path(tempfile.mkdtemp()) / "hostapd.conf"
        path.write_text("old")
        os.chmod(path, 0o664)
        before = path.stat().st_ino
        _write_private(path, "new")
        self.assertEqual(path.read_text(), "new")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotEqual(path.stat().st_ino, before)
        self.assertEqual([p.name for p in path.parent.iterdir()], ["hostapd.conf"])


if __name__ == "__main__":
    unittest.main()
