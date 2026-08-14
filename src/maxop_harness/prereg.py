"""Canonical preregistration payload shared by CLI, MCP, ledger, and audit."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    source = spec or {}
    return {
        "touch_files": list(source.get("touch_files") or ["agent_out/module.py"]),
        "required_api": list(source.get("required_api") or ["run"]),
        "notes": str(source.get("notes") or ""),
    }


def prereg_sha256(goal: str, spec: dict[str, Any] | None) -> str:
    payload = {"goal": goal, "spec": canonical_spec(spec)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
