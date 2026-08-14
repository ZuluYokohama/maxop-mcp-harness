from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maxop_harness.loop import MaxOpHarness


class MaxOpLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_happy_path(self) -> None:
        h = MaxOpHarness(self.workspace)
        ledger = h.run(
            "demo",
            spec={"touch_files": ["out/mod.py"], "required_api": ["run", "health"]},
        )
        self.assertEqual(ledger["final"], "DONE")
        self.assertTrue((self.workspace / "out/mod.py").exists())
        states = ledger["states"]
        self.assertIn("COCYCLE", states)
        self.assertIn("MAXOP", states)
        self.assertIn("COMMIT", states)

    def test_api_gate_abstain(self) -> None:
        h = MaxOpHarness(self.workspace)
        body = {"out/mod.py": "def run():\n    return 1\n"}
        ledger = h.run(
            "demo",
            spec={"touch_files": ["out/mod.py"], "required_api": ["run", "health"]},
            body=body,
        )
        self.assertEqual(ledger["final"], "ABSTAIN")
        self.assertTrue(ledger.get("abstain_reason"))


if __name__ == "__main__":
    unittest.main()
