"""MCP-shaped tool surface for pure codebase operations (local FS only)."""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path
from typing import Any, Callable

from .types import ToolResult, ToolSpec


class CodebaseTools:
    """Minimal MCP-compatible tool registry scoped to a workspace root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace root not a directory: {self.root}")

    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise PermissionError(f"path escapes workspace: {rel}")
        return p

    def list_tools(self) -> list[ToolSpec]:
        return [
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
                "fs_write",
                "Write text to a file under the workspace (creates parents).",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
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
            for dirpath, _, files in os.walk(base):
                for f in files:
                    out.append(str(Path(dirpath, f).relative_to(self.root)))
            return sorted(out)[:500]
        return sorted(
            str(p.relative_to(self.root)) + ("/" if p.is_dir() else "")
            for p in base.iterdir()
        )

    def _fs_read(self, path: str, max_bytes: int = 100_000) -> dict[str, Any]:
        p = self._safe(path)
        data = p.read_bytes()[:max_bytes]
        return {"path": path, "bytes": len(data), "text": data.decode("utf-8", errors="replace")}

    def _fs_write(self, path: str, content: str) -> dict[str, Any]:
        p = self._safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode("utf-8"))}

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
        hits = []
        for p in self.root.rglob(glob):
            if not p.is_file():
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
