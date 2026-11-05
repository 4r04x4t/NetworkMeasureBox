"""Unit tests for NetworkMeasureBox DNS Ad-Blocker & Sinkhole (Pi-hole Engine)."""
from __future__ import annotations

import os
import socket
import struct
import unittest
from pathlib import Path

from nmb.netd.adblock import (
    parse_dns_qname,
    parse_dns_query,
    build_sinkhole_response,
    AdblockEngine,
    get_adblock_engine,
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
        self.engine = get_adblock_engine()

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

    def test_temp_disable_and_enable(self):
        # Normal state
        self.assertTrue(self.engine.is_blocking_active())

        # Temporarily disable for 60s
        res = self.engine.disable_temporarily(60)
        self.assertFalse(self.engine.is_blocking_active())
        self.assertGreater(res["seconds_left"], 0)

        # Re-enable
        res_en = self.engine.enable_blocking()
        self.assertTrue(self.engine.is_blocking_active())
        self.assertTrue(res_en["enabled"])

    def test_local_dns_resolution(self):
        from nmb.netd.adblock import (
            add_local_dns_record,
            remove_local_dns_record,
            get_local_dns_records,
            build_dns_response_ip,
        )
        test_domain = "router.lan"
        test_ip = "192.168.1.1"

        ok = add_local_dns_record(test_domain, test_ip)
        self.assertTrue(ok)
        self.assertEqual(self.engine.custom_dns.get(test_domain), test_ip)

        # Synthetic response check
        q_slice = b"\x06router\x03lan\x00\x00\x01\x00\x01"
        resp = build_dns_response_ip(0x4321, QTYPE_A, q_slice, test_ip)
        self.assertIsNotNone(resp)
        self.assertEqual(resp[-4:], socket.inet_aton(test_ip))

        # Test request handler with local DNS
        packet = b"\x43\x21\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06router\x03lan\x00\x00\x01\x00\x01"
        dns_resp = self.engine.handle_dns_request(packet, ("192.168.1.50", 12345))
        self.assertEqual(dns_resp[-4:], socket.inet_aton(test_ip))

        # Clean up
        remove_local_dns_record(test_domain)
        self.assertNotIn(test_domain, self.engine.custom_dns)

    def test_regex_filtering(self):
        from nmb.netd.adblock import (
            add_regex_filter,
            remove_regex_filter,
            get_regex_filters,
        )
        # Add regex blacklist pattern
        pat = r"^telemetry\..*"
        ok = add_regex_filter(pat, kind="black", comment="Block all telemetry")
        self.assertTrue(ok)

        # Test matching
        blocked, reason = self.engine.is_domain_blocked("telemetry.corp.com")
        self.assertTrue(blocked)
        self.assertEqual(reason, "regex_blacklist")

        # Add regex whitelist override
        wl_pat = r".*safe-telemetry\.corp\.com$"
        add_regex_filter(wl_pat, kind="white", comment="Allow safe")
        blocked_wl, reason_wl = self.engine.is_domain_blocked("telemetry.safe-telemetry.corp.com")
        self.assertFalse(blocked_wl)
        self.assertEqual(reason_wl, "regex_whitelist")

        # Cleanup
        remove_regex_filter(pat, kind="black")
        remove_regex_filter(wl_pat, kind="white")

    def test_adlists_management(self):
        from nmb.netd.adblock import (
            get_adlists,
            add_adlist,
            toggle_adlist,
            remove_adlist,
        )
        test_url = "https://example.com/custom_hosts.txt"
        add_adlist(test_url, name="Custom Test Adlist")
        adlists = get_adlists()
        self.assertTrue(any(a["url"] == test_url for a in adlists))

        # Toggle disable
        toggle_adlist(test_url, False)
        adlists = get_adlists()
        target = next((a for a in adlists if a["url"] == test_url), None)
        self.assertIsNotNone(target)
        self.assertFalse(target["enabled"])

        # Remove
        remove_adlist(test_url)
        adlists = get_adlists()
        self.assertFalse(any(a["url"] == test_url for a in adlists))

    def test_timeline_and_charts_telemetry(self):
        from nmb.netd.adblock import get_charts_telemetry

        # Record some queries
        self.engine.record_query("192.168.1.10", "ad1.com", QTYPE_A, "BLOCKED", "gravity", 0.2, upstream="blocked")
        self.engine.record_query("192.168.1.10", "safe.com", QTYPE_AAAA, "ALLOWED", "upstream", 18.4, upstream="1.1.1.1")
        self.engine.record_query("192.168.1.20", "safe.com", QTYPE_A, "CACHED", "cache", 0.05, upstream="cache")

        timeline = self.engine.get_timeline(24)
        self.assertEqual(len(timeline), 144)
        last_slot = timeline[-1]
        self.assertGreaterEqual(last_slot["total"], 3)
        self.assertGreaterEqual(last_slot["blocked"], 1)

        charts = get_charts_telemetry()
        self.assertIn("timeline", charts)
        self.assertIn("query_types", charts)
        self.assertIn("upstreams", charts)
        self.assertIn("clients", charts)
        self.assertGreaterEqual(len(charts["clients"]), 2)



if __name__ == "__main__":
    unittest.main()

