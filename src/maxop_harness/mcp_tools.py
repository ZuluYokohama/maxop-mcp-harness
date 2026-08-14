"""MCP-shaped tool surface for pure codebase operations (local FS only)."""

from __future__ import annotations

import ast
import os
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from .types import ToolResult, ToolSpec


class CodebaseTools:
    """Minimal MCP-compatible tool registry scoped to a workspace root."""

    _CONTROL_PARTS = frozenset({".git", ".maxop"})

    def __init__(self, root: str | Path, *, allow_writes: bool = False):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace root not a directory: {self.root}")
        self.allow_writes = allow_writes

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        """Return True for POSIX links and Windows reparse points/junctions."""
        if path.is_symlink():
            return True
        try:
            attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        except OSError:
            return False
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(flag and attrs & flag)

    def _relative_path(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel or "\x00" in rel:
            raise PermissionError("path must be a non-empty relative string")
        # Check both syntaxes so a Windows absolute path is rejected even when a
        # request is inspected on POSIX, and vice versa.
        windows = PureWindowsPath(rel)
        posix = PurePosixPath(rel)
        if windows.is_absolute() or windows.drive or windows.root or posix.is_absolute():
            raise PermissionError(f"absolute path is not allowed: {rel}")
        raw = Path(rel)
        if any(part == ".." for part in raw.parts):
            raise PermissionError(f"parent traversal is not allowed: {rel}")
        if any(":" in part or part.rstrip(" .") != part for part in windows.parts):
            raise PermissionError(f"ambiguous Windows path syntax is not allowed: {rel}")
        if windows.is_reserved():
            raise PermissionError(f"reserved Windows path is not allowed: {rel}")
        if any(part.casefold() in self._CONTROL_PARTS for part in raw.parts):
            raise PermissionError(f"protected control path is not allowed: {rel}")
        return raw

    def _safe(self, rel: str, *, for_write: bool = False) -> Path:
        raw = self._relative_path(rel)
        unresolved = self.root / raw

        # Reject links/reparse points in every existing component. This avoids
        # following an in-root link during a later write and closes junction
        # escapes on Windows as well as symlink escapes on POSIX.
        current = self.root
        for part in raw.parts:
            if part in ("", "."):
                continue
            current = current / part
            if self._is_link_or_reparse(current):
                raise PermissionError(f"link/reparse path is not allowed: {rel}")

        p = unresolved.resolve(strict=False)
        try:
            p.relative_to(self.root)
        except ValueError:
            raise PermissionError(f"path escapes workspace: {rel}")
        if for_write and p == self.root:
            raise PermissionError("workspace root cannot be a write target")
        return p

    def list_tools(self) -> list[ToolSpec]:
        tools = [
            ToolSpec(
                "fs_list",
                "List files under a relative directory (non-recursive by default).",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "recursive": {"type": "boolean", "default": False},
                    },
                },
            ),
            ToolSpec(
                "fs_read",
                "Read a text file under the workspace.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer", "default": 100_000},
                    },
                    "required": ["path"],
                },
            ),
            ToolSpec(
                "py_parse",
                "Parse Python source; return AST summary or syntax error.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "source": {"type": "string"},
                    },
                },
            ),
            ToolSpec(
                "py_compile_check",
                "compile() check for a .py file; ok/fail with message.",
                {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            ToolSpec(
                "grep_literal",
                "Literal substring search under workspace (capped).",
                {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "glob": {"type": "string", "default": "*.py"},
                        "max_hits": {"type": "integer", "default": 50},
                    },
                    "required": ["pattern"],
                },
            ),
        ]
        if self.allow_writes:
            tools.insert(
                2,
                ToolSpec(
                    "fs_write",
                    "Write text under an explicitly write-enabled workspace.",
                    {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                ),
            )
        return tools

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        arguments = arguments or {}
        t0 = time.perf_counter()
        handlers: dict[str, Callable[..., Any]] = {
            "fs_list": self._fs_list,
            "fs_read": self._fs_read,
            "fs_write": self._fs_write,
            "py_parse": self._py_parse,
            "py_compile_check": self._py_compile_check,
            "grep_literal": self._grep_literal,
        }
        if name not in handlers:
            return ToolResult(False, name, None, error=f"unknown tool: {name}")
        try:
            content = handlers[name](**arguments)
            return ToolResult(True, name, content, ms=(time.perf_counter() - t0) * 1e3)
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                False, name, None, error=f"{type(e).__name__}: {e}", ms=(time.perf_counter() - t0) * 1e3
            )

    def _fs_list(self, path: str = ".", recursive: bool = False) -> list[str]:
        base = self._safe(path)
        if recursive:
            out = []
            limit_reached = False
            for dirpath, dirs, files in os.walk(base):
                safe_dirs = []
                for dirname in dirs:
                    candidate = Path(dirpath, dirname)
                    try:
                        self._safe(str(candidate.relative_to(self.root)))
                    except PermissionError:
                        continue
                    safe_dirs.append(dirname)
                dirs[:] = safe_dirs
                for f in files:
                    candidate = Path(dirpath, f)
                    try:
                        self._safe(str(candidate.relative_to(self.root)))
                    except PermissionError:
                        continue
                    out.append(str(candidate.relative_to(self.root)))
                    if len(out) >= 500:
                        dirs[:] = []
                        limit_reached = True
                        break
                if limit_reached:
                    break
            return sorted(out)
        out = []
        for p in base.iterdir():
            try:
                self._safe(str(p.relative_to(self.root)))
            except PermissionError:
                continue
            out.append(str(p.relative_to(self.root)) + ("/" if p.is_dir() else ""))
            if len(out) >= 500:
                break
        return sorted(out)

    def _fs_read(self, path: str, max_bytes: int = 100_000) -> dict[str, Any]:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes < 0 or max_bytes > 1_000_000:
            raise ValueError("max_bytes must be between 0 and 1000000")
        p = self._safe(path)
        with p.open("rb") as stream:
            data = stream.read(max_bytes)
        return {"path": path, "bytes": len(data), "text": data.decode("utf-8", errors="replace")}

    def _fs_write(self, path: str, content: str) -> dict[str, Any]:
        if not self.allow_writes:
            raise PermissionError("raw filesystem writes are disabled for this tool surface")
        p = self._safe(path, for_write=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p = self._safe(path, for_write=True)
        data = content.encode("utf-8")
        prior_mode = stat.S_IMODE(p.stat().st_mode) if p.exists() else None
        fd, name = tempfile.mkstemp(prefix=".maxop-raw-write-", dir=p.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if prior_mode is not None:
                os.chmod(temporary, prior_mode)
            self._safe(path, for_write=True)
            os.replace(temporary, p)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": path, "bytes": len(data)}

    def _py_parse(self, path: str | None = None, source: str | None = None) -> dict[str, Any]:
        if source is None:
            if not path:
                raise ValueError("path or source required")
            source = self._safe(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports.extend(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                imports.append(n.module or "")
        return {
            "ok": True,
            "functions": funcs,
            "classes": classes,
            "imports": imports,
            "n_nodes": sum(1 for _ in ast.walk(tree)),
        }

    def _py_compile_check(self, path: str) -> dict[str, Any]:
        p = self._safe(path)
        src = p.read_text(encoding="utf-8")
        compile(src, str(p), "exec")
        return {"ok": True, "path": path}

    def _grep_literal(self, pattern: str, glob: str = "*.py", max_hits: int = 50) -> list[dict[str, Any]]:
        if not glob or ".." in glob or "/" in glob or "\\" in glob:
            raise PermissionError("glob must be a filename pattern within the workspace")
        hits = []
        for p in self.root.rglob(glob):
            if not p.is_file():
                continue
            try:
                self._safe(str(p.relative_to(self.root)))
            except PermissionError:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern in line:
                    hits.append(
                        {
                            "path": str(p.relative_to(self.root)),
                            "line": i,
                            "text": line[:200],
                        }
                    )
                    if len(hits) >= max_hits:
                        return hits
        return hits
