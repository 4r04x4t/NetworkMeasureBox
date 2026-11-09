"""The evaluation parts of nmb-selftest, on recorded shapes from the Pi 4 (2026-11-08)."""
import unittest
from unittest.mock import patch

from nmb.selftest import live

IW_PHY_PI4 = """Wiphy phy0
	Band 1:
		Capabilities: 0x1020
			HT20
			Static SM Power Save
	Band 2:
		Capabilities: 0x1062
			HT20/HT40
		VHT Capabilities (0x00001020):
"""


def _rows(engine, n, down, iface="eth0", ip="192.0.2.1", pmin=None, pmed=None):
    return [{"engine": engine, "iface": iface, "down_bps": down, "up_bps": 1, "client_ip": ip,
             "ping_min": pmin, "ping_median": pmed} for _ in range(n)]


class EngineEvaluationTest(unittest.TestCase):
    def test_missing_client_ip_fails(self):
        # RTR on the box: 2508 of 2518 rows without a client IP.
        res = {n: (s, d) for n, s, d in live.evaluate_engines(_rows("rtr", 10, 800e6, ip=None))}
        self.assertEqual(res["client IP rtr@eth0"][0], live.FAIL)

    def test_a_few_missing_is_only_a_warning(self):
        rows = _rows("iperf3", 50, 600e6) + _rows("iperf3", 2, 600e6, ip="")
        res = {n: s for n, s, _ in live.evaluate_engines(rows)}
        self.assertEqual(res["client IP iperf3@eth0"], live.WARN)

    def test_engine_far_above_the_reference_warns(self):
        rows = _rows("ookla", 5, 100e6, iface="eth1") + _rows("cloudflare", 5, 90e6, iface="eth1") \
            + _rows("rtr", 5, 200e6, iface="eth1")
        res = {n: (s, d) for n, s, d in live.evaluate_engines(rows)}
        self.assertEqual(res["download rtr@eth1 vs reference"][0], live.WARN)
        self.assertIn("x2.", res["download rtr@eth1 vs reference"][1])

    def test_engines_that_agree_pass(self):
        rows = _rows("ookla", 5, 840e6) + _rows("fastcom", 5, 820e6)
        res = {n: s for n, s, _ in live.evaluate_engines(rows)}
        self.assertEqual(res["download fastcom@eth0 vs reference"], live.PASS)

    def test_no_reference_no_comparison(self):
        res = [n for n, _, _ in live.evaluate_engines(_rows("rtr", 5, 1e8, iface="br-lan"))]
        self.assertFalse(any("vs reference" in n for n in res))

    def test_rtr_single_ping_sample_is_flagged(self):
        res = {n: s for n, s, _ in live.evaluate_engines(_rows("rtr", 6, 1e8, pmin=31.1, pmed=31.1))}
        self.assertEqual(res["ping samples rtr@eth0"], live.WARN)


class WifiParseTest(unittest.TestCase):
    def test_pi4_radio_does_40_mhz_only_on_5ghz(self):
        bands = live.parse_iw_phy(IW_PHY_PI4)
        self.assertEqual(bands["2.4ghz"], {"ht40": False, "vht": False})
        self.assertEqual(bands["5ghz"], {"ht40": True, "vht": True})

    def test_hostapd_password_is_never_kept(self):
        conf = live.parse_hostapd("hw_mode=g\nwpa_passphrase=secret123\nwpa_psk=abc\nchannel=6\n# x=y\n")
        self.assertEqual(conf, {"hw_mode": "g", "channel": "6"})


class I18nCheckTest(unittest.TestCase):
    def test_missing_keys_and_hungarian_leaks(self):
        probs = live.i18n_problems({"en": {"a": "Save", "b": "Off"}, "hu": {"a": "Mentés", "b": "Kikapcsolva"},
                                    "de": {"a": "Speichern"}, "fr": {"a": "Enregistrer", "b": "Kikapcsolő"}})
        self.assertEqual(probs["hu"], [])
        self.assertEqual(probs["de"], ["missing b"])
        self.assertEqual(probs["fr"], ["hungarian in b"])

    def test_real_web_tables_are_complete(self):
        from nmb.web.i18n import SUPPORTED_LANGUAGES, get_translations_for_lang
        tables = {lang: get_translations_for_lang(lang) for lang in SUPPORTED_LANGUAGES}
        bad = {k: v for k, v in live.i18n_problems(tables).items() if any("hungarian" in p for p in v)}
        self.assertEqual(bad, {})


class ReportTest(unittest.TestCase):
    def test_exit_code_follows_failures(self):
        with patch.object(live, "_cfg"), patch.object(live.os, "geteuid", return_value=0), \
             patch.dict(live.GROUPS, {"services": lambda rep, cfg: rep.add("services", "x", live.FAIL)}), \
             patch("builtins.print"):
            self.assertEqual(live.main(["services", "--json", "/dev/null"]), 1)
        with patch.object(live, "_cfg"), patch.object(live.os, "geteuid", return_value=0), \
             patch.dict(live.GROUPS, {"services": lambda rep, cfg: rep.add("services", "x", live.PASS)}), \
             patch("builtins.print"):
            self.assertEqual(live.main(["services", "--json", "/dev/null"]), 0)

    def test_crashing_group_is_reported_not_raised(self):
        def boom(rep, cfg):
            raise RuntimeError("x")
        with patch.object(live, "_cfg"), patch.object(live.os, "geteuid", return_value=0), \
             patch.dict(live.GROUPS, {"usb": boom}), patch("builtins.print"):
            self.assertEqual(live.main(["usb", "--json", "/dev/null"]), 1)


if __name__ == "__main__":
    unittest.main()


class PruneTest(unittest.TestCase):
    def test_keeps_the_newest_reports(self):
        import os
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        for i in range(35):
            p = d / f"selftest-20261109-{i:06d}.json"
            p.write_text("{}")
            os.utime(p, (1000 + i, 1000 + i))
        (d / "selftest-latest.md").write_text("x")
        self.assertEqual(live.prune_reports(keep=30, folder=d), 5)
        self.assertFalse((d / "selftest-20261109-000000.json").exists())
        self.assertTrue((d / "selftest-20261109-000034.json").exists())
        self.assertTrue((d / "selftest-latest.md").exists())
