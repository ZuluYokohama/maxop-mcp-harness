"""Markov outer loop: PLAN → DELEGATE → ACT → VERIFY → COCYCLE → MAXOP → COMMIT|ABSTAIN."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import CoderAgent, CriticAgent, Plan, PlannerAgent, VerifierAgent
from .gates import (
    content_hash,
    gate_api_surface_stable,
    gate_circular_imports,
    gate_import_cocycle,
    gate_lexicon,
    gate_syntax,
    maxop_score,
)
from .mcp_tools import CodebaseTools
from .pin import load_pin
from .state import write_ledger
from .types import MarkState, RunLedger, StepRecord, TRANSITIONS


class TransitionError(RuntimeError):
    pass


class MaxOpHarness:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.tools = CodebaseTools(self.workspace)
        self.state = MarkState.IDLE
        self.ledger = RunLedger()
        self.plan: Plan | None = None
        self._step = 0

    def _go(self, to: MarkState, agent: str, action: str, note: str = "", **extra: Any) -> None:
        if to not in TRANSITIONS.get(self.state, set()):
            raise TransitionError(f"illegal transition {self.state} → {to}")
        rec = StepRecord(
            step=self._step,
            state_from=self.state.value,
            state_to=to.value,
            agent=agent,
            action=action,
            note=note,
            verdicts=extra.get("verdicts", []),
            tool_results=extra.get("tool_results", []),
        )
        self._step += 1
        self.state = to
        self.ledger.states.append(to.value)
        self.ledger.steps.append(rec)

    def run(
        self,
        goal: str,
        spec: dict[str, Any] | None = None,
        body: dict[str, str] | None = None,
        max_cycles: int = 1,
    ) -> dict[str, Any]:
        """
        Execute one or more PLAN…COMMIT cycles.
        `spec`: touch_files, required_api, notes
        `body`: optional path → source overrides for CoderAgent
        """
        spec = spec or {}
        pin = load_pin()
        self.ledger = RunLedger(goal=goal, pin_version=str(pin.get("pin_version")))
        self.state = MarkState.IDLE
        self._step = 0
        self._go(MarkState.PLAN, "planner", "start")

        planner = PlannerAgent()
        coder = CoderAgent(self.tools)
        verifier = VerifierAgent(self.tools)
        critic = CriticAgent()

        cycles = 0
        while cycles < max_cycles and self.state not in (MarkState.DONE, MarkState.FAIL, MarkState.ABSTAIN):
            cycles += 1
            if self.state == MarkState.PLAN:
                self.plan = planner.plan(goal, spec)
                self._go(
                    MarkState.DELEGATE,
                    "planner",
                    "emit_plan",
                    note=f"touch={self.plan.touch_files} api={self.plan.required_api}",
                )

            if self.state == MarkState.DELEGATE:
                self._go(MarkState.ACT, "router", "delegate_coder")

            if self.state == MarkState.ACT:
                assert self.plan is not None
                tool_results = coder.implement(self.plan, body=body)
                self._go(
                    MarkState.VERIFY,
                    "coder",
                    "write",
                    tool_results=tool_results,
                )

            if self.state == MarkState.VERIFY:
                assert self.plan is not None
                tool_results = verifier.check_compile(self.plan.touch_files)
                failed = [t for t in tool_results if not t.get("ok")]
                if failed:
                    self._go(
                        MarkState.FAIL,
                        "verifier",
                        "compile_fail",
                        tool_results=tool_results,
                        note=str(failed),
                    )
                    break
                self._go(MarkState.COCYCLE, "verifier", "compile_ok", tool_results=tool_results)

            if self.state == MarkState.COCYCLE:
                assert self.plan is not None
                v1 = gate_syntax(self.workspace, self.plan.touch_files)
                v2 = gate_import_cocycle(self.workspace, self.plan.touch_files)
                v3 = gate_api_surface_stable(
                    self.workspace, self.plan.touch_files[0], self.plan.required_api
                )
                v4 = gate_lexicon(
                    [goal, self.plan.notes, " ".join(self.plan.required_api)]
                )
                v5 = gate_circular_imports(self.workspace, self.plan.touch_files)
                verdicts = [v1, v2, v3, v4, v5]
                if not all(v.passed for v in verdicts):
                    reason = critic.review([v.detail for v in verdicts])
                    self._go(
                        MarkState.ABSTAIN,
                        "cocycle",
                        "gate_fail",
                        verdicts=[v.to_dict() for v in verdicts],
                        note=reason or "cocycle fail",
                    )
                    self.ledger.abstain_reason = reason
                    self.ledger.final = MarkState.ABSTAIN.value
                    break
                self._go(
                    MarkState.MAXOP,
                    "cocycle",
                    "consistent",
                    verdicts=[v.to_dict() for v in verdicts],
                )
                self._last_verdicts = verdicts

            if self.state == MarkState.MAXOP:
                verdicts = getattr(self, "_last_verdicts", [])
                mop = maxop_score(verdicts)
                if not mop.passed:
                    self._go(
                        MarkState.ABSTAIN,
                        "maxop",
                        "below_floor",
                        verdicts=[mop.to_dict()],
                        note=mop.detail,
                    )
                    self.ledger.abstain_reason = mop.detail
                    self.ledger.final = MarkState.ABSTAIN.value
                    break
                self._go(
                    MarkState.COMMIT,
                    "maxop",
                    "clear_floor",
                    verdicts=[mop.to_dict()],
                    note=mop.detail,
                )

            if self.state == MarkState.COMMIT:
                assert self.plan is not None
                self.ledger.content_hashes = {
                    rel: content_hash(self.workspace, rel) for rel in self.plan.touch_files
                }
                self._go(
                    MarkState.DONE,
                    "harness",
                    "commit",
                    note=f"hashes={self.ledger.content_hashes}",
                )
                self.ledger.final = MarkState.DONE.value

        if self.ledger.final is None:
            self.ledger.final = self.state.value
        out = self.ledger.to_dict()
        try:
            path = write_ledger(self.workspace, out)
            out["ledger_path"] = str(path)
        except OSError as e:
            out["ledger_path_error"] = str(e)
        return out


def mcp_list_tools(workspace: str) -> list[dict]:
    return [t.to_mcp() for t in CodebaseTools(workspace).list_tools()]
