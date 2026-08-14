"""Markov outer loop: PLAN → DELEGATE → ACT → VERIFY → COCYCLE → MAXOP → COMMIT|ABSTAIN."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import CoderAgent, CriticAgent, Plan, PlannerAgent, VerifierAgent
from .gates import (
    gate_api_surface_stable,
    gate_circular_imports,
    gate_import_cocycle,
    gate_lexicon,
    gate_syntax,
    maxop_score,
)
from .mcp_tools import CodebaseTools
from .pin import load_pin
from .prereg import canonical_spec, prereg_sha256 as compute_prereg_sha256
from .state import StatePersistenceUncertain, WorkspaceLock, write_ledger
from .transaction import WorkspaceTransaction
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
        prereg_sha256: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute one or more PLAN…COMMIT cycles.
        `spec`: touch_files, required_api, notes
        `body`: optional path → source overrides for CoderAgent
        """
        spec = canonical_spec(spec)
        pin = load_pin()
        computed_prereg = compute_prereg_sha256(goal, spec)
        prereg_was_provided = prereg_sha256 is not None
        if prereg_sha256 is not None and prereg_sha256 != computed_prereg:
            raise ValueError("provided preregistration hash does not match canonical goal/spec")
        self.ledger = RunLedger(
            goal=goal,
            spec=spec,
            pin_version=str(pin.get("pin_version")),
            prereg_sha256=computed_prereg,
            preregistration_mode=(
                "provided_frozen_digest" if prereg_was_provided else "computed_at_run"
            ),
        )
        planner = PlannerAgent()
        critic = CriticAgent()
        workspace_lock = WorkspaceLock(self.workspace, self.ledger.run_id)
        try:
            workspace_lock.__enter__()
        except Exception as exc:
            self.state = MarkState.FAIL
            self.ledger.states.append(MarkState.FAIL.value)
            self.ledger.final = MarkState.FAIL.value
            out = self.ledger.to_dict()
            out["lock_error"] = f"{type(exc).__name__}: {exc}"
            return out
        self.state = MarkState.IDLE
        self._step = 0
        transaction: WorkspaceTransaction | None = None
        coder: CoderAgent | None = None
        verifier: VerifierAgent | None = None

        cycles = 0
        try:
            self._go(MarkState.PLAN, "planner", "start")
            while cycles < max_cycles and self.state not in (
                MarkState.DONE,
                MarkState.FAIL,
                MarkState.ABSTAIN,
            ):
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
                    assert self.plan is not None
                    try:
                        transaction = WorkspaceTransaction(self.workspace, self.plan.touch_files)
                        transaction.__enter__()
                        assert transaction.tools is not None
                        coder = CoderAgent(transaction.tools)
                        verifier = VerifierAgent(transaction.tools)
                    except Exception as exc:  # fail before any live write
                        self._go(
                            MarkState.FAIL,
                            "router",
                            "unsafe_or_invalid_plan",
                            note=f"{type(exc).__name__}: {exc}",
                        )
                        self.ledger.final = MarkState.FAIL.value
                        break
                    self._go(MarkState.ACT, "router", "delegate_coder_transaction")

                if self.state == MarkState.ACT:
                    assert self.plan is not None and coder is not None
                    tool_results = coder.implement(self.plan, body=body)
                    failed = [result for result in tool_results if not result.get("ok")]
                    if failed:
                        self._go(
                            MarkState.FAIL,
                            "coder",
                            "staged_write_fail",
                            tool_results=tool_results,
                            note=str(failed),
                        )
                        self.ledger.final = MarkState.FAIL.value
                        break
                    self._go(
                        MarkState.VERIFY,
                        "coder",
                        "staged_write",
                        tool_results=tool_results,
                    )

                if self.state == MarkState.VERIFY:
                    assert self.plan is not None and verifier is not None
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
                        self.ledger.final = MarkState.FAIL.value
                        break
                    self._go(
                        MarkState.COCYCLE,
                        "verifier",
                        "compile_ok",
                        tool_results=tool_results,
                    )

                if self.state == MarkState.COCYCLE:
                    assert self.plan is not None and transaction is not None
                    assert transaction.stage is not None
                    v1 = gate_syntax(transaction.stage, self.plan.touch_files)
                    v2 = gate_import_cocycle(transaction.stage, self.plan.touch_files)
                    v3 = gate_api_surface_stable(
                        transaction.stage,
                        self.plan.touch_files[0],
                        self.plan.required_api,
                    )
                    v4 = gate_lexicon(
                        [goal, self.plan.notes, " ".join(self.plan.required_api)]
                    )
                    v5 = gate_circular_imports(transaction.stage, self.plan.touch_files)
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
                    assert self.plan is not None and transaction is not None
                    try:
                        transaction.commit()
                    except Exception as exc:
                        self._go(
                            MarkState.FAIL,
                            "harness",
                            "transaction_commit_fail",
                            note=f"{type(exc).__name__}: {exc}",
                        )
                        self.ledger.final = MarkState.FAIL.value
                        break
                    self.ledger.content_hashes = transaction.content_hashes()
                    self._go(
                        MarkState.DONE,
                        "harness",
                        "transaction_commit",
                        note=f"hashes={self.ledger.content_hashes}",
                    )
                    self.ledger.final = MarkState.DONE.value
        except BaseException as exc:  # always reach rollback and lock release
            if MarkState.FAIL in TRANSITIONS.get(self.state, set()):
                self._go(
                    MarkState.FAIL,
                    "harness",
                    "unexpected_exception",
                    note=f"{type(exc).__name__}: {exc}",
                )
            else:
                self.state = MarkState.FAIL
                self.ledger.states.append(MarkState.FAIL.value)
            self.ledger.final = MarkState.FAIL.value
        if self.ledger.final is None:
            self.ledger.final = self.state.value
        rollback_error: str | None = None
        if (
            transaction is not None
            and transaction.committed
            and self.ledger.final != MarkState.DONE.value
        ):
            try:
                transaction.rollback_committed()
            except BaseException as exc:
                rollback_error = f"{type(exc).__name__}: {exc}"

        if rollback_error is None and transaction is not None:
            rollback_error = transaction.rollback_error
        if rollback_error is not None:
            self.ledger.integrity_status = "NEEDS_MANUAL_RECOVERY"
            self.ledger.rollback_error = rollback_error

        out = self.ledger.to_dict()
        try:
            path = write_ledger(self.workspace, out)
            out["ledger_path"] = str(path)
        except BaseException as exc:
            ledger_error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, StatePersistenceUncertain):
                rollback_error = f"ledger state persistence is uncertain: {ledger_error}"
            if transaction is not None and transaction.committed:
                try:
                    transaction.rollback_committed()
                except BaseException as rollback_exc:
                    rollback_error = f"{type(rollback_exc).__name__}: {rollback_exc}"
            if rollback_error is None and transaction is not None:
                rollback_error = transaction.rollback_error
            prior = self.state
            self.state = MarkState.FAIL
            self.ledger.final = MarkState.FAIL.value
            self.ledger.content_hashes = {}
            if rollback_error is not None:
                self.ledger.integrity_status = "NEEDS_MANUAL_RECOVERY"
                self.ledger.rollback_error = rollback_error
            self.ledger.states.append(MarkState.FAIL.value)
            self.ledger.steps.append(
                StepRecord(
                    step=self._step,
                    state_from=prior.value,
                    state_to=MarkState.FAIL.value,
                    agent="harness",
                    action="ledger_persist_fail",
                    note=ledger_error,
                )
            )
            self._step += 1
            out = self.ledger.to_dict()
            out["ledger_path_error"] = ledger_error

        stage_cleanup_error: str | None = None
        lock_release_error: str | None = None
        try:
            if transaction is not None:
                transaction.__exit__(None, None, None)
        except BaseException as exc:
            stage_cleanup_error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                if rollback_error is not None:
                    workspace_lock.retain_for_recovery()
                workspace_lock.__exit__(None, None, None)
            except BaseException as exc:
                lock_release_error = f"{type(exc).__name__}: {exc}"
        if stage_cleanup_error is not None:
            out["stage_cleanup_error"] = stage_cleanup_error
        if lock_release_error is not None:
            out["lock_release_error"] = lock_release_error
        if rollback_error is not None:
            out["rollback_error"] = rollback_error
            out["integrity_status"] = "NEEDS_MANUAL_RECOVERY"
        return out


def mcp_list_tools(workspace: str) -> list[dict]:
    return [t.to_mcp() for t in CodebaseTools(workspace).list_tools()]
