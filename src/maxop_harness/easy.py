"""Hyper-simple semantic front door — same gates, fewer knobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .audit import audit_ledger
from .loop import MaxOpHarness
from .pin import load_pin


HELP = """
maxop easy — plain-language commands (gates still enforce)

  check              Am I healthy? (pin + selftest + audit if any)
  write NAME         Write a tiny module NAME.py with a run() stub
  write NAME --fns a,b,c   Require functions a,b,c
  status             Show latest ledger / audit in plain English
  why                Explain what this system refuses to do

Workspace defaults to ./ws (or --workspace).
Nothing commits unless syntax, imports, API, and claim-language clear the pin.
"""


def plain_status(workspace: Path) -> str:
    led_path = workspace / ".maxop" / "ledger_latest.json"
    if not led_path.exists():
        return "No runs yet in this workspace. Try: maxop easy write demo"
    led = json.loads(led_path.read_text(encoding="utf-8"))
    final = led.get("final")
    goal = led.get("goal") or "(no goal)"
    hashes = led.get("content_hashes") or {}
    lines = [
        f"Last run: {final}",
        f"Goal: {goal}",
        f"Files sealed: {', '.join(hashes) if hashes else '(none)'}",
    ]
    if led.get("abstain_reason"):
        lines.append(f"Stopped because: {led['abstain_reason']}")
    audit = audit_ledger(workspace, led)
    lines.append(f"Audit now: {audit.get('AUDIT')}")
    if audit.get("findings"):
        for f in audit["findings"][:5]:
            lines.append(f"  - {f.get('code')}: {f.get('path', f.get('detail', ''))}")
    return "\n".join(lines)


def easy_write(
    workspace: Path,
    name: str,
    fns: list[str] | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """One-shot: write <name>.py with required fns under full MaxOp gates."""
    fns = fns or ["run"]
    rel = f"{name}.py" if not name.endswith(".py") else name
    goal = goal or f"easy write {rel}"
    harness = MaxOpHarness(workspace)
    return harness.run(
        goal,
        spec={"touch_files": [rel], "required_api": fns, "notes": "easy-mode"},
    )


def easy_why() -> str:
    pin = load_pin()
    lex = ", ".join(pin.get("prohibited_lexicon", [])[:8])
    return (
        "This tool writes code only when checks pass.\n"
        "It will ABSTAIN (refuse) if:\n"
        "  • the file does not compile\n"
        "  • required function names are missing\n"
        "  • local imports point at missing modules\n"
        "  • your goal text uses overclaim words\n"
        f"    (e.g. {lex}…)\n"
        "Refusal is the feature. See CAPABILITIES.md / SOEW.md."
    )
