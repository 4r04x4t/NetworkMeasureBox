"""The default speed test schedule is hourly and has a single scheduler."""
import unittest
from pathlib import Path

from nmb.config import SpeedtestConfig
from nmb.speed.scheduler import normalize_cron_expression

ROOT = Path(__file__).resolve().parent.parent


class SpeedScheduleDefaultTest(unittest.TestCase):
    def test_defaults_are_hourly(self):
        self.assertEqual(SpeedtestConfig().schedule_cron, "0 * * * *")
        self.assertEqual(normalize_cron_expression(""), "0 * * * *")
        self.assertIn("schedule_cron = 0 * * * *", (ROOT / "config/nmb.conf.example").read_text())

    def test_no_second_scheduler(self):
        self.assertFalse((ROOT / "systemd/nmb-speed.timer").exists())
        self.assertNotIn("nmb-speed --trigger schedule", (ROOT / "setup.sh").read_text())


if __name__ == "__main__":
    unittest.main()
