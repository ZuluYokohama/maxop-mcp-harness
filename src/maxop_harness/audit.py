"""Re-verify a ledger against the workspace — computed AUDIT PASS/FAIL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gates import (
    content_hash,
    gate_api_surface_stable,
    gate_circular_imports,
    gate_import_cocycle,
    gate_lexicon,
    gate_syntax,
    maxop_score,
)
from .mcp_tools import CodebaseTools
from .pin import load_pin
from .prereg import canonical_spec, prereg_sha256
from .state import load_latest_ledger, state_dir
from .types import MarkState, TRANSITIONS


def audit_ledger(workspace: Path, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    workspace = Path(workspace).resolve()
    pin = load_pin()
    findings: list[dict[str, Any]] = []

    if ledger is None:
        try:
            ledger = load_latest_ledger(workspace)
        except Exception as exc:
            return {
                "AUDIT": "FAIL",
                "reason": "corrupt or unsafe ledger_latest.json",
                "findings": [
                    {"code": "CORRUPT_LEDGER", "detail": f"{type(exc).__name__}: {exc}"}
                ],
            }
    if ledger is None:
        return {
            "AUDIT": "FAIL",
            "reason": "no ledger_latest.json under .maxop/",
            "findings": [],
        }
    if not isinstance(ledger, dict):
        return {
            "AUDIT": "FAIL",
            "reason": "ledger must be a JSON object",
            "findings": [{"code": "CORRUPT_LEDGER", "detail": type(ledger).__name__}],
        }

    if str(ledger.get("pin_version")) != str(pin.get("pin_version")):
        findings.append(
            {
                "code": "PIN_MISMATCH",
                "detail": f"ledger={ledger.get('pin_version')} pin={pin.get('pin_version')}",
            }
        )

    run_id = ledger.get("run_id")
    if (
        not isinstance(run_id, str)
        or len(run_id) != 12
        or any(char not in "0123456789abcdef" for char in run_id)
    ):
        findings.append({"code": "INVALID_RUN_ID", "detail": str(run_id)})

    if ledger.get("integrity_status") != "CLEAN" or ledger.get("rollback_error") is not None:
        findings.append(
            {
                "code": "INTEGRITY_UNCERTAIN",
                "status": ledger.get("integrity_status"),
                "detail": str(ledger.get("rollback_error") or "missing clean integrity marker"),
            }
        )
    if ledger.get("preregistration_mode") not in {
        "computed_at_run",
        "provided_frozen_digest",
    }:
        findings.append(
            {
                "code": "INVALID_PREREGISTRATION_MODE",
                "detail": str(ledger.get("preregistration_mode")),
            }
        )

    expected_states = [
        MarkState.PLAN.value,
        MarkState.DELEGATE.value,
        MarkState.ACT.value,
        MarkState.VERIFY.value,
        MarkState.COCYCLE.value,
        MarkState.MAXOP.value,
        MarkState.COMMIT.value,
        MarkState.DONE.value,
    ]
    states = ledger.get("states")
    steps = ledger.get("steps")
    if states != expected_states or not isinstance(steps, list) or len(steps) != len(expected_states):
        findings.append({"code": "INVALID_STATE_TRACE", "detail": str(states)})
    else:
        prior = MarkState.IDLE
        for index, (step, state_name) in enumerate(zip(steps, states)):
            if not isinstance(step, dict):
                findings.append({"code": "INVALID_STEP", "step": index})
                break
            try:
                target = MarkState(state_name)
            except (TypeError, ValueError):
                findings.append({"code": "INVALID_STEP_STATE", "step": index})
                break
            if (
                step.get("state_from") != prior.value
                or step.get("state_to") != target.value
                or target not in TRANSITIONS.get(prior, set())
            ):
                findings.append({"code": "INVALID_STEP_TRANSITION", "step": index})
            prior = target

        cocycle_step = steps[5]
        gate_rows = cocycle_step.get("verdicts") if isinstance(cocycle_step, dict) else None
        required_gates = {
            "syntax_compile",
            "import_cocycle",
            "api_surface",
            "lexicon",
            "circular_imports",
        }
        passed_gate_names: set[str] = set()
        if isinstance(gate_rows, list):
            for row in gate_rows:
                if not isinstance(row, dict) or row.get("passed") is not True:
                    continue
                name = row.get("name")
                if isinstance(name, str):
                    passed_gate_names.add(name)
        if not isinstance(gate_rows, list) or passed_gate_names != required_gates:
            findings.append({"code": "MISSING_GATE_EVIDENCE"})
        maxop_step = steps[6]
        maxop_rows = maxop_step.get("verdicts") if isinstance(maxop_step, dict) else None
        if not isinstance(maxop_rows, list) or not any(
            isinstance(row, dict) and row.get("name") == "maxop" and row.get("passed")
            for row in maxop_rows
        ):
            findings.append({"code": "MISSING_MAXOP_EVIDENCE"})

    ledger_spec = ledger.get("spec")
    stored_prereg = ledger.get("prereg_sha256")
    goal = ledger.get("goal")
    valid_spec = False
    if not isinstance(ledger_spec, dict) or not isinstance(stored_prereg, str):
        findings.append({"code": "PREREG_UNVERIFIABLE", "detail": "missing canonical spec/hash"})
    else:
        try:
            normalized_spec = canonical_spec(ledger_spec)
            touch_files_value = ledger_spec.get("touch_files")
            required_api_value = ledger_spec.get("required_api")
            valid_spec = (
                normalized_spec == ledger_spec
                and isinstance(goal, str)
                and isinstance(touch_files_value, list)
                and bool(touch_files_value)
                and all(isinstance(item, str) and item for item in touch_files_value)
                and isinstance(required_api_value, list)
                and bool(required_api_value)
                and all(isinstance(item, str) and item for item in required_api_value)
                and isinstance(ledger_spec.get("notes"), str)
            )
        except (TypeError, ValueError):
            valid_spec = False
        if not valid_spec:
            findings.append({"code": "INVALID_CANONICAL_SPEC"})
        elif (
            len(stored_prereg) != 64
            or any(char not in "0123456789abcdef" for char in stored_prereg)
        ):
            findings.append({"code": "INVALID_PREREG_HASH"})
        else:
            computed_prereg = prereg_sha256(goal, ledger_spec)
            if computed_prereg != stored_prereg:
                findings.append(
                    {
                        "code": "PREREG_MISMATCH",
                        "expected": stored_prereg,
                        "actual": computed_prereg,
                    }
                )

    hashes = ledger.get("content_hashes")
    if not isinstance(hashes, dict):
        findings.append({"code": "CORRUPT_LEDGER", "detail": "content_hashes must be an object"})
        hashes = {}
    if not hashes:
        findings.append({"code": "EMPTY_CONTENT_HASHES", "detail": "no sealed files"})
    safe_paths: list[str] = []
    tools = CodebaseTools(workspace)
    canonical_touch: list[str] = []
    if valid_spec and isinstance(ledger_spec, dict):
        touch_files = ledger_spec.get("touch_files")
        if not isinstance(touch_files, list) or not touch_files:
            findings.append({"code": "INVALID_TOUCH_SET"})
        else:
            for rel in touch_files:
                try:
                    target = tools._safe(rel, for_write=True)
                    canonical_touch.append(target.relative_to(workspace).as_posix())
                except (PermissionError, ValueError, TypeError) as exc:
                    findings.append(
                        {"code": "INVALID_TOUCH_PATH", "path": rel, "detail": str(exc)}
                    )
            if len(canonical_touch) != len(set(canonical_touch)):
                findings.append({"code": "DUPLICATE_TOUCH_PATH"})
            if set(canonical_touch) != set(hashes):
                findings.append(
                    {
                        "code": "SEALED_FILE_SET_MISMATCH",
                        "planned": sorted(canonical_touch),
                        "sealed": sorted(str(path) for path in hashes),
                    }
                )
    for rel, expected in hashes.items():
        try:
            tools._safe(rel)
        except (PermissionError, TypeError, ValueError) as exc:
            findings.append({"code": "UNSAFE_LEDGER_PATH", "path": rel, "detail": str(exc)})
            continue
        if not isinstance(expected, str) or len(expected) != 64 or any(
            char not in "0123456789abcdef" for char in expected
        ):
            findings.append({"code": "INVALID_CONTENT_HASH", "path": rel})
            continue
        safe_paths.append(rel)
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

    if safe_paths and valid_spec and isinstance(ledger_spec, dict):
        try:
            rerun_verdicts = [
                gate_syntax(workspace, safe_paths),
                gate_import_cocycle(workspace, safe_paths),
                gate_api_surface_stable(
                    workspace,
                    canonical_touch[0],
                    ledger_spec["required_api"],
                ),
                gate_lexicon(
                    [goal, ledger_spec["notes"], " ".join(ledger_spec["required_api"])]
                ),
                gate_circular_imports(workspace, safe_paths),
            ]
            for g in rerun_verdicts:
                if not g.passed:
                    findings.append(
                        {"code": "GATE_FAIL", "gate": g.name, "detail": g.detail}
                    )
            rerun_maxop = maxop_score(rerun_verdicts)
            if not rerun_maxop.passed:
                findings.append(
                    {
                        "code": "MAXOP_FAIL",
                        "gate": rerun_maxop.name,
                        "detail": rerun_maxop.detail,
                    }
                )
        except Exception as exc:
            findings.append(
                {"code": "AUDIT_GATE_ERROR", "detail": f"{type(exc).__name__}: {exc}"}
            )

    ok = len(findings) == 0 and ledger.get("final") == "DONE"
    try:
        state_path: str | None = str(state_dir(workspace))
    except Exception as exc:
        findings.append(
            {"code": "UNSAFE_STATE_DIR", "detail": f"{type(exc).__name__}: {exc}"}
        )
        ok = False
        state_path = None
    return {
        "AUDIT": "PASS" if ok else "FAIL",
        "run_id": ledger.get("run_id"),
        "final": ledger.get("final"),
        "findings": findings,
        "state_dir": state_path,
    }


def audit_to_text(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2)
