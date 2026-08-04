from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import time
import uuid


class MarkState(str, Enum):
    """Markov states of the outer agent loop."""

    IDLE = "IDLE"
    PLAN = "PLAN"
    DELEGATE = "DELEGATE"
    ACT = "ACT"
    VERIFY = "VERIFY"
    COCYCLE = "COCYCLE"
    MAXOP = "MAXOP"
    COMMIT = "COMMIT"
    ABSTAIN = "ABSTAIN"
    FAIL = "FAIL"
    DONE = "DONE"


TRANSITIONS: dict[MarkState, set[MarkState]] = {
    MarkState.IDLE: {MarkState.PLAN},
    MarkState.PLAN: {MarkState.DELEGATE, MarkState.ABSTAIN, MarkState.FAIL},
    MarkState.DELEGATE: {MarkState.ACT, MarkState.FAIL},
    MarkState.ACT: {MarkState.VERIFY, MarkState.FAIL},
    MarkState.VERIFY: {MarkState.COCYCLE, MarkState.FAIL},
    MarkState.COCYCLE: {MarkState.MAXOP, MarkState.ABSTAIN, MarkState.FAIL},
    MarkState.MAXOP: {MarkState.COMMIT, MarkState.ABSTAIN, MarkState.FAIL},
    MarkState.COMMIT: {MarkState.DONE, MarkState.PLAN},
    MarkState.ABSTAIN: {MarkState.DONE},
    MarkState.FAIL: set(),
    MarkState.DONE: set(),
}


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class ToolResult:
    ok: bool
    name: str
    content: Any
    error: Optional[str] = None
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateVerdict:
    name: str
    passed: bool
    score: float
    floor: float
    detail: str
    null_arm: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepRecord:
    step: int
    state_from: str
    state_to: str
    agent: str
    action: str
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunLedger:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    goal: str = ""
    states: list[str] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    final: Optional[str] = None
    abstain_reason: Optional[str] = None
    content_hashes: dict[str, str] = field(default_factory=dict)
    pin_version: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "states": self.states,
            "steps": [s.to_dict() for s in self.steps],
            "final": self.final,
            "abstain_reason": self.abstain_reason,
            "content_hashes": self.content_hashes,
            "pin_version": self.pin_version,
        }
