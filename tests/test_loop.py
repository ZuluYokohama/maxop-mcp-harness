from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maxop_harness.loop import MaxOpHarness


def test_happy_path(tmp_path: Path) -> None:
    h = MaxOpHarness(tmp_path)
    ledger = h.run(
        "demo",
        spec={"touch_files": ["out/mod.py"], "required_api": ["run", "health"]},
    )
    assert ledger["final"] == "DONE"
    assert (tmp_path / "out/mod.py").exists()
    states = ledger["states"]
    assert "COCYCLE" in states and "MAXOP" in states and "COMMIT" in states


def test_api_gate_abstain(tmp_path: Path) -> None:
    h = MaxOpHarness(tmp_path)
    body = {
        "out/mod.py": "def run():\n    return 1\n",
    }
    ledger = h.run(
        "demo",
        spec={"touch_files": ["out/mod.py"], "required_api": ["run", "health"]},
        body=body,
    )
    assert ledger["final"] == "ABSTAIN"
    assert ledger.get("abstain_reason")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_happy_path(Path(d))
        print("happy_path OK")
    with tempfile.TemporaryDirectory() as d:
        test_api_gate_abstain(Path(d))
        print("abstain OK")
    print("ALL OK")
