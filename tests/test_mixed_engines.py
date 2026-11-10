"""The owner picks the engines of the scheduled mixed run (e.g. Cloudflare, Fast.com and RTR, with iPerf3
and Ookla left out for a while); tests started by hand still run them all."""
import _box_isolation  # noqa: F401  (private measurement lock on a working box)
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nmb.config import Config, load_config, parse_mixed_engines, save_config
from nmb.speed import runner
from nmb.speed.ookla import SpeedtestResult

SCHEMA = (Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class MixedEnginesTest(unittest.TestCase):
    def _run(self, trigger, chosen):
        cfg = Config()
        cfg.speedtest.mixed_engines = chosen
        cfg.speedtest.ookla_interval_min = 60
        for e in ("rtr", "cloudflare", "fastcom", "iperf3"):
            setattr(cfg.speedtest, f"{e}_interval_min", 0)
        ran = []

        def single(eng, *a, **k):
            ran.append(eng)
            return SpeedtestResult(status="ok", engine=eng)
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value=None), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.0.2.2", True)), \
             mock.patch.object(runner, "_usb_test_not_allowed", return_value=False), \
             mock.patch.object(runner, "_iperf3_usable", return_value=True), \
             mock.patch.object(runner, "_usable_iperf3_servers", return_value=[("iperf.example", 5201)]), \
             mock.patch.object(runner, "_ookla_blocked_now", return_value=False), \
             mock.patch.object(runner.db, "connect", side_effect=lambda *a, **k: _conn()), \
             mock.patch.object(runner, "_run_single_engine", side_effect=single), \
             mock.patch.object(runner, "run_port_neutrality_check", return_value=[]), \
             mock.patch.object(runner, "record_port_checks_to_db"), \
             mock.patch("nmb.speed.data_cap.check", return_value=(False, "")), \
             mock.patch("nmb.probe.traffic_gate.TrafficGate.wait_for_idle", return_value=mock.MagicMock(is_idle=True, threshold_kbps=1)):
            runner._run_measurement_cycle(cfg, trigger=trigger, engine="all", force=True, run_port_check=False)
        return ran

    def test_scheduled_mixed_run_uses_only_the_ticked_engines(self):
        self.assertEqual(self._run("schedule", ["cloudflare", "fastcom", "rtr"]), ["cloudflare", "fastcom", "rtr"])

    def test_iperf3_only_when_ticked(self):
        self.assertIn("iperf3", self._run("schedule", ["rtr", "iperf3"]))

    def test_nothing_ticked_runs_nothing(self):
        self.assertEqual(self._run("schedule", []), [])

    def test_manual_mixed_run_runs_them_all(self):
        ran = self._run("manual", ["cloudflare"])
        self.assertEqual(set(ran), {"ookla", "cloudflare", "fastcom", "rtr", "iperf3"})

    def test_parse_and_round_trip(self):
        self.assertEqual(parse_mixed_engines("RTR, cloudflare,unknown"), ["cloudflare", "rtr"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nmb.conf"
            cfg = load_config(path)
            self.assertEqual(cfg.speedtest.mixed_engines, ["ookla", "cloudflare", "fastcom", "rtr", "iperf3"])
            cfg.speedtest.mixed_engines = ["cloudflare", "fastcom", "rtr"]
            save_config(cfg, path)
            self.assertEqual(load_config(path).speedtest.mixed_engines, ["cloudflare", "fastcom", "rtr"])


if __name__ == "__main__":
    unittest.main()
