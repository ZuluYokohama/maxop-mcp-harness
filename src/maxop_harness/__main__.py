"""python -m maxop_harness → easy mode by default."""
from __future__ import annotations

import sys

from .cli import main


def _normalize(argv: list[str]) -> list[str]:
    """Pull global flags (--workspace) to the front; default subcommand = easy."""
    power = {"tools", "pin", "selftest", "audit", "doctor", "mcp", "run", "easy"}
    globals_: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--workspace" and i + 1 < len(argv):
            globals_ += [a, argv[i + 1]]
            i += 2
            continue
        if a.startswith("--workspace="):
            globals_.append(a)
            i += 1
            continue
        rest.append(a)
        i += 1
    if not rest or rest[0] not in power:
        rest = ["easy", *rest]
    return globals_ + rest


def _entry() -> int:
    return main(_normalize(list(sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(_entry())
