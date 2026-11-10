"""The donation addresses are valid (checksums), so a mistyped character can never send money elsewhere."""
import unittest

from nmb.common import donate

_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_kind(addr):
    hrp, _, data = addr.rpartition("1")
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + [_B32.index(c) for c in data]:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    values = [_B32.index(c) for c in data]
    return {1: "bech32", 0x2BC830A3: "bech32m"}.get(chk), values[0], (len(values) - 7) * 5 // 8


def _keccak256(msg):
    rc = [0x1, 0x8082, 0x800000000000808A, 0x8000000080008000, 0x808B, 0x80000001, 0x8000000080008081,
          0x8000000000008009, 0x8A, 0x88, 0x80008009, 0x8000000A, 0x8000808B, 0x800000000000008B,
          0x8000000000008089, 0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x800A,
          0x800000008000000A, 0x8000000080008081, 0x8000000000008080, 0x80000001, 0x8000000080008008]
    rot = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
    mask = (1 << 64) - 1

    def rol(x, n):
        return ((x << n) | (x >> (64 - n))) & mask if n else x

    state = [[0] * 5 for _ in range(5)]
    data = bytearray(msg) + b"\x01"
    data += b"\x00" * ((-len(data)) % 136)
    data[-1] |= 0x80
    for off in range(0, len(data), 136):
        for i in range(17):
            state[i % 5][i // 5] ^= int.from_bytes(data[off + 8 * i:off + 8 * i + 8], "little")
        for c in rc:
            col = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
            d = [col[(x - 1) % 5] ^ rol(col[(x + 1) % 5], 1) for x in range(5)]
            state = [[state[x][y] ^ d[x] for y in range(5)] for x in range(5)]
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    b[y][(2 * x + 3 * y) % 5] = rol(state[x][y], rot[x][y])
            state = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
            state[0][0] ^= c
    return b"".join(state[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


class DonationAddressTest(unittest.TestCase):
    def setUp(self):
        self.by_key = {a.key: a.address for a in donate.ADDRESSES}

    def test_keccak_reference(self):
        self.assertEqual(_keccak256(b"").hex(), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")

    def test_bitcoin_native_segwit(self):
        self.assertEqual(_bech32_kind(self.by_key["btc_segwit"]), ("bech32", 0, 20))

    def test_bitcoin_taproot(self):
        self.assertEqual(_bech32_kind(self.by_key["btc_taproot"]), ("bech32m", 1, 32))

    def test_solana_is_a_32_byte_key(self):
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        s = self.by_key["sol"]
        n = 0
        for c in s:
            n = n * 58 + alphabet.index(c)
        size = (n.bit_length() + 7) // 8 + (len(s) - len(s.lstrip("1")))
        self.assertEqual(size, 32)

    def test_evm_eip55_checksum(self):
        hexpart = self.by_key["evm"][2:]
        digest = _keccak256(hexpart.lower().encode()).hex()
        expected = "".join(c.upper() if c.isalpha() and int(digest[i], 16) >= 8 else c.lower() for i, c in enumerate(hexpart))
        self.assertEqual(hexpart, expected)

    def test_plain_text_lists_all(self):
        text = donate.plain_text()
        for a in donate.ADDRESSES:
            self.assertIn(a.address, text)


if __name__ == "__main__":
    unittest.main()
