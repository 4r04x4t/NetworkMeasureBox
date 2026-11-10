"""The developer log fits the file system it is on (nmb/devlog.py fit_rotation).

2026-11-10: /var/log on the box is a 48 MB RAM disk; 10 MB x 5 copies filled it, services lost their logs
and the installer stopped halfway.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb import devlog


def _fs(size_mb):
    return SimpleNamespace(f_frsize=4096, f_blocks=size_mb * 1024 * 1024 // 4096)


class FitRotationTest(unittest.TestCase):
    def test_small_ram_disk_shrinks_the_rotation(self):
        with mock.patch.object(devlog.os, "statvfs", return_value=_fs(48)):
            size, count = devlog.fit_rotation(Path("/var/log/nmb"), 10 * 1024 * 1024, 5)
        self.assertLessEqual(size * (count + 1), 48 * 1024 * 1024 * 0.4 + 1)
        self.assertEqual(count, 2)

    def test_big_disk_keeps_the_settings(self):
        with mock.patch.object(devlog.os, "statvfs", return_value=_fs(100_000)):
            self.assertEqual(devlog.fit_rotation(Path("/var/log/nmb"), 10 * 1024 * 1024, 5), (10 * 1024 * 1024, 5))

    def test_unknown_file_system_keeps_the_settings(self):
        with mock.patch.object(devlog.os, "statvfs", side_effect=OSError):
            self.assertEqual(devlog.fit_rotation(Path("/nowhere"), 1000, 3), (1000, 3))


if __name__ == "__main__":
    unittest.main()
