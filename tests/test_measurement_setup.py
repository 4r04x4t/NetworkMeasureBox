"""How the box was connected for each measurement (owner, 2026-11-10): mode, link and position."""
import re
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _box_isolation  # noqa: F401  (private measurement lock on a working box)

from nmb.common import net_setup, setup_texts
from nmb.db import setup_backfill

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()
T0 = 1_794_200_000_000
MIN = 60_000


def _db():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _event(conn, ts, kind, detail):
    conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'info', 'netd', ?, ?)",
                 (ts, kind, detail))


class ClassifyTest(unittest.TestCase):
    def test_position_comes_from_the_address(self):
        self.assertEqual(net_setup.isp_path_for("pppoe", "198.51.100.7"), "direct_pppoe")
        self.assertEqual(net_setup.isp_path_for("ethernet", "198.51.100.7"), "direct_public")
        self.assertEqual(net_setup.isp_path_for("usb", "100.70.1.2"), "direct_cgnat")
        self.assertEqual(net_setup.isp_path_for("ethernet", "192.168.1.4"), "behind_router")
        self.assertEqual(net_setup.isp_path_for("ethernet", "10.0.0.5"), "behind_router")

    def test_ipv6_and_junk_prove_nothing(self):
        for value in ("2001:db8::1", "fe80::1", "169.254.3.4", "", None, "not an address"):
            self.assertIsNone(net_setup.isp_path_for("ethernet", value), value)

    def test_link_kind_from_a_stored_name_only_when_sure(self):
        by = net_setup.uplink_kind_by_name
        self.assertEqual(by("ppp0"), "pppoe")
        self.assertEqual(by("eth1", usb_ifaces=("eth1",)), "usb")   # named as a USB tether by the event log
        self.assertEqual(by("eth1"), "ethernet")
        self.assertEqual(by("usb0"), "usb")
        self.assertEqual(by("wlan0"), "wifi")
        self.assertEqual(by("br-pass"), "passthrough")
        self.assertEqual(by("bond0"), "lag")
        self.assertEqual(by("br0", box_mode="mode_b"), "bridge")
        self.assertIsNone(by("br-lan", box_mode="mode_a"))      # the box's own LAN: never the uplink
        self.assertIsNone(by("tailscale0"))
        self.assertEqual(by("eth0"), "ethernet")

    def test_live_link_never_a_vpn(self):
        self.assertIsNone(net_setup.uplink_kind_live("tailscale0"))
        self.assertIsNone(net_setup.uplink_kind_live("wg0"))

    def test_no_bound_address_describes_the_default_route(self):
        facts = net_setup.describe_link("eth0", None, "standalone",
                                        ipv4_reader=lambda i: {"wlan0": "192.168.8.9"}.get(i),
                                        kind_reader=lambda i, m: "wifi" if i == "wlan0" else "ethernet",
                                        default_iface=lambda: "wlan0")
        self.assertEqual(facts, {"iface": "wlan0", "uplink_kind": "wifi", "isp_path": "behind_router"})

    def test_an_ipv6_test_takes_its_position_from_the_link_s_ipv4(self):
        facts = net_setup.describe_link("eth0", "2001:db8::5", "standalone",
                                        ipv4_reader=lambda i: "192.168.1.4", kind_reader=lambda i, m: "ethernet",
                                        default_iface=lambda: "eth0")
        self.assertEqual(facts["isp_path"], "behind_router")


class FinishTest(unittest.TestCase):
    def test_a_mode_switch_during_the_test_is_changed(self):
        conn = _db()
        conn.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'standalone', ?)", (T0 - MIN,))
        setup = {"box_mode": "standalone", "mode_ts": T0 - MIN, "uplink_kind": "ethernet", "isp_path": "behind_router"}
        self.assertEqual(net_setup.finish(conn, setup, T0, now_ms=T0 + MIN)["setup_source"], "recorded")
        # a netd restart into the same mode, or a settings reload, is no change of mode
        conn.execute("UPDATE kv SET ts = ? WHERE k = 'active_mode'", (T0 + 20_000,))
        _event(conn, T0 + 20_000, "mode_change", "Switched from None to standalone: initial startup (x)")
        conn.execute("INSERT INTO own_action (start_ts, end_ts, kind, source) VALUES (?, ?, 'network_reload', 'netd')",
                     (T0 + 10_000, T0 + 12_000))
        self.assertEqual(net_setup.finish(conn, setup, T0, now_ms=T0 + MIN)["setup_source"], "recorded")
        # there and back within the test: seen from the event log
        _event(conn, T0 + 25_000, "mode_change", "Switched from standalone to mode_a: manual override set to mode_a")
        _event(conn, T0 + 40_000, "mode_change", "Switched from mode_a to standalone: static configuration mode=standalone")
        self.assertEqual(net_setup.finish(conn, setup, T0, now_ms=T0 + MIN)["setup_source"], "changed")
        conn.execute("DELETE FROM event")
        conn.execute("UPDATE kv SET v = 'mode_a', ts = ? WHERE k = 'active_mode'", (T0 + 30_000,))
        fin = net_setup.finish(conn, setup, T0, now_ms=T0 + MIN)
        self.assertEqual((fin["setup_source"], fin["box_mode"]), ("changed", "standalone"))


class HistoryTest(unittest.TestCase):
    def test_record_only_on_change(self):
        conn = _db()
        state = {"box_mode": "mode_a", "iface": "ppp0", "uplink_kind": "pppoe", "isp_path": "direct_pppoe"}
        self.assertTrue(net_setup.record_state(conn, state, ts=T0))
        self.assertFalse(net_setup.record_state(conn, state, ts=T0 + 5000))
        self.assertTrue(net_setup.record_state(conn, dict(state, isp_path=None), ts=T0 + 10_000))
        tl = net_setup.Timeline.load(conn)
        self.assertEqual(tl.at(T0 + 7000)["isp_path"], "direct_pppoe")
        self.assertIsNone(tl.at(T0 - 1)["box_mode"])

    def test_a_short_restart_is_not_its_own_period(self):
        rows = [(T0, "standalone", "ethernet", "behind_router", "recorded"),
                (T0 + 10 * MIN, None, None, None, "recorded"),
                (T0 + 10 * MIN + 5000, "standalone", "ethernet", "behind_router", "recorded"),
                (T0 + 20 * MIN, "mode_a", "pppoe", "direct_pppoe", "recorded")]
        tl = net_setup.Timeline(rows)
        self.assertEqual(len(tl.periods(T0, T0 + 30 * MIN)), 4)
        merged = tl.periods(T0, T0 + 30 * MIN, absorb_unknown_ms=120_000)
        self.assertEqual([(p["box_mode"], p["end_ts"] - p["start_ts"]) for p in merged],
                         [("standalone", 20 * MIN), ("mode_a", 10 * MIN)])


class BackfillTest(unittest.TestCase):
    def _speed(self, conn, ts, iface, ip, status="ok", ctype="fiber", mode=None, dur=None):
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, bound_iface, bound_ip, connection_type, "
                     "box_mode, duration_ms) VALUES (?, 'schedule', ?, 'rtr', ?, ?, ?, ?, ?)",
                     (ts, status, iface, ip, ctype, mode, dur))

    def test_rows_get_the_setup_of_their_time(self):
        conn = _db()
        _event(conn, T0, "mode_change", "Switched from None to standalone: initial startup (a router gives addresses on eth0)")
        _event(conn, T0 + 60 * MIN, "mode_change", "Switched from None to mode_a: initial startup (a PPPoE server "
               "answers on eth0 and a PPPoE login is saved: router mode with PPPoE)")
        self._speed(conn, T0 + 10 * MIN, "eth0", "192.168.1.4")
        self._speed(conn, T0 + 70 * MIN, "ppp0", "198.51.100.7")
        _event(conn, T0 + 79 * MIN, "uplink_usb_fallback", "No wired or Wi-Fi internet: using USB tethering on eth1")
        _event(conn, T0 + 85 * MIN, "uplink_usb_fallback_end", "Wired or Wi-Fi internet is back")
        self._speed(conn, T0 + 80 * MIN, "eth1", "192.168.1.4", ctype="fwa")
        self._speed(conn, T0 + 90 * MIN, None, None, status="skipped_busy")
        conn.execute("INSERT INTO outage (start_ts, cause) VALUES (?, 'x')", (T0 + 75 * MIN,))
        self.assertGreater(setup_backfill.apply(conn, now_ms=T0 + 100 * MIN), 0)
        got = [tuple(r) for r in conn.execute(
            "SELECT box_mode, uplink_kind, isp_path, setup_source FROM speedtest ORDER BY ts")]
        self.assertEqual(got, [("standalone", "ethernet", "behind_router", "derived"),
                               ("mode_a", "pppoe", "direct_pppoe", "derived"),
                               ("mode_a", "usb", "behind_router", "derived"),
                               ("mode_a", None, None, "derived")])
        self.assertEqual(tuple(conn.execute("SELECT box_mode, uplink_kind, isp_path, setup_source FROM outage").fetchone()),
                         ("mode_a", "pppoe", "direct_pppoe", "derived"))
        # every value written into a speed test row is on record (and travels to the collector):
        # mode, link, position and source for three tests, mode and source for the skipped one
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM speedtest_correction").fetchone()[0], 4 + 4 + 4 + 2)
        self.assertEqual(setup_backfill.apply(conn), 0)        # once

    def test_a_fixed_wireless_home_line_is_not_usb(self):
        # 'fwa' is also the configured type of an ordinary home line: it proves no USB tether
        conn = _db()
        _event(conn, T0, "mode_change", "Switched from None to standalone: initial startup (a router gives addresses on eth0)")
        self._speed(conn, T0 + MIN, "eth0", "192.168.0.20", ctype="fwa")
        setup_backfill.apply(conn, now_ms=T0 + 2 * MIN)
        self.assertEqual(tuple(conn.execute("SELECT uplink_kind, isp_path FROM speedtest").fetchone()),
                         ("ethernet", "behind_router"))

    def test_link_aggregation_alone_is_not_passthrough(self):
        conn = _db()
        _event(conn, T0, "mode_change",
               "Switched from None to standalone: initial startup (LAN passthrough or link aggregation enabled)")
        setup_backfill.apply(conn, now_ms=T0 + MIN)
        self.assertEqual(tuple(conn.execute("SELECT uplink_kind FROM network_state").fetchone()), (None,))

    def test_nothing_measured_is_replaced(self):
        conn = _db()
        _event(conn, T0, "mode_change", "Switched from None to mode_a: manual override set to mode_a")
        conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, bound_iface, bound_ip, box_mode, uplink_kind, "
                     "isp_path, setup_source) VALUES (?, 'schedule', 'ok', 'rtr', 'eth0', '192.168.1.4', 'standalone', "
                     "'ethernet', 'behind_router', 'recorded')", (T0 + MIN,))
        setup_backfill.apply(conn, now_ms=T0 + 2 * MIN)
        self.assertEqual(conn.execute("SELECT box_mode FROM speedtest").fetchone()[0], "standalone")

    def test_a_switch_to_another_mode_during_a_test_is_changed_a_restart_is_not(self):
        conn = _db()
        _event(conn, T0, "mode_change", "Switched from None to standalone: static configuration mode=standalone")
        _event(conn, T0 + 2 * MIN, "mode_change", "Switched from None to standalone: initial startup (x)")
        _event(conn, T0 + 12 * MIN, "mode_change", "Switched from standalone to mode_a: manual override set to mode_a")
        self._speed(conn, T0 + MIN, "eth0", "192.168.1.4", dur=3 * MIN)       # a restart into the same mode
        self._speed(conn, T0 + 11 * MIN, "eth0", "192.168.1.4", dur=3 * MIN)  # standalone -> router mode
        setup_backfill.apply(conn, now_ms=T0 + 20 * MIN)
        self.assertEqual([r[0] for r in conn.execute("SELECT setup_source FROM speedtest ORDER BY ts")],
                         ["derived", "changed"])

    def test_inside_an_own_mode_change_the_mode_is_unknown(self):
        conn = _db()
        _event(conn, T0, "mode_change", "Switched from None to standalone: static configuration mode=standalone")
        conn.execute("INSERT INTO own_action (start_ts, end_ts, kind, source) VALUES (?, ?, 'mode_change', 'netd')",
                     (T0 + 10 * MIN, T0 + 11 * MIN))
        self._speed(conn, T0 + 10 * MIN + 30_000, "eth0", "192.168.1.4")
        setup_backfill.apply(conn, now_ms=T0 + 20 * MIN)
        self.assertIsNone(conn.execute("SELECT box_mode FROM speedtest").fetchone()[0])

    def test_a_period_gets_its_link_only_when_its_tests_agree(self):
        conn = _db()
        _event(conn, T0, "mode_change", "Switched from None to standalone: static configuration mode=standalone")
        _event(conn, T0 + 60 * MIN, "mode_change", "Switched from standalone to mode_a: manual override set to mode_a")
        self._speed(conn, T0 + MIN, "eth0", "192.168.1.4")
        self._speed(conn, T0 + 2 * MIN, "eth0", "192.168.1.4")
        self._speed(conn, T0 + 61 * MIN, "eth0", "192.168.1.4")
        self._speed(conn, T0 + 62 * MIN, "eth0", "198.51.100.7")              # disagrees: unknown
        setup_backfill.apply(conn, now_ms=T0 + 90 * MIN)
        rows = [tuple(r) for r in conn.execute(
            "SELECT box_mode, uplink_kind, isp_path FROM network_state WHERE source = 'derived' ORDER BY ts")]
        self.assertEqual(rows, [("standalone", "ethernet", "behind_router"), ("mode_a", None, None)])


class RunnerTest(unittest.TestCase):
    def test_the_row_stores_the_setup_of_its_start(self):
        from nmb.speed import runner
        conn = _db()
        conn.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'mode_a', ?)", (T0,))
        conn.commit()
        cfg = SimpleNamespace(isp=SimpleNamespace(connection_type="fiber"),
                              iperf=SimpleNamespace(target_host="iperf.example", target_port=5201, duration=10,
                                                    protocol="tcp", parallel=4, reverse=False, bidir=False,
                                                    auto_direction="download"))
        with mock.patch("nmb.speed.iperf.run_iperf_client_test", return_value={"status": "ok", "bps": 9e8}), \
                mock.patch("nmb.netd.interfaces.find_preferred_measurement_interface",
                           return_value=("ppp0", "198.51.100.7", False)), \
                mock.patch("nmb.common.net_setup.uplink_kind_live", return_value="pppoe"), \
                mock.patch("nmb.common.netaddr.lookup_public_ip", return_value=None):
            runner._run_single_engine("iperf3", cfg, "schedule", None, conn, 1000, target_iface=None)
        row = conn.execute("SELECT box_mode, uplink_kind, isp_path, setup_source FROM speedtest").fetchone()
        self.assertEqual(tuple(row), ("mode_a", "pppoe", "direct_pppoe", "recorded"))

    def test_skip_rows_carry_the_mode(self):
        from nmb.speed import runner
        conn = _db()
        conn.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'standalone', ?)", (T0,))
        runner._skip_row(conn, T0, "schedule", "deferred: x", "rtr")
        self.assertEqual(tuple(conn.execute("SELECT box_mode, setup_source, nmb_version IS NOT NULL FROM speedtest").fetchone()),
                         ("standalone", "recorded", 1))


class NetdLinkTest(unittest.TestCase):
    def test_standalone_uses_the_measuring_link_not_the_default_route(self):
        with mock.patch.object(net_setup, "default_route_iface", return_value="eth0"):
            self.assertEqual(net_setup.netd_link("standalone", {}, None, lambda: "wlan0"), "wlan0")
            self.assertEqual(net_setup.netd_link("standalone", {}, None, lambda: None), "eth0")
        self.assertEqual(net_setup.netd_link("mode_a", {"wan_interface": "ppp0"}, None, lambda: "wlan0"), "ppp0")

    def test_prune_keeps_the_setup_that_still_holds(self):
        from nmb.db import database as db
        conn = _db()
        old = db.now_ms() - 800 * 86_400_000
        for i, mode in enumerate(("standalone", "mode_a")):
            conn.execute("INSERT INTO network_state (ts, box_mode, source) VALUES (?, ?, 'recorded')", (old + i, mode))
        with mock.patch.object(db, "RETENTION", {"network_state": 730}):
            db.prune(conn)
        self.assertEqual([r[0] for r in conn.execute("SELECT box_mode FROM network_state")], ["mode_a"])


class OutageTest(unittest.TestCase):
    def test_outage_takes_netd_s_last_record(self):
        from nmb.probe import engine
        conn = _db()
        net_setup.record_state(conn, {"box_mode": "mode_a", "iface": "ppp0", "uplink_kind": "pppoe",
                                      "isp_path": "direct_pppoe"}, ts=T0)
        self.assertEqual(engine._setup_at(conn, T0 + MIN),
                         {"box_mode": "mode_a", "uplink_kind": "pppoe", "isp_path": "direct_pppoe", "setup_source": "recorded"})
        empty = _db()
        empty.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'standalone', ?)", (T0,))
        self.assertEqual(engine._setup_at(empty, T0)["box_mode"], "standalone")


class NetdTest(unittest.TestCase):
    def test_netd_records_a_change_once(self):
        from nmb.netd import daemon
        conn = _db()
        nd = daemon.NetworkDaemon.__new__(daemon.NetworkDaemon)
        nd.cfg = SimpleNamespace(network=SimpleNamespace(bridge_interface="br0"))
        nd.current_mode_name = "mode_a"
        nd.current_mode_inst = SimpleNamespace(get_status=lambda: {"wan_interface": "ppp0"})
        class _Keep:                           # the daemon closes its connection; the test reads it after
            def __getattr__(self, name):
                return getattr(conn, name)

            def close(self):
                pass
        with mock.patch.object(daemon.db, "connect", return_value=_Keep()), \
                mock.patch("nmb.common.net_setup.uplink_kind_live", return_value="pppoe"), \
                mock.patch("nmb.common.net_setup.iface_ipv4", return_value="198.51.100.7"):
            nd._record_setup()
            nd._record_setup()
            nd._record_setup(stopped=True)
        rows = [tuple(r) for r in conn.execute("SELECT box_mode, iface, uplink_kind, isp_path FROM network_state ORDER BY id")]
        self.assertEqual(rows, [("mode_a", "ppp0", "pppoe", "direct_pppoe"), (None, None, None, None)])


class CollectorTest(unittest.TestCase):
    def test_only_known_codes_are_stored(self):
        from nmb.collector import server
        self.assertEqual(server._speed_value("isp_path", "behind_router"), "behind_router")
        self.assertIsNone(server._speed_value("isp_path", "<script>"))
        self.assertIsNone(server._speed_value("box_mode", 1))
        from nmb.collector import client
        self.assertEqual(client.SPEED_FIELDS[1:], server.SPEED_COLS[1:])


class TextsTest(unittest.TestCase):
    def test_every_language_has_every_text(self):
        for lang in setup_texts.LANGUAGES:
            with self.subTest(lang=lang):
                self.assertEqual(set(setup_texts.TEXTS[lang]), set(setup_texts.TEXTS["en"]))
                for key, text in setup_texts.TEXTS[lang].items():
                    self.assertTrue(text.strip(), key)
                    self.assertNotIn("{", text)          # used with str.format by the bot
                    if lang != "hu":
                        self.assertIsNone(re.search(r"[őűŐŰ]", text), (lang, key))
        for key, text in setup_texts.TEXTS["en"].items():
            self.assertIsNone(re.search("[áéíóúÁÉÍÓÚ]", text), key)

    def test_every_code_has_a_label(self):
        for lang in setup_texts.LANGUAGES:
            unknown = setup_texts.TEXTS[lang]["setup_unknown"]
            for code in net_setup.MODES:
                self.assertNotEqual(setup_texts.mode_label(code, lang), unknown)
            for code in net_setup.UPLINK_KINDS:
                self.assertNotEqual(setup_texts.link_label(code, lang), unknown)
            for code in net_setup.ISP_PATHS:
                self.assertNotEqual(setup_texts.path_label(code, lang), unknown)
            for code in net_setup.SOURCES:
                self.assertNotEqual(setup_texts.source_label(code, lang), unknown)

    def test_web_and_bot_have_the_same_texts(self):
        from nmb.bot import i18n as bot
        from nmb.web.i18n import TRANSLATIONS
        for lang in setup_texts.LANGUAGES:
            self.assertEqual(TRANSLATIONS[lang]["setup_path_behind_router"], setup_texts.TEXTS[lang]["setup_path_behind_router"])
            self.assertEqual(bot.t("setup_label", lang), setup_texts.TEXTS[lang]["setup_label"])


if __name__ == "__main__":
    unittest.main()
