"""Cocycle / consistency gates and maxop scoring — residual, not self-certifying."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

from .pin import floor, hard_gates, lexicon_hits
from .types import GateVerdict


def gate_syntax(workspace: Path, rel_paths: list[str]) -> GateVerdict:
    """All listed Python files must parse and compile."""
    errors = []
    for rel in rel_paths:
        p = workspace / rel
        if not p.exists():
            errors.append(f"missing:{rel}")
            continue
        try:
            src = p.read_text(encoding="utf-8")
            compile(src, str(p), "exec")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{rel}:{type(e).__name__}:{e}")
    ok = len(errors) == 0
    fl = floor("hard_gate_score", 1.0)
    return GateVerdict(
        name="syntax_compile",
        passed=ok,
        score=1.0 if ok else 0.0,
        floor=fl,
        detail="ok" if ok else "; ".join(errors[:5]),
    )


def gate_import_cocycle(workspace: Path, rel_paths: list[str]) -> GateVerdict:
    """
    Cocycle-lite on import graph: if A imports B and B is in the touch set,
    B must exist and parse. Not full sheaf cohomology — a restriction consistency
    check: local 'I depend on X' must restrict to a real X.
    """
    missing = []
    broken = []
    for rel in rel_paths:
        p = workspace / rel
        if not p.exists() or p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            broken.append(f"{rel}:SyntaxError:{e}")
            continue
        for n in ast.walk(tree):
            mods: list[str] = []
            if isinstance(n, ast.Import):
                mods = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods = [n.module.split(".")[0]]
            for m in mods:
                cand = workspace / m
                py = workspace / f"{m}.py"
                if cand.is_dir() or py.exists():
                    target = py if py.exists() else cand / "__init__.py"
                    if target.exists():
                        try:
                            compile(target.read_text(encoding="utf-8"), str(target), "exec")
                        except Exception as e:  # noqa: BLE001
                            broken.append(f"{rel}-> {m}: {e}")
    ok = not missing and not broken
    fl = floor("hard_gate_score", 1.0)
    return GateVerdict(
        name="import_cocycle",
        passed=ok,
        score=1.0 if ok else 0.0,
        floor=fl,
        detail="ok" if ok else "; ".join((missing + broken)[:8]),
        null_arm="skip_non_local_imports",
    )


def gate_api_surface_stable(
    workspace: Path, rel: str, required_names: list[str]
) -> GateVerdict:
    """Restriction: public names promised by plan must exist after ACT."""
    fl = floor("api_surface", 1.0)
    p = workspace / rel
    if not p.exists():
        return GateVerdict("api_surface", False, 0.0, fl, f"missing file {rel}")
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return GateVerdict("api_surface", False, 0.0, fl, str(e))
    found = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    found.add(t.id)
    missing = [n for n in required_names if n not in found]
    ok = len(missing) == 0
    return GateVerdict(
        name="api_surface",
        passed=ok,
        score=1.0 - len(missing) / max(len(required_names), 1),
        floor=fl,
        detail="ok" if ok else f"missing:{missing}",
    )


def gate_lexicon(texts: list[str]) -> GateVerdict:
    """Soft residual: claim text must not use prohibited overclaim lexicon."""
    all_hits: list[str] = []
    for t in texts:
        all_hits.extend(lexicon_hits(t or ""))
    all_hits = sorted(set(all_hits))
    ok = len(all_hits) == 0
    return GateVerdict(
        name="lexicon",
        passed=ok,
        score=1.0 if ok else 0.0,
        floor=1.0,
        detail="ok" if ok else f"hits:{all_hits}",
        null_arm="word_boundary_lexicon",
    )


def maxop_score(verdicts: list[GateVerdict], weights: dict[str, float] | None = None) -> GateVerdict:
    """MaxOp aggregate from pin floors: hard gates must pass; aggregate >= maxop_aggregate."""
    weights = weights or {v.name: 1.0 for v in verdicts}
    hard = hard_gates()
    agg_floor = floor("maxop_aggregate", 0.99)
    for v in verdicts:
        if v.name in hard and not v.passed:
            return GateVerdict(
                name="maxop",
                passed=False,
                score=0.0,
                floor=agg_floor,
                detail=f"hard gate failed: {v.name} ({v.detail})",
            )
    if not verdicts:
        return GateVerdict("maxop", False, 0.0, agg_floor, "no verdicts")
    num = sum(weights.get(v.name, 1.0) * v.score for v in verdicts)
    den = sum(weights.get(v.name, 1.0) for v in verdicts)
    score = num / den
    return GateVerdict(
        name="maxop",
        passed=score >= agg_floor and all(v.passed for v in verdicts),
        score=score,
        floor=agg_floor,
        detail=f"aggregate={score:.4f} over {len(verdicts)} gates",
    )


def gate_circular_imports(workspace: Path, rel_paths: list[str]) -> GateVerdict:
    """Detect trivial circular imports among workspace-local modules in the touch set."""
    graph: dict[str, set[str]] = {}
    name_to_path: dict[str, str] = {}
    for rel in rel_paths:
        if not rel.endswith(".py"):
            continue
        mod = Path(rel).with_suffix("").as_posix().replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        name_to_path[mod] = rel
        graph.setdefault(mod, set())
        p = workspace / rel
        if not p.exists():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            mods: list[str] = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods = [n.module]
            for m in mods:
                top = m.split(".")[0]
                for cand in list(name_to_path):
                    if cand == mod:
                        continue
                    if cand == m or cand.startswith(m + ".") or m.startswith(cand + ".") or cand.split(".")[0] == top:
                        if cand in name_to_path:
                            graph[mod].add(cand)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}
    cycles: list[str] = []

    def dfs(u: str, stack: list[str]) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in graph.get(u, ()):
            if color.get(v, WHITE) == GRAY:
                cycles.append(" -> ".join(stack + [v]))
            elif color.get(v, WHITE) == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node, [])

    ok = len(cycles) == 0
    return GateVerdict(
        name="circular_imports",
        passed=ok,
        score=1.0 if ok else 0.0,
        floor=1.0,
        detail="ok" if ok else "; ".join(cycles[:5]),
        null_arm="touch_set_only",
    )


def content_hash(workspace: Path, rel: str) -> str:
    p = workspace / rel
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
