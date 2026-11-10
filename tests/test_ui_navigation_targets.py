"""Every tab button in the Web UI opens a tab that exists (2026-11-10: the default-password notice's
"Change password" button opened 'tab-config', which no longer existed, so nothing happened)."""
import re
import unittest
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "nmb" / "web" / "assets"


class NavigationTargetTest(unittest.TestCase):
    def setUp(self):
        self.html = (ASSETS / "dashboard.html").read_text(encoding="utf-8")
        self.js = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
        self.ids = set(re.findall(r'id="([^"]+)"', self.html))

    def test_tab_and_subtab_targets_exist(self):
        for fn in ("switchTab", "switchRouterSubtab"):
            targets = set(re.findall(fn + r"\('([^']+)'\)", self.html + self.js))
            self.assertTrue(targets, fn)
            self.assertEqual(sorted(t for t in targets if t not in self.ids), [], fn)

    def test_password_button_reaches_the_credentials_card(self):
        self.assertIn('onclick="openPasswordSettings()"', self.html)
        body = self.js.split("function openPasswordSettings()", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn("switchTab('tab-info')", body)
        self.assertIn("switchRouterSubtab('rsub-system')", body)
        self.assertIn("cfg-admin-pass", body)
        # the credentials field really is in that subtab
        system = self.html.split('<div id="rsub-system"', 1)[1].split('<div id="rsub-', 1)[0]
        self.assertIn('id="cfg-admin-pass"', system)


if __name__ == "__main__":
    unittest.main()
