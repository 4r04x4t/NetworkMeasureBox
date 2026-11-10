"""The Web UI and nmb-cli say how the box was connected for a result (owner, 2026-11-10).

Mode, link and whether the box was directly on the ISP or behind another router: on /api/status (every
latest result and the current setup), on the dashboard (card, history, chart tooltip, header) and in
`nmb-cli latest`. Unknown stays unknown; the words come from nmb/common/setup_texts.py only.
"""
import contextlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.common import setup_texts
from nmb.config import Config
from nmb.tui import cli
from nmb.web import server
from nmb.web.i18n import TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "nmb" / "db" / "schema.sql").read_text()
JS = (ROOT / "nmb" / "web" / "assets" / "dashboard.js").read_text(encoding="utf-8")
HTML = (ROOT / "nmb" / "web" / "assets" / "dashboard.html").read_text(encoding="utf-8")
T0 = 1_794_200_000_000


def _db(schema=SCHEMA):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    return conn


def _speed(conn, ts, engine="rtr", **setup):
    cols = ["ts", "trigger", "status", "engine", "down_bps", "up_bps", "ping_us"] + list(setup)
    conn.execute(f"INSERT INTO speedtest ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 (ts, "schedule", "ok", engine, 900_000_000, 300_000_000, 9000, *setup.values()))


def _state(conn, ts, mode, iface, kind, path, source="recorded"):
    conn.execute("INSERT INTO network_state (ts, box_mode, iface, uplink_kind, isp_path, source) VALUES (?, ?, ?, ?, ?, ?)",
                 (ts, mode, iface, kind, path, source))


# An old database opened read-only (not migrated yet): the speed test table before the setup columns.
OLD_SPEEDTEST = """
CREATE TABLE speedtest (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, trigger TEXT NOT NULL, status TEXT NOT NULL,
  server_id TEXT, server_name TEXT, server_host TEXT, server_location TEXT, client_ip TEXT, client_ipv6 TEXT,
  down_bps INTEGER, up_bps INTEGER, ping_us INTEGER, jitter_us INTEGER, loss_pct REAL, result_url TEXT, error TEXT,
  down_loaded_lat_ms REAL, up_loaded_lat_ms REAL, bufferbloat_grade TEXT, bufferbloat_delta_ms REAL,
  connection_type TEXT, engine TEXT, colo TEXT, client_ip_source TEXT, server_ip TEXT);
"""


class LatestResultSetupTest(unittest.TestCase):
    def test_the_latest_result_carries_its_stored_setup(self):
        conn = _db()
        _speed(conn, T0, box_mode="mode_a", uplink_kind="pppoe", isp_path="direct_pppoe", setup_source="recorded")
        row = server._latest_ok_test(conn, "rtr", server._speed_setup_select(conn))
        self.assertEqual((row["box_mode"], row["uplink_kind"], row["isp_path"], row["setup_source"]),
                         ("mode_a", "pppoe", "direct_pppoe", "recorded"))

    def test_junk_or_missing_codes_are_unknown_not_a_default(self):
        conn = _db()
        _speed(conn, T0, box_mode="router", uplink_kind=None, isp_path="nat")
        row = server._latest_ok_test(conn, "rtr", server._speed_setup_select(conn))
        for key in ("box_mode", "uplink_kind", "isp_path", "setup_source"):
            self.assertIsNone(row[key], key)

    def test_an_old_database_without_the_columns_still_answers(self):
        conn = _db(OLD_SPEEDTEST)
        self.assertEqual(server._speed_setup_select(conn), "")
        _speed(conn, T0)
        row = server._latest_ok_test(conn, "rtr", server._speed_setup_select(conn))
        self.assertEqual(row["down_bps"], 900_000_000)
        self.assertEqual({k: row[k] for k in ("box_mode", "uplink_kind", "isp_path", "setup_source")},
                         dict.fromkeys(("box_mode", "uplink_kind", "isp_path", "setup_source")))

    def test_only_the_columns_that_exist_are_selected(self):
        conn = _db(OLD_SPEEDTEST.replace("server_ip TEXT)", "server_ip TEXT, box_mode TEXT)"))
        self.assertEqual(server._speed_setup_select(conn), ", box_mode")
        self.assertEqual(server._speed_setup_select(_db()), ", box_mode, uplink_kind, isp_path, setup_source")


class CurrentSetupTest(unittest.TestCase):
    def test_newest_record_of_netd(self):
        conn = _db()
        _state(conn, T0, "standalone", "eth0", "ethernet", "behind_router")
        _state(conn, T0 + 60_000, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        _state(conn, T0 + 120_000, "mode_b", "br0", "bridge", "direct_public", source="derived")   # history, not now
        self.assertEqual(server._current_setup(conn), {"box_mode": "mode_a", "uplink_kind": "pppoe",
                                                       "isp_path": "direct_pppoe", "iface": "ppp0", "ts": T0 + 60_000})

    def test_no_table_or_no_record_is_unknown(self):
        unknown = {"box_mode": None, "uplink_kind": None, "isp_path": None, "iface": None, "ts": None}
        self.assertEqual(server._current_setup(_db(OLD_SPEEDTEST)), unknown)
        self.assertEqual(server._current_setup(_db()), unknown)

    def test_netd_stopped_and_junk_are_unknown(self):
        conn = _db()
        _state(conn, T0, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        _state(conn, T0 + 1, None, None, None, None)                        # netd stopped
        self.assertEqual(server._current_setup(conn)["box_mode"], None)
        _state(conn, T0 + 2, "router", "eth1", "fiber", "nat")
        setup = server._current_setup(conn)
        self.assertEqual((setup["box_mode"], setup["uplink_kind"], setup["isp_path"], setup["iface"]),
                         (None, None, None, "eth1"))


class LanguageTest(unittest.TestCase):
    def test_the_page_language_wins_when_supported(self):
        self.assertEqual(server._ui_language("lang=it", "hu"), "it")
        self.assertEqual(server._ui_language("lang=pt-br&x=1", "en"), "pt-br")
        self.assertEqual(server._ui_language("lang=xx", "de"), "de")
        self.assertEqual(server._ui_language("", "fr"), "fr")
        self.assertEqual(server._ui_language("lang=<b>", None), "en")


class StatusEndpointTest(unittest.TestCase):
    """The whole /api/status handler on an in-memory database; nothing of the real system is read."""

    def _status(self, conn, path="/api/status?lang=de"):
        handler = server.WebRequestHandler.__new__(server.WebRequestHandler)
        handler.path = path
        cfg = Config()
        cfg.web.language = "hu"
        handler.server = SimpleNamespace(cfg=cfg, scheduler=None, is_measuring=False)
        sent, chart = {}, {}
        handler._send_json = lambda data, status=200: sent.update(data)
        no_file = SimpleNamespace(exists=lambda: False, read_text=lambda: "0")
        patches = [
            mock.patch.object(server.db, "connect", return_value=conn),
            mock.patch.object(server, "render_latency_chart", side_effect=lambda *a, **k: chart.update(k) or "<svg/>"),
            mock.patch.object(server, "Path", side_effect=lambda *a: no_file),
            mock.patch.object(server, "get_sniffer", return_value=SimpleNamespace(running=False, get_stats=dict)),
            mock.patch.object(server, "detect_os_info", return_value={}),
            mock.patch.object(server, "get_hardware_model", return_value="test"),
            mock.patch.object(server, "_installed_version", return_value="dev"),
            mock.patch.object(server.interfaces, "get_dual_stack_ips", return_value={}),
            mock.patch.object(server.interfaces, "get_mac_address", return_value=None),
            mock.patch.object(server.interfaces, "get_carrier", return_value=None),
            mock.patch.object(server.dns, "get_dns_status", return_value={}),
            mock.patch.object(server, "find_drive_config_path", return_value=None),
            mock.patch.object(server, "get_writable_drive_config_target", return_value=None),
            mock.patch.object(server, "detect_wifi_capabilities", return_value={}),
            mock.patch.object(server, "get_wifi_status", return_value={}),
            mock.patch.object(server, "is_iperf_running", return_value=False),
            mock.patch.object(server, "get_latest_iperf_result", return_value=None),
            mock.patch.object(server, "get_iperf_server_status", return_value={}),
            mock.patch.object(server, "is_traceroute_running", return_value=False),
            mock.patch.object(server, "get_latest_traceroute", return_value=None),
            mock.patch.object(server, "get_cached_devices", return_value=[]),
            mock.patch("nmb.netd.geoip.get_public_geoip", return_value={}),          # never the network
            mock.patch("nmb.common.memory.get_total_ram_mb", return_value=1024),
            mock.patch("nmb.common.memory.get_available_ram_mb", return_value=512),
            mock.patch("nmb.common.memory.get_effective_memory_profile", return_value="standard"),
            mock.patch("nmb.common.memory.is_low_memory_system", return_value=False),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            handler._handle_api_status()
        return sent, chart

    def test_latest_results_and_current_setup(self):
        conn = _db()
        conn.execute("INSERT INTO kv (k, v, ts) VALUES ('active_mode', 'mode_a', 1), ('active_wan_iface', 'ppp0', 1)")
        _speed(conn, T0, box_mode="mode_a", uplink_kind="pppoe", isp_path="direct_pppoe", setup_source="changed")
        _speed(conn, T0, engine="cloudflare")                                # stored before the setup was recorded
        _state(conn, T0, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        sent, chart = self._status(conn)
        per = sent["latest_per_engine"]
        self.assertEqual((per["rtr"]["box_mode"], per["rtr"]["uplink_kind"], per["rtr"]["isp_path"],
                          per["rtr"]["setup_source"]), ("mode_a", "pppoe", "direct_pppoe", "changed"))
        self.assertEqual([per["cloudflare"][k] for k in ("box_mode", "uplink_kind", "isp_path", "setup_source")],
                         [None] * 4)
        si = sent["system_info"]
        self.assertEqual(si["setup"], {"box_mode": "mode_a", "uplink_kind": "pppoe", "isp_path": "direct_pppoe",
                                       "iface": "ppp0", "ts": T0})
        self.assertEqual((si["mode"], si["wan_iface"]), ("mode_a", "ppp0"))      # the existing keys stay
        self.assertIsInstance(si["system_time_ms"], int)
        json.dumps(sent)                                                       # it still goes out as JSON

    def test_chart_speaks_the_page_language(self):
        sent, chart = self._status(_db(), "/api/status?lang=de")
        self.assertEqual(chart.get("lang"), "de")
        sent, chart = self._status(_db(), "/api/status")
        self.assertEqual(chart.get("lang"), "hu")                             # the configured one without ?lang=
        self.assertEqual(sent["system_info"]["setup"]["box_mode"], None)


NODE_HARNESS = """
let currentTranslations = {};
%s
%s
%s
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = input.cases.map(c => {
  currentTranslations = c.tr;
  return { short: setupSummary(c.row), full: setupSummary(c.row, true), note: setupSourceNote(c.row), line: setupLineHtml(c.row) };
});
process.stdout.write(JSON.stringify(out));
"""


def _js_function(name):
    m = re.search(r"\n  function %s\(.*?\n  \}\n" % name, JS, re.S)
    if not m:
        raise AssertionError(f"function {name} not found in dashboard.js")
    return m.group(0)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class DashboardLabelsTest(unittest.TestCase):
    """The dashboard's setup words are the shared ones (setup_texts.py), in every language, unknown kept."""

    ROWS = [
        {"box_mode": "mode_a", "uplink_kind": "pppoe", "isp_path": "direct_pppoe", "setup_source": "recorded"},
        {"box_mode": "standalone", "uplink_kind": "ethernet", "isp_path": "behind_router", "setup_source": "derived"},
        {"box_mode": "mode_b", "uplink_kind": "bridge", "isp_path": "direct_cgnat", "setup_source": "changed"},
        {"box_mode": "standalone", "uplink_kind": "wifi", "isp_path": "direct_public"},
        {"box_mode": "mode_a", "uplink_kind": None, "isp_path": None},
        {"box_mode": "__proto__", "uplink_kind": "toString", "isp_path": "constructor", "setup_source": "hasOwnProperty"},
        {},
    ]

    def _run(self, cases):
        block = re.search(r"  // setup-labels-begin.*?// setup-labels-end", JS, re.S).group(0)
        code = NODE_HARNESS % (_js_function("t"), _js_function("escapeHtml"), block)
        res = subprocess.run(["node", "-e", code], input=json.dumps({"cases": cases}), capture_output=True,
                             text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr[:500])
        return json.loads(res.stdout)

    @staticmethod
    def _full(row, lang):
        from nmb.common.net_setup import label_codes
        mode, kind, path, _ = label_codes(row)
        if mode is None and kind is None and path is None:
            return setup_texts.texts(lang)["setup_unknown"]
        return " · ".join((setup_texts.mode_label(mode, lang, short=True), setup_texts.link_label(kind, lang),
                           setup_texts.path_label(path, lang)))

    def test_same_words_as_the_dossier_and_the_bot_in_every_language(self):
        cases = [{"row": row, "tr": TRANSLATIONS[lang], "lang": lang} for lang in setup_texts.LANGUAGES for row in self.ROWS]
        for case, got in zip(cases, self._run(cases)):
            row, lang = case["row"], case["lang"]
            self.assertEqual(got["short"], setup_texts.summary(row, lang), (lang, row))
            self.assertEqual(got["full"], self._full(row, lang), (lang, row))
            src = row.get("setup_source")
            self.assertEqual(got["note"], setup_texts.source_label(src, lang) if src in ("changed", "derived") else "")

    def test_fallbacks_are_the_english_words(self):
        cases = [{"row": row, "tr": {}} for row in self.ROWS]
        for case, got in zip(cases, self._run(cases)):
            self.assertEqual(got["short"], setup_texts.summary(case["row"], "en"))
            self.assertEqual(got["full"], self._full(case["row"], "en"))
            self.assertTrue(got["line"].startswith("Setup: "))

    def test_the_line_is_escaped(self):
        tr = dict(TRANSLATIONS["en"], setup_label="<img src=x onerror=alert(1)>", setup_src_changed="a&b")
        got = self._run([{"row": self.ROWS[2], "tr": tr}])[0]
        self.assertNotIn("<img", got["line"])
        self.assertIn("&lt;img", got["line"])
        self.assertIn("(a&amp;b)", got["line"])


class DashboardWiringTest(unittest.TestCase):
    def test_card_has_a_translated_setup_line(self):
        self.assertRegex(HTML, r'<span data-i18n="setup_label">Setup</span>:</span> <span id="home-setup"')
        self.assertTrue(all("setup_label" in TRANSLATIONS[lang] for lang in TRANSLATIONS))
        card = re.search(r"function renderHomeEngineCard.*?\n  \}\n", JS, re.S).group(0)
        self.assertIn("elSetup.textContent = setupSummary(latest, true)", card)
        self.assertIn("elSetup.innerHTML = '<span style=\"color:#94a3b8;\">--</span>'", card)   # no result: reset

    def test_history_and_tooltip_show_the_setup(self):
        self.assertIn("${clientIpCell}<div", JS)
        self.assertIn("${setupLineHtml(st)}</div></td>", JS)
        tip = re.search(r"function showSpeedChartTooltip.*?\n  \}\n", JS, re.S).group(0)
        self.assertIn("setupLineHtml(item)", tip)

    def test_header_reads_only_keys_the_server_sends(self):
        for gone in ("system_info.wan_interface", "system_info.uptime", "system_info.wan_ip", "si.wan_ip",
                     "/^ppp/.test(si.wan_iface"):
            self.assertNotIn(gone, JS, gone)
        self.assertIn("si.wan_iface ||", JS)
        self.assertIn("si.system_time_ms", JS)
        self.assertIn("fetch('/api/status?lang=' + encodeURIComponent(currentLang))", JS)
        self.assertIn('<span id="hdr-wan-iface" class="meta-val">--</span>', HTML)          # no made-up eth0


class _Client:
    def __init__(self, status):
        self.status = status

    def call(self, method, path, body=None, timeout=10):
        assert (method, path) == ("GET", "/api/status")
        return self.status


class CliLatestTest(unittest.TestCase):
    def _latest(self, per, engine="all"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli._latest(_Client({"latest_per_engine": per}), engine, False), 0)
        return out.getvalue().splitlines()

    def test_setup_column(self):
        per = {
            "rtr": {"ts": T0, "down_bps": 9e8, "up_bps": 3e8, "ping_us": 9000, "server_name": "Wien",
                    "box_mode": "mode_a", "uplink_kind": "pppoe", "isp_path": "direct_pppoe", "setup_source": "recorded"},
            "ookla": {"ts": T0, "down_bps": 9e8, "server_name": "Budapest", "box_mode": "standalone",
                      "uplink_kind": "ethernet", "isp_path": "behind_router", "setup_source": "derived"},
            "cloudflare": {"ts": T0, "down_bps": 9e8, "server_name": "BUD"},
        }
        lines = self._latest(per)
        self.assertRegex(lines[0], r"ping ms  setup +server$")
        rtr = next(l for l in lines if l.startswith("rtr "))
        self.assertRegex(rtr, r"  Router · PPPoE · direct to the ISP +Wien$")
        ookla = next(l for l in lines if l.startswith("ookla "))
        self.assertIn("Standalone · Ethernet · behind another router", ookla)
        self.assertIn("setup reconstructed from the event log", lines[lines.index(ookla) + 1])
        cf = next(l for l in lines if l.startswith("cloudflare "))
        self.assertRegex(cf, r" -- +BUD$")                                   # unknown, not a guess
        self.assertEqual(lines[0].index("setup"), rtr.index("Router"))        # the column lines up
        self.assertTrue(any(l.startswith("fastcom ") and "no result yet" in l for l in lines))

    def test_setup_text(self):
        self.assertEqual(cli.setup_text({}), "--")
        self.assertEqual(cli.setup_text({"box_mode": "router", "isp_path": "nat"}), "--")
        self.assertEqual(cli.setup_text({"box_mode": "mode_a"}), "Router · unknown · unknown")
        self.assertEqual(cli.setup_text({"box_mode": "mode_b", "uplink_kind": "bridge", "isp_path": "direct_cgnat"}),
                         "Bridge · Inline bridge · direct to the ISP")


if __name__ == "__main__":
    unittest.main()
