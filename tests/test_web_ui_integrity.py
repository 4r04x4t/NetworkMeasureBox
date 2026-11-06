"""The dashboard must parse as JavaScript and foreign languages must not contain Hungarian."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from nmb.web.i18n import TRANSLATIONS
from nmb.web.templates import get_dashboard_html, get_logout_html

HU_ONLY_LETTERS = re.compile("[őűŐŰ]")
# Legacy labels matched to strip old values, the theme's place name in a CSS comment.
ALLOWED_TEMPLATE_LINES = ("stripNotSupported", "'Betöltés...'", "Vereckei")


def scripts(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


class DashboardIntegrityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_every_script_parses(self):
        for lang in TRANSLATIONS:
            for html in (get_dashboard_html(initial_lang=lang), get_logout_html()):
                for code in scripts(html):
                    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as f:
                        f.write(code)
                        f.flush()
                        res = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, res.stderr[:500])

    def test_template_has_no_hardcoded_hungarian(self):
        source = "".join(Path(f"nmb/web/assets/dashboard.{e}").read_text(encoding="utf-8") for e in ("html", "css", "js"))
        accented = re.compile("[áéíóöőúüűÁÉÍÓÖŐÚÜŰ]")
        leaks = [
            line.strip()[:100] for line in source.splitlines()
            if accented.search(line) and not any(a in line for a in ALLOWED_TEMPLATE_LINES)
        ]
        self.assertEqual(leaks, [])

    def test_foreign_languages_have_no_hungarian(self):
        hu = TRANSLATIONS["hu"]
        for lang in ("en", "de", "fr", "uk"):
            for key, value in TRANSLATIONS[lang].items():
                self.assertIsNone(HU_ONLY_LETTERS.search(value), f"{lang}.{key}: {value}")
                if re.search("[áéíóúÁÉÍÓÚ]", value) and lang == "en":
                    self.fail(f"en.{key}: {value}")
                self.assertTrue(value != hu.get(key) or not re.search("[áéíóöúü]", value), f"{lang}.{key}")

    def test_inline_handlers_do_not_quote_html_escaped_values(self):
        source = Path("nmb/web/assets/dashboard.js").read_text(encoding="utf-8")
        unsafe = re.findall(r"""on[a-z]+="[^"\n]*'\$\{(?!idx)[^"\n]*escapeHtml[^"\n]*\"""", source)
        self.assertEqual(unsafe, [])

    def test_all_languages_define_the_same_keys(self):
        keys = set(TRANSLATIONS["en"])
        for lang, values in TRANSLATIONS.items():
            self.assertEqual(set(values) ^ keys, set(), lang)

    def test_every_static_key_is_translated(self):
        used = set(re.findall(r'data-i18n="([^"]+)"', get_dashboard_html()))
        self.assertEqual(sorted(used - set(TRANSLATIONS["en"])), [])


if __name__ == "__main__":
    unittest.main()
