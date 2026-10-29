"""
Run registry: persists RunResults and experiments, and reads them back.

Default database: SQLite file at ``VEXA_DB_PATH`` (data/vexa.sqlite3). Set
``DATABASE_URL`` to any SQLAlchemy URL (e.g. postgresql+psycopg://...) to use
another backend; the schema is portable.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, event, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.agents.contracts import RunResult
from backend.core.config import get_settings
from backend.db.models import (
    AgentRun,
    Base,
    CoordinationRow,
    Experiment,
    Run,
    Span,
    StateAccessRow,
    StateEntryRow,
)


def _database_url() -> str:
    s = get_settings()
    if s.database_url:
        url = s.database_url
        # The async driver in older .env templates is not used by the registry.
        return url.replace("+asyncpg", "+psycopg")
    path = Path(s.vexa_db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


class RunRegistry:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or _database_url()
        self.engine: Engine = create_engine(self.url, future=True)
        if self.url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(conn, _record):  # FK cascades + concurrent readers
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")  # concurrent writers wait instead of failing
                cur.execute("PRAGMA synchronous=NORMAL")   # durable at checkpoints in WAL mode
                cur.close()
        Base.metadata.create_all(self.engine)
        self._migrate()
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    def _migrate(self) -> None:
        """Additive migration: add columns that newer code defines to existing tables."""
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if not insp.has_table(table.name):
                    continue
                existing = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name not in existing:
                        ddl = col.type.compile(dialect=self.engine.dialect)
                        conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))

    # ------------------------------------------------------------------
    # Prompt archive (never rewritten: a changed prompt is a new version)
    # ------------------------------------------------------------------

    def archive_prompt_set(self, prompt_set: Any) -> bool:
        """Store a prompt set's texts under its version if unseen. Returns True if newly archived."""
        from backend.db.models import PromptArchive
        with self._session.begin() as s:
            if s.get(PromptArchive, prompt_set.version) is not None:
                return False
            s.add(PromptArchive(version=prompt_set.version, variant=prompt_set.name, texts=dict(prompt_set.texts),
                                agent_versions=prompt_set.agent_versions))
            return True

    def get_archived_prompt(self, version: str) -> dict[str, Any] | None:
        from backend.db.models import PromptArchive
        with self._session() as s:
            row = s.get(PromptArchive, version)
            return None if row is None else {"version": row.version, "variant": row.variant, "texts": row.texts,
                                             "agent_versions": row.agent_versions, "first_seen": row.first_seen}

    def list_prompt_versions(self) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from backend.db.models import PromptArchive
        with self._session() as s:
            return [{"version": r.version, "variant": r.variant, "agent_versions": r.agent_versions,
                     "first_seen": r.first_seen.isoformat() if r.first_seen else None}
                    for r in s.scalars(select(PromptArchive).order_by(PromptArchive.first_seen))]

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def create_experiment(self, experiment_id: str, name: str, config: dict[str, Any],
                          environment: dict[str, Any] | None = None, *, description: str | None = None,
                          total_trials: int | None = None, status: str = "running") -> None:
        with self._session.begin() as s:
            s.add(Experiment(experiment_id=experiment_id, name=name, description=description, config=config,
                             environment=environment or {}, status=status, total_trials=total_trials,
                             completed_trials=0, failed_trials=0))

    def set_experiment_status(self, experiment_id: str, status: str, error: str | None = None) -> None:
        with self._session.begin() as s:
            exp = s.get(Experiment, experiment_id)
            if exp is not None:
                exp.status = status
                if error is not None:
                    exp.error = error
                if status not in ("running", "created", "queued"):
                    exp.finished_at = datetime.now(UTC)
                else:
                    exp.finished_at = None
                    if error is None:
                        exp.error = None  # a resumed experiment no longer carries the old error

    def update_progress(self, experiment_id: str, *, total: int | None = None) -> None:
        with self._session.begin() as s:
            exp = s.get(Experiment, experiment_id)
            if exp is None:
                return
            rows = s.execute(select(Run.status).where(Run.experiment_id == experiment_id)).scalars().all()
            exp.completed_trials = len(rows)
            exp.failed_trials = sum(1 for st in rows if st == "failed")
            if total is not None:
                exp.total_trials = total

    def finish_experiment(self, experiment_id: str, status: str = "completed", error: str | None = None) -> None:
        self.set_experiment_status(experiment_id, status, error)

    def record_run_started(self, result: RunResult) -> None:
        """Placeholder row so a run that never finishes (backend killed) is still on record."""
        self.save_run(result)
        with self._session.begin() as s:
            row = s.get(Run, result.run_id)
            if row is not None:
                row.status = "running"

    def mark_interrupted_runs(self) -> list[str]:
        """Runs left 'running' by a previous process become 'interrupted' (their partial record is kept)."""
        with self._session.begin() as s:
            stale = s.scalars(select(Run).where(Run.status == "running")).all()
            for row in stale:
                row.status = "interrupted"
                data = dict(row.result_json or {})
                data["status"] = "failed"
                data["errors"] = list(data.get("errors") or []) + [
                    "Interrupted: the backend stopped before this run finished; no result was produced."]
                row.result_json = data
                row.error_count = len(data["errors"])
            return [r.run_id for r in stale]

    def mark_interrupted(self, active_ids: set[str]) -> list[str]:
        """Experiments left 'running' by a previous process are 'interrupted' (resumable)."""
        with self._session.begin() as s:
            stale = s.scalars(select(Experiment).where(Experiment.status.in_(("running", "queued")))).all()
            out = []
            for exp in stale:
                if exp.experiment_id not in active_ids:
                    exp.status, exp.error = "interrupted", "backend stopped while the experiment was running"
                    out.append(exp.experiment_id)
            return out

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._session() as s:
            exp = s.get(Experiment, experiment_id)
            if exp is None:
                return None
            n = s.scalar(select(func.count()).select_from(Run).where(Run.experiment_id == experiment_id))
            return _experiment_dict(exp, n)

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._session() as s:
            counts = dict(s.execute(select(Run.experiment_id, func.count()).group_by(Run.experiment_id)).all())
            exps = s.scalars(select(Experiment).order_by(Experiment.created_at.desc())).all()
            return [_experiment_dict(e, counts.get(e.experiment_id, 0)) for e in exps]

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def save_run(
        self,
        result: RunResult,
        *,
        experiment_id: str | None = None,
        task_id: str | None = None,
        repeat_index: int | None = None,
        grading: dict[str, Any] | None = None,
    ) -> None:
        t = result.final_test_result
        v = result.verification_result
        metrics = result.agent_metrics or {}
        row = Run(
            run_id=result.run_id,
            experiment_id=experiment_id,
            task_id=task_id,
            repeat_index=repeat_index,
            architecture=result.architecture,
            prompt_variant=result.prompt_variant,
            prompt_version=result.prompt_version,
            prompt_versions=result.prompt_versions or None,
            config_fingerprint=result.config_fingerprint,
            run_config=result.config or None,
            execution_mode=result.execution_mode,
            provider=result.provider,
            model=result.model,
            sandbox_backend=result.sandbox_backend,
            tool_transport=result.tool_transport,
            verifier_backend=result.verifier_backend,
            workspace_id=result.workspace_id,
            requirement=result.requirement,
            status=result.status.value,
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_ms=result.total_duration_ms,
            tests_passed=t.passed if t else None,
            no_tests=t.no_tests if t else None,
            tests_found=t.tests_found if t else None,
            tests_failed=t.tests_failed if t else None,
            verified=v.verified if v else None,
            debug_iterations=result.debug_iterations,
            test_attempts=result.test_attempts,
            files_changed=len(result.files_changed),
            error_count=len(result.errors),
            usage_available=result.usage_available,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            cost_basis=result.cost_basis,
            llm_calls=sum(m.get("llm_calls", 0) for m in metrics.values()),
            tool_calls=sum(m.get("tool_calls", 0) for m in metrics.values()),
            agent_invocations=sum(m.get("invocations", 0) for m in metrics.values()),
            trace_id=result.trace_id,
            grading=grading,
            result_json=result.model_dump(mode="json"),
        )
        with self._session.begin() as s:
            s.merge(row)
            for table in (AgentRun, Span, StateEntryRow, StateAccessRow, CoordinationRow):
                s.execute(delete(table).where(table.run_id == result.run_id))
            s.add_all(self._children(result))

    @staticmethod
    def _children(result: RunResult) -> list[Any]:
        rid = result.run_id
        rows: list[Any] = []
        for agent, m in (result.agent_metrics or {}).items():
            rows.append(AgentRun(run_id=rid, agent=agent, **{k: m.get(k, 0) for k in (
                "invocations", "failures", "duration_ms", "llm_calls", "llm_failures", "input_tokens",
                "output_tokens", "tool_calls", "tool_errors", "validation_retries")}))
        for sp in result.trace.get("spans", []):
            rows.append(Span(
                run_id=rid, trace_id=sp["trace_id"], span_id=sp["span_id"], parent_span_id=sp["parent_span_id"],
                name=sp["name"], kind=sp["kind"], agent=sp["attributes"].get("vexa.agent"),
                start_ns=sp["start_ns"], end_ns=sp["end_ns"], duration_ms=sp["duration_ms"],
                status=sp["status"], attributes=sp["attributes"],
            ))
        for e in result.state.get("entries", []):
            rows.append(StateEntryRow(
                run_id=rid, entry_id=e["entry_id"], seq=e["seq"], key=e["key"], version=e["version"],
                author=e["author"], value_type=e["value_type"], value=e["value"], derived_from=e["derived_from"],
            ))
        for a in result.state.get("access_log", []):
            rows.append(StateAccessRow(run_id=rid, seq=a["seq"], kind=a["kind"], key=a["key"],
                                       agent=a["agent"], version=a["version"]))
        for c in result.coordination_log:
            rows.append(CoordinationRow(run_id=rid, seq=c["seq"], kind=c["kind"], actor=c["actor"],
                                        target=c["target"], detail=c["detail"], data=c["data"]))
        return rows

    def set_grading(self, run_id: str, grading: dict[str, Any]) -> None:
        with self._session.begin() as s:
            run = s.get(Run, run_id)
            if run is not None:
                run.grading = grading

    def get_run(self, run_id: str) -> RunResult | None:
        with self._session() as s:
            row = s.get(Run, run_id)
            return RunResult.model_validate(row.result_json) if row else None

    def get_run_row(self, run_id: str) -> dict[str, Any] | None:
        with self._session() as s:
            row = s.get(Run, run_id)
            return _run_summary(row) if row else None

    def list_runs(
        self,
        *,
        experiment_id: str | None = None,
        architecture: str | None = None,
        status: str | None = None,
        execution_mode: str | None = None,
        task_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        q = select(Run).order_by(Run.started_at.desc()).limit(limit).offset(offset)
        for col, val in ((Run.experiment_id, experiment_id), (Run.architecture, architecture),
                         (Run.status, status), (Run.execution_mode, execution_mode), (Run.task_id, task_id)):
            if val is not None:
                q = q.where(col == val)
        with self._session() as s:
            return [_run_summary(r) for r in s.scalars(q).all()]

    def agent_metrics(self, run_ids: list[str]) -> list[dict[str, Any]]:
        with self._session() as s:
            rows = s.scalars(select(AgentRun).where(AgentRun.run_id.in_(run_ids))).all()
            return [{c.name: getattr(r, c.name) for c in AgentRun.__table__.columns if c.name != "id"} for r in rows]

    def session(self) -> Session:
        return self._session()


_SUMMARY_COLUMNS = [c.name for c in Run.__table__.columns if c.name not in ("result_json",)]


def _run_summary(row: Run) -> dict[str, Any]:
    out = {name: getattr(row, name) for name in _SUMMARY_COLUMNS}
    if not out["usage_available"]:  # stored as 0; unmeasured must not read as zero in APIs or exports
        out["input_tokens"] = out["output_tokens"] = out["total_tokens"] = None
    for k in ("started_at", "finished_at", "created_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    return out


def _experiment_dict(e: Experiment, run_count: int) -> dict[str, Any]:
    return {
        "experiment_id": e.experiment_id, "name": e.name, "description": e.description, "status": e.status,
        "config": e.config, "environment": e.environment, "created_at": e.created_at.isoformat(),
        "finished_at": e.finished_at.isoformat() if e.finished_at else None, "run_count": run_count,
        "total_trials": e.total_trials, "completed_trials": e.completed_trials if e.completed_trials is not None else run_count,
        "failed_trials": e.failed_trials, "error": e.error,
    }


_registry: RunRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> RunRegistry:
    """Process-wide registry (created lazily from settings)."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = RunRegistry()
        return _registry


def reset_registry() -> None:
    """Forget the cached registry (tests / settings changes)."""
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.engine.dispose()
        _registry = None
