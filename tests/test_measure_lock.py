"""One speed test at a time on the whole box, across processes (2026-11-09: Telegram Ookla + scheduled iPerf3)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.speed import runner


class MeasureLockTest(unittest.TestCase):
    def setUp(self):
        self.lock = str(Path(tempfile.mkdtemp()) / "speedtest.lock")
        p = patch.object(runner, "MEASURE_LOCK", self.lock)
        p.start()
        self.addCleanup(p.stop)

    def test_scheduled_test_skips_while_another_process_measures(self):
        code = ("import fcntl,os,sys,time; fd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT); "
                "fcntl.flock(fd, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(30)")
        holder = subprocess.Popen([sys.executable, "-c", code, self.lock], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        out = {}
        with patch.object(runner, "_run_measurement_cycle") as inner:
            self.assertFalse(runner.run_measurement_cycle(None, "schedule", record_skip=False, outcome=out))
        inner.assert_not_called()
        self.assertEqual(out["status"], "skipped_busy")

    def test_manual_test_waits_then_runs(self):
        with patch.object(runner, "_run_measurement_cycle", return_value=True) as inner:
            self.assertTrue(runner.run_measurement_cycle(None, "manual", engine="cloudflare"))
        inner.assert_called_once()
        fd = runner._measure_lock(0)          # released afterwards
        self.assertIsNotNone(fd)
        os.close(fd)


if __name__ == "__main__":
    unittest.main()
