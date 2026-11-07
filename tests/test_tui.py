"""The terminal interface must offer what the WebGUI offers."""
import re
import unittest
from pathlib import Path

from nmb.tui import catalog
from nmb.tui.app import TEXTS, layout_tabs
from nmb.tui.render import to_lines

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "nmb/web/assets/dashboard.js").read_text()
SERVER = (ROOT / "nmb/web/server.py").read_text()


def covered_paths():
    paths = set()
    for screen in catalog.all_screens(catalog.read_menu()):
        paths.update(screen.views)
        paths.update(a.path for a in screen.actions)
    return paths


class ParityTest(unittest.TestCase):
    def test_every_webgui_tab_and_subtab_has_content(self):
        html = catalog.DASHBOARD_HTML.read_text()
        tabs = set(re.findall(r"switchTab\('(tab-[\w-]+)'\)", html))
        menu = catalog.read_menu()
        self.assertTrue(tabs <= {t.key for t in menu})
        empty = [s.key for s in catalog.all_screens(menu) if not (s.views or s.actions)]
        self.assertEqual(empty, [])
        self.assertGreater(sum(len(t.subs) for t in menu), 25)

    def test_every_endpoint_the_webgui_calls_is_covered(self):
        used = set(re.findall(r"['\"`](/api/[a-zA-Z0-9_/-]+)", JS))
        missing = sorted(p for p in used - covered_paths() - set(catalog.NOT_SHOWN)
                         if not any(c.startswith(p.rstrip("/") + "/") for c in covered_paths()))
        self.assertEqual(missing, [])

    def test_catalog_paths_exist_on_the_server(self):
        for path in covered_paths():
            self.assertIn(f'"{path}"', SERVER, path)

    def test_action_ids_are_unique(self):
        ids = [a.id for s in catalog.all_screens(catalog.read_menu()) for a in s.actions]
        self.assertEqual(len(ids), len(set(ids)))


class ActionBodyTest(unittest.TestCase):
    def test_blank_fields_are_left_out_and_types_converted(self):
        action = catalog.A("x", "x", "/x", "name port:int on:bool")
        self.assertEqual(catalog.build_body(action, {"name": "", "port": "80", "on": "igen"}), {"port": 80, "on": True})

    def test_destructive_actions_need_confirmation(self):
        menu = catalog.read_menu()
        for action_id, text in (("factory.reset", "RESET"), ("data.purge", "PURGE"), ("log.purge", "PURGE"), ("sys.reboot", "YES")):
            self.assertEqual(catalog.find_action(menu, action_id).confirm, text)
        self.assertEqual(catalog.build_body(catalog.find_action(menu, "factory.reset"), {})["confirm"], "RESET")


class LogsTest(unittest.TestCase):
    def setUp(self):
        self.rows = [{"ts": 2000000000000, "level": "ERROR", "logger": "nmb.a", "message": "new\nfailure"},
                     {"ts": 1000000000000, "level": "INFO", "logger": "nmb.b", "message": "old"}]
        self.client = type("C", (), {"call": lambda _s, *a, **k: {"records": list(self.rows)}})()

    def test_newest_entry_is_last_and_one_line(self):
        from nmb.tui.logs import read_lines
        lines = read_lines(self.client, "dev")
        self.assertIn("old", lines[0])
        self.assertTrue(lines[-1].endswith("new failure"))

    def test_filters(self):
        from nmb.tui.logs import read_lines
        self.assertEqual(len(read_lines(self.client, "dev", level="error")), 1)
        self.assertEqual(len(read_lines(self.client, "dev", grep="OLD")), 1)
        self.assertEqual(len(read_lines(self.client, "dev", lines=1)), 1)


class LogoTest(unittest.TestCase):
    def test_logo_is_three_words_of_seven_rows(self):
        from nmb.tui.logo import LOGO
        self.assertEqual(len(LOGO), 21)
        self.assertEqual({len(line) for line in LOGO}, {80})


class RenderTest(unittest.TestCase):
    def test_secrets_are_hidden_and_tables_drawn(self):
        text = "\n".join(to_lines({"admin_password": "abc", "rows": [{"a": 1, "b": None}]}))
        self.assertNotIn("abc", text)
        self.assertIn("| a ", text)

    def test_tabs_wrap_inside_the_width(self):
        rows = layout_tabs(["a" * 30, "b" * 30, "c" * 30], 70)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(end <= 70 for row in rows for _, _, end in row))

    def test_all_languages_have_all_texts(self):
        self.assertEqual({len(v) for v in TEXTS.values()}, {12})
        self.assertEqual(set(TEXTS), {"en", "hu", "de", "fr", "uk"})


if __name__ == "__main__":
    unittest.main()
