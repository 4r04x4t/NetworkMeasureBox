"""The ping probe follows the line, and gateway targets that do not fit it are switched off.

2026-11-09, router mode on PPPoE: the probe stayed bound to eth0 (no address under PPPoE) and lost every
ping for 6 hours, opening false outages; the ISP First Hop was the PPP peer placeholder 10.0.0.1, which
never answers, and the Local Gateway was still the home router that was no longer there.
"""
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.netd import interfaces
from nmb.probe import engine

SCHEMA = (Path(engine.__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM target")
    for addr, label, role in (("1.1.1.1", "Cloudflare", "Public DNS"), ("192.168.8.1", "Local Gateway", "Local Gateway"),
                              ("10.0.0.1", "ISP First Hop", "ISP First Hop")):
        conn.execute("INSERT INTO target (addr, label, enabled, role) VALUES (?, ?, 1, ?)", (addr, label, role))
    return conn


def _enabled(conn):
    return {r["role"]: r["enabled"] for r in conn.execute("SELECT role, enabled FROM target")}


class ProbeDeviceTest(unittest.TestCase):
    def test_router_mode_probes_over_the_router_wan(self):
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value="ppp0"), \
             mock.patch("nmb.netd.interfaces._usable_address", return_value="198.51.100.7"):
            self.assertEqual(engine.probe_device(SimpleNamespace()), "ppp0")

    def test_no_binding_to_a_link_without_an_address(self):
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value="ppp0"), \
             mock.patch("nmb.netd.interfaces._usable_address", return_value=None):
            self.assertIsNone(engine.probe_device(SimpleNamespace()))
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value=None), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", None, True)):
            self.assertIsNone(engine.probe_device(SimpleNamespace()))
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value=None), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("eth0", "192.168.8.218", True)):
            self.assertEqual(engine.probe_device(SimpleNamespace()), "eth0")

    def test_rebinds_when_the_line_changes(self):
        eng = engine.ProbeEngine.__new__(engine.ProbeEngine)
        eng.cfg, eng.bind_dev, eng.last_bind_check, eng.epoll = SimpleNamespace(), "eth0", -1e9, None
        eng.sock = mock.MagicMock()
        eng.pending_pings = {(1, 1): object()}
        with mock.patch.object(engine, "probe_device", return_value="ppp0"), \
             mock.patch.object(engine, "create_icmp_socket", return_value=(mock.MagicMock(), False)) as mk, \
             mock.patch.object(engine.ProbeEngine, "_load_targets"):
            eng._check_bind_device(100.0)
        mk.assert_called_once_with(bind_iface="ppp0")
        self.assertEqual((eng.bind_dev, eng.pending_pings), ("ppp0", {}))


class GatewayTargetsTest(unittest.TestCase):
    def _sync(self, conn, gw, hop, peers, isp_first_hop=True):
        with mock.patch.object(interfaces, "get_default_gateway", return_value=gw), \
             mock.patch.object(interfaces, "get_isp_first_hop", return_value=hop), \
             mock.patch.object(interfaces, "ppp_peer_addresses", return_value=peers):
            interfaces.sync_gateway_ping_targets(conn, "ppp0", isp_first_hop=isp_first_hop)

    def test_pppoe_switches_off_the_placeholder_and_the_missing_gateway(self):
        conn = _conn()
        self._sync(conn, None, "10.0.0.1", ["10.0.0.1"])
        self.assertEqual(_enabled(conn), {"Public DNS": 1, "Local Gateway": 0, "ISP First Hop": 0})

    def test_owner_can_turn_the_first_hop_off(self):
        conn = _conn()
        self._sync(conn, "192.168.8.1", "84.2.0.1", [], isp_first_hop=False)
        self.assertEqual(_enabled(conn)["ISP First Hop"], 0)
        self.assertEqual(_enabled(conn)["Local Gateway"], 1)

    def test_behind_a_router_both_come_back(self):
        conn = _conn()
        conn.execute("UPDATE target SET enabled = 0 WHERE role != 'Public DNS'")
        self._sync(conn, "192.168.8.1", "84.2.0.1", [])
        self.assertEqual(_enabled(conn), {"Public DNS": 1, "Local Gateway": 1, "ISP First Hop": 1})
        self.assertEqual(conn.execute("SELECT addr FROM target WHERE role = 'ISP First Hop'").fetchone()[0], "84.2.0.1")

    def test_ppp_peer_parsing(self):
        out = "5: ppp0    inet 62.77.199.46 peer 10.0.0.1/32 scope global ppp0\\n"
        with mock.patch.object(interfaces, "run_cmd", return_value=SimpleNamespace(stdout=out)), \
             mock.patch.object(interfaces.shutil, "which", return_value="/usr/sbin/ip"):
            self.assertEqual(interfaces.ppp_peer_addresses(), ["10.0.0.1"])


class MetricsHideSwitchedOffTargetsTest(unittest.TestCase):
    def test_switched_off_target_is_not_in_the_table(self):
        from nmb.report import metrics
        import inspect
        src = inspect.getsource(metrics)
        self.assertIn("FROM target WHERE enabled = 1", src)
        self.assertIn("if tid not in target_map:", src)


if __name__ == "__main__":
    unittest.main()


class WiredMetricTest(unittest.TestCase):
    """The wired priority goes into the NetworkManager profile, not a route of our own outside it."""

    def test_metric_set_in_the_profile_and_old_route_removed(self):
        calls = []

        def run(cmd, **k):
            calls.append(cmd)
            out = ""
            if cmd[:3] == ["nmcli", "-g", "GENERAL.CONNECTION"]:
                out = "netplan-eth0\n"
            elif cmd[:3] == ["nmcli", "-g", "ipv4.route-metric"]:
                out = "-1\n"
            elif cmd[:4] == ["ip", "-4", "route", "show"]:
                out = "default via 192.168.8.1 metric 50\n"
            return SimpleNamespace(stdout=out, stderr="", returncode=0)
        with mock.patch.object(interfaces.shutil, "which", return_value="/usr/bin/nmcli"), \
             mock.patch.object(interfaces.subprocess, "run", side_effect=run):
            self.assertTrue(interfaces._wired_metric_via_network_manager("eth0"))
        self.assertIn(["nmcli", "connection", "modify", "netplan-eth0", "ipv4.route-metric", "50"], calls)
        self.assertIn(["nmcli", "device", "reapply", "eth0"], calls)
        dels = [c for c in calls if c[:4] == ["ip", "-4", "route", "del"]]
        self.assertEqual(dels, [["ip", "-4", "route", "del", "default", "via", "192.168.8.1", "metric", "50", "dev", "eth0"]])
        self.assertFalse(any(c[:3] == ["ip", "route", "replace"] for c in calls))

    def test_unmanaged_port_falls_back(self):
        with mock.patch.object(interfaces.shutil, "which", return_value="/usr/bin/nmcli"), \
             mock.patch.object(interfaces.subprocess, "run", return_value=SimpleNamespace(stdout="--\n", stderr="", returncode=0)):
            self.assertIsNone(interfaces._wired_metric_via_network_manager("eth0"))
