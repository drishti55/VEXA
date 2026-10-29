"""
VEXA M3 — Agent Run API Endpoints

POST /agent-runs       Submit a new baseline sequential agent run
GET  /agent-runs/{id}  (stub — in-memory only for M3; DB persistence in M4+)

Note: M3 runs are synchronous (blocking until completion).
      Async/streaming is deferred to a later milestone.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agents.context import RunContext
from backend.agents.contracts import AgentStatus, ExecutionMode, RunResult
from backend.agents.crew import SoftwareEngineeringCrew
from backend.agents.reporting import RunReport, build_run_report, render_markdown
from backend.core.logging import get_logger
from backend.orchestration import ARCHITECTURES, list_architectures
from backend.tools.service import ToolService

logger = get_logger(__name__)
router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])

# Single ToolService for the lifetime of the process (same as workspace router)
_svc = ToolService()

# Runs in flight live here (RunContext, for live polling). Completed runs are
# persisted to the run registry (SQLite) and evicted from memory.
_run_store: dict[str, RunResult | RunContext] = {}


def _persist(result: RunResult) -> None:
    from backend.db.registry import get_registry
    try:
        get_registry().save_run(result)
        _run_store.pop(result.run_id, None)
    except Exception as exc:  # keep the result available even if the DB write fails
        logger.error("run_persist_failed | run_id=%s error=%s", result.run_id, exc)
        _run_store[result.run_id] = result


def _lookup(run_id: str) -> RunResult | RunContext | None:
    record = _run_store.get(run_id)
    if record is not None:
        return record
    from backend.db.registry import get_registry
    return get_registry().get_run(run_id)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    # Unknown fields are an error: a misspelt "architecture" must not silently run the default one.
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(description="ID of the workspace to operate on")
    requirement: str = Field(
        min_length=10,
        max_length=4096,
        description="Natural-language software task requirement",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.mock,
        description="'mock' (scripted agents, no LLM, no network) or 'real' (live LLM, incurs cost).",
    )
    architecture: str = Field(
        default="sequential",
        description="Orchestration architecture (GET /agent-runs/architectures lists them).",
    )
    prompt_variant: str = Field(
        default="baseline",
        pattern="^(baseline|react|few_shot|minimal_persona)$",
        description="Prompt strategy (GET /agent-runs/prompt-variants lists them).",
    )
    verifier_backend: str | None = Field(default=None, pattern="^(crewai|adk_a2a)$",
                                         description="Default from server settings (adk_a2a)")
    tool_transport: str | None = Field(default=None, pattern="^(mcp|direct)$",
                                       description="Default from server settings (mcp)")

    task_category: str | None = Field(
        default=None, pattern="^[a-z_]+(,[a-z_]+)*$",
        description="Structured task category (feature, bug_fix, refactoring, testing, ...; comma-separated for "
                    "mixed tasks). Drives the deterministic hierarchical mock policy; recorded on the run.",
    )
    confirm_guardrail_review: bool = Field(
        default=False,
        description="Set after a human reviewed a requirement that G1 flagged as ambiguous (HTTP 409).",
    )
    llm_model: str | None = Field(default=None, description="Optional LiteLLM model string override")
    llm_api_key: str | None = Field(default=None, description="Optional primary API key override")
    llm_fallback_api_key: str | None = Field(default=None, description="Optional fallback API key override")

    @field_validator("requirement")
    @classmethod
    def _requirement_has_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("requirement must contain at least 10 non-blank characters")
        return v


class AgentRunResponse(BaseModel):
    run_id: str
    workspace_id: str
    execution_mode: str
    architecture: str
    status: str
    total_duration_ms: float
    files_changed: list[str]
    debug_iterations: int
    errors: list[str]
    result: dict  # Full RunResult or RunContext serialised — typed access via SDK later


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _screen_requirement(body: AgentRunRequest) -> None:
    """G1 pre-check. Ambiguous matches need confirmation (409, nothing runs yet).

    Unambiguous blocks are not rejected here: the runtime records them as a
    failed run with the G1 decision and a report, so the refusal is auditable.
    """
    from backend.guardrails import check_requirement, needs_review
    findings = check_requirement(body.requirement)
    review = needs_review(findings)
    if review and not body.confirm_guardrail_review and len(review) == len(findings):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "guardrail": "G1", "decision": "indeterminate", "needs_confirmation": True,
            "message": "This requirement matches patterns that are often legitimate but can also be an attempt "
                       "to exfiltrate credentials or weaken the sandbox. Review it and resubmit with "
                       "confirm_guardrail_review=true to proceed.",
            "findings": [{"rule": f.rule, "match": f.match} for f in review],
        })


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentRunResponse)
def submit_agent_run(body: AgentRunRequest) -> AgentRunResponse:
    """
    Submit a software engineering task to the baseline sequential agent crew.

    The call is synchronous — it blocks until all agents have completed.
    Returns the full structured result of the run.
    """
    # Validate workspace
    if not _svc.workspace_exists(body.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{body.workspace_id}' not found",
        )

    _screen_requirement(body)
    logger.info("agent_run_requested | workspace=%s mode=%s req=%s", body.workspace_id, body.execution_mode, body.requirement[:80])

    try:
        from backend.agents.config import get_agent_settings
        settings = get_agent_settings()
        if body.llm_model:
            settings.llm_model = body.llm_model
        if body.llm_api_key:
            settings.llm_api_key = body.llm_api_key
        if body.llm_fallback_api_key:
            settings.llm_fallback_api_key = body.llm_fallback_api_key
        _apply_overrides(settings, body)

        crew = SoftwareEngineeringCrew(tool_service=_svc, settings=settings)
        run_result = crew.run_task(
            workspace_id=body.workspace_id,
            requirement=body.requirement,
            execution_mode=body.execution_mode.value,
            architecture=body.architecture,
            guardrail_confirmed=body.confirm_guardrail_review,
            metadata={"task_category": body.task_category} if body.task_category else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    _persist(run_result)

    return AgentRunResponse(
        run_id=run_result.run_id,
        workspace_id=run_result.workspace_id,
        execution_mode=run_result.execution_mode,
        architecture=run_result.architecture,
        status=run_result.status.value,
        total_duration_ms=run_result.total_duration_ms,
        files_changed=run_result.files_changed,
        debug_iterations=run_result.debug_iterations,
        errors=run_result.errors,
        result=run_result.model_dump(mode="json"),
    )

def _apply_overrides(settings: Any, body: AgentRunRequest) -> None:
    settings.prompt_variant = body.prompt_variant
    if body.verifier_backend:
        settings.verifier_backend = body.verifier_backend
    if body.tool_transport:
        settings.tool_transport = body.tool_transport


def _execute_async_run(ctx: RunContext, crew: SoftwareEngineeringCrew, execution_mode: str,
                       guardrail_confirmed: bool = False, metadata: dict | None = None) -> None:
    try:
        run_result = crew.run_task(
            workspace_id=ctx.workspace_id,
            requirement=ctx.requirement,
            execution_mode=execution_mode,
            ctx=ctx,
            architecture=ctx.architecture,
            guardrail_confirmed=guardrail_confirmed,
            metadata=metadata,
        )
        _persist(run_result)
    except Exception as e:
        # The runtime normally converts every failure into a RunResult; this is
        # the last line of defence so a run never stays "running"/unreportable.
        logger.exception("async_run_crashed | run_id=%s", ctx.run_id)
        ctx.errors.append(str(e))
        ctx.finish()
        _persist(RunResult(
            run_id=ctx.run_id, workspace_id=ctx.workspace_id, requirement=ctx.requirement,
            architecture=ctx.architecture, execution_mode=ctx.execution_mode, status=AgentStatus.failed,
            errors=list(ctx.errors), events=[ev.model_dump(mode="json") for ev in ctx.events],
            finished_at=ctx.finished_at,
        ))

@router.post("/async", status_code=status.HTTP_202_ACCEPTED, response_model=AgentRunResponse)
def submit_agent_run_async(body: AgentRunRequest, bg_tasks: BackgroundTasks) -> AgentRunResponse:
    """
    Submit a task asynchronously for frontend polling.
    """
    if not _svc.workspace_exists(body.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{body.workspace_id}' not found",
        )

    if body.architecture not in ARCHITECTURES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Unknown architecture '{body.architecture}'")
    _screen_requirement(body)
    run_id = str(uuid.uuid4())
    ctx = RunContext(workspace_id=body.workspace_id, requirement=body.requirement, run_id=run_id,
                     architecture=body.architecture)
    ctx.execution_mode = body.execution_mode.value
    _run_store[run_id] = ctx
    try:  # on record from the start: survives a backend crash as 'interrupted'
        from backend.db.registry import get_registry
        get_registry().record_run_started(RunResult(
            run_id=run_id, workspace_id=body.workspace_id, requirement=body.requirement,
            architecture=body.architecture, execution_mode=body.execution_mode.value, status=AgentStatus.failed,
            errors=["Run in progress (no result yet)"],
            metadata={"task_category": body.task_category} if body.task_category else {}))
    except Exception as exc:
        logger.error("run_placeholder_failed | run_id=%s error=%s", run_id, exc)
    
    from backend.agents.config import get_agent_settings
    settings = get_agent_settings()
    if body.llm_model:
        settings.llm_model = body.llm_model
    if body.llm_api_key:
        settings.llm_api_key = body.llm_api_key
    if body.llm_fallback_api_key:
        settings.llm_fallback_api_key = body.llm_fallback_api_key
    _apply_overrides(settings, body)

    crew = SoftwareEngineeringCrew(tool_service=_svc, settings=settings)
    bg_tasks.add_task(_execute_async_run, ctx, crew, body.execution_mode.value, body.confirm_guardrail_review,
                      {"task_category": body.task_category} if body.task_category else None)

    return _format_run_response(run_id, ctx)

class TestModelRequest(BaseModel):
    llm_model: str | None = None
    llm_api_key: str | None = None


@router.post("/test-model")
def test_model(body: TestModelRequest) -> dict:
    """
    One-token call to check that a model string and key work (costs ~1 token).
    Errors are returned, not raised, so the UI can show them.
    """
    import time as _time

    import litellm

    from backend.agents.config import _PROVIDER_KEY_ENV, get_agent_settings, infer_provider
    from backend.observability.redaction import redact_text, register_secret

    s = get_agent_settings()
    model = body.llm_model or s.llm_model
    key = body.llm_api_key or s.llm_api_key
    register_secret(key)
    provider = infer_provider(model, s.llm_provider)
    if not key and not __import__("os").environ.get(_PROVIDER_KEY_ENV.get(provider, "_")):
        return {"ok": False, "model": model, "provider": provider, "error": "no API key configured for this provider"}
    t0 = _time.perf_counter()
    try:
        litellm.completion(model=model, messages=[{"role": "user", "content": "Reply with OK"}], max_tokens=1,
                           timeout=20, num_retries=0, **({"api_key": key} if key else {}))
    except Exception as exc:
        return {"ok": False, "model": model, "provider": provider, "error": redact_text(str(exc))[:400]}
    return {"ok": True, "model": model, "provider": provider, "latency_ms": (_time.perf_counter() - t0) * 1000}


@router.get("/provider-status")
def get_provider_status() -> dict:
    """Is the configured provider usable? Names and booleans only — never key values."""
    from backend.agents.config import provider_status
    return provider_status()


@router.get("/prompt-variants")
def get_prompt_variants() -> list[dict[str, Any]]:
    """Registered prompt strategies with their content hashes."""
    from backend.agents.prompt_variants import describe_variants
    return describe_variants()


@router.get("/architectures")
def get_architectures() -> list[dict[str, str]]:
    """Registered orchestration architectures."""
    return list_architectures()


@router.get("", response_model=AgentRunListResponse)
def list_agent_runs(limit: int = Query(default=50, ge=1, le=500)) -> AgentRunListResponse:
    """Active runs (newest first) followed by the most recent persisted runs."""
    from backend.db.registry import get_registry
    active = [_format_run_response(rid, rec) for rid, rec in reversed(list(_run_store.items()))]
    seen = {r.run_id for r in active}
    stored = []
    for row in get_registry().list_runs(limit=limit):
        if row["run_id"] not in seen:
            stored.append(AgentRunResponse(
                run_id=row["run_id"], workspace_id=row["workspace_id"], execution_mode=row["execution_mode"],
                architecture=row["architecture"], status=row["status"], total_duration_ms=row["duration_ms"],
                files_changed=[], debug_iterations=row["debug_iterations"], errors=[],
                result={"summary": row},
            ))
    return AgentRunListResponse(runs=(active + stored)[:limit])


@router.get("/registry/runs")
def query_runs(
    experiment_id: str | None = None,
    architecture: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    execution_mode: str | None = None,
    task_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Filterable run summaries from the persistent registry (no full payloads)."""
    from backend.db.registry import get_registry
    return get_registry().list_runs(experiment_id=experiment_id, architecture=architecture, status=status_,
                                    execution_mode=execution_mode, task_id=task_id, limit=limit, offset=offset)


@router.get("/{run_id}", response_model=AgentRunResponse)
def get_agent_run(run_id: str) -> AgentRunResponse:
    """A run in flight (live) or a completed run from the registry."""
    record = _lookup(run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return _format_run_response(run_id, record)

@router.get("/{run_id}/report", response_model=RunReport)
def get_agent_run_report(run_id: str, format: str = Query(default="json", pattern="^(json|md)$")):
    """Structured final report for a finished run (JSON, or Markdown with ?format=md)."""
    record = _lookup(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")
    if not isinstance(record, RunResult):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has not finished yet")
    report = build_run_report(record)
    if format == "md":
        return PlainTextResponse(render_markdown(report), media_type="text/markdown")
    return report


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_agent_run(run_id: str) -> dict:
    """
    Ask a running run to stop. It stops before the next agent starts; tool calls
    are refused from now on so the current agent finishes quickly. A request
    already sent to the LLM is not interrupted. The run ends as failed with the
    cancellation in its errors.
    """
    record = _run_store.get(run_id)
    if isinstance(record, RunContext):
        record.cancel_requested = record.cancel_requested or "cancelled by user"
        record.record("runtime", "cancel_requested", "the run stops before the next agent starts")
        return {"run_id": run_id, "status": "cancelling"}
    if record is not None or _lookup(run_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has already finished")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")


@router.get("/{run_id}/stream")
async def stream_agent_run(run_id: str, interval: float = Query(default=0.5, ge=0.1, le=5.0)):
    """
    Server-sent events: a ``snapshot`` event (AgentRunResponse JSON) whenever the
    run changes, then ``done`` when it has finished. Replaces client polling.
    """
    import asyncio

    from fastapi.responses import StreamingResponse

    if _lookup(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")

    async def events():
        last = None
        while True:
            record = _lookup(run_id)
            if record is None:
                yield "event: error\ndata: {\"detail\": \"run disappeared\"}\n\n"
                return
            body = _format_run_response(run_id, record).model_dump_json()
            if body != last:
                last = body
                yield f"event: snapshot\ndata: {body}\n\n"
            if isinstance(record, RunResult):
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(interval)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{run_id}/trace")
def get_agent_run_trace(run_id: str) -> dict:
    """
    Full execution record for reconstruction/export: OpenTelemetry spans,
    CrewAI callback events, coordination log, shared-state versions with
    provenance, per-agent metrics and file provenance.
    """
    record = _lookup(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")
    if isinstance(record, RunResult):
        return {
            "run_id": record.run_id, "trace_id": record.trace_id, "finished": True,
            "spans": record.trace.get("spans", []), "callback_events": record.trace.get("callback_events", []),
            "coordination_log": record.coordination_log, "state": record.state,
            "agent_metrics": record.agent_metrics, "file_provenance": record.file_provenance,
            "events": record.events,
        }
    live = record.to_dict()
    trace = live.get("trace") or {}
    return {
        "run_id": run_id, "trace_id": trace.get("trace_id"), "finished": False,
        "spans": trace.get("spans", []), "callback_events": trace.get("callback_events", []),
        "coordination_log": live["coordination_log"], "state": live["state"],
        "agent_metrics": trace.get("agent_metrics", {}), "file_provenance": trace.get("file_provenance", {}),
        "events": live["events"],
    }


def _format_run_response(run_id: str, record: RunResult | RunContext) -> AgentRunResponse:
    if isinstance(record, RunResult):
        return AgentRunResponse(
            run_id=record.run_id,
            workspace_id=record.workspace_id,
            execution_mode=record.execution_mode,
            architecture=record.architecture,
            status=record.status.value,
            total_duration_ms=record.total_duration_ms,
            files_changed=record.files_changed,
            debug_iterations=record.debug_iterations,
            errors=record.errors,
            result=record.model_dump(mode="json"),
        )
    else:
        # An active RunContext is "running" until the final RunResult replaces it
        # (finished_at is set a moment before usage, report and persistence are done;
        # reporting "failed" then made pollers stop with an incomplete snapshot).
        current_status = "running"
            
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        duration_ms = (now - record.started_at).total_seconds() * 1000
        if record.finished_at:
            duration_ms = (record.finished_at - record.started_at).total_seconds() * 1000
            
        return AgentRunResponse(
            run_id=record.run_id,
            workspace_id=record.workspace_id,
            execution_mode=record.execution_mode,
            architecture=record.architecture,
            status=current_status,
            total_duration_ms=duration_ms,
            files_changed=record.files_changed,
            debug_iterations=record.debug_iterations,
            errors=record.errors,
            result=record.to_dict(),
        )
