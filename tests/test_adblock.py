"""Unit tests for NetworkMeasureBox DNS Ad-Blocker & Sinkhole (Pi-hole Engine)."""
from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path

from nmb.netd.adblock import (
    parse_dns_qname,
    parse_dns_query,
    build_sinkhole_response,
    AdblockEngine,
    get_router_dhcp_guide,
    add_whitelist_entry,
    remove_whitelist_entry,
    get_whitelist_entries,
    add_blacklist_entry,
    remove_blacklist_entry,
    get_blacklist_entries,
    QTYPE_A,
    QTYPE_AAAA,
    QTYPE_HTTPS,
)


class TestAdblock(unittest.TestCase):
    def setUp(self):
        self.engine = AdblockEngine()

    def test_dns_packet_parsing(self):
        # Transaction ID 0x1234, standard query for 'doubleclick.net', QTYPE=A (1)
        # \x0bdoubleclick\x03net\x00
        packet = (
            b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
            b"\x0bdoubleclick\x03net\x00\x00\x01\x00\x01"
        )
        parsed = parse_dns_query(packet)
        self.assertIsNotNone(parsed)
        txid, domain, qtype, qclass, q_slice = parsed
        self.assertEqual(txid, 0x1234)
        self.assertEqual(domain, "doubleclick.net")
        self.assertEqual(qtype, 1)
        self.assertEqual(qclass, 1)

    def test_sinkhole_response_generation(self):
        # A record sinkhole -> 0.0.0.0
        q_slice = b"\x0bdoubleclick\x03net\x00\x00\x01\x00\x01"
        resp_a = build_sinkhole_response(0x1234, QTYPE_A, q_slice)
        txid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", resp_a[:12])
        self.assertEqual(txid, 0x1234)
        self.assertEqual(flags, 0x8180)
        self.assertEqual(qd, 1)
        self.assertEqual(an, 1)
        # Check last 4 bytes for 0.0.0.0
        self.assertEqual(resp_a[-4:], bytes([0, 0, 0, 0]))

        # AAAA record sinkhole -> ::
        resp_aaaa = build_sinkhole_response(0x5678, QTYPE_AAAA, q_slice)
        txid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", resp_aaaa[:12])
        self.assertEqual(txid, 0x5678)
        self.assertEqual(an, 1)
        self.assertEqual(resp_aaaa[-16:], bytes([0] * 16))

        # HTTPS record sinkhole -> NODATA (0 answers)
        resp_https = build_sinkhole_response(0x9999, QTYPE_HTTPS, q_slice)
        txid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", resp_https[:12])
        self.assertEqual(an, 0)

    def test_is_domain_blocked_exact_and_subdomain(self):
        self.engine.blocked_domains.add("bad-tracker.com")
        self.engine.whitelist.discard("bad-tracker.com")

        # Exact match
        blocked, reason = self.engine.is_domain_blocked("bad-tracker.com")
        self.assertTrue(blocked)
        self.assertEqual(reason, "gravity")

        # Subdomain match
        blocked_sub, reason_sub = self.engine.is_domain_blocked("sub.ads.bad-tracker.com")
        self.assertTrue(blocked_sub)
        self.assertEqual(reason_sub, "gravity_parent")

        # Allowed domain
        blocked_ok, _ = self.engine.is_domain_blocked("trusted-site.org")
        self.assertFalse(blocked_ok)

    def test_whitelist_override(self):
        self.engine.blocked_domains.add("ad-domain.com")
        self.engine.whitelist.add("ad-domain.com")

        # Whitelist must take priority over gravity
        blocked, reason = self.engine.is_domain_blocked("ad-domain.com")
        self.assertFalse(blocked)
        self.assertEqual(reason, "whitelisted")

        # Subdomain of whitelisted domain must also be permitted
        blocked_sub, reason_sub = self.engine.is_domain_blocked("cdn.ad-domain.com")
        self.assertFalse(blocked_sub)
        self.assertEqual(reason_sub, "whitelisted_parent")

    def test_blacklist_crud(self):
        test_domain = "custom-evil-site.net"
        add_blacklist_entry(test_domain)
        self.assertIn(test_domain, get_blacklist_entries())

        # Test removal
        remove_blacklist_entry(test_domain)
        self.assertNotIn(test_domain, get_blacklist_entries())

    def test_whitelist_crud(self):
        test_domain = "safe-cdn.org"
        add_whitelist_entry(test_domain)
        self.assertIn(test_domain, get_whitelist_entries())

        # Test removal
        remove_whitelist_entry(test_domain)
        self.assertNotIn(test_domain, get_whitelist_entries())

    def test_telemetry_and_query_logging(self):
        self.engine.record_query("192.168.1.50", "ad.doubleclick.net", QTYPE_A, "BLOCKED", "gravity", 0.12)
        self.engine.record_query("192.168.1.50", "example.com", QTYPE_A, "ALLOWED", "upstream", 24.5)

        stats = self.engine.get_stats()
        self.assertGreaterEqual(stats["total_queries"], 2)
        self.assertGreaterEqual(stats["blocked_queries"], 1)

        recent = self.engine.get_recent_queries(5)
        self.assertGreaterEqual(len(recent), 2)
        self.assertEqual(recent[0]["domain"], "example.com")
        self.assertEqual(recent[1]["domain"], "ad.doubleclick.net")

    def test_router_dhcp_guide(self):
        guide = get_router_dhcp_guide()
        self.assertIn("box_ip", guide)
        self.assertIn("steps_hu", guide)
        self.assertIn("steps_en", guide)
        self.assertTrue(len(guide["steps_hu"]) >= 4)
        self.assertTrue(len(guide["steps_en"]) >= 4)


if __name__ == "__main__":
    unittest.main()

