"""
VEXA M3 — RunContext

Lightweight execution context threaded through the agent pipeline.
Designed to be expanded by M8 observability without schema replacement.

The RunContext:
- carries shared state across agents
- records timing and file-change events
- provides the workspace_id reference for tool calls
- will be persisted to the database in M8
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.core.logging import get_logger

logger = get_logger(__name__)


class AgentEvent(BaseModel):
    """A single structured log event within a run."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent: str
    event: str
    detail: str = ""
    duration_ms: float | None = None


class RunContext:
    """
    Mutable execution context threaded through the agent pipeline.

    Not a Pydantic model (needs mutable methods). Serialised to dict for
    API responses.

    Architecture is set at creation time (defaults to 'sequential').
    M4/M5/M6 will pass their architecture names.
    """

    def __init__(
        self,
        workspace_id: str,
        requirement: str,
        architecture: str = "sequential",
        run_id: str | None = None,
    ) -> None:
        self.run_id: str = run_id or str(uuid.uuid4())
        self.workspace_id: str = workspace_id
        self.requirement: str = requirement
        self.architecture: str = architecture
        self.execution_mode: str = "mock"
        self.provider: str | None = None
        self.model: str | None = None
        self.current_agent: str = "none"
        self.started_at: datetime = datetime.now(UTC)
        self.finished_at: datetime | None = None

        # Mutable state accumulated during the run
        self.files_changed: list[str] = []
        self.test_attempts: int = 0
        self.debug_iterations: int = 0
        self.errors: list[str] = []
        self.events: list[AgentEvent] = []

        # Shared, versioned run state and the architecture's coordination log
        from backend.orchestration.state import SharedState
        self.state = SharedState(self.run_id)
        self.coordination: list[Any] = []  # list[orchestration.base.CoordinationEvent]

        # Tracing / metrics / provenance (set by the runtime when the run starts)
        self.observer: Any = None  # observability.tracing.RunObserver

        # Guardrails (see backend/guardrails.py)
        import time as _time
        self.guardrail_events: list[dict[str, Any]] = []
        self.max_tool_calls_per_agent: int | None = None
        self.max_run_seconds: float | None = None
        self.invocation_tool_calls = 0
        self.tool_origin = "agent"  # 'scripted' while mock agents run their scripted tool calls
        self.started_monotonic = _time.monotonic()

        # Usage and Cost Tracking
        self.usage_available: bool = False
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.total_tokens: int = 0
        self.estimated_cost_usd: float | None = None
        self.mcp_servers: list[dict[str, Any]] = []
        self.cancel_requested: str | None = None  # set by POST /agent-runs/{id}/cancel  # same list as RunResult.mcp_servers, visible while running

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record(self, agent: str, event: str, detail: str = "", duration_ms: float | None = None) -> None:
        """Record a structured (redacted) event."""
        from backend.observability.redaction import redact_text
        detail = redact_text(detail)
        ev = AgentEvent(agent=agent, event=event, detail=detail, duration_ms=duration_ms)
        self.events.append(ev)
        if duration_ms is not None:
            logger.info("run=%s agent=%s event=%s duration_ms=%.1f | %s", self.run_id, agent, event, duration_ms, detail)
        else:
            logger.info("run=%s agent=%s event=%s | %s", self.run_id, agent, event, detail)

    def guard(self, kind: str, agent: str | None, decision: str, reason: str = "", *,
              action: str | None = None, **data: Any) -> dict[str, Any]:
        """
        Record one guardrail decision.

        decision: allowed | blocked | sanitized | flagged | indeterminate
        action:   proceed | reject | retry | sanitize | stop | record   (what the system did)
        The rule id (G1–G8) is derived from *kind* (see guardrails.RULES).
        """
        from backend.guardrails import GUARDRAILS_VERSION, RULES, STAGES, STATUS
        from backend.observability.redaction import redact
        rule_id, rule_name = RULES.get(kind, ("G?", kind))
        default_action = {"allowed": "proceed", "blocked": "reject", "sanitized": "sanitize",
                          "flagged": "record", "indeterminate": "record"}[decision]
        ev = {
            "seq": len(self.guardrail_events) + 1, "run_id": self.run_id, "rule": rule_id, "rule_name": rule_name,
            "kind": kind, "agent": agent, "decision": decision, "status": STATUS[decision],
            "stage": STAGES.get(kind, "other"), "version": GUARDRAILS_VERSION,
            "trace_id": getattr(self.observer, "trace_id", None), "action": action or default_action,
            "reason": redact(reason, 300), "detail": redact(reason, 300),
            "at": datetime.now(UTC).isoformat(), **redact(data, 300),
        }
        self.guardrail_events.append(ev)
        # Routine passes (allowed, and the spotlighting wrap applied to every tool output)
        # stay in guardrail_events and the trace; the live agent log shows only what needs attention.
        routine = decision == "allowed" or (decision == "sanitized" and kind == "tool_output")
        if not routine:
            self.record(agent or "runtime", f"guardrail:{kind}", f"{decision}: {reason}")
        if self.observer:
            self.observer.guardrail_event(ev)
        return ev

    def agent_started(self, agent_name: str) -> None:
        self.current_agent = agent_name
        self.invocation_tool_calls = 0
        self.injection_taint = None  # set when this invocation received suspected injected content (G6)
        self.record(agent_name, "started")
        if self.observer:
            self.observer.agent_started(agent_name)

    def agent_completed(self, agent_name: str, duration_ms: float = 0.0) -> None:
        self.record(agent_name, "completed", duration_ms=duration_ms)
        if self.observer:
            self.observer.agent_finished(agent_name, duration_ms)

    def agent_failed(self, agent_name: str, error: str, duration_ms: float = 0.0) -> None:
        from backend.observability.redaction import redact_text
        self.record(agent_name, "failed", error, duration_ms=duration_ms)
        self.errors.append(f"{agent_name} failed: {redact_text(error)}")
        if self.observer:
            self.observer.agent_finished(agent_name, duration_ms, error=error)

    def tool_invoked(self, agent_name: str, tool: str, detail: str = "") -> None:
        self.record(agent_name, "tool_invoked", f"{tool}: {detail}")

    def tool_failed(self, agent_name: str, tool: str, error: str) -> None:
        self.record(agent_name, "tool_failed", f"{tool}: {error}")
        self.errors.append(f"{agent_name}:{tool} — {error}")

    def coordinate(self, kind: str, actor: str, target: str | None = None, detail: str = "", **data: Any) -> Any:
        """Append an architecture/communication event (see orchestration.base.CoordinationEvent)."""
        from backend.orchestration.base import CoordinationEvent
        ev = CoordinationEvent(seq=len(self.coordination) + 1, kind=kind, actor=actor,
                               target=target, detail=detail, data=data)
        self.coordination.append(ev)
        return ev

    def file_changed(self, path: str) -> None:
        if path not in self.files_changed:
            self.files_changed.append(path)

    def test_attempted(self) -> None:
        self.test_attempts += 1
        self.record("Tester", "test_started", f"attempt #{self.test_attempts}")

    def debug_iterated(self) -> None:
        self.debug_iterations += 1
        self.record("Debugger", "debug_iteration", f"iteration #{self.debug_iterations}")

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        # While running, usage comes live from the per-call LLM events (the
        # final totals are only copied onto the context when the run ends).
        usage = {"usage_available": self.usage_available, "input_tokens": self.input_tokens,
                 "output_tokens": self.output_tokens, "total_tokens": self.total_tokens}
        if self.observer is not None and not self.usage_available:
            live = self.observer.usage_totals()
            if live["usage_available"]:
                usage = {k: live[k] for k in usage}
        return {
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "requirement": self.requirement,
            "architecture": self.architecture,
            "execution_mode": self.execution_mode,
            "provider": self.provider,
            "model": self.model,
            "current_agent": self.current_agent,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "files_changed": self.files_changed,
            "test_attempts": self.test_attempts,
            "debug_iterations": self.debug_iterations,
            "errors": self.errors,
            **usage,
            "estimated_cost_usd": self.estimated_cost_usd,
            "mcp_servers": self.mcp_servers,
            "tool_transport": getattr(self, "tool_transport", None),
            "events": [e.model_dump(mode="json") for e in self.events],
            "coordination_log": [c.model_dump(mode="json") for c in self.coordination],
            "state": self.state.to_dict(),
            "trace": self.observer.export() if self.observer else None,
            "guardrail_events": self.guardrail_events,
        }
