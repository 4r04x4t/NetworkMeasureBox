"""Unit tests for NetworkMeasureBox Task Manager and Resource Monitor Engine."""
from __future__ import annotations

import os
import unittest
from nmb.common import tasks


class TestTasksEngine(unittest.TestCase):
    def test_cpu_telemetry(self):
        """Test real-time CPU counters and per-core telemetry."""
        cpu = tasks.get_cpu_telemetry()
        self.assertIn("total_usage_pct", cpu)
        self.assertIsInstance(cpu["total_usage_pct"], float)
        self.assertGreaterEqual(cpu["total_usage_pct"], 0.0)
        self.assertLessEqual(cpu["total_usage_pct"], 100.0)

        self.assertIn("cores", cpu)
        self.assertIsInstance(cpu["cores"], list)
        self.assertGreater(cpu["cores_count"], 0)
        if cpu["cores"]:
            core0 = cpu["cores"][0]
            self.assertIn("core", core0)
            self.assertIn("usage_pct", core0)

    def test_memory_telemetry(self):
        """Test RAM and Swap parsing from /proc/meminfo."""
        mem = tasks.get_memory_telemetry()
        self.assertIn("total_bytes", mem)
        self.assertIn("used_bytes", mem)
        self.assertIn("used_pct", mem)
        self.assertGreater(mem["total_bytes"], 0)
        self.assertGreaterEqual(mem["used_pct"], 0.0)
        self.assertLessEqual(mem["used_pct"], 100.0)
        self.assertIn("swap_used_pct", mem)

    def test_system_summary(self):
        """Test load averages and uptime metrics."""
        summary = tasks.get_system_summary()
        self.assertIn("loadavg_1m", summary)
        self.assertIn("uptime_seconds", summary)
        self.assertIn("uptime_human", summary)
        self.assertGreaterEqual(summary["loadavg_1m"], 0.0)

    def test_processes_list(self):
        """Test process table extraction via ps."""
        procs, stats = tasks.get_processes_list(limit=25)
        self.assertIsInstance(procs, list)
        self.assertGreater(len(procs), 0)
        self.assertIn("total", stats)
        self.assertGreater(stats["total"], 0)

        first = procs[0]
        self.assertIn("pid", first)
        self.assertIn("user", first)
        self.assertIn("cpu_pct", first)
        self.assertIn("mem_pct", first)
        self.assertIn("command", first)
        self.assertIn("args", first)
        self.assertIn("is_nmb", first)

    def test_kill_process_safety_guardrails(self):
        """Test that init (PID 1) and self (current process) cannot be terminated."""
        res_init = tasks.kill_process(1)
        self.assertEqual(res_init["status"], "error")
        self.assertIn("Cannot kill init", res_init["message"])

        res_self = tasks.kill_process(os.getpid())
        self.assertEqual(res_self["status"], "error")
        self.assertIn("Cannot terminate self", res_self["message"])

    def test_full_payload_structure(self):
        """Test get_full_task_manager_payload aggregates all sections."""
        payload = tasks.get_full_task_manager_payload(limit=10)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("cpu", payload)
        self.assertIn("memory", payload)
        self.assertIn("system", payload)
        self.assertIn("processes", payload)
        self.assertLessEqual(len(payload["processes"]), 10)


if __name__ == "__main__":
    unittest.main()

