"""Per-workspace state under .maxop/ — survives process exit; never /tmp."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


STATE_DIRNAME = ".maxop"


def state_dir(workspace: Path) -> Path:
    override = os.environ.get("MAXOP_STATE_DIR")
    if override:
        d = Path(override).resolve()
    else:
        d = (Path(workspace).resolve() / STATE_DIRNAME)
    d.mkdir(parents=True, exist_ok=True)
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
    return d


def write_ledger(workspace: Path, ledger: dict[str, Any]) -> Path:
    d = state_dir(workspace)
    run_id = ledger.get("run_id") or "unknown"
    path = d / f"ledger_{run_id}.json"
    path.write_text(json.dumps(ledger, indent=2, default=str), encoding="utf-8")
    latest = d / "ledger_latest.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    idx = d / "runs.jsonl"
    with idx.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "run_id": run_id,
                    "final": ledger.get("final"),
                    "goal": ledger.get("goal"),
                    "prereg_sha256": ledger.get("prereg_sha256"),
                    "path": path.name,
                },
                default=str,
            )
            + "\n"
        )
    return path


def load_latest_ledger(workspace: Path) -> dict[str, Any] | None:
    p = state_dir(workspace) / "ledger_latest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
