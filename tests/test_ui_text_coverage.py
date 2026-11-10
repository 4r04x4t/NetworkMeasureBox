"""Every visible text of the Web UI has a translation key (2026-11-10: ~950 texts had none in any language).

Only the technical values below may stay without a key; a new visible text must get data-i18n (HTML) or go
through t() (JS) and be added to every language. Hungarian must not leak into the template either, not even
without accents ("pl." for "e.g." sat in five placeholders until 2026-11-10).
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "nmb" / "web" / "assets"
TECHNICAL = {
    "-- MHz", "-- Mbps", ".duckdns.org", "/boot/firmware/nmb_invasive_dev_snapshot.md", "/results", "0 pps",
    "10 Mbps", "100 Mbps", "160 MHz", "2.4 GHz", "20 MHz", "320 MHz", "40 MHz", "5 GHz", "50 Mbps", "500 Mbps",
    "80 MHz", "admin", "auto", "box", "eth0", "fast", "layer2", "nmb-01", "nmb-invasive-log", "root@", "root@box:~#",
    "slow",
}


class _Texts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.untagged, self.placeholders = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("placeholder"):
            self.placeholders.append(a["placeholder"])
        if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "wbr"):
            self.stack.append((tag, "data-i18n" in a or "data-i18n-html" in a, a.get("id")))

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        text = " ".join(data.split())
        if not re.search(r"[A-Za-z]{3}", text) or any(tagged for _, tagged, _ in self.stack):
            return
        if self.stack and self.stack[-1][0] in ("script", "style", "title", "code", "pre"):
            return
        if any(i == "lang-select" for _, _, i in self.stack):      # language names stay in their own language
            return
        self.untagged.append(text)


class UiTextCoverageTest(unittest.TestCase):
    def setUp(self):
        self.parser = _Texts()
        self.parser.feed((ASSETS / "dashboard.html").read_text(encoding="utf-8"))

    def test_every_visible_text_has_a_key(self):
        self.assertEqual(sorted(set(self.parser.untagged) - TECHNICAL), [])

    def test_no_hungarian_abbreviation_in_the_template(self):
        for name in ("dashboard.html", "dashboard.js"):
            text = (ASSETS / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"""(?<![\w.])pl\. """, text), name)
        self.assertEqual([p for p in self.parser.placeholders if re.match(r"pl\. ", p)], [])


if __name__ == "__main__":
    unittest.main()
