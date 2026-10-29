"""
Event-driven architecture.

Agents subscribe to event types on an in-process bus; nobody calls an agent
directly and there is no central scheduler. Each agent receives everything it
needs in the event payload and decides which event to publish next:

    TASK_SUBMITTED         → RequirementAnalyst → REQUIREMENTS_READY
    REQUIREMENTS_READY     → ProjectAnalyst     → PROJECT_ANALYZED
    PROJECT_ANALYZED       → Planner            → PLAN_READY
    PLAN_READY             → Coder              → CODE_CHANGED
    CODE_CHANGED, PATCH_READY → Tester          → TEST_PASSED | TEST_FAILED | NO_TESTS
    TEST_FAILED            → Debugger           → PATCH_READY | VERIFICATION_REQUESTED (budget spent)
    TEST_PASSED, NO_TESTS, VERIFICATION_REQUESTED → Verifier → VERIFIED | NOT_VERIFIED
    REQUIREMENTS_FAILED, EXECUTION_FAILED, VERIFIED, NOT_VERIFIED → (no subscribers; the run ends)

PLAN_READY and CODE_CHANGED are replaced by EXECUTION_FAILED when the Planner
failed, or the Coder failed without changing a file (RunHandle.stop_on_failure).

Every event carries a unique id, the run id, a timestamp and the id of the
event that caused it. Its payload is checked against the schema for its type
when published (a malformed event never reaches a handler), and each
(event, subscriber) pair is delivered at most once, so a re-published event
cannot repeat a side effect. The bus delivers in FIFO order (deterministic,
single-threaded) and logs every publish, delivery and skipped duplicate. A
delivery budget guards against loops. SharedState is written as an audit
mirror only.
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.contracts import AgentStatus
from backend.orchestration.base import Architecture, RunHandle

BUS = "bus"


# Payload keys each event type must carry for its subscribers (cumulative: an
# event carries its cause's payload forward). Unknown types are rejected.
EVENT_SCHEMA: dict[str, tuple[str, ...]] = {
    "TASK_SUBMITTED": ("requirement",),
    "REQUIREMENTS_READY": ("requirement", "req"),
    "REQUIREMENTS_FAILED": ("requirement", "req"),
    "PROJECT_ANALYZED": ("req", "proj"),
    "PLAN_READY": ("req", "proj", "plan"),
    "CODE_CHANGED": ("req", "proj", "plan", "coding"),
    "PATCH_READY": ("req", "plan", "coding", "debug_record"),
    "TEST_PASSED": ("req", "test"),
    "TEST_FAILED": ("req", "plan", "coding", "test"),
    "NO_TESTS": ("req", "test"),
    "VERIFICATION_REQUESTED": ("req", "test"),
    "VERIFIED": ("req", "verification"),
    "NOT_VERIFIED": ("req", "verification"),
    "EXECUTION_FAILED": ("stage", "reason"),
}


class BusEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: str
    source: str
    run_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    causation_id: str | None = Field(default=None, description="event that caused this one")
    payload: dict[str, Any] = Field(default_factory=dict)

    def validate_payload(self) -> None:
        required = EVENT_SCHEMA.get(self.type)
        if required is None:
            raise ValueError(f"unknown event type '{self.type}'")
        missing = [k for k in required if self.payload.get(k) is None]
        if missing:
            raise ValueError(f"{self.type} from {self.source} is missing payload field(s) {missing}")


Handler = Callable[[BusEvent], None]


class EventBus:
    def __init__(self, h: RunHandle) -> None:
        self._h = h
        self._subs: dict[str, list[tuple[str, Handler]]] = {}
        self._queue: deque[BusEvent] = deque()
        self._done: set[tuple[str, str]] = set()  # (event_id, subscriber) already delivered
        self.delivered = 0
        self.duplicates = 0

    def subscribe(self, event_type: str, agent: str, handler: Handler) -> None:
        if event_type not in EVENT_SCHEMA:
            raise ValueError(f"cannot subscribe to unknown event type '{event_type}'")
        self._subs.setdefault(event_type, []).append((agent, handler))

    def publish(self, event: BusEvent) -> None:
        event.run_id = event.run_id or self._h.ctx.run_id
        event.validate_payload()  # a malformed event is a bug in its publisher: fail loudly, deliver nothing
        self._queue.append(event)
        subs = [a for a, _ in self._subs.get(event.type, [])]
        self._h.coordinate("event", event.source, None, event.type, event_id=event.event_id,
                           causation_id=event.causation_id, subscribers=subs, run_id=event.run_id,
                           created_at=event.created_at.isoformat())

    def run(self, max_deliveries: int) -> None:
        while self._queue:
            event = self._queue.popleft()
            for agent, handler in self._subs.get(event.type, []):
                if (event.event_id, agent) in self._done:
                    self.duplicates += 1
                    self._h.coordinate("delivery", BUS, agent, f"{event.type} (duplicate, skipped)",
                                       event_id=event.event_id, duplicate=True)
                    continue
                if self.delivered >= max_deliveries:
                    self._h.coordinate("stop", BUS, None, f"delivery budget ({max_deliveries}) exhausted")
                    self._h.result.errors.append(f"Event bus stopped after {max_deliveries} deliveries")
                    return
                self.delivered += 1
                self._done.add((event.event_id, agent))
                self._h.coordinate("delivery", BUS, agent, event.type, event_id=event.event_id)
                self._h.coordinate("dispatch", BUS, agent)
                handler(event)
        self._h.coordinate("stop", BUS, None, "event queue drained")


class EventDrivenArchitecture(Architecture):
    name = "event_driven"
    description = "Agents subscribe to typed events and publish new ones; no central scheduler."

    def execute(self, h: RunHandle) -> None:
        rt, ctx, kit = h.runtime, h.ctx, h.kit
        bus = EventBus(h)

        def emit(source: str, etype: str, cause: BusEvent, **payload: Any) -> None:
            bus.publish(BusEvent(type=etype, source=source, causation_id=cause.event_id,
                                 payload={**cause.payload, **payload}))

        def requirement_analyst(ev: BusEvent) -> None:
            req = rt.analyze_requirements(ctx, ev.payload["requirement"])
            h.result.requirement_analysis = req
            failed = req.status == AgentStatus.failed
            emit("RequirementAnalyst", "REQUIREMENTS_FAILED" if failed else "REQUIREMENTS_READY", ev, req=req)

        def project_analyst(ev: BusEvent) -> None:
            proj = rt.analyze_project(ctx, kit, ev.payload["req"])
            h.result.project_analysis = proj
            emit("ProjectAnalyst", "PROJECT_ANALYZED", ev, proj=proj)

        def planner(ev: BusEvent) -> None:
            plan = rt.plan(ctx, kit, ev.payload["req"], ev.payload["proj"])
            h.result.implementation_plan = plan
            reason = h.stop_on_failure(BUS, "Planner", plan)
            if reason:
                emit("Planner", "EXECUTION_FAILED", ev, stage="Planner", reason=reason, plan=plan)
            else:
                emit("Planner", "PLAN_READY", ev, plan=plan)

        def coder(ev: BusEvent) -> None:
            p = ev.payload
            coding = rt.code(ctx, kit, p["plan"], p["proj"], p["req"])
            h.record_coding(coding)
            reason = h.stop_on_failure(BUS, "Coder", coding)
            if reason:
                emit("Coder", "EXECUTION_FAILED", ev, stage="Coder", reason=reason, coding=coding)
            else:
                emit("Coder", "CODE_CHANGED", ev, coding=coding)

        def tester(ev: BusEvent) -> None:
            test = rt.test(ctx, kit)
            h.record_test(test)
            pending = ev.payload.get("debug_record")
            if ev.type == "PATCH_READY" and pending is not None:
                pending.test_result_after = test
                h.record_debug_iteration(pending)
            etype = "NO_TESTS" if test.no_tests else ("TEST_PASSED" if test.passed else "TEST_FAILED")
            emit("Tester", etype, ev, test=test, debug_record=None)

        def debugger(ev: BusEvent) -> None:
            p = ev.payload
            if h.debug_budget_left <= 0:
                emit("Debugger", "VERIFICATION_REQUESTED", ev, reason="debug budget exhausted")
                return
            iteration = h.max_debug_iterations - h.debug_budget_left + 1
            record, applied = rt.debug(ctx, kit, p["coding"], p["test"], iteration, h.max_debug_iterations,
                                       p["req"], p["plan"])
            if applied:
                emit("Debugger", "PATCH_READY", ev, debug_record=record)
            else:
                record.test_result_after = p["test"]
                h.record_debug_iteration(record)
                emit("Debugger", "TEST_FAILED" if h.debug_budget_left > 0 else "VERIFICATION_REQUESTED", ev)

        def verifier(ev: BusEvent) -> None:
            p = ev.payload
            v = rt.verify(ctx, kit, p["req"], h.result.files_changed, p["test"])
            h.record_verification(v)
            emit("Verifier", "VERIFIED" if v.verified else "NOT_VERIFIED", ev, verification=v)

        for etype, agent, fn in (
            ("TASK_SUBMITTED", "RequirementAnalyst", requirement_analyst),
            ("REQUIREMENTS_READY", "ProjectAnalyst", project_analyst),
            ("PROJECT_ANALYZED", "Planner", planner),
            ("PLAN_READY", "Coder", coder),
            ("CODE_CHANGED", "Tester", tester),
            ("PATCH_READY", "Tester", tester),
            ("TEST_FAILED", "Debugger", debugger),
            ("TEST_PASSED", "Verifier", verifier),
            ("NO_TESTS", "Verifier", verifier),
            ("VERIFICATION_REQUESTED", "Verifier", verifier),
        ):
            bus.subscribe(etype, agent, fn)

        bus.publish(BusEvent(type="TASK_SUBMITTED", source="user", payload={"requirement": ctx.requirement}))
        bus.run(max_deliveries=h.max_cycles)

        req = h.result.requirement_analysis
        if req is not None and req.status == AgentStatus.failed:
            raise RuntimeError("Requirement analysis failed: " + "; ".join(req.errors))
        if h.result.verification_result is None:
            h.result.errors.append("Event-driven run ended without a verification result")
