"""
Experiment endpoints (benchmark runs, summaries, exports).

POST /experiments                  start an experiment in the background
GET  /experiments                  list experiments
GET  /experiments/{id}             experiment metadata
GET  /experiments/{id}/summary     derived statistics (recomputed from raw rows)
GET  /experiments/{id}/runs        raw per-run rows
GET  /experiments/{id}/export      ?format=csv|json|md
GET  /experiments/benchmark/tasks  the benchmark task set
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.logging import get_logger
from backend.db.registry import get_registry
from backend.evaluation.benchmark import load_tasks
from backend.evaluation.experiment import (
    ExperimentConfig,
    ModelSpec,
    key_source,
    models_missing_keys,
)
from backend.evaluation.stats import load_rows, rows_to_csv, summarise_rows

logger = get_logger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])


def _reject_unknown_config_keys(data: Any) -> Any:
    """Typos in a submitted configuration are errors, not silent defaults.

    Checked here, at the API boundary, rather than on ExperimentConfig itself so
    stored configurations from older versions can still be loaded and rerun.
    """
    cfg = data.get("config") if isinstance(data, dict) else None
    if isinstance(cfg, dict):
        unknown = sorted(set(cfg) - set(ExperimentConfig.model_fields))
        for m in cfg.get("models") or []:
            if isinstance(m, dict):
                unknown += [f"models.{k}" for k in sorted(set(m) - set(ModelSpec.model_fields))]
        if unknown:
            raise ValueError(f"unknown configuration field(s): {unknown}")
        tasks_dir = cfg.get("tasks_dir")
        if tasks_dir is not None:
            from pathlib import Path

            from backend.evaluation.benchmark import DEFAULT_TASKS_DIR
            root = DEFAULT_TASKS_DIR.parent.resolve()
            resolved = Path(str(tasks_dir)).expanduser().resolve()
            if resolved != root and root not in resolved.parents:
                raise ValueError(f"tasks_dir must be inside the benchmark directory ({root.name}/)")
    return data


class _ConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ExperimentConfig

    @model_validator(mode="before")
    @classmethod
    def _check_config_keys(cls, data: Any) -> Any:
        return _reject_unknown_config_keys(data)


class StartExperimentRequest(_ConfigRequest):
    confirm_real_cost: bool = False
    llm_api_key: str | None = Field(default=None, description="Used for this job only; never stored or returned")


class ValidateRequest(_ConfigRequest):
    llm_api_key: str | None = None


def _key_available(api_key: str | None) -> bool:
    """Is there a key for the server's configured default model?"""
    from backend.agents.config import get_agent_settings
    s = get_agent_settings()
    return key_source(ModelSpec(provider=s.llm_provider or "openai", model=s.llm_model or ""), api_key, s) is not None


@router.get("/options")
def experiment_options() -> dict:
    """Only options that are implemented and available on this server (no secrets)."""
    from backend.agents.config import get_agent_settings, infer_provider
    from backend.agents.prompt_variants import describe_variants
    from backend.core.config import get_settings
    from backend.orchestration import list_architectures

    s = get_agent_settings()
    return {
        "tasks": [{"id": t.id, "title": t.title, "category": t.category, "difficulty": t.difficulty} for t in load_tasks()],
        "architectures": list_architectures(),
        "prompt_variants": describe_variants(),
        "execution_modes": ["mock", "real"],
        "tool_transports": ["mcp", "direct"],
        "verifier_backends": [
            {"name": "adk_a2a", "description": "Google ADK Verifier over A2A (embedded server)" if s.a2a_embedded
             else f"Google ADK Verifier over A2A at {s.a2a_verifier_url}"},
            {"name": "crewai", "description": "CrewAI Verifier in-process"},
        ],
        "configured_model": {
            "model": s.llm_model, "provider": infer_provider(s.llm_model, s.llm_provider),
            "api_key_configured": _key_available(None),
            "input_cost_per_1m": s.llm_input_cost_per_1m, "output_cost_per_1m": s.llm_output_cost_per_1m,
        },
        "docs_search_available": bool(s.docs_search_api_key),
        "sandbox_backend": get_settings().sandbox_backend,
        "rag": {"available": False, "note": "Project RAG is not implemented"},
    }


@router.post("/validate")
def validate_experiment(body: ValidateRequest) -> dict:
    from backend.evaluation.experiment import validate_config
    return validate_config(body.config, missing_key_models=models_missing_keys(body.config, body.llm_api_key))


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def start_experiment(body: StartExperimentRequest) -> dict:
    from backend.evaluation.experiment import validate_config
    from backend.evaluation.jobs import jobs

    check = validate_config(body.config, missing_key_models=models_missing_keys(body.config, body.llm_api_key))
    if not check["valid"]:
        raise HTTPException(status_code=422, detail="; ".join(check["errors"]))
    if body.config.execution_mode == "real" and not body.confirm_real_cost:
        raise HTTPException(status_code=400, detail="Real-mode experiments call paid LLM APIs; set confirm_real_cost=true")
    existing = jobs.running_with_hash(body.config.config_hash)
    if existing:
        raise HTTPException(status_code=409, detail=f"An identical experiment is already running: {existing}")
    if body.llm_api_key:
        from backend.observability.redaction import register_secret
        register_secret(body.llm_api_key)
    exp_id, total = jobs.start(body.config, api_key=body.llm_api_key)
    return {"experiment_id": exp_id, "status": "queued", "total_trials": total, "warnings": check["warnings"]}


@router.post("/{experiment_id}/cancel")
def cancel_experiment(experiment_id: str) -> dict:
    from backend.evaluation.jobs import jobs
    _experiment_or_404(experiment_id)
    if not jobs.cancel(experiment_id):
        raise HTTPException(status_code=409, detail="Experiment is not running in this backend process")
    return {"experiment_id": experiment_id, "cancelling": True}


class RerunRequest(BaseModel):
    pin_prompt_versions: bool = Field(default=True, description="Use the prompt texts the original runs used")
    confirm_real_cost: bool = False
    llm_api_key: str | None = Field(default=None, description="Used for this job only; never stored or returned")


@router.post("/{experiment_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
def rerun_experiment(experiment_id: str, body: RerunRequest) -> dict:
    """New experiment with the same configuration (and, by default, the same archived prompt versions).

    The original experiment and its runs are not modified; the rerun records its
    own configuration fingerprints.
    """
    exp = _experiment_or_404(experiment_id)
    config = dict(exp["config"] or {})
    runs = get_registry().list_runs(experiment_id=experiment_id, limit=100_000)
    pins: dict[str, str] = {}
    if body.pin_prompt_versions:
        by_variant: dict[str, set[str]] = {}
        for r in runs:
            if r.get("prompt_version"):
                by_variant.setdefault(r.get("prompt_variant") or "baseline", set()).add(r["prompt_version"])
        mixed = {v: sorted(s) for v, s in by_variant.items() if len(s) > 1}
        if mixed:
            raise HTTPException(status_code=409, detail=f"original runs used several prompt versions per variant "
                                                        f"({mixed}); rerun with pin_prompt_versions=false")
        pins = {v: next(iter(s)) for v, s in by_variant.items()}
    config.update(name=f"Rerun of {exp['name']}"[:200], rerun_of=experiment_id, prompt_version_pins=pins)
    try:
        cfg = ExperimentConfig.model_validate(config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"stored configuration is no longer valid: {exc}") from exc
    return start_experiment(StartExperimentRequest(config=cfg, confirm_real_cost=body.confirm_real_cost,
                                                   llm_api_key=body.llm_api_key))


@router.get("/prompt-versions")
def prompt_versions() -> dict:
    """Current prompt versions per variant and every archived version (texts are not returned)."""
    from backend.agents.prompt_variants import describe_variants
    return {"current": describe_variants(), "archived": get_registry().list_prompt_versions()}


class ResumeRequest(BaseModel):
    llm_api_key: str | None = None


@router.post("/{experiment_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_experiment(experiment_id: str, body: ResumeRequest | None = None) -> dict:
    """Run the trials that are still missing (after cancel, interruption or failure)."""
    from backend.evaluation.jobs import jobs
    _experiment_or_404(experiment_id)
    try:
        jobs.resume(experiment_id, api_key=body.llm_api_key if body else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"experiment_id": experiment_id, "status": "running"}


@router.get("")
def list_experiments() -> list[dict]:
    from backend.evaluation.jobs import jobs
    active = jobs.active()
    return [{**e, "active": e["experiment_id"] in active} for e in get_registry().list_experiments()]


@router.get("/benchmark/tasks")
def benchmark_tasks() -> list[dict]:
    return [t.model_dump() for t in load_tasks()]


def _experiment_or_404(experiment_id: str) -> dict:
    exp = get_registry().get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")
    return exp


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str) -> dict:
    return _experiment_or_404(experiment_id)


@router.get("/{experiment_id}/runs")
def experiment_runs(experiment_id: str) -> list[dict]:
    _experiment_or_404(experiment_id)
    return [{k: v for k, v in r.items() if k != "agent_metrics"} for r in load_rows(experiment_id)]


@router.get("/{experiment_id}/summary")
def experiment_summary(experiment_id: str) -> dict:
    exp = _experiment_or_404(experiment_id)
    return {"experiment": exp, **summarise_rows(load_rows(experiment_id))}


@router.get("/{experiment_id}/export")
def export_experiment(experiment_id: str, format: str = Query(default="csv", pattern="^(csv|json|md)$")):
    exp = _experiment_or_404(experiment_id)
    rows = load_rows(experiment_id)
    if format == "csv":
        return PlainTextResponse(rows_to_csv(rows), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{experiment_id}.csv"'})
    summary = {"experiment": exp, **summarise_rows(rows)}
    if format == "md":
        from backend.evaluation.stats import experiment_report_markdown
        return PlainTextResponse(experiment_report_markdown(summary, rows), media_type="text/markdown")
    body = json.dumps({"summary": summary, "raw_runs": rows}, default=str, indent=2)
    return PlainTextResponse(body, media_type="application/json",
                             headers={"Content-Disposition": f'attachment; filename="{experiment_id}.json"'})
