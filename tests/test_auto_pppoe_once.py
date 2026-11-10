"""Automatic mode dials PPPoE once per netd start (nmb/netd/daemon.py, _apply_auto_details).

2026-11-10, real DIGI line: after `systemctl restart nmb-netd` router mode came up with PPPoE, then 7 s
later "auto mode: PPPoE on; rebuilding router mode" hung up and dialled again (about 20 s more offline).
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from nmb.config import Config
from nmb.netd import daemon as netd_daemon
from nmb.netd.modes import ModeA, ModeStandalone


def _daemon(pppoe_enabled: bool, decision_pppoe: bool, running: bool):
    cfg = Config()
    cfg.network.mode = "auto"
    cfg.network.pppoe_enabled = pppoe_enabled
    d = netd_daemon.NetworkDaemon.__new__(netd_daemon.NetworkDaemon)
    d.cfg = cfg
    ma = mock.Mock(spec=ModeA)
    ma.auto_pppoe = False
    std = mock.Mock(spec=ModeStandalone)
    std.auto_passthrough = []
    d.modes = {"mode_a": ma, "standalone": std}
    d.detector = SimpleNamespace(last_decision=SimpleNamespace(mode="mode_a", pppoe=decision_pppoe, passthrough_ports=[]))
    d.current_mode_name = "mode_a" if running else None
    d.current_mode_inst = ma if running else None
    return d, ma


class AutoPppoeTest(unittest.TestCase):
    def test_no_rebuild_when_pppoe_is_dialled_anyway(self):
        d, ma = _daemon(pppoe_enabled=True, decision_pppoe=True, running=True)
        d._apply_auto_details(None)
        self.assertTrue(ma.auto_pppoe)
        ma.teardown.assert_not_called()
        ma.setup.assert_not_called()

    def test_rebuild_when_auto_mode_turns_pppoe_on(self):
        d, ma = _daemon(pppoe_enabled=False, decision_pppoe=True, running=True)
        d._apply_auto_details(None)
        ma.teardown.assert_called_once()
        ma.setup.assert_called_once()

    def test_details_set_before_the_first_setup(self):
        d, ma = _daemon(pppoe_enabled=False, decision_pppoe=True, running=False)
        d._apply_auto_details(None)
        self.assertTrue(ma.auto_pppoe)       # setup will dial right away
        ma.teardown.assert_not_called()      # nothing runs yet, nothing to rebuild


if __name__ == "__main__":
    unittest.main()
