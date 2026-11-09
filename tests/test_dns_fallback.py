"""DNS fallback (2026-11-09: a brief failure during an update injected public resolvers and nothing undid it)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nmb.netd import dns


class DnsFallbackTest(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.resolv = d / "resolv.conf"
        self.resolv.write_text("nameserver 192.168.8.1\n")
        for name, val in (("RESOLV_CONF", self.resolv), ("BACKUP_RESOLV_CONF", d / "orig"), ("FALLBACK_MARKER", d / "marker")):
            p = patch.object(dns, name, val)
            p.start()
            self.addCleanup(p.stop)
        for name in ("_run_privileged", "_record_dns_event"):
            p = patch.object(dns, name)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(dns.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_outage_is_not_a_dns_problem(self):
        with patch.object(dns, "test_dns_resolution", return_value=(False, "fail", 0.0)), \
             patch.object(dns, "_ip_connectivity", return_value=False):
            ok, msg = dns.ensure_dns_fallback(iface="eth0")
        self.assertFalse(ok)
        self.assertIn("No IP connectivity", msg)
        self.assertEqual(self.resolv.read_text(), "nameserver 192.168.8.1\n")
        self.assertFalse(dns.FALLBACK_MARKER.exists())

    def test_one_failed_lookup_changes_nothing(self):
        answers = iter([(False, "x", 0.0), (True, "1.2.3.4", 5.0)])
        with patch.object(dns, "test_dns_resolution", side_effect=lambda **k: next(answers)), \
             patch.object(dns, "_ip_connectivity", return_value=True):
            ok, _ = dns.ensure_dns_fallback(iface="eth0")
        self.assertTrue(ok)
        self.assertFalse(dns.FALLBACK_MARKER.exists())

    def test_broken_resolver_gets_the_fallback_and_it_is_undone_later(self):
        with patch.object(dns, "test_dns_resolution", return_value=(False, "x", 0.0)), \
             patch.object(dns, "_ip_connectivity", return_value=True):
            dns.ensure_dns_fallback(iface="eth0")
        self.assertTrue(dns.FALLBACK_MARKER.exists())
        self.assertIn("Fallback DNS Active", self.resolv.read_text())
        self.assertEqual(dns.BACKUP_RESOLV_CONF.read_text(), "nameserver 192.168.8.1\n")
        old = time.time() - dns.FALLBACK_RETRY_SEC - 5
        os.utime(dns.FALLBACK_MARKER, (old, old))
        with patch.object(dns, "test_dns_resolution", return_value=(True, "1.2.3.4", 5.0)):
            ok, msg = dns.ensure_dns_fallback(iface="eth0")
        self.assertTrue(ok)
        self.assertIn("works again", msg)
        self.assertFalse(dns.FALLBACK_MARKER.exists())
        self.assertEqual(self.resolv.read_text(), "nameserver 192.168.8.1\n")


if __name__ == "__main__":
    unittest.main()
