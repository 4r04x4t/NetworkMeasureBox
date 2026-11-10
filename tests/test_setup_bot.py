"""The bot, the self-test and the collector say how the box was connected (owner, 2026-11-10).

Every value comes from the row itself (never today's setup for an old row); unknown says so.
"""
import contextlib
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.bot import commands as C
from nmb.bot.alerts import AlertMonitor
from nmb.bot.commands import CommandHandler
from nmb.bot.i18n import set_chat_lang
from nmb.collector import server as col
from nmb.config import Config
from nmb.db import database as db
from nmb.selftest import live

NOW = 1_762_780_000_000      # a fixed clock for the rows of one /test run
HU_LETTERS = re.compile(r"[őűŐŰ]|ismeretlen|mögött|szolgáltató")


class Client:
    def __init__(self):
        self.messages = []
        self.documents = []

    def send_message(self, chat_id, text, parse_mode="HTML", reply_markup=None):
        self.messages.append(text)
        return True

    def send_document(self, chat_id, filename, content, caption=""):
        self.documents.append((filename, content))
        return True

    def __getattr__(self, name):
        return lambda *a, **k: True


class _DbCase(unittest.TestCase):
    """A throwaway box database (NMB_LIVE_DB), so nothing touches the real one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "nmb.db")
        env = patch.dict(os.environ, {"NMB_LIVE_DB": path, "NMB_PERSIST_DB": path})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        conn = db.connect()
        db.init(conn)
        conn.close()
        self.cfg = Config()
        self.cfg.telegram.allowed_chat_ids = [4242]
        self.client = Client()
        self.bot = CommandHandler(self.cfg, self.client)

    def sql(self, query, args=()):
        conn = db.connect()
        try:
            with db.tx(conn):
                conn.execute(query, args)
        finally:
            conn.close()

    def speed(self, engine="ookla", mode="mode_a", kind="pppoe", path="direct_pppoe", source="recorded",
              ts=NOW, trigger="telegram"):
        self.sql("INSERT INTO speedtest (ts, trigger, status, down_bps, up_bps, ping_us, jitter_us, server_name, engine, "
                 "box_mode, uplink_kind, isp_path, setup_source) VALUES (?, ?, 'ok', 500000000, 100000000, 8500, 1200, "
                 "'Srv', ?, ?, ?, ?, ?)", (ts, trigger, engine, mode, kind, path, source))

    def state(self, mode, iface, kind, path, source="recorded", ts=None):
        self.sql("INSERT INTO network_state (ts, box_mode, iface, uplink_kind, isp_path, source) VALUES (?, ?, ?, ?, ?, ?)",
                 (ts or int(time.time() * 1000) - 60_000, mode, iface, kind, path, source))

    def kv(self, key, value):
        self.sql("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (key, value, int(time.time() * 1000)))

    def run_test(self, lang="en"):
        set_chat_lang(1, lang)
        self.client.messages.clear()
        with patch.object(C, "run_measurement_cycle", return_value=True), patch.object(C.db, "now_ms", return_value=NOW):
            self.bot.handle_command(1, "/test")
        return self.client.messages[-1]

    def run_status(self, lang="en"):
        set_chat_lang(1, lang)
        self.client.messages.clear()
        with contextlib.ExitStack() as st:     # nothing of the real system, nothing on the network
            st.enter_context(patch.object(C.interfaces, "get_dual_stack_ips", return_value={}))
            st.enter_context(patch.object(C.interfaces, "get_carrier", return_value=True))
            st.enter_context(patch.object(C.tailscale, "get_tailscale_status", return_value={}))
            st.enter_context(patch.object(C.wg, "get_wireguard_status", return_value={"active": False}))
            st.enter_context(patch.object(C.ab, "get_full_adblock_status", return_value={"enabled": False}))
            self.bot.handle_command(1, "/status")
        return self.client.messages[-1]


class TestResultSetup(_DbCase):
    def test_one_engine_says_its_setup(self):
        self.speed()
        msg = self.run_test()
        self.assertIn("<b>Setup:</b> Router · PPPoE · direct to the ISP", msg)
        self.assertNotIn("Measured behind another router", msg)

    def test_behind_a_router_warns_and_a_changed_setup_says_so(self):
        self.speed(mode="standalone", kind="ethernet", path="behind_router", source="changed")
        msg = self.run_test()
        self.assertIn("Standalone · Ethernet · behind another router (<i>changed during the test</i>)", msg)
        self.assertIn("<i>Measured behind another router: that router may limit the speed", msg)

    def test_an_unknown_setup_is_unknown_not_todays(self):
        self.state("mode_a", "ppp0", "pppoe", "direct_pppoe")       # the box is on PPPoE now ...
        self.speed(mode=None, kind=None, path=None, source=None)    # ... but this row recorded nothing
        msg = self.run_test()
        self.assertIn("<b>Setup:</b> unknown", msg)
        self.assertNotIn("PPPoE", msg)

    def test_engines_with_different_setups_each_say_their_own(self):
        self.speed("ookla", path="direct_pppoe")
        self.speed("cloudflare", path="behind_router")
        msg = self.run_test()
        self.assertIn("• OOKLA: 500.0 / 100.0 Mbps, 8.5 ms | Setup: Router · PPPoE · direct to the ISP", msg)
        self.assertIn("• CLOUDFLARE: 500.0 / 100.0 Mbps, 8.5 ms | Setup: Router · PPPoE · behind another router", msg)
        self.assertIn("Measured behind another router", msg)

    def test_engines_with_one_setup_say_it_once(self):
        self.speed("ookla")
        self.speed("cloudflare")
        msg = self.run_test()
        self.assertEqual(msg.count("Setup"), 1)

    def test_a_database_without_the_columns_still_answers(self):
        self.speed()
        with patch.object(C, "_columns", return_value=set()):   # a read-only connection on an old database
            msg = self.run_test()
        self.assertIn("500.0 Mbps", msg)
        self.assertNotIn("Setup", msg)

    def test_every_language_has_its_own_words(self):
        self.speed(path="behind_router")
        self.assertIn("<b>Bekötés:</b> Router · PPPoE · másik router mögött", self.run_test("hu"))
        for lang in ("en", "de", "fr", "uk", "ro", "it", "es", "pt", "pt-br", "zh"):
            with self.subTest(lang=lang):
                self.assertIsNone(HU_LETTERS.search(self.run_test(lang)))


class TestStatusAndMode(_DbCase):
    def test_status_shows_the_mode_in_words_and_the_current_link(self):
        self.kv("active_mode", "mode_a")
        self.state("mode_a", "ppp0", "pppoe", "direct_pppoe")
        self.speed(ts=int(time.time() * 1000) - 120_000, trigger="schedule", mode="standalone", kind="ethernet",
                   path="behind_router", source="derived")
        msg = self.run_status()
        self.assertIn("<b>Operating Mode:</b> <b>Router</b>", msg)
        self.assertNotIn("MODE_A", msg)
        self.assertIn("<b>Link:</b> PPPoE (<code>ppp0</code>) | <b>Path to the ISP:</b> Direct to the ISP (own PPPoE session)", msg)
        # the latest test keeps its own setup, not the current one
        self.assertIn("↳ Setup: Standalone · Ethernet · behind another router (<i>reconstructed from the event log</i>)", msg)

    def test_status_without_records_says_unknown(self):
        self.state("mode_b", "br0", "bridge", "direct_public", source="derived")   # history, not the present
        msg = self.run_status()
        self.assertIn("<b>Operating Mode:</b> <b>unknown</b>", msg)
        self.assertIn("<b>Link:</b> unknown | <b>Path to the ISP:</b> unknown", msg)
        self.assertNotIn("↳", msg)                                                # no test, no setup line
        self.assertIn("<b>Üzemmód:</b> <b>ismeretlen</b>", self.run_status("hu"))

    def test_status_in_every_language(self):
        self.kv("active_mode", "mode_b")
        self.state("mode_b", "br0", "bridge", "direct_cgnat")
        self.speed(ts=int(time.time() * 1000) - 60_000, trigger="schedule")
        for lang in ("en", "de", "fr", "uk", "ro", "it", "es", "pt", "pt-br", "zh"):
            with self.subTest(lang=lang):
                msg = self.run_status(lang)
                self.assertIsNone(HU_LETTERS.search(msg))
                self.assertIsNone(re.search(r"\{[a-z_]+\}|setup_[a-z_]+", msg))   # no raw key, no placeholder

    def test_a_raw_mode_value_is_never_echoed(self):
        self.kv("active_mode", "<b>MODE_X")
        self.assertIn("<b>Operating Mode:</b> <b>unknown</b>", self.run_status())
        self.bot.handle_command(1, "/mode")
        self.assertIn("Current mode: <b>unknown</b>", self.client.messages[-1])
        self.assertNotIn("MODE_X", self.client.messages[-1])

    def test_mode_command_says_the_mode_and_its_code(self):
        self.kv("active_mode", "standalone")
        set_chat_lang(1, "de")
        self.bot.handle_command(1, "/mode")
        self.assertIn("<b>Eigenständig (Client in einem bestehenden Netz) (standalone)</b>", self.client.messages[-1])

    def test_ai_bundle_uses_its_cache(self):
        with patch("nmb.report.llm_bundle.generate_llm_diagnostic_bundle", return_value="# Bundle") as gen:
            self.bot.handle_command(1, "/ai")
        gen.assert_called_once_with(self.cfg)        # no connection in force_refresh's place
        self.assertEqual(self.client.documents[0][1], b"# Bundle")


class TestOutageAlertSetup(_DbCase):
    def alert(self, **cols):
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        self.sql(f"INSERT INTO outage (start_ts, cause{', ' if cols else ''}{names}) VALUES (?, 'WAN down'"
                 f"{', ' if cols else ''}{marks})", (int(time.time() * 1000), *cols.values()))
        mon = AlertMonitor(self.cfg, self.client)
        conn = db.connect()
        try:
            mon.check_outages(conn)
        finally:
            conn.close()
        return self.client.messages[-1]

    def test_alert_says_the_setup_when_it_began(self):
        msg = self.alert(box_mode="standalone", uplink_kind="wifi", isp_path="behind_router", setup_source="recorded")
        self.assertIn("CRITICAL NETWORK OUTAGE DETECTED", msg)
        self.assertIn("\nSetup: Standalone · Wi-Fi client · behind another router", msg)

    def test_alert_with_nothing_recorded_says_unknown(self):
        self.assertIn("\nSetup: unknown", self.alert())


class TestSelftestBotCleanup(_DbCase):
    def langs(self):
        conn = db.connect(readonly=True)
        try:
            return {r[0] for r in conn.execute("SELECT k FROM kv WHERE k LIKE 'telegram_lang_%'")}
        finally:
            conn.close()

    def test_fake_chats_never_take_a_configured_one(self):
        self.assertEqual(live.fake_chat_ids(3, [990000101, "x"]), [990000100, 990000102, 990000103])

    def test_the_check_removes_only_its_own_rows(self):
        set_chat_lang(4242, "de")                      # a real chat
        set_chat_lang(990000100, "fr")                 # left over by an earlier run
        rep = live.Report(quiet=True)

        class Handler:
            def __init__(self, cfg, client):
                self.client = client

            def handle_command(self, chat, text):
                self.client.send_message(chat, "ok")

        with patch("nmb.bot.commands.CommandHandler", Handler):
            live.g_telegram(rep, self.cfg)
        self.assertEqual(self.langs(), {"telegram_lang_4242"})
        self.assertIn(("test chats removed", "PASS"), [(r["check"], r["status"]) for r in rep.rows])

    def test_the_rows_go_also_when_the_check_breaks(self):
        rep = live.Report(quiet=True)
        set_chat_lang(4242, "de")
        with patch("nmb.bot.i18n.get_main_keyboard", side_effect=[{"keyboard": []}, RuntimeError("broken")]), \
             patch("nmb.bot.commands.CommandHandler"):
            with self.assertRaises(RuntimeError):
                live.g_telegram(rep, self.cfg)
        self.assertEqual(self.langs(), {"telegram_lang_4242"})


class TestSelftestRespectsTheSetup(unittest.TestCase):
    def rows(self, engine, path, down, n=5):
        return [{"engine": engine, "iface": "eth0", "isp_path": path, "down_bps": down, "client_ip": "192.0.2.1"}
                for _ in range(n)]

    def test_engines_are_compared_only_in_one_setup(self):
        rows = self.rows("ookla", "behind_router", 100e6) + self.rows("rtr", "direct_public", 300e6)
        names = [n for n, _, _ in live.evaluate_engines(rows)]
        self.assertIn("client IP rtr@eth0/direct_public", names)
        self.assertFalse(any("vs reference" in n for n in names))
        same = self.rows("ookla", "behind_router", 100e6) + self.rows("rtr", "behind_router", 300e6)
        res = {n: s for n, s, _ in live.evaluate_engines(same)}
        self.assertEqual(res["download rtr@eth0/behind_router vs reference"], live.WARN)

    def test_the_newest_test_must_carry_its_setup(self):
        old = {"box_mode": None, "uplink_kind": None, "isp_path": None, "setup_source": None}
        new = {"box_mode": "mode_a", "uplink_kind": "pppoe", "isp_path": "direct_pppoe", "setup_source": "recorded"}
        (name, st, detail), = live.evaluate_setup([old, new])
        self.assertEqual((name, st), ("setup of the tests", live.PASS))
        self.assertEqual(detail, "1x direct_pppoe, 1x unknown")
        (_, st, detail), = live.evaluate_setup([new, old])
        self.assertEqual(st, live.WARN)
        self.assertIn("lacks its setup (source none, box_mode, uplink_kind)", detail)
        self.assertEqual(live.evaluate_setup([]), [])

    def test_the_history_follows_the_running_mode(self):
        state = {"box_mode": "standalone", "iface": "eth0", "uplink_kind": "ethernet", "isp_path": "behind_router"}
        self.assertEqual(live.evaluate_setup_history(state, "standalone"),
                         ("setup history", live.PASS, "standalone on eth0: ethernet, behind_router"))
        self.assertEqual(live.evaluate_setup_history(state, "mode_a")[1], live.WARN)
        self.assertEqual(live.evaluate_setup_history(None, "mode_a")[1], live.WARN)


class TestCollectorSetupColumn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = col.connect(Path(self.tmp.name))
        self.addCleanup(self.conn.close)
        now = int(time.time() * 1000)
        self.conn.execute("INSERT INTO box (box_uid, box_name, last_seen) VALUES ('b1', 'Box', ?)", (now,))
        rows = [(1, "mode_a", "pppoe", "direct_pppoe", "recorded"),
                (2, "standalone", "ethernet", "behind_router", "changed"),
                (3, "<script>x</script>", "wifi", "<img src=x>", "derived"),     # what a box should never send
                (4, None, None, None, None)]
        for src_id, mode, kind, path, source in rows:
            self.conn.execute("INSERT INTO speedtest (box_uid, src_id, ts, status, engine, box_mode, uplink_kind, isp_path, "
                              "setup_source) VALUES ('b1', ?, ?, 'ok', 'rtr', ?, ?, ?, ?)",
                              (src_id, now - src_id * 1000, mode, kind, path, source))
        self.conn.commit()

    def test_the_latest_tests_say_their_setup(self):
        page = col.render_box(self.conn, "b1", "en")
        self.assertIn("<th>Setup</th>", page)
        self.assertIn("<td>Router · PPPoE · direct to the ISP</td>", page)
        self.assertIn('Standalone · Ethernet · behind another router <span class="muted">(changed during the test)</span>', page)
        self.assertIn("<td>unknown</td>", page)

    def test_untrusted_values_show_as_unknown(self):
        page = col.render_box(self.conn, "b1", "en")
        self.assertNotIn("<script>x", page)
        self.assertNotIn("<img src=x>", page)
        self.assertIn("unknown · Wi-Fi client · unknown", page)

    def test_hungarian_page(self):
        page = col.render_box(self.conn, "b1", "hu")
        self.assertIn("<th>Bekötés</th>", page)
        self.assertIn("Router · PPPoE · közvetlenül a szolgáltatón", page)


if __name__ == "__main__":
    unittest.main()
