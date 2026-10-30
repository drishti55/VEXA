"""
VEXA — Orchestration architecture interface

All architectures receive the same inputs and produce the same RunResult:

    Architecture.execute(handle)        handle = task + workspace + runtime + config

The *runtime* (``SoftwareEngineeringCrew``) owns everything that must be held
constant in an experiment: the agents, their prompts, tools, output schemas,
LLM, the sandboxed test verdict and the debug budget. An architecture only
decides **control flow** (who runs next) and **communication** (how an agent
obtains its inputs). That makes the architecture the experimental variable.

Every control decision is appended to the run's coordination log so runs can
be compared step by step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from backend.agents.contracts import (
    AgentTestResult,
    CodingResult,
    DebugIteration,
    DebugResult,
    RunResult,
    VerificationResult,
)

if TYPE_CHECKING:
    from backend.agents.context import RunContext
    from backend.agents.crew import SoftwareEngineeringCrew
    from backend.agents.tools import WorkspaceToolKit


CoordinationKind = Literal[
    "dispatch",      # an agent was started by the architecture
    "decision",      # a manager / controller chose what happens next
    "event",         # an event was published on the bus
    "delivery",      # an event was delivered to a subscriber
    "message",       # an agent-to-agent / protocol message (A2A, MCP, manager brief)
    "review",        # a manager reviewed a specialist's result (accept / revise)
    "stop",          # the architecture stopped, with the reason
]


class CoordinationEvent(BaseModel):
    seq: int
    kind: CoordinationKind
    actor: str = Field(description="Who made the move: controller, manager, bus, or an agent id")
    target: str | None = None
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RunHandle:
    """Everything an architecture needs for one run."""

    runtime: SoftwareEngineeringCrew
    ctx: RunContext
    result: RunResult
    kit: WorkspaceToolKit
    max_debug_iterations: int
    max_cycles: int = 40
    _debug_iterations: list[DebugIteration] = field(default_factory=list)

    # -- coordination log ------------------------------------------------

    def coordinate(self, kind: CoordinationKind, actor: str, target: str | None = None,
                   detail: str = "", **data: Any) -> CoordinationEvent:
        if kind == "dispatch":
            from backend.guardrails import (
                RunBudgetExceeded,
                RunCancelled,
                check_run_budget,
                check_token_budget,
            )
            if getattr(self.ctx, "cancel_requested", None):
                self.ctx.coordinate("stop", actor, target, f"cancelled before {target}: {self.ctx.cancel_requested}")
                raise RunCancelled(f"Run cancelled before {target} started ({self.ctx.cancel_requested})")
            try:
                check_run_budget(self.ctx.started_monotonic, self.ctx.max_run_seconds)  # G7 time
                check_token_budget(self.ctx.observer, getattr(self.ctx, "max_run_tokens", None))  # G7 tokens
            except RunBudgetExceeded as exc:
                kind_ = "run_token_budget" if "token" in str(exc) else "run_time_budget"
                self.ctx.guard(kind_, target or "runtime", "blocked", str(exc), action="stop")
                raise
        return self.ctx.coordinate(kind, actor, target, detail, **data)

    # -- result recording (identical for every architecture) --------------

    def record_coding(self, coding: CodingResult) -> None:
        if self.result.coding_result is None:
            self.result.coding_result = coding
        for fc in coding.files_changed:
            self._file_changed(fc.path)

    def record_test(self, test: AgentTestResult) -> None:
        if self.result.initial_test_result is None:
            self.result.initial_test_result = test
        self.result.final_test_result = test
        if self.result.debug_result is not None:
            self.result.debug_result.final_test_result = test

    def record_debug_iteration(self, iteration: DebugIteration) -> None:
        self._debug_iterations.append(iteration)
        for fc in iteration.files_changed:
            self._file_changed(fc.path)
        from backend.agents.contracts import AgentStatus

        final = self.result.final_test_result
        passed = bool(final and final.passed)
        self.result.debug_result = DebugResult(
            status=AgentStatus.success if passed else AgentStatus.failed,
            summary=(
                f"Debug loop ran {len(self._debug_iterations)} iteration(s). "
                f"{'Tests now pass.' if passed else 'Tests still failing.'}"
            ),
            iterations=list(self._debug_iterations),
            final_test_result=final,
            max_iterations_reached=(not passed and len(self._debug_iterations) >= self.max_debug_iterations),
        )
        self.result.debug_iterations = len(self._debug_iterations)

    def record_verification(self, verification: VerificationResult) -> None:
        self.result.verification_result = verification

    def stop_on_failure(self, actor: str, agent: str, result: Any) -> str | None:
        """
        Stop rule shared by the architectures without a manager.

        Returns the reason (and records the stop) when *agent*'s failed result
        leaves the following agents nothing to work on, else None:
        a failed plan has nothing for the Coder to implement; a failed Coder
        that changed no file has nothing new to test or verify. Continuing would
        only spend LLM calls on an outcome that is already known.

        "Changed no file" is judged from the workspace on disk, not only from the
        Coder's report: a Coder whose final answer was invalid may still have
        written files, and those are worth testing and debugging.
        """
        from backend.agents.contracts import AgentStatus
        if result is None or getattr(result, "status", None) != AgentStatus.failed:
            return None
        if agent == "Planner":
            reason = "Planner failed, so there is no plan to implement"
        elif agent == "Coder" and not getattr(result, "files_changed", None) and not self._changed_on_disk():
            reason = "Coder failed without changing any file, so there is nothing to test or verify"
        else:
            return None
        errors = "; ".join(getattr(result, "errors", [])[:2])
        self.coordinate("stop", actor, agent, reason, stage=agent)
        self.result.errors.append(f"Stopped: {reason}" + (f" ({errors})" if errors else ""))
        return reason

    def _changed_on_disk(self) -> list[str]:
        actual = getattr(type(self.runtime), "_actual_changes", None)
        return actual(self.ctx) if actual else []

    @property
    def debug_budget_left(self) -> int:
        return self.max_debug_iterations - len(self._debug_iterations)

    def _file_changed(self, path: str) -> None:
        if path and path not in self.result.files_changed:
            self.result.files_changed.append(path)
        self.ctx.file_changed(path)


class Architecture(ABC):
    """Base class for orchestration architectures."""

    name: ClassVar[str]
    description: ClassVar[str]

    @abstractmethod
    def execute(self, handle: RunHandle) -> None:
        """Drive the agents for one run, recording results on ``handle``."""

    def __repr__(self) -> str:
        return f"<Architecture {self.name}>"
