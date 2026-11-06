"""Tests for the RTR client failure diagnostics."""
import unittest

from nmb.speed.rtr import _output_tail


class OutputTailTests(unittest.TestCase):
    def test_prefers_first_non_empty_stream(self):
        self.assertEqual(_output_tail("", "out"), "out")
        self.assertEqual(_output_tail("err", "out"), "err")

    def test_handles_bytes_none_and_limit(self):
        self.assertEqual(_output_tail(None, b"abc"), "abc")
        self.assertEqual(_output_tail(None, None), "(no output)")
        self.assertEqual(_output_tail("x" * 500, limit=10), "x" * 10)


if __name__ == "__main__":
    unittest.main()
