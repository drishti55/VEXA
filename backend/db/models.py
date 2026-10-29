"""
VEXA persistence schema (SQLAlchemy 2.0, SQLite by default, Postgres-compatible).

Raw measurements are stored once and never overwritten:

    experiments ─< runs ─< agent_runs        per-agent metrics of a run
                       ├─< spans             OpenTelemetry spans
                       ├─< state_entries     versioned shared-state items (+ provenance)
                       ├─< state_access      read/write access log
                       └─< coordination_events  architecture control decisions

``runs.result_json`` keeps the complete RunResult so nothing is lost when
columns are added later. Derived statistics are never stored here; they are
recomputed from these rows (see backend.evaluation.stats).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created")
    total_trials: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_trials: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_trials: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    environment: Mapped[dict] = mapped_column(JSON, default=dict, doc="versions, git sha, host info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    runs: Mapped[list[Run]] = relationship(back_populates="experiment")


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.experiment_id"), index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    repeat_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    architecture: Mapped[str] = mapped_column(String(64), index=True)
    prompt_variant: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_versions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_fingerprint: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    run_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, doc="outcome-relevant configuration")
    execution_mode: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    sandbox_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_transport: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verifier_backend: Mapped[str | None] = mapped_column(String(16), nullable=True)

    workspace_id: Mapped[str] = mapped_column(String(200))
    requirement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    tests_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    no_tests: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tests_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tests_failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    debug_iterations: Mapped[int] = mapped_column(Integer, default=0)
    test_attempts: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    usage_available: Mapped[bool] = mapped_column(Boolean, default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(200), default="unavailable")
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    agent_invocations: Mapped[int] = mapped_column(Integer, default=0)

    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grading: Mapped[dict | None] = mapped_column(JSON, nullable=True, doc="independent benchmark grading")
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    experiment: Mapped[Experiment | None] = relationship(back_populates="runs")
    agent_runs: Mapped[list[AgentRun]] = relationship(cascade="all, delete-orphan")


class PromptArchive(Base):
    """Exact prompt texts of every prompt version a run used, so historical configs can be rerun."""

    __tablename__ = "prompt_archive"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    variant: Mapped[str] = mapped_column(String(64))
    texts: Mapped[dict] = mapped_column(JSON)
    agent_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    invocations: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_failures: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_errors: Mapped[int] = mapped_column(Integer, default=0)
    validation_retries: Mapped[int] = mapped_column(Integer, default=0)


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"), index=True)
    trace_id: Mapped[str] = mapped_column(String(32))
    span_id: Mapped[str] = mapped_column(String(16))
    parent_span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16))
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class StateEntryRow(Base):
    __tablename__ = "state_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str] = mapped_column(String(32))
    seq: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    author: Mapped[str] = mapped_column(String(64))
    value_type: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    derived_from: Mapped[list] = mapped_column(JSON, default=list)


class StateAccessRow(Base):
    __tablename__ = "state_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    key: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(64))
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CoordinationRow(Base):
    __tablename__ = "coordination_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
