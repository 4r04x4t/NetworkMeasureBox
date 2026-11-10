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


class PurgeLogsTest(unittest.TestCase):
    """/purge logs: the warnings kept on the SD card go too (2026-11-10)."""

    def test_persisted_logs_are_cleared(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            persist = Path(tmp) / "persist-logs"
            persist.mkdir()
            (persist / "warnings-nmb-web.log").write_text("x" * 100)
            (persist / "warnings-nmb-web.log.1").write_text("old")
            (persist / "notes.txt").write_text("keep")
            with mock.patch.dict(os.environ, {"NMB_PERSIST_LOG_DIR": str(persist)}), \
                 mock.patch.object(devlog, "LOG_DIRS", ()), \
                 mock.patch.object(devlog, "get_active_log_file", return_value=None):
                res = devlog.purge_all_logs(include_database_events=False, include_system_journal=False)
            self.assertEqual((persist / "warnings-nmb-web.log").stat().st_size, 0)
            self.assertFalse((persist / "warnings-nmb-web.log.1").exists())
            self.assertEqual((persist / "notes.txt").read_text(), "keep")
            self.assertIn(str(persist / "warnings-nmb-web.log"), res["files_truncated"])


class KillSignalTest(unittest.TestCase):
    def test_unknown_signal_is_refused_not_replaced(self):
        from nmb.common import tasks
        with mock.patch.object(tasks.os, "kill") as kill:
            res = tasks.kill_process(4242, sig_num=19)
        self.assertEqual(res["status"], "error")
        kill.assert_not_called()


class BundleRedactionTest(unittest.TestCase):
    """The diagnostic bundle never carries tokens or passwords (it packed nmb.conf as it was until 2026-11-10)."""

    def test_config_in_the_bundle_is_redacted(self):
        import os
        import tarfile
        import tempfile
        from nmb.report import crash_trap
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "nmb.conf"
            conf.write_text("[telegram]\ntoken = 123456:SECRETSECRET\nenabled = true\n[network]\npppoe_user = someone\n")
            with mock.patch.dict(os.environ, {"NMB_CONFIG": str(conf), "NMB_BUNDLE_DIR": f"{tmp}/b"}):
                bundle = crash_trap.create_diagnostic_bundle()
            with tarfile.open(bundle, "r:gz") as tar:
                member = next(m for m in tar.getmembers() if m.name == "config/nmb.conf")
                text = tar.extractfile(member).read().decode()
        self.assertNotIn("SECRETSECRET", text)
        self.assertNotIn("someone", text)
        self.assertIn("enabled = true", text)
        self.assertIn("<redacted", text)
