"""The nmb-ooni CLI must only call functions that exist in nmb.probe.ooni, with valid arguments."""
import ast
import inspect
import unittest
from pathlib import Path

from nmb.probe import ooni


class OoniCliContractTests(unittest.TestCase):
    def test_calls_match_module(self):
        tree = ast.parse(Path("bin/nmb-ooni").read_text(encoding="utf-8"))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "ooni"
        ]
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(hasattr(ooni, call.func.attr), call.func.attr)
            params = inspect.signature(getattr(ooni, call.func.attr)).parameters
            for keyword in call.keywords:
                self.assertIn(keyword.arg, params, f"{call.func.attr}({keyword.arg}=)")


if __name__ == "__main__":
    unittest.main()
