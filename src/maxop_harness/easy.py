"""Hyper-simple semantic front door — same gates, fewer knobs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .audit import audit_ledger
from .loop import MaxOpHarness
from .pin import load_pin


HELP = """
maxop easy — plain English (gates still enforce)

  check | ok | healthy     Am I healthy?
  status | what happened   Last run in plain English
  why | help me            What it refuses to do
  write NAME               Sealed stub NAME.py (needs run())
  write NAME with a, b     Require functions a, b
  make / create            Same as write

Also free-form:
  easy write demo with run and health
  easy am i ok
  easy what happened

Workspace: --workspace DIR or MAXOP_WORKSPACE env (default ./ws)
Nothing is sealed unless syntax, imports, API, and claim-language clear the pin.
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
    rel = Path(rel).name
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


def parse_phrase(phrase: str) -> dict[str, Any]:
    """Map short English to {action, name?, fns?}. Unknown → help."""
    raw = (phrase or "").strip()
    s = raw.lower().strip().strip("\"'")

    if not s or s in ("help", "?", "hi", "hello"):
        return {"action": "help"}

    if s in ("why", "help me", "what is this", "what does this do", "explain"):
        return {"action": "why"}

    if s in (
        "check",
        "ok",
        "okay",
        "healthy",
        "am i ok",
        "am i okay",
        "health",
        "doctor",
    ):
        return {"action": "check"}

    if s in (
        "status",
        "what happened",
        "what happened?",
        "last run",
        "show",
        "history",
    ):
        return {"action": "status"}

    m = re.match(
        r"^(?:write|make|create|scaffold|new)\s+([A-Za-z_][\w\-]*)(?:\.py)?"
        r"(?:\s+(?:with|fns?|functions?)\s+(.+))?$",
        s,
        flags=re.I,
    )
    if m:
        name = m.group(1)
        fns_raw = m.group(2)
        fns = ["run"]
        if fns_raw:
            parts = re.split(r"[,/\s]+and\s+|[,/\s]+", fns_raw)
            fns = [p.strip() for p in parts if p.strip() and p.strip().isidentifier()]
            if not fns:
                fns = ["run"]
        return {"action": "write", "name": name, "fns": fns}

    return {"action": "help", "note": f"could not parse: {raw!r}"}
