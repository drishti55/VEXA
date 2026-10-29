"""
Blackboard architecture.

Classic blackboard model (Hayes-Roth / HEARSAY-II style), three parts:

1. **Blackboard** — the run's SharedState: a versioned, access-logged knowledge
   space holding the standard knowledge items (requirement_analysis,
   implementation_plan, code_changes, test_result, debug_report, ...).

2. **Knowledge sources** — the same seven VEXA agents. Each declares
   ``reads`` (the knowledge items it consumes), an activation condition over
   the blackboard, and a priority. A knowledge source obtains its inputs ONLY
   through ``Blackboard.read`` (logged per agent) and contributes ONLY by
   writing a knowledge item. Knowledge sources never call each other.

3. **Control component** — subscribes to blackboard writes. Each write puts the
   knowledge sources that read the written item on the *agenda*. The
   controller evaluates activation conditions for agenda entries, picks the
   highest-priority triggered source, runs it, and repeats until nothing can
   contribute or the cycle budget is used up. Every decision is logged.

Nothing here encodes the pipeline order or the debug loop. "Tester after a
patch" and "Debugger after a failing test" emerge from activation conditions
over knowledge freshness (global write sequence numbers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from backend.agents.contracts import AgentStatus, AgentTestResult, DebugIteration
from backend.orchestration.base import Architecture, RunHandle
from backend.orchestration.state import SharedState, StateEntry

CONTROLLER = "controller"


class Blackboard:
    """Knowledge-source facing view of the shared state."""

    def __init__(self, state: SharedState) -> None:
        self.state = state

    def read(self, key: str, reader: str) -> Any | None:
        return self.state.read(key, reader)

    # Controller-side inspection: does not count as an agent read.
    def peek(self, key: str) -> Any | None:
        return self.state.peek(key)

    def has(self, key: str) -> bool:
        return self.state.has(key)

    def seq(self, key: str) -> int:
        return self.state.seq_of(key)

    def newer(self, key: str, *than: str) -> bool:
        """True if *key* exists and was written after every key in *than*."""
        s = self.seq(key)
        return s > 0 and all(s > self.seq(k) for k in than)


class KnowledgeSource(ABC):
    name: ClassVar[str]
    reads: ClassVar[tuple[str, ...]]
    priority: ClassVar[int]

    @abstractmethod
    def is_triggered(self, bb: Blackboard, h: RunHandle) -> bool:
        """Activation condition, evaluated by the controller."""

    @abstractmethod
    def contribute(self, bb: Blackboard, h: RunHandle) -> None:
        """Read inputs from the blackboard, run the agent, write the result."""


def _ok(value: Any) -> bool:
    return value is not None and getattr(value, "status", None) != AgentStatus.failed


class RequirementAnalystKS(KnowledgeSource):
    name, reads, priority = "RequirementAnalyst", ("requirement",), 70

    def is_triggered(self, bb, h):
        return bb.has("requirement") and not bb.has("requirement_analysis")

    def contribute(self, bb, h):
        req = h.runtime.analyze_requirements(h.ctx, bb.read("requirement", self.name))
        h.result.requirement_analysis = req


class ProjectAnalystKS(KnowledgeSource):
    name, reads, priority = "ProjectAnalyst", ("requirement_analysis",), 60

    def is_triggered(self, bb, h):
        return _ok(bb.peek("requirement_analysis")) and not bb.has("project_analysis")

    def contribute(self, bb, h):
        req = bb.read("requirement_analysis", self.name)
        h.result.project_analysis = h.runtime.analyze_project(h.ctx, h.kit, req)


class PlannerKS(KnowledgeSource):
    name, reads, priority = "Planner", ("requirement_analysis", "project_analysis"), 50

    def is_triggered(self, bb, h):
        return (_ok(bb.peek("requirement_analysis")) and bb.has("project_analysis")
                and not bb.has("implementation_plan"))

    def contribute(self, bb, h):
        req = bb.read("requirement_analysis", self.name)
        proj = bb.read("project_analysis", self.name)
        h.result.implementation_plan = h.runtime.plan(h.ctx, h.kit, req, proj)


class CoderKS(KnowledgeSource):
    name, reads, priority = "Coder", ("implementation_plan", "project_analysis", "requirement_analysis"), 40

    def is_triggered(self, bb, h):
        return bb.has("implementation_plan") and not bb.has("code_changes")

    def contribute(self, bb, h):
        plan = bb.read("implementation_plan", self.name)
        proj = bb.read("project_analysis", self.name)
        req = bb.read("requirement_analysis", self.name)
        h.record_coding(h.runtime.code(h.ctx, h.kit, plan, proj, req))


class TesterKS(KnowledgeSource):
    """Fires whenever the code (initial change or a debug patch) is newer than the last test."""

    name, reads, priority = "Tester", ("code_changes", "debug_report"), 30

    def is_triggered(self, bb, h):
        if not bb.has("code_changes"):
            return False
        return not bb.has("test_result") or not bb.newer("test_result", "code_changes", "debug_report")

    def contribute(self, bb, h):
        bb.read("code_changes", self.name)
        pending: DebugIteration | None = bb.read("debug_report", self.name) if bb.newer(
            "debug_report", "test_result") else None
        test = h.runtime.test(h.ctx, h.kit)
        h.record_test(test)
        if pending is not None:
            pending.test_result_after = test
            h.record_debug_iteration(pending)


class DebuggerKS(KnowledgeSource):
    """Fires on a fresh failing test result while debug budget remains."""

    name, reads, priority = "Debugger", ("test_result",), 20

    def is_triggered(self, bb, h):
        test: AgentTestResult | None = bb.peek("test_result")
        return (
            test is not None and not test.passed and not test.no_tests
            and bb.newer("test_result", "code_changes", "debug_report")
            and h.debug_budget_left > 0
        )

    def contribute(self, bb, h):
        test = bb.read("test_result", self.name)
        coding = bb.read("code_changes", self.name)
        req = bb.read("requirement_analysis", self.name)
        plan = bb.read("implementation_plan", self.name)
        iteration = h.max_debug_iterations - h.debug_budget_left + 1
        h.runtime.debug(h.ctx, h.kit, coding, test, iteration, h.max_debug_iterations, req, plan)


class VerifierKS(KnowledgeSource):
    """Fires on a fresh test result that the Debugger will not act on."""

    name, reads, priority = "Verifier", ("test_result", "requirement_analysis"), 10

    def is_triggered(self, bb, h):
        test: AgentTestResult | None = bb.peek("test_result")
        if test is None or not bb.newer("test_result", "code_changes", "debug_report"):
            return False
        settled = test.passed or test.no_tests or h.debug_budget_left <= 0
        return settled and not bb.newer("verification", "test_result")

    def contribute(self, bb, h):
        req = bb.read("requirement_analysis", self.name)
        test = bb.read("test_result", self.name)
        h.record_verification(h.runtime.verify(h.ctx, h.kit, req, h.result.files_changed, test))


DEFAULT_KNOWLEDGE_SOURCES: tuple[type[KnowledgeSource], ...] = (
    RequirementAnalystKS, ProjectAnalystKS, PlannerKS, CoderKS, TesterKS, DebuggerKS, VerifierKS,
)


class BlackboardArchitecture(Architecture):
    name = "blackboard"
    description = (
        "Agents are knowledge sources that read/write a shared versioned blackboard; "
        "a controller schedules them from an agenda driven by blackboard changes."
    )

    def __init__(self, sources: tuple[type[KnowledgeSource], ...] = DEFAULT_KNOWLEDGE_SOURCES) -> None:
        self.sources = [cls() for cls in sources]

    def execute(self, h: RunHandle) -> None:
        bb = Blackboard(h.ctx.state)
        agenda: list[KnowledgeSource] = []

        def on_write(entry: StateEntry) -> None:
            woken = [ks for ks in self.sources if entry.key in ks.reads and ks not in agenda]
            agenda.extend(woken)
            if woken:
                h.coordinate("event", CONTROLLER, None, f"{entry.key} v{entry.version} written by {entry.author}",
                             key=entry.key, version=entry.version, woke=[ks.name for ks in woken])

        h.ctx.state.subscribe(on_write)
        # The requirement was posted before the architecture started.
        agenda.extend(ks for ks in self.sources if "requirement" in ks.reads)

        for cycle in range(1, h.max_cycles + 1):
            triggered = [ks for ks in agenda if ks.is_triggered(bb, h)]
            if not triggered:
                h.coordinate("stop", CONTROLLER, None, "no knowledge source can contribute",
                             cycle=cycle, agenda=[ks.name for ks in agenda])
                break
            chosen = max(triggered, key=lambda ks: ks.priority)
            agenda.remove(chosen)
            h.coordinate("decision", CONTROLLER, chosen.name, "highest-priority triggered knowledge source",
                         cycle=cycle, triggered=[ks.name for ks in triggered],
                         agenda=[ks.name for ks in agenda])
            h.coordinate("dispatch", CONTROLLER, chosen.name)
            chosen.contribute(bb, h)
            latest = {"Planner": h.result.implementation_plan, "Coder": h.result.coding_result}.get(chosen.name)
            if h.stop_on_failure(CONTROLLER, chosen.name, latest):
                break
        else:
            h.coordinate("stop", CONTROLLER, None, f"cycle budget ({h.max_cycles}) exhausted")
            h.result.errors.append(f"Blackboard controller stopped after {h.max_cycles} cycles")

        req = bb.peek("requirement_analysis")
        if req is not None and req.status == AgentStatus.failed:
            raise RuntimeError("Requirement analysis failed: " + "; ".join(req.errors))
        if h.result.verification_result is None:
            h.result.errors.append("Blackboard run ended without a verification result")
