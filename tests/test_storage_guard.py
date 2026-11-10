"""Storage guard: the free-space target follows the disk size; cleanup order; measurements last."""
import os
import sqlite3
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.common import storage_guard as sg

GB = 1024 ** 3
MB = 1024 ** 2
Usage = namedtuple("Usage", "total used free")


class TargetTest(unittest.TestCase):
    def test_target_scales_with_the_disk(self):
        self.assertEqual(sg.free_target_bytes(1 * GB), 200 * MB)              # 15 % = 154 MB -> floor
        self.assertEqual(sg.free_target_bytes(8 * GB), int(8 * GB * 0.10))    # 819 MB
        self.assertEqual(sg.free_target_bytes(32 * GB), int(32 * GB * 0.05))  # 1.6 GB
        self.assertEqual(sg.free_target_bytes(128 * GB), 2048 * MB)           # ceiling
        self.assertEqual(sg.free_target_bytes(128 * GB, min_free_mb=300), 300 * MB)


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.logs, self.data = root / "log", root / "lib"
        for d in (self.logs / "bundles", self.data / "backups", self.data / "persist" / "reports"):
            d.mkdir(parents=True)
        self.free = [0]
        for p in [mock.patch.object(sg, "LOG_DIR", self.logs), mock.patch.object(sg, "DATA_DIR", self.data),
                  mock.patch.object(sg, "STATE_FILE", root / "state.json"),
                  mock.patch.object(sg, "_free", side_effect=lambda path: self.free[0]),
                  mock.patch.object(sg.shutil, "disk_usage", side_effect=lambda path: Usage(8 * GB, 0, self.free[0])),
                  mock.patch.object(sg.shutil, "which", return_value=None)]:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def _file(self, path, mb, age_s):
        path.write_bytes(b"\0" * 10)
        t = time.time() - age_s
        os.utime(path, (t, t))
        return path

    def test_enough_space_deletes_nothing(self):
        f = self._file(self.logs / "nmb.log.1", 1, 100)
        self.free[0] = 4 * GB
        res = sg.run(SimpleNamespace(storage=SimpleNamespace(auto_cleanup=True, min_free_mb=0, keep_days=7)), force=True)
        self.assertEqual(res["deleted"], [])
        self.assertTrue(f.exists())

    def test_old_logs_go_first_and_measurements_stay(self):
        old = self._file(self.logs / "nmb.log.2", 1, 900)
        new = self._file(self.logs / "nmb.log.1", 1, 100)
        backup_old = self._file(self.data / "backups" / "a.tar", 1, 900)
        backup_new = self._file(self.data / "backups" / "b.tar", 1, 100)
        deleted = []

        def unlink(self_path, *a, **k):
            deleted.append(self_path.name)
            os.remove(self_path)
            if self_path.name == "nmb.log.2":
                CleanupTest.current.free[0] = 2 * GB   # enough after the oldest log
        CleanupTest.current = self
        self.free[0] = 100 * MB
        with mock.patch.object(Path, "unlink", unlink), mock.patch.object(sg, "prune_measurements") as prune:
            res = sg.run(None, force=True)
        self.assertEqual(deleted, ["nmb.log.2"])
        self.assertTrue(new.exists() and backup_old.exists() and backup_new.exists())
        prune.assert_not_called()
        self.assertEqual(res["status"], "cleaned")

    def test_newest_backup_is_kept(self):
        a = self._file(self.data / "backups" / "a.tar", 1, 900)
        b = self._file(self.data / "backups" / "b.tar", 1, 100)
        self.assertEqual(sg._backups_but_newest(self.data / "backups"), [a])


class PruneTest(unittest.TestCase):
    def test_keeps_the_last_days(self):
        conn = sqlite3.connect(":memory:")
        now = int(time.time() * 1000)
        for t in sg.TABLES:
            conn.execute(f"CREATE TABLE {t} (ts INTEGER)")
        conn.executemany("INSERT INTO ping_sample VALUES (?)", [(now - d * 86_400_000,) for d in range(30)])
        done = []
        with mock.patch.object(sg, "_free", return_value=0), mock.patch.object(sg, "_shrink_persist"):
            n = sg.prune_measurements(conn, Path("/"), goal=1, keep_days=7, done=done)
        left = [r[0] for r in conn.execute("SELECT ts FROM ping_sample")]
        self.assertEqual(n, 30 - len(left))
        self.assertTrue(all(ts >= now - 7 * 86_400_000 - 1000 for ts in left))
        self.assertGreaterEqual(len(left), 7)


if __name__ == "__main__":
    unittest.main()


class LogDiskTest(unittest.TestCase):
    """/var/log as its own 48 MB RAM disk (2026-11-10: 100 % full, nothing cleaned it)."""

    def test_rotated_logs_go_first_then_big_active_logs_are_emptied(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp)
            old, new = logs / "nmb_developer.log.2", logs / "nmb_developer.log.1"
            for f in (old, new):
                f.write_bytes(b"x" * (10 * MB))
            os.utime(old, (time.time() - 3600, time.time() - 3600))
            active = logs / "nmb_developer.log"
            active.write_bytes(b"x" * (7 * MB))
            total = 48 * MB

            def usage(path):
                used = sum(f.stat().st_size for f in logs.rglob("*") if f.is_file()) + 20 * MB   # other files
                return Usage(total, used, total - used)

            with mock.patch.object(sg, "LOG_DIR", logs), mock.patch.object(sg, "_usage", side_effect=usage), \
                 mock.patch.object(sg, "_same_fs", return_value=False):
                done = sg.guard_log_fs(Path("/var/lib/nmb"))
            self.assertFalse(old.exists())                 # oldest rotated copy first
            self.assertTrue(done)
            self.assertGreaterEqual(usage(logs).free, int(total * sg.LOG_FS_KEEP_FREE))

    def test_same_disk_as_the_data_is_left_to_the_main_check(self):
        with mock.patch.object(sg, "_same_fs", return_value=True), mock.patch.object(sg, "_usage") as u:
            self.assertEqual(sg.guard_log_fs(Path("/var/lib/nmb")), [])
        u.assert_not_called()
