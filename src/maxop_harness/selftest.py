"""Planted-fixture selftest — G1–G11, non-zero exit on failure (driftwave-style)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from .loop import MaxOpHarness
from .pin import load_pin


def g1_happy(tmp: Path) -> None:
    h = MaxOpHarness(tmp)
    led = h.run(
        "selftest happy",
        spec={"touch_files": ["out/a.py"], "required_api": ["run", "health"]},
    )
    assert led["final"] == "DONE", led
    assert "COCYCLE" in led["states"] and "MAXOP" in led["states"]


def g2_api_abstain(tmp: Path) -> None:
    h = MaxOpHarness(tmp)
    led = h.run(
        "selftest api miss",
        spec={"touch_files": ["out/a.py"], "required_api": ["run", "health"]},
        body={"out/a.py": "def run():\n    return 1\n"},
    )
    assert led["final"] == "ABSTAIN", led


def g3_syntax_fail(tmp: Path) -> None:
    h = MaxOpHarness(tmp)
    led = h.run(
        "selftest syntax",
        spec={"touch_files": ["out/bad.py"], "required_api": ["run"]},
        body={"out/bad.py": "def run(\n"},
    )
    assert led["final"] in ("FAIL", "ABSTAIN"), led


def g4_pin_loads() -> None:
    pin = load_pin()
    assert pin["pin_version"] == "1"
    assert "syntax_compile" in pin["hard_gates"]
    assert pin["floors"]["maxop_aggregate"] <= 1.0


def g5_lexicon_abstain(tmp: Path) -> None:
    h = MaxOpHarness(tmp)
    led = h.run(
        "this breakthrough module proves everything",
        spec={"touch_files": ["out/a.py"], "required_api": ["run"]},
    )
    assert led["final"] == "ABSTAIN", led
    blob = str(led)
    assert "lexicon" in blob or "hits:" in blob or led.get("abstain_reason")


def g6_hashes_and_pin(tmp: Path) -> None:
    h = MaxOpHarness(tmp)
    led = h.run(
        "hash check",
        spec={"touch_files": ["out/a.py"], "required_api": ["run"]},
    )
    assert led["final"] == "DONE", led
    assert led.get("pin_version") == "1"
    assert led.get("content_hashes", {}).get("out/a.py")


def g7_mcp_list() -> None:
    from .mcp_server import handle

    resp = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert resp and "result" in resp
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "fs_read" in names and "py_compile_check" in names
    assert "harness_run" in names and "prereg_freeze" in names


def g8_harness_run_tool(tmp: Path) -> None:
    import os
    from .mcp_server import handle

    os.environ["MAXOP_WORKSPACE"] = str(tmp)
    resp = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "harness_run",
                "arguments": {
                    "goal": "via mcp",
                    "touch_files": ["out/m.py"],
                    "required_api": ["run"],
                },
            },
        }
    )
    assert resp and resp["result"]["isError"] is False
    import json as _json

    led = _json.loads(resp["result"]["content"][0]["text"])
    assert led["final"] == "DONE"
    assert led.get("prereg_sha256")


def g11_circular(tmp: Path) -> None:
    body = {
        "pkg/a.py": "from pkg import b\ndef run():\n    return b\n",
        "pkg/b.py": "from pkg import a\ndef other():\n    return a\n",
        "pkg/__init__.py": "",
    }
    h = MaxOpHarness(tmp)
    led = h.run(
        "circular",
        spec={"touch_files": ["pkg/a.py", "pkg/b.py", "pkg/__init__.py"], "required_api": ["run"]},
        body=body,
    )
    assert led["final"] in ("DONE", "ABSTAIN", "FAIL"), led
    if led["final"] == "ABSTAIN":
        blob = str(led)
        assert "circular" in blob or "cocycle" in blob or led.get("abstain_reason")


def g10_audit(tmp: Path) -> None:
    from .audit import audit_ledger

    h = MaxOpHarness(tmp)
    led = h.run("audit me", spec={"touch_files": ["out/a.py"], "required_api": ["run"]})
    assert led["final"] == "DONE"
    assert (tmp / ".maxop" / "ledger_latest.json").exists()
    result = audit_ledger(tmp)
    assert result["AUDIT"] == "PASS", result
    (tmp / "out/a.py").write_text("# drifted\n", encoding="utf-8")
    result2 = audit_ledger(tmp)
    assert result2["AUDIT"] == "FAIL"
    assert any(f["code"] == "HASH_DRIFT" for f in result2["findings"])


def g9_prereg_freeze() -> None:
    from .mcp_server import handle
    import json as _json

    resp = handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "prereg_freeze",
                "arguments": {"goal": "x", "spec": {"a": 1}},
            },
        }
    )
    assert resp and not resp["result"]["isError"]
    body = _json.loads(resp["result"]["content"][0]["text"])
    assert body["frozen"] and len(body["prereg_sha256"]) == 64


GATES = [
    ("G1_happy", lambda: g1_happy(Path(tempfile.mkdtemp()))),
    ("G2_api_abstain", lambda: g2_api_abstain(Path(tempfile.mkdtemp()))),
    ("G3_syntax_fail", lambda: g3_syntax_fail(Path(tempfile.mkdtemp()))),
    ("G4_pin_loads", g4_pin_loads),
    ("G5_lexicon_abstain", lambda: g5_lexicon_abstain(Path(tempfile.mkdtemp()))),
    ("G6_hashes_and_pin", lambda: g6_hashes_and_pin(Path(tempfile.mkdtemp()))),
    ("G7_mcp_list", g7_mcp_list),
    ("G8_harness_run_tool", lambda: g8_harness_run_tool(Path(tempfile.mkdtemp()))),
    ("G9_prereg_freeze", g9_prereg_freeze),
    ("G10_audit", lambda: g10_audit(Path(tempfile.mkdtemp()))),
    ("G11_circular", lambda: g11_circular(Path(tempfile.mkdtemp()))),
]


def main() -> int:
    failed = []
    for name, fn in GATES:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {type(e).__name__}: {e}")
            failed.append(name)
    if failed:
        print(f"SELFTEST FAIL ({len(failed)}/{len(GATES)})")
        return 1
    print(f"SELFTEST PASS ({len(GATES)}/{len(GATES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
