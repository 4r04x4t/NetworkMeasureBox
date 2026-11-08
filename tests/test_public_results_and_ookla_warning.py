"""Optional password-free results on the LAN, and the Ookla schedule warning."""
import tempfile
import unittest
from pathlib import Path

from nmb.config import load_config, save_config
from nmb.speed import anti_ban
from nmb.speed.scheduler import shortest_gap_seconds
from nmb.web import i18n
from nmb.web.results_page import LANGS, TEXT, allows_without_password, is_local_client, render_results_page

# Never touch the box's real Ookla cooldown file.
import tempfile as _tf
from pathlib import Path as _P
from nmb.speed import anti_ban as _ab
_ab.CLIENT_COOLDOWN_FILE = _P(_tf.mkdtemp(prefix="nmb-test-")) / "ookla_cooldown.json"



class PublicResultsTest(unittest.TestCase):
    def test_off_by_default_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nmb.conf"
            cfg = load_config(path)
            self.assertFalse(cfg.web.public_results)
            cfg.web.public_results = True
            save_config(cfg, path)
            self.assertTrue(load_config(path).web.public_results)

    def test_only_reads_of_result_pages_from_the_lan(self):
        self.assertTrue(allows_without_password(True, "GET", "/results", "192.168.1.20"))
        self.assertTrue(allows_without_password(True, "GET", "/export/speedtests.csv", "10.8.0.2"))
        self.assertTrue(allows_without_password(True, "GET", "/dossier", "::ffff:192.168.1.20"))
        # Off, a public address, a write, or anything that is not a result page: password needed.
        self.assertFalse(allows_without_password(False, "GET", "/results", "192.168.1.20"))
        self.assertFalse(allows_without_password(True, "GET", "/results", "81.0.0.1"))
        self.assertFalse(allows_without_password(True, "POST", "/results", "192.168.1.20"))
        for path in ("/", "/api/config", "/api/status", "/api/system/credentials", "/api/report/llm-bundle"):
            self.assertFalse(allows_without_password(True, "GET", path, "192.168.1.20"), path)

    def test_local_client(self):
        for ip in ("127.0.0.1", "::1", "192.168.100.5", "fd42::2"):
            self.assertTrue(is_local_client(ip), ip)
        for ip in ("8.8.8.8", "2001:4860::8888", "not-an-ip"):
            self.assertFalse(is_local_client(ip), ip)

    def test_page_in_every_language(self):
        for lang in LANGS:
            page = render_results_page(lang, "box-1")
            self.assertIn(TEXT[lang]["title"], page)
            self.assertIn('href="/export/speedtests.csv"', page)
        self.assertIn('lang="en"', render_results_page("xx"))

    def test_box_id_is_escaped(self):
        self.assertNotIn("<script>", render_results_page("en", "<script>"))


class OoklaWarningTest(unittest.TestCase):
    def setUp(self):
        anti_ban.clear_quarantine()

    def tearDown(self):
        anti_ban.clear_quarantine()

    def test_gaps(self):
        self.assertEqual(shortest_gap_seconds("* * * * *"), 60)
        self.assertEqual(shortest_gap_seconds("0,30 * * * *"), 1800)
        self.assertEqual(shortest_gap_seconds("0 * * * *"), 3600)

    def test_frequent_ookla_warns(self):
        w = anti_ban.ookla_schedule_warning("ookla", "scheduled", "*/15 * * * *")
        self.assertEqual(w["code"], "ookla_rate_limit_risk")
        self.assertEqual(w["interval_min"], 15)
        self.assertEqual(anti_ban.ookla_schedule_warning("all", "scheduled", "* * * * *")["code"], "ookla_rate_limit_risk")

    def test_no_warning_when_safe(self):
        self.assertIsNone(anti_ban.ookla_schedule_warning("ookla", "scheduled", "0 * * * *"))
        self.assertIsNone(anti_ban.ookla_schedule_warning("rtr", "scheduled", "* * * * *"))
        self.assertIsNone(anti_ban.ookla_schedule_warning("ookla", "manual", "* * * * *"))

    def test_pause_is_reported(self):
        anti_ban.mark_client_rate_limited()
        w = anti_ban.ookla_schedule_warning("ookla", "scheduled", "0 * * * *")
        self.assertEqual(w["code"], "ookla_paused")
        self.assertGreater(w["paused_min"], 0)

    def test_texts_in_every_language(self):
        for lang, table in i18n.TRANSLATIONS.items():
            for key in ("ookla_warn_risk", "ookla_warn_paused", "sys_public_results", "sys_public_results_hint"):
                self.assertIn(key, table, f"{lang}:{key}")
            self.assertIn("{interval}", table["ookla_warn_risk"])


if __name__ == "__main__":
    unittest.main()
