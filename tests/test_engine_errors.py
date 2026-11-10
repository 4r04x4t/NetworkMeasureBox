"""A speed test engine that raises is a failed measurement of that engine, never a lost cycle.

2026-11-09 on the box: while it had no internet, RTR's control-server request raised URLError out of
the scheduled cycle (24 tracebacks in an hour): no error row, and the engines after it did not run.
"""
import _box_isolation  # noqa: F401  (private measurement lock on a working box)
import sqlite3
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.speed import runner
from nmb.speed.rmbt import connection, control


class EngineRaisesTest(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript((Path(runner.__file__).resolve().parent.parent / "db" / "schema.sql").read_text())
        return conn

    def test_network_error_is_stored_as_a_failed_test(self):
        conn = self._conn()
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"))
        boom = urllib.error.URLError(OSError(101, "Network is unreachable"))
        with mock.patch.object(runner, "execute_rtr_speedtest", side_effect=boom), \
             mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface", return_value=("ppp0", "192.0.2.9", True)):
            res = runner._run_single_engine("rtr", cfg, "schedule", None, conn, 1, target_iface=None)
        self.assertEqual(res.status, "error")
        self.assertIn("unreachable", res.error)
        row = conn.execute("SELECT status, engine, error FROM speedtest").fetchone()
        self.assertEqual(row[:2], ("error", "rtr"))


class RmbtControlBoundTest(unittest.TestCase):
    def tearDown(self):
        connection.set_bind_target(interface=None, bind_ip=None)

    def test_no_unbound_retry_when_bound(self):
        connection.set_bind_target(interface="ppp0", bind_ip="192.0.2.9")
        opener = mock.MagicMock()
        opener.open.side_effect = urllib.error.URLError(OSError(22, "Invalid argument"))
        with mock.patch.object(control.urllib.request, "build_opener", return_value=opener), \
             mock.patch.object(control.urllib.request, "urlopen") as unbound:
            with self.assertRaises(RuntimeError) as ctx:
                control._post("https://example.invalid/x", {}, False)
        unbound.assert_not_called()
        self.assertIn("ppp0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class RouterWanDownTest(unittest.TestCase):
    """2026-11-09: DIGI refused the PPPoE login ("Too many sessions") for some minutes and router mode had no
    WAN; 19 scheduled tests in an hour then ran over the USB hotspot (the wrong line, and mobile data)."""

    def _cycle(self, target_iface=None, addr=None):
        from nmb.config import Config
        cfg = Config()
        outcome = {}
        with mock.patch("nmb.netd.interfaces.router_wan_interface", return_value="ppp0"), \
             mock.patch("nmb.netd.interfaces._usable_address", return_value=addr), \
             mock.patch.object(runner, "_run_single_engine", side_effect=AssertionError("no test may run")) as eng:
            try:
                ok = runner._run_measurement_cycle(cfg, trigger="schedule", engine="cloudflare",
                                                   target_iface=target_iface, outcome=outcome)
            except AssertionError:
                ok = None
        return ok, outcome, eng.called

    def test_no_test_while_the_router_wan_is_down(self):
        ok, outcome, ran = self._cycle()
        self.assertFalse(ok)
        self.assertTrue(outcome.get("wan_down"))
        self.assertFalse(ran)

    def test_a_chosen_interface_still_runs(self):
        _, outcome, _ = self._cycle(target_iface="eth1")
        self.assertNotIn("wan_down", outcome)


class DynDnsIpv4DetectionTest(unittest.TestCase):
    """2026-11-09: with IPv6 on the box a dual-stack detector answered with the IPv6 address, and it was sent
    to dynv6 as the IPv4 one (the A record then pointed elsewhere)."""

    def test_an_ipv6_answer_is_not_an_ipv4_address(self):
        from nmb.netd import duckdns
        answers = iter(["2a01:db8::1", "198.51.100.7"])
        with mock.patch.object(duckdns, "_get_over_ipv4", side_effect=lambda url, t: next(answers)):
            self.assertEqual(duckdns.detect_public_ip(), "198.51.100.7")

    def test_nothing_usable_gives_none(self):
        from nmb.netd import duckdns
        with mock.patch.object(duckdns, "_get_over_ipv4", side_effect=["", "not an ip", OSError("down")]):
            self.assertIsNone(duckdns.detect_public_ip())

    def test_detectors_are_ipv4_only_names(self):
        from nmb.netd import duckdns
        self.assertNotIn("https://icanhazip.com", duckdns.IP_DETECTORS_V4)
        self.assertNotIn("https://ifconfig.me/ip", duckdns.IP_DETECTORS_V4)


class DynDnsSendsIpv4Test(unittest.TestCase):
    def test_dynv6_gets_the_ipv4_address_not_auto(self):
        from nmb.netd import duckdns
        sent = {}

        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"addresses updated"

        def fake_open(req, timeout=0):
            sent["url"] = req.full_url
            return Resp()
        with mock.patch.object(duckdns, "detect_public_ip", return_value="198.51.100.7"), \
             mock.patch.object(duckdns, "detect_public_ipv6", return_value=""), \
             mock.patch.object(duckdns.urllib.request, "urlopen", side_effect=fake_open):
            duckdns.update_duckdns(domain="x.v6.army", token="t" * 30, provider="dynv6", ipv6_mode="none")
        self.assertIn("ipv4=198.51.100.7", sent["url"])
        self.assertNotIn("ipv4=auto", sent["url"])


class UsbTestGuardTest(unittest.TestCase):
    def _allowed(self, state, link="auto", iface="eth1"):
        import json as _json
        from nmb.config import Config
        cfg = Config()
        cfg.network.measurement_link = link
        real_read = Path.read_text

        def fake(self_path, *a, **k):
            if str(self_path) == "/run/nmb/netd_state.json":
                if state is None:
                    raise FileNotFoundError(self_path)
                return _json.dumps(state)
            return real_read(self_path, *a, **k)
        with mock.patch("nmb.netd.interfaces.usb_tether_kind", side_effect=lambda i: "tether" if i == "eth1" else None), \
             mock.patch.object(Path, "read_text", fake):
            return not runner._usb_test_not_allowed(cfg, iface)

    def test_no_usb_test_while_netd_restarts_or_in_router_mode(self):
        self.assertFalse(self._allowed(None))                                                    # state file gone
        self.assertFalse(self._allowed({"active_mode": None}))
        self.assertFalse(self._allowed({"active_mode": "mode_a", "details": {"wan_interface": "ppp0"}}))

    def test_usb_allowed_when_it_is_the_line(self):
        self.assertTrue(self._allowed({"active_mode": "mode_a", "details": {"wan_interface": "eth1"}}))
        self.assertTrue(self._allowed({"active_mode": "standalone"}))
        self.assertTrue(self._allowed(None, link="usb"))
        self.assertTrue(self._allowed(None, iface="eth0"))                                       # not USB at all


class IperfRestWarningOnceTest(unittest.TestCase):
    def test_warning_once_also_with_the_usable_check_in_between(self):
        cfg = mock.MagicMock()
        runner._IPERF3_REST_LOGGED.clear()
        self.addCleanup(runner._IPERF3_REST_LOGGED.clear)
        conn = object()
        with mock.patch.object(runner, "iperf3_servers", return_value=[("iperf.example", 5201)]), \
             mock.patch.object(runner, "_iperf3_failing", side_effect=lambda c, h, now_ms=None: c is not None), \
             mock.patch.object(runner, "_answers", return_value=True), \
             mock.patch.object(runner.log, "warning") as warn:
            for _ in range(5):
                runner._iperf3_usable(cfg)               # no history: says nothing about failing
                runner._usable_iperf3_servers(cfg, conn)  # with history: failing, left out
        self.assertEqual(warn.call_count, 1)
