"""Re-verify a ledger against the workspace — computed AUDIT PASS/FAIL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gates import content_hash, gate_api_surface_stable, gate_import_cocycle, gate_syntax
from .pin import load_pin
from .state import load_latest_ledger, state_dir


def audit_ledger(workspace: Path, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    workspace = Path(workspace).resolve()
    pin = load_pin()
    findings: list[dict[str, Any]] = []

    if ledger is None:
        ledger = load_latest_ledger(workspace)
    if ledger is None:
        return {
            "AUDIT": "FAIL",
            "reason": "no ledger_latest.json under .maxop/",
            "findings": [],
        }

    if str(ledger.get("pin_version")) != str(pin.get("pin_version")):
        findings.append(
            {
                "code": "PIN_MISMATCH",
                "detail": f"ledger={ledger.get('pin_version')} pin={pin.get('pin_version')}",
            }
        )

    hashes = ledger.get("content_hashes") or {}
    for rel, expected in hashes.items():
        actual = content_hash(workspace, rel)
        if not actual:
            findings.append({"code": "MISSING_FILE", "path": rel})
        elif actual != expected:
            findings.append(
                {
                    "code": "HASH_DRIFT",
                    "path": rel,
                    "expected": expected,
                    "actual": actual,
                }
            )

    paths = list(hashes.keys()) or []
    if paths:
        for g in (
            gate_syntax(workspace, paths),
            gate_import_cocycle(workspace, paths),
        ):
            if not g.passed:
                findings.append({"code": "GATE_FAIL", "gate": g.name, "detail": g.detail})

    ok = len(findings) == 0 and ledger.get("final") == "DONE"
    return {
        "AUDIT": "PASS" if ok else "FAIL",
        "run_id": ledger.get("run_id"),
        "final": ledger.get("final"),
        "findings": findings,
        "state_dir": str(state_dir(workspace)),
    }


def audit_to_text(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2)
