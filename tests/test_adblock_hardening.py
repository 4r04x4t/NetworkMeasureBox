"""DNS ad-blocker hardening (audit netd H4, H5, M2, M3)."""
import socket
import struct
import threading
import time
import unittest
from unittest import mock

import nmb.netd.adblock as ab


def qname(name: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".") if p) + b"\x00"


def query(name="example.com", txid=0x1234, qtype=1, qd=1, flags=0x0100, tail=b"", arcount=0):
    return struct.pack("!HHHHHH", txid, flags, qd, 0, 0, arcount) + qname(name) + struct.pack("!HH", qtype, 1) + tail


def answer_for(q: bytes, txid=None, ip=b"\x01\x02\x03\x04", rcode=0, question=None):
    t = struct.unpack("!H", q[:2])[0] if txid is None else txid
    question = q[12:12 + len(qname("example.com")) + 4] if question is None else question
    return (struct.pack("!HHHHHH", t, 0x8180 | rcode, 1, 1, 0, 0) + question
            + b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + ip)


class ParserTest(unittest.TestCase):
    def test_plain_name_lowercased(self):
        self.assertEqual(ab.parse_dns_query(query("Ads.Example.COM"))[1], "ads.example.com")

    def test_pointer_in_question_refused(self):
        pkt = struct.pack("!HHHHHH", 1, 0x0100, 1, 0, 0, 0) + b"\x03ads\xc0\x0c" + b"\x00\x01\x00\x01"
        self.assertIsNone(ab.parse_dns_query(pkt))

    def test_bad_bytes_refused_not_skipped(self):
        # "a\xffd.com" used to become "ad.com", and "a.b" inside one label became a two-label name.
        for label in (b"a\xffd", b"a.b", b"a b"):
            pkt = struct.pack("!HHHHHH", 1, 0x0100, 1, 0, 0, 0) + bytes([len(label)]) + label + b"\x03com\x00\x00\x01\x00\x01"
            self.assertIsNone(ab.parse_dns_query(pkt), label)

    def test_too_long_name_refused(self):
        self.assertIsNone(ab.parse_dns_query(query(".".join(["a" * 60] * 5))))

    def test_two_questions_or_other_opcode_refused(self):
        self.assertIsNone(ab.parse_dns_query(query(qd=2)))
        self.assertIsNone(ab.parse_dns_query(query(flags=0x2800)))  # opcode 5 (UPDATE)

    def test_pointer_loop_is_cheap_and_refused(self):
        pkt = b"\x00" * 12 + b"\xc0\x0e" + b"\xc0\x0c"
        t = time.perf_counter()
        for _ in range(1000):
            self.assertEqual(ab.parse_dns_qname(pkt, 14), ("", -1))
        self.assertLess(time.perf_counter() - t, 0.5)

    def test_backward_pointer_in_answer_works(self):
        pkt = b"\x00" * 12 + qname("example.com") + b"\x03www\xc0\x0c"
        self.assertEqual(ab.parse_dns_qname(pkt, 12 + len(qname("example.com"))), ("www.example.com", len(pkt)))


class FakeUpstream:
    """A UDP 'resolver' on 127.0.0.1 that answers with a scripted list of replies."""

    def __init__(self, script):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.script = script
        self.seen = []
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        self.sock.settimeout(3)
        try:
            q, addr = self.sock.recvfrom(4096)
        except OSError:
            return
        self.seen.append(q)
        for make in self.script:
            kind, pkt = make(q)
            if kind == "spoof":   # from another port, like a LAN client guessing the box's port
                other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                other.sendto(pkt, addr)
                other.close()
            else:
                self.sock.sendto(pkt, addr)
            time.sleep(0.02)

    def close(self):
        self.sock.close()


class ForwardTest(unittest.TestCase):
    def forward(self, script, client_q=None):
        up = FakeUpstream(script)
        self.addCleanup(up.close)
        eng = ab.AdblockEngine.__new__(ab.AdblockEngine)
        eng.config = mock.Mock(upstreams=["127.0.0.1"])
        with mock.patch.object(ab, "DNS_PORT", up.port):
            resp, who = eng.forward_upstream(client_q or query(txid=0xBEEF))
        return resp, who, up

    def test_random_id_upstream_and_client_id_restored(self):
        resp, who, up = self.forward([lambda q: ("ok", answer_for(q))])
        self.assertEqual(who, "127.0.0.1")
        self.assertEqual(struct.unpack("!H", resp[:2])[0], 0xBEEF)
        self.assertEqual(resp[-4:], b"\x01\x02\x03\x04")
        self.assertNotEqual(up.seen[0][:2], b"\xbe\xef", "the client's ID must not reach upstream (2^-16 chance)")

    def test_spoofed_and_mismatched_replies_ignored(self):
        evil = b"\x06\x06\x06\x06"
        resp, _, _ = self.forward([
            lambda q: ("spoof", answer_for(q, ip=evil)),                       # right ID, wrong source port
            lambda q: ("ok", answer_for(q, txid=struct.unpack("!H", q[:2])[0] ^ 1, ip=evil)),  # wrong ID
            lambda q: ("ok", answer_for(q, ip=evil, question=qname("evil.com") + b"\x00\x01\x00\x01")),
            lambda q: ("ok", q),                                                # the query echoed (QR=0)
            lambda q: ("ok", answer_for(q)),
        ])
        self.assertIsNotNone(resp)
        self.assertEqual(resp[-4:], b"\x01\x02\x03\x04")

    def test_no_valid_reply_gives_none(self):
        resp, _, _ = self.forward([lambda q: ("spoof", answer_for(q))])
        self.assertIsNone(resp)


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.eng = ab.AdblockEngine.__new__(ab.AdblockEngine)
        self.eng.config = mock.Mock(cache_ttl_max=300)
        self.eng.cache = {}
        self.eng.cache_lock = threading.Lock()

    def key(self, q):
        p = ab.parse_dns_query(q)
        return self.eng.cache_key(q, p[1], p[2], p[3], len(p[4]))

    def test_servfail_and_truncated_not_cached(self):
        q = query()
        self.eng.store_cache_response(self.key(q), 1, answer_for(q, rcode=2), ttl=60)
        tc = bytearray(answer_for(q)); tc[2] |= 0x02
        self.eng.store_cache_response(self.key(q), 1, bytes(tc), ttl=60)
        self.assertEqual(self.eng.cache, {})

    def test_noerror_cached_with_client_id(self):
        q = query()
        self.eng.store_cache_response(self.key(q), 1, answer_for(q), ttl=60)
        got = self.eng.get_cached_response(self.key(query(txid=7)), 1, 7)
        self.assertEqual(struct.unpack("!H", got[:2])[0], 7)

    def test_key_separates_flags_and_dnssec_ok(self):
        opt = b"\x00\x00\x29\x04\xd0\x00\x00\x00\x00\x00\x00"
        opt_do = b"\x00\x00\x29\x04\xd0\x00\x00\x80\x00\x00\x00"
        keys = {self.key(query()), self.key(query(flags=0x0000)), self.key(query(flags=0x0110)),
                self.key(query(tail=opt, arcount=1)), self.key(query(tail=opt_do, arcount=1)),
                self.key(query(qtype=28))}
        self.assertEqual(len(keys), 6)


class WorkerTest(unittest.TestCase):
    def test_udp_worker_survives_socket_errors(self):
        srv = ab.AdblockDNSServer.__new__(ab.AdblockDNSServer)
        srv.running = True
        srv._udp_slots = threading.BoundedSemaphore(4)
        srv._pool = None
        answered = threading.Event()
        srv.engine = mock.Mock(handle_dns_request=lambda d, a: b"reply")
        calls = {"n": 0}

        class Sock:
            def fileno(self):
                return 5

            def recvfrom(self, n):
                calls["n"] += 1
                if calls["n"] <= 3:
                    raise OSError(90, "Message too long")
                if calls["n"] == 4:
                    return query(), ("192.168.1.9", 5353)
                srv.running = False
                raise OSError(9, "closed")

            def sendto(self, data, addr):
                answered.set()

        with mock.patch.object(ab.select, "select", lambda r, w, x, t: (r, [], [])), \
                mock.patch.object(ab.time, "sleep", lambda s: None):
            srv._udp_worker(Sock())
        self.assertTrue(answered.wait(2), "the worker must keep serving after an OSError")
        srv._pool.shutdown(wait=True)

    def test_closed_socket_ends_worker(self):
        srv = ab.AdblockDNSServer.__new__(ab.AdblockDNSServer)
        srv.running = True
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.close()
        self.assertFalse(srv._keep_going(s, OSError()))


if __name__ == "__main__":
    unittest.main()
