"""Donation addresses of the NetworkMeasureBox project, shown in the Web UI, the bot, the CLI and the READMEs.

One place for them: every screen reads this list, so a change is made here only (tests/test_donate.py checks
every address's checksum, so a mistyped character fails the tests instead of sending money elsewhere).
"""
from typing import List, NamedTuple


class Address(NamedTuple):
    key: str        # stable id
    network: str    # shown as is (network names are not translated)
    address: str


ADDRESSES: List[Address] = [
    Address("sol", "Solana", "An7eoFNzfVwudvHJNte8pB2xRh85uP4CN18zERVNWAWj"),
    Address("btc_segwit", "Bitcoin (Native SegWit)", "bc1q6syess8m43gsw8zlykkvuvcg0qhxv8dmtvjehm"),
    Address("btc_taproot", "Bitcoin (Taproot)", "bc1pfwmanxzpa3d52trthxxvd70m9dmguwt09tzcwufdwptgjr23nevq6g7l9g"),
    Address("evm", "Ethereum, BNB, Polygon, other ERC-20", "0x23B12da9f4a224e7Fad4CCa5B17Bb450F3d4ABC4"),
]


def as_dicts() -> List[dict]:
    """For the Web API and the UI."""
    return [a._asdict() for a in ADDRESSES]


def plain_text(indent: str = "  ") -> str:
    """For terminals, the bot (inside <code> there) and logs: one line per address."""
    return "\n".join(f"{indent}{a.network}: {a.address}" for a in ADDRESSES)
