"""Per-workspace state under .maxop/ — survives process exit; never /tmp."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .mcp_tools import CodebaseTools


STATE_DIRNAME = ".maxop"


class StatePersistenceUncertain(RuntimeError):
    """A state-file write failed and its previous byte set was not fully restored."""


class WorkspaceLock:
    """Fail-closed cooperative process lock for one harness workspace."""

    def __init__(self, workspace: Path, run_id: str):
        self.workspace = Path(workspace).resolve()
        self.run_id = run_id
        self.path: Path | None = None
        self._identity: tuple[int, int] | None = None
        self._retain_for_recovery = False

    def __enter__(self) -> "WorkspaceLock":
        directory = state_dir(self.workspace)
        path = directory / "transaction.lock"
        if CodebaseTools._is_link_or_reparse(path):
            raise PermissionError("MAXOP transaction lock cannot be a link/reparse point")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise RuntimeError(
                "another MaxOp run holds workspace/.maxop/transaction.lock; "
                "inspect and remove a stale lock manually only after confirming no run is active"
            ) from exc
        try:
            payload = json.dumps({"run_id": self.run_id, "pid": os.getpid()}) + "\n"
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            stat_result = path.stat()
            self._identity = (stat_result.st_dev, stat_result.st_ino)
            self.path = path
            return self
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise

    def retain_for_recovery(self) -> None:
        """Leave the exclusive lock in place after an uncertain rollback."""
        self._retain_for_recovery = True

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.path is None or self._identity is None:
            return
        try:
            current = self.path.stat()
        except FileNotFoundError:
            return
        if (current.st_dev, current.st_ino) != self._identity:
            raise RuntimeError("MAXOP transaction lock identity changed; refusing to remove it")
        if self._retain_for_recovery:
            return
        self.path.unlink()


def state_dir(workspace: Path) -> Path:
    root = Path(workspace).resolve()
    override = os.environ.get("MAXOP_STATE_DIR")
    if override:
        requested = Path(override)
        d = (requested if requested.is_absolute() else root / requested).resolve(strict=False)
    else:
        d = root / STATE_DIRNAME
    try:
        relative = d.relative_to(root)
    except ValueError as exc:
        raise PermissionError("MAXOP state directory must remain inside the workspace") from exc
    if relative != Path(STATE_DIRNAME):
        raise PermissionError("MAXOP state directory is fixed at workspace/.maxop")
    current = root
    for part in relative.parts:
        current = current / part
        if CodebaseTools._is_link_or_reparse(current):
            raise PermissionError("MAXOP state directory cannot traverse a link/reparse point")
    d.mkdir(parents=True, exist_ok=True)
    if CodebaseTools._is_link_or_reparse(d):
        raise PermissionError("MAXOP state directory cannot be a link/reparse point")
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        _atomic_write_text(gitignore, "*\n!.gitignore\n")
    return d


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".maxop-state-", dir=path.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write_many(payloads: dict[Path, str]) -> None:
    """Replace a small state-file set and restore all members on failure."""
    before: dict[Path, bytes | None] = {}
    prepared: dict[Path, Path] = {}
    applied: list[Path] = []
    try:
        for path, text in payloads.items():
            if CodebaseTools._is_link_or_reparse(path):
                raise PermissionError(f"MAXOP state file cannot be a link/reparse point: {path.name}")
            before[path] = path.read_bytes() if path.exists() else None
            fd, name = tempfile.mkstemp(prefix=".maxop-state-", dir=path.parent)
            temp_path = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            prepared[path] = temp_path

        for path, temp_path in prepared.items():
            os.replace(temp_path, path)
            applied.append(path)
    except BaseException as write_error:
        rollback_failures: list[str] = []
        for path in reversed(applied):
            try:
                original = before[path]
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    fd, name = tempfile.mkstemp(prefix=".maxop-state-restore-", dir=path.parent)
                    restore = Path(name)
                    try:
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(original)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(restore, path)
                    finally:
                        restore.unlink(missing_ok=True)
            except BaseException as exc:
                rollback_failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
        if rollback_failures:
            raise StatePersistenceUncertain(
                f"state write failed ({type(write_error).__name__}: {write_error}); "
                f"state rollback is uncertain ({'; '.join(rollback_failures)})"
            ) from write_error
        raise
    finally:
        for temp_path in prepared.values():
            temp_path.unlink(missing_ok=True)


def write_ledger(workspace: Path, ledger: dict[str, Any]) -> Path:
    d = state_dir(workspace)
    run_id = ledger.get("run_id") or "unknown"
    if (
        not isinstance(run_id, str)
        or len(run_id) != 12
        or any(c not in "0123456789abcdef" for c in run_id)
    ):
        raise ValueError("ledger run_id must be exactly 12 lowercase hexadecimal characters")
    path = d / f"ledger_{run_id}.json"
    text = json.dumps(ledger, indent=2, default=str)
    latest = d / "ledger_latest.json"
    idx = d / "runs.jsonl"
    if CodebaseTools._is_link_or_reparse(idx):
        raise PermissionError("MAXOP runs index cannot be a link/reparse point")
    old_index = idx.read_text(encoding="utf-8") if idx.exists() else ""
    row = json.dumps(
        {
            "run_id": run_id,
            "final": ledger.get("final"),
            "goal": ledger.get("goal"),
            "prereg_sha256": ledger.get("prereg_sha256"),
            "path": path.name,
        },
        default=str,
    )
    _atomic_write_many(
        {
            path: text,
            latest: text,
            idx: old_index + row + "\n",
        }
    )
    return path


def load_latest_ledger(workspace: Path) -> dict[str, Any] | None:
    p = state_dir(workspace) / "ledger_latest.json"
    if not p.exists():
        return None
    if CodebaseTools._is_link_or_reparse(p):
        raise PermissionError("ledger_latest.json cannot be a link/reparse point")
    return json.loads(p.read_text(encoding="utf-8"))
