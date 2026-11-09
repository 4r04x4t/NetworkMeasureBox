"""The guided router-mode scenario: flow, restore on stop, counters (no real network)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nmb.selftest import live, scenario as S, scenario_router as R


class RouterFlowTest(unittest.TestCase):
    def setUp(self):
        self.snap = Path(tempfile.mkdtemp()) / "snap.json"
        p = patch.object(S, "SNAPSHOT", self.snap)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, funcs, preflight=True):
        with patch.object(live, "_cfg"), patch.object(S.Scenario, "snapshot", lambda sc: self.snap.write_text("{}")), \
             patch.object(S, "restore") as rest, patch.object(live, "run"), patch("builtins.print"), \
             patch.object(S, "_finish", side_effect=lambda rep, sc: rep), \
             patch.dict(R.FUNCS, funcs):
            rep = S.run_steps(list(funcs), R.FUNCS, lambda sc: preflight, {"router-up", "wan-loss"})
        return rep, rest

    def test_failed_preflight_changes_nothing(self):
        rep, rest = self._run({"router-up": MagicMock()}, preflight=False)
        rest.assert_not_called()
        self.assertFalse(self.snap.exists())

    def test_stop_signal_mid_step_restores(self):
        def stopped(sc):
            raise SystemExit("stopped by signal 15")
        after = MagicMock()
        rep, rest = self._run({"router-up": stopped, "wan-loss": after})
        rest.assert_called_once()
        after.assert_not_called()                     # nothing runs after a stop
        self.assertIn("stopped", [r["check"] for r in rep.rows])

    def test_plan_lists_only_steps(self):
        text = R.plan(R.STEPS)
        self.assertIn("wan-loss", text)
        self.assertNotIn("restore service after", text)


class InputCounterTest(unittest.TestCase):
    def test_web_ui_counter_uses_the_input_hook(self):
        sc = S.Scenario(live.Report(), SimpleNamespace())
        with patch.object(live, "run") as run:
            sc.count_start_input("192.168.100.0/24", 80)
        cmds = [" ".join(c.args[0]) for c in run.call_args_list]
        self.assertTrue(any("hook input" in c for c in cmds))
        self.assertTrue(any(c.endswith("tcp dport 80 counter") for c in cmds))


if __name__ == "__main__":
    unittest.main()


class TailscaleGuardTest(unittest.TestCase):
    def test_offline_tailscale_stops_and_restores(self):
        import threading
        sc = S.Scenario(live.Report(), SimpleNamespace())
        sc.step = "router-up"
        states = iter([True] + [False] * 50)    # online at the start, then gone
        killed = threading.Event()
        with patch.object(live, "tailscale_online", side_effect=lambda: next(states)), \
             patch.object(S.time, "sleep"), patch.object(S, "TAILSCALE_GRACE_SEC", 0), \
             patch.object(S.os, "kill", side_effect=lambda pid, sig: killed.set()), patch("builtins.print"):
            S._tailscale_guard(sc)
            self.assertTrue(killed.wait(5))
        self.assertEqual(sc.rep.rows[-1]["status"], live.FAIL)

    def test_no_guard_when_tailscale_is_not_used(self):
        sc = S.Scenario(live.Report(), SimpleNamespace())
        with patch.object(live, "tailscale_online", return_value=None), patch.object(S.threading if hasattr(S, "threading") else __import__("threading"), "Thread") as th:
            S._tailscale_guard(sc)
        th.assert_not_called()
