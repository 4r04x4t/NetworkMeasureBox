"""Reports and exports say how the box was connected for each result (owner, 2026-11-10).

CSV exports (codes, appended after the old columns), the dossier (a setup section, a column in the
speed and outage tables), the diagnostic bundle (active mode, link, path, periods) and the e-mail.
"""
import csv
import io
import re
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import _box_isolation  # noqa: F401  (private measurement lock on a working box)

from nmb.common import net_setup, setup_texts
from nmb.config import Config
from nmb.report import csv_export as ce
from nmb.report import llm_bundle as lb
from nmb.report import metrics
from nmb.report.dossier import generate_html_dossier
from nmb.report.smtp import format_plain_text_summary

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()
T0 = 1_794_200_000_000
H = 3_600_000
MIN = 60_000
FOREIGN = tuple(lang for lang in setup_texts.LANGUAGES if lang != "hu")


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _state(conn, ts, mode, iface, kind, path, source="recorded"):
    conn.execute("INSERT INTO network_state (ts, box_mode, iface, uplink_kind, isp_path, source) VALUES (?, ?, ?, ?, ?, ?)",
                 (ts, mode, iface, kind, path, source))


def _speed(conn, ts, mode=None, kind=None, path=None, source=None, down_bps=500_000_000):
    conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, box_mode, uplink_kind, isp_path, "
                 "setup_source) VALUES (?, 'schedule', 'ok', 'rtr', ?, ?, ?, ?, ?)", (ts, down_bps, mode, kind, path, source))


def _rows(text, delim=","):
    return list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=delim))


def _report(conn):
    return metrics.aggregate_report_data(conn, Config(), window_hours=24, end_ms=T0 + 24 * H)


def _two_setups(conn):
    """Behind the customer's router (reconstructed) until T0+6h, then router mode on its own PPPoE."""
    _state(conn, T0 - H, "standalone", "eth0", "ethernet", "behind_router", "derived")
    _state(conn, T0 + 6 * H, "mode_a", "ppp0", "pppoe", "direct_pppoe")


def _drop_columns(conn, table, cols):
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise unittest.SkipTest("DROP COLUMN needs SQLite 3.35")
    for col in cols:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")


class SpeedCsvTest(unittest.TestCase):
    def test_setup_codes_are_appended_after_the_old_columns(self):
        conn = _db()
        _speed(conn, T0, "mode_a", "pppoe", "direct_pppoe", "changed")
        _speed(conn, T0 - MIN, "standalone", "warp-drive", "somewhere", "guessed")     # not known codes
        rows = _rows(ce.export_speedtests_csv(conn, 0, 2 ** 62))
        head = rows[0]
        self.assertEqual(head[37:41], ["box_mode", "client_ip_source", "server_ip", "servers_all"])  # unmoved
        self.assertEqual(head[-3:], ["uplink_kind", "isp_path", "setup_source"])
        new, junk = dict(zip(head, rows[1])), dict(zip(head, rows[2]))
        self.assertEqual((new["box_mode"], new["uplink_kind"], new["isp_path"], new["setup_source"]),
                         ("mode_a", "pppoe", "direct_pppoe", "changed"))
        self.assertEqual((junk["uplink_kind"], junk["isp_path"], junk["setup_source"]), ("", "", ""))

    def test_a_database_without_the_columns_gives_empty_cells(self):
        conn = _db()
        _speed(conn, T0, "mode_a", "pppoe", "direct_pppoe", "recorded")
        _drop_columns(conn, "speedtest", ("uplink_kind", "isp_path", "setup_source"))
        _state(conn, T0 - H, "mode_a", "ppp0", "pppoe", "direct_pppoe")          # today's setup: not used
        row = dict(zip(*_rows(ce.export_speedtests_csv(conn, 0, 2 ** 62))))
        self.assertEqual((row["uplink_kind"], row["isp_path"], row["setup_source"]), ("", "", ""))
        self.assertEqual(row["box_mode"], "mode_a")
        detailed = _rows(ce.export_detailed_speedtests_csv(conn, 0, 2 ** 62), ";")
        self.assertEqual(detailed[1][-3:], ["Router", "unknown", "unknown"])

    def test_detailed_csv_has_the_setup_in_words(self):
        conn = _db()
        _speed(conn, T0, "mode_a", "pppoe", "direct_pppoe", "recorded")
        _speed(conn, T0 - MIN, "standalone", "ethernet", "behind_router", "derived")
        _speed(conn, T0 - 2 * MIN)
        text = ce.export_detailed_speedtests_csv(conn, 0, 2 ** 62)
        rows = [line.split(";") for line in text.lstrip("﻿").splitlines()]    # a naive split must work
        self.assertEqual(rows[0][:15][-1], "Server address")                          # the old columns first
        self.assertEqual(rows[0][15:], ["Mode", "Link", "Path to the ISP"])
        self.assertEqual(rows[1][15:], ["Router", "PPPoE", "direct to the ISP"])
        self.assertEqual(rows[2][15:], ["Standalone", "Ethernet", "behind another router"])
        self.assertEqual(rows[3][15:], ["unknown", "unknown", "unknown"])            # never a guess
        self.assertTrue(all(len(r) == 18 for r in rows))

    def test_no_label_can_break_a_cell_or_be_a_formula(self):
        en = setup_texts.texts("en")
        words = [en["setup_unknown"]] + [setup_texts.mode_label(c, "en", short=True) for c in net_setup.MODES]
        words += [setup_texts.link_label(c, "en") for c in net_setup.UPLINK_KINDS]
        words += [setup_texts.path_label(c, "en", short=True) for c in net_setup.ISP_PATHS]
        words += [en["setup_col_mode"], en["setup_col_link"], en["setup_col_path"]]
        for w in words:
            self.assertFalse(set(w) & {",", ";", "\n"}, w)
            self.assertNotIn(w[:1], ("-", "+", "=", "@"), w)


class OutageCsvTest(unittest.TestCase):
    def test_the_setup_when_the_outage_began(self):
        conn = _db()
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause, box_mode, uplink_kind, isp_path, setup_source) "
                     "VALUES (?, ?, 'x', 'standalone', 'wifi', 'behind_router', 'derived')", (T0, T0 + 5 * MIN))
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, ?, 'y')", (T0 + H, T0 + H + 5 * MIN))
        rows = _rows(ce.export_outages_csv(conn, T0 - H, T0 + 2 * H))
        self.assertEqual(rows[0][9:], ["own_action_sec", "box_mode", "uplink_kind", "isp_path", "setup_source"])
        by_cause = {r[6]: r[-4:] for r in rows[1:]}
        self.assertEqual(by_cause["x"], ["standalone", "wifi", "behind_router", "derived"])
        self.assertEqual(by_cause["y"], ["", "", "", ""])

    def test_a_database_without_the_columns(self):
        conn = _db()
        _drop_columns(conn, "outage", ("box_mode", "uplink_kind", "isp_path", "setup_source"))
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause) VALUES (?, ?, 'y')", (T0, T0 + 5 * MIN))
        rows = _rows(ce.export_outages_csv(conn, T0 - H, T0 + H))
        self.assertEqual(rows[1][-4:], ["", "", "", ""])


class PingCsvTest(unittest.TestCase):
    def setUp(self):
        self.conn = _db()
        self.conn.execute("INSERT INTO target (id, addr, label, role) VALUES (101, '192.0.2.1', 'DNS', 'Public DNS')")
        _state(self.conn, T0, "standalone", "eth0", "ethernet", "behind_router")
        _state(self.conn, T0 + 90_000, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        for ts in (T0 - MIN, T0, T0 + MIN, T0 + 2 * MIN):
            self.conn.execute("INSERT INTO ping_minute (target_id, ts, sent, lost) VALUES (101, ?, 120, 0)", (ts,))

    def test_each_minute_has_the_setup_of_its_time(self):
        rows = _rows(ce.export_ping_summary_csv(self.conn, 0, 10 ** 13))
        self.assertEqual(rows[0][13:], ["target_role", "time_zone", "box_mode", "uplink_kind", "isp_path", "setup_source"])
        setup = [r[-4:] for r in rows[1:]]
        self.assertEqual(setup[0], ["", "", "", ""])                                    # before any record
        self.assertEqual(setup[1], ["standalone", "ethernet", "behind_router", "recorded"])
        self.assertEqual(setup[2], ["standalone", "ethernet", "behind_router", "changed"])  # switched inside it
        self.assertEqual(setup[3], ["mode_a", "pppoe", "direct_pppoe", "recorded"])

    def test_the_history_is_read_once_not_per_row(self):
        with mock.patch.object(net_setup.Timeline, "load", wraps=net_setup.Timeline.load) as load:
            text = "".join(ce.iter_ping_summary_csv(self.conn, 0, 10 ** 13, batch=1))
        self.assertEqual(load.call_count, 1)
        self.assertEqual(len(text.strip().splitlines()), 5)

    def test_no_history_table(self):
        self.conn.execute("DROP TABLE network_state")
        rows = _rows(ce.export_ping_summary_csv(self.conn, 0, 10 ** 13))
        self.assertTrue(all(r[-4:] == ["", "", "", ""] for r in rows[1:]))


class DossierTest(unittest.TestCase):
    def test_setup_section_in_every_language(self):
        conn = _db()
        _two_setups(conn)
        report = _report(conn)
        self.assertEqual(len(report.setup_periods), 2)
        for lang in setup_texts.LANGUAGES:
            st = setup_texts.texts(lang)
            html = generate_html_dossier(report, lang=lang)
            for key in ("setup_title", "setup_intro", "setup_col_from", "setup_col_path", "setup_col_source",
                        "setup_warn_behind", "setup_mixed", "setup_mode_mode_a", "setup_path_behind_router",
                        "setup_path_direct_pppoe", "setup_src_derived", "setup_src_recorded"):
                self.assertIn(st[key], html, (lang, key))
            section = html.index(st["setup_intro"])
            self.assertLess(html.index('<div class="kpi-grid">'), section, lang)
            self.assertLess(section, html.index("<!-- 1. GRAPH"), lang)

    def test_one_setup_is_named_in_the_header_without_a_warning(self):
        conn = _db()
        _state(conn, T0 - H, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        html = generate_html_dossier(_report(conn), lang="en")
        self.assertIn("<strong>Setup:</strong> Router · PPPoE · direct to the ISP</div>", html)
        self.assertNotIn(setup_texts.texts("en")["setup_mixed"], html)
        self.assertNotIn(setup_texts.texts("en")["setup_warn_behind"], html)

    def test_nothing_recorded_says_so(self):
        html = generate_html_dossier(_report(_db()), lang="de")
        st = setup_texts.texts("de")
        self.assertIn(st["setup_none"], html)
        self.assertIn(f"<strong>{st['setup_label']}:</strong> {st['setup_unknown']}</div>", html)
        self.assertNotIn(st["setup_col_from"], html)                 # no table of invented periods
        self.assertNotIn(st["setup_warn_behind"], html)

    def test_partly_unknown_window_is_not_one_known_setup(self):
        conn = _db()
        _state(conn, T0 + 12 * H, "mode_a", "ppp0", "pppoe", "direct_pppoe")       # nothing before noon
        html = generate_html_dossier(_report(conn), lang="en")
        en = setup_texts.texts("en")
        # the one known setup, said to be unknown for part of the window; an unknown stretch is no "change"
        self.assertIn("<strong>Setup:</strong> Router · PPPoE · direct to the ISP (" + en["setup_partly_unknown"] + ")", html)
        self.assertNotIn("<strong>Setup:</strong> " + en["setup_mixed"], html)

    def test_a_restart_into_the_same_setup_is_not_a_change(self):
        from nmb.report.smtp import format_plain_text_summary
        conn = _db()
        _state(conn, T0 - H, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        _state(conn, T0 + 10 * H, None, None, None, None)                           # netd stopped for 3 minutes
        _state(conn, T0 + 10 * H + 3 * MIN, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        report = _report(conn)
        self.assertNotIn(setup_texts.texts("en")["setup_mixed"], generate_html_dossier(report, lang="en").split("setup-section")[0])
        mail = format_plain_text_summary(report)
        self.assertNotIn("changed during the period", mail)
        self.assertIn("Router mode", mail)

    def test_each_test_and_outage_carries_its_own_setup(self):
        conn = _db()
        _state(conn, T0 - H, "mode_a", "ppp0", "pppoe", "direct_pppoe")             # today's setup
        _speed(conn, T0 + H, "mode_a", "pppoe", "direct_pppoe", "changed")
        _speed(conn, T0 + 2 * H, down_bps=400_000_000)                              # stored without one
        conn.execute("INSERT INTO outage (start_ts, end_ts, cause, box_mode, uplink_kind, isp_path, setup_source) "
                     "VALUES (?, ?, 'cut', 'standalone', 'wifi', 'behind_router', 'derived')", (T0 + 3 * H, T0 + 3 * H + 5 * MIN))
        html = generate_html_dossier(_report(conn), lang="en")
        cells = re.findall(r'<td class="setup-cell">(.*?)</td>', html)
        self.assertIn("Router · PPPoE · direct to the ISP<br><small class='text-muted'>changed during the test</small>", cells)
        self.assertIn("unknown", cells)                              # never today's setup for an old row
        self.assertIn("Standalone · Wi-Fi client · behind another router<br>"
                      "<small class='text-muted'>reconstructed from the event log</small>", cells)

    def test_empty_tables_span_every_column(self):
        html = generate_html_dossier(_report(_db()), lang="en")
        tr = __import__("nmb.report.dossier", fromlist=["DOSSIER_I18N"]).DOSSIER_I18N["en"]
        self.assertIn(f"<td colspan='10' class='text-center text-muted'>{tr['speed_empty']}</td>", html)
        self.assertIn(f"<td colspan='5' class='text-center text-muted'>{tr['outage_empty']}</td>", html)
        speed_head = html.split(tr["th_date_time"], 1)[1].split("</tr>", 1)[0]
        self.assertEqual(speed_head.count("<th"), 9)                 # + the first one: 10 columns

    def test_texts_are_placed_once_unescaped_and_never_hungarian_abroad(self):
        conn = _db()
        _two_setups(conn)
        report = _report(conn)
        html = generate_html_dossier(report, lang="fr")
        self.assertIn("Autonome (client d'un réseau existant)", html)     # raw text, not escaped twice
        self.assertNotIn("&amp;#", html)
        self.assertNotIn("&amp;amp;", html)
        hu = setup_texts.texts("hu")
        for lang in FOREIGN:
            html = generate_html_dossier(report, lang=lang)
            for key in ("setup_title", "setup_intro", "setup_warn_behind", "setup_mode_standalone", "setup_src_derived"):
                self.assertNotIn(hu[key], html, (lang, key))


class BundleTest(unittest.TestCase):
    def test_deployment_mode_is_the_active_one(self):
        line = lb._deployment_mode_line("mode_a", "auto")
        self.assertIn("Router", line)
        self.assertIn("active: `mode_a`; configured: `auto`", line)
        self.assertNotIn("behind NAT router", line)                 # what "auto" printed in router mode
        standalone = lb._deployment_mode_line("standalone", "standalone")
        self.assertNotIn("behind", standalone)                      # standalone proves no position
        self.assertTrue(lb._deployment_mode_line(None, "auto").startswith("- **Deployment Mode**: unknown"))
        self.assertIn("unknown", lb._deployment_mode_line("warp", ""))

    def test_current_link_and_path_from_the_newest_record(self):
        conn = _db()
        _state(conn, T0 - H, "standalone", "eth0", "ethernet", "behind_router")
        _state(conn, T0, "mode_b", "br0", "usb", "direct_cgnat")
        state = lb._current_setup(conn)
        line = lb._current_setup_line(state)
        self.assertIn("**Measuring Link**: USB tethering (mobile) via `br0`", line)
        self.assertIn("**Path to the ISP**: Direct to the ISP (carrier-grade NAT address)", line)
        self.assertIsNone(re.search(r"\d+\.\d+\.\d+\.\d+", line))      # words, never the box's address
        conn.execute("DROP TABLE network_state")
        self.assertIsNone(lb._current_setup(conn))
        self.assertIn("unknown", lb._current_setup_line(None))

    def test_setup_periods_subsection(self):
        conn = _db()
        _two_setups(conn)
        lines = lb._setup_period_lines(lb._setup_periods(conn, T0, T0 + 24 * H))
        text = "\n".join(lines)
        self.assertEqual(lines[1], "### 1.1 Measurement Setup Periods (Past 24 Hours)")
        self.assertNotRegex(text, r"(?m)^## ")                     # no pinned section renumbered
        self.assertIn("| `2026-11-09 04:53` | `2026-11-09 10:53` | Standalone (client on an existing network) | Ethernet | "
                      "Behind another router (private address) | reconstructed from the event log |", text)
        self.assertIn("| Router mode | PPPoE | Direct to the ISP (own PPPoE session) | recorded |", text)
        self.assertIn("> " + setup_texts.texts("en")["setup_warn_behind"], text)
        empty = lb._setup_period_lines(lb._setup_periods(_db(), T0, T0 + 24 * H))
        self.assertEqual(empty[-1], "- " + setup_texts.texts("en")["setup_none"])

    def test_recent_runs_have_their_setup(self):
        self.assertEqual(lb._run_setup_cells({"box_mode": "mode_a", "uplink_kind": "pppoe", "isp_path": "direct_pppoe",
                                              "setup_source": "changed"}),
                         "Router (changed during the test) | PPPoE | direct to the ISP")
        self.assertEqual(lb._run_setup_cells({}), "unknown | unknown | unknown")

    def test_runs_query_works_without_the_columns(self):
        conn = _db()
        _drop_columns(conn, "speedtest", ("uplink_kind", "isp_path", "setup_source"))
        tail = ce.setup_select(conn, "speedtest")
        self.assertEqual(tail, ", box_mode, NULL AS uplink_kind, NULL AS isp_path, NULL AS setup_source")
        conn.execute(f"SELECT ts{tail} FROM speedtest").fetchall()


class EmailTest(unittest.TestCase):
    def test_one_setup(self):
        conn = _db()
        _state(conn, T0 - H, "mode_a", "ppp0", "pppoe", "direct_pppoe")
        text = format_plain_text_summary(_report(conn), Config())
        self.assertIn("Measurement Setup   : Router mode · PPPoE · Direct to the ISP (own PPPoE session)\n", text)
        self.assertNotIn("WARNING", text)

    def test_a_changed_setup_lists_its_periods_and_warns(self):
        conn = _db()
        _two_setups(conn)
        text = format_plain_text_summary(_report(conn), Config())
        self.assertIn("Measurement Setup   : changed during the period:\n", text)
        self.assertIn("  - 2026-11-09 04:53 UTC -> 2026-11-09 10:53 UTC: Standalone (client on an existing network) · "
                      "Ethernet · Behind another router (private address) (reconstructed from the event log)", text)
        self.assertIn("  - 2026-11-09 10:53 UTC -> 2026-11-10 04:53 UTC: Router mode · PPPoE · Direct to the ISP", text)
        self.assertIn("WARNING             : " + setup_texts.texts("en")["setup_warn_behind"], text)

    def test_no_record(self):
        text = format_plain_text_summary(_report(_db()), Config())
        self.assertIn("Measurement Setup   : " + setup_texts.texts("en")["setup_none"], text)


if __name__ == "__main__":
    unittest.main()
