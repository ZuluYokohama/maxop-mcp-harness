"""Load and enforce the MaxOp pin — residual, fail-closed."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


PIN_PATH = Path(__file__).with_name("pin.json")


@lru_cache(maxsize=1)
def load_pin() -> dict[str, Any]:
    data = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    if data.get("pin_version") != "1":
        raise RuntimeError(f"unsupported pin_version: {data.get('pin_version')}")
    return data


def floor(name: str, default: float = 1.0) -> float:
    return float(load_pin().get("floors", {}).get(name, default))


def hard_gates() -> set[str]:
    return set(load_pin().get("hard_gates", []))


def soft_gates() -> set[str]:
    return set(load_pin().get("soft_gates", []))


def lexicon_hits(text: str) -> list[str]:
    """Word-boundary hits against prohibited lexicon (same idea as driftwave stage review)."""
    lex = load_pin().get("prohibited_lexicon", [])
    hits = []
    for w in lex:
        if re.search(rf"\b{re.escape(w)}\b", text, flags=re.IGNORECASE):
            hits.append(w)
    return hits


def assert_no_overclaim(*texts: str) -> None:
    for t in texts:
        hits = lexicon_hits(t or "")
        if hits:
            raise ValueError(f"prohibited lexicon in claim text: {hits}")
