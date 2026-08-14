"""Isolated workspace transaction for candidate code changes.

Candidate files are written and checked in a private staging copy.  The live
workspace is touched only after every gate has passed, and a controlled failed
apply is rolled back to the byte snapshot captured before ACT. Multi-file
replacement is deliberately not described as crash-atomic.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from .mcp_tools import CodebaseTools


_STAGE_IGNORES = {".git", ".maxop", ".pytest_cache", "__pycache__", ".venv", "node_modules"}


def _ignore_stage_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _STAGE_IGNORES}


class WorkspaceTransaction:
    """Stage, validate, then apply a fixed set with controlled-failure rollback."""

    def __init__(self, workspace: str | Path, rel_paths: list[str]):
        self.workspace = Path(workspace).resolve()
        self.live_tools = CodebaseTools(self.workspace)
        self.rel_paths: list[str] = []
        self._targets: dict[str, Path] = {}
        self._before: dict[str, tuple[bytes | None, int | None]] = {}
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        self.stage: Path | None = None
        self.tools: CodebaseTools | None = None
        self.committed = False
        self._created_dirs: list[Path] = []
        self._committed_bytes: dict[str, bytes] = {}
        self.rollback_error: str | None = None

        seen: set[Path] = set()
        for requested in rel_paths:
            target = self.live_tools._safe(requested, for_write=True)
            if target in seen:
                raise PermissionError(f"duplicate write target: {requested}")
            if target.exists() and not target.is_file():
                raise PermissionError(f"write target is not a regular file: {requested}")
            seen.add(target)
            canonical = target.relative_to(self.workspace).as_posix()
            self.rel_paths.append(canonical)
            self._targets[canonical] = target

        targets = list(seen)
        for left in targets:
            for right in targets:
                if left != right and left in right.parents:
                    raise PermissionError(
                        f"write targets overlap as file and parent: "
                        f"{left.relative_to(self.workspace)} / {right.relative_to(self.workspace)}"
                    )

        for rel, target in self._targets.items():
            if target.exists():
                self._before[rel] = (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))
            else:
                self._before[rel] = (None, None)

    def __enter__(self) -> "WorkspaceTransaction":
        self._assert_workspace_has_no_links()
        self._tempdir = tempfile.TemporaryDirectory(prefix="maxop-stage-")
        self.stage = Path(self._tempdir.name) / "workspace"
        shutil.copytree(
            self.workspace,
            self.stage,
            symlinks=True,
            ignore=_ignore_stage_entries,
        )
        self.tools = CodebaseTools(self.stage, allow_writes=True)
        for rel in self.rel_paths:
            self.tools._safe(rel, for_write=True)
        return self

    def _assert_workspace_has_no_links(self) -> None:
        """Fail closed instead of copying an external link into the proof stage."""
        for dirpath, dirs, files in os.walk(self.workspace, followlinks=False):
            dirs[:] = [name for name in dirs if name not in _STAGE_IGNORES]
            for name in [*dirs, *files]:
                candidate = Path(dirpath, name)
                if CodebaseTools._is_link_or_reparse(candidate):
                    rel = candidate.relative_to(self.workspace)
                    raise PermissionError(f"workspace link/reparse entry is not allowed: {rel}")
                if name in files and not candidate.is_file():
                    rel = candidate.relative_to(self.workspace)
                    raise PermissionError(f"workspace special file is not allowed: {rel}")

    def _assert_no_live_drift(self) -> None:
        for rel, target in self._targets.items():
            # Re-run containment/reparse checks immediately before applying.
            current_target = self.live_tools._safe(rel, for_write=True)
            if current_target != target:
                raise RuntimeError(f"write target identity changed during run: {rel}")
            before, _mode = self._before[rel]
            if before is None:
                if target.exists():
                    raise RuntimeError(f"write target appeared during run: {rel}")
            elif not target.is_file() or target.read_bytes() != before:
                raise RuntimeError(f"write target changed during run: {rel}")

    @staticmethod
    def _write_temp(parent: Path, data: bytes, mode: int | None) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".maxop-commit-", dir=parent)
        temp_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_path, 0o600 if mode is None else mode)
            return temp_path
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _missing_parent_chain(parent: Path, stop: Path) -> list[Path]:
        missing: list[Path] = []
        current = parent
        while current != stop and not current.exists():
            missing.append(current)
            current = current.parent
        return missing

    def commit(self) -> list[str]:
        if self.committed:
            raise RuntimeError("workspace transaction already committed")
        if self.stage is None or self.tools is None:
            raise RuntimeError("workspace transaction is not active")

        self._assert_no_live_drift()
        staged: dict[str, bytes] = {}
        staged_modes: dict[str, int] = {}
        for rel in self.rel_paths:
            source = self.tools._safe(rel)
            if not source.is_file():
                raise RuntimeError(f"staged output is missing or not a regular file: {rel}")
            staged[rel] = source.read_bytes()
            staged_modes[rel] = stat.S_IMODE(source.stat().st_mode)

        prepared: dict[str, Path] = {}
        applied: list[str] = []
        created_dirs: list[Path] = []
        try:
            for rel, target in self._targets.items():
                created_dirs.extend(self._missing_parent_chain(target.parent, self.workspace))
                target.parent.mkdir(parents=True, exist_ok=True)
                self.live_tools._safe(rel, for_write=True)
                _before, mode = self._before[rel]
                effective_mode = staged_modes[rel] if mode is None else mode
                prepared[rel] = self._write_temp(
                    target.parent, staged[rel], effective_mode
                )

            for rel, target in self._targets.items():
                # Parent creation can expose a late reparse point; fail closed.
                self.live_tools._safe(rel, for_write=True)
                os.replace(prepared[rel], target)
                applied.append(rel)

            self.committed = True
            self._created_dirs = list(set(created_dirs))
            self._committed_bytes = dict(staged)
            return list(self.rel_paths)
        except BaseException as commit_error:
            rollback_failures: list[str] = []
            for rel in reversed(applied):
                target = self._targets[rel]
                before, mode = self._before[rel]
                try:
                    if self.live_tools._safe(rel, for_write=True) != target:
                        raise RuntimeError("write target identity changed before rollback")
                    expected = staged[rel]
                    if not target.is_file() or target.read_bytes() != expected:
                        raise RuntimeError("live target drifted before rollback")
                    if before is None:
                        target.unlink(missing_ok=True)
                    else:
                        restore = self._write_temp(target.parent, before, mode)
                        os.replace(restore, target)
                except BaseException as exc:
                    rollback_failures.append(f"{rel}: {type(exc).__name__}: {exc}")
            for temp_path in prepared.values():
                temp_path.unlink(missing_ok=True)
            for directory in sorted(set(created_dirs), key=lambda p: len(p.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            if rollback_failures:
                self.rollback_error = "; ".join(rollback_failures)
                raise RuntimeError(
                    f"commit failed ({type(commit_error).__name__}: {commit_error}); "
                    f"rollback is uncertain ({self.rollback_error})"
                ) from commit_error
            raise
        finally:
            for temp_path in prepared.values():
                temp_path.unlink(missing_ok=True)

    def rollback_committed(self) -> None:
        """Restore the pre-ACT snapshot if durable ledger persistence fails."""
        if not self.committed:
            return
        rollback_failures: list[str] = []
        for rel in reversed(self.rel_paths):
            target = self._targets[rel]
            before, mode = self._before[rel]
            try:
                if self.live_tools._safe(rel, for_write=True) != target:
                    raise RuntimeError("write target identity changed before rollback")
                expected = self._committed_bytes[rel]
                if not target.is_file() or target.read_bytes() != expected:
                    raise RuntimeError("live target drifted after commit; not overwritten")
                if before is None:
                    target.unlink(missing_ok=True)
                else:
                    restore = self._write_temp(target.parent, before, mode)
                    os.replace(restore, target)
            except BaseException as exc:
                rollback_failures.append(f"{rel}: {type(exc).__name__}: {exc}")
        for directory in sorted(
            set(self._created_dirs), key=lambda path: len(path.parts), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        if rollback_failures:
            self.rollback_error = "; ".join(rollback_failures)
            raise RuntimeError(f"rollback is uncertain: {self.rollback_error}")
        self.committed = False

    def content_hashes(self) -> dict[str, str]:
        if not self.committed:
            raise RuntimeError("content hashes are available only after commit")
        return {
            rel: hashlib.sha256(data).hexdigest()
            for rel, data in self._committed_bytes.items()
        }

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._tempdir is not None:
            self._tempdir.cleanup()
