"""
Repeatable experiments: architecture × prompt variant × model × task × repeat.

    python -m backend.evaluation.experiment benchmarks/experiments/pilot_mock.json
    python -m backend.evaluation.experiment <config> --resume <experiment_id>

What makes runs comparable
--------------------------
- Every condition uses the same tasks, agents, tools, schemas, debug budget,
  temperature and sandbox; only the declared factors vary.
- Trial order is shuffled with a fixed seed so slow drifts (provider latency,
  rate limits) do not line up with one architecture.
- Each trial starts from a fresh copy of the task repository and is graded by
  hidden tests the agents never see (benchmark.grade).
- The environment (package versions, platform, config hash) is stored with
  the experiment; raw rows are written to the registry and to
  <dir of VEXA_DB_PATH>/experiments/<id>/raw_runs.jsonl. Statistics are always recomputed
  from raw rows (stats.py) — nothing derived is stored as if it were measured.

Cost control: ``max_cost_usd`` stops the experiment once the summed *estimated*
cost of completed real runs reaches the cap. Runs whose cost is unknown are
counted (and reported) separately; if pricing is missing the cap cannot be
enforced and the runner refuses to start a real experiment with a cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import sys
import uuid
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from backend.agents.config import AgentSettings
from backend.agents.crew import SoftwareEngineeringCrew
from backend.agents.prompt_variants import PROMPT_VARIANTS
from backend.core.logging import get_logger
from backend.db.registry import RunRegistry, get_registry
from backend.evaluation.benchmark import DEFAULT_TASKS_DIR, grade, load_tasks, materialise
from backend.orchestration import ARCHITECTURES
from backend.tools.service import ToolService

logger = get_logger(__name__)

def _default_out_dir() -> Path:
    """Raw experiment files live next to the run registry database."""
    from backend.core.config import get_settings
    return Path(get_settings().vexa_db_path).expanduser().resolve().parent / "experiments"


class ModelSpec(BaseModel):
    """One model condition. Prices are USD per 1M tokens (used for estimates only)."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    input_cost_per_1m: float | None = None
    output_cost_per_1m: float | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


class ExperimentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    execution_mode: Literal["mock", "real"] = "mock"
    tasks: list[str] | Literal["all"] = "all"
    architectures: list[str] = Field(default_factory=lambda: ["sequential"])
    prompt_variants: list[str] = Field(default_factory=lambda: ["baseline"])
    models: list[ModelSpec] = Field(default_factory=lambda: [ModelSpec()])
    repeats: int = Field(default=1, ge=1, le=100)
    seed: int = 1234
    temperature: float = Field(default=0.1, ge=0, le=2)
    debug_max_iter: int = Field(default=3, ge=0, le=10)
    max_run_seconds: float = Field(default=1800, gt=0, le=6 * 3600)
    tool_transport: Literal["mcp", "direct"] = "mcp"
    manager_revision_budget: int = Field(default=2, ge=0, le=5)
    verifier_backend: Literal["crewai", "adk_a2a"] = "adk_a2a"
    max_cost_usd: float | None = Field(default=None, gt=0)
    tasks_dir: str | None = None
    prompt_version_pins: dict[str, str] = Field(
        default_factory=dict,
        description="Rerun: prompt variant → archived prompt version to use instead of the current prompts",
    )
    rerun_of: str | None = Field(default=None, description="Experiment id this configuration was copied from")

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()

    @field_validator("architectures")
    @classmethod
    def _archs(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(ARCHITECTURES)
        if unknown:
            raise ValueError(f"unknown architectures {sorted(unknown)}; available {sorted(ARCHITECTURES)}")
        return v

    @field_validator("prompt_variants")
    @classmethod
    def _variants(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(PROMPT_VARIANTS)
        if unknown:
            raise ValueError(f"unknown prompt variants {sorted(unknown)}; available {list(PROMPT_VARIANTS)}")
        return v

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


class Trial(BaseModel):
    task_id: str
    architecture: str
    prompt_variant: str
    model: ModelSpec
    repeat_index: int

    @property
    def key(self) -> str:
        return f"{self.task_id}|{self.architecture}|{self.prompt_variant}|{self.model.label}|{self.repeat_index}"


def plan_trials(cfg: ExperimentConfig, task_ids: list[str]) -> list[Trial]:
    trials = [
        Trial(task_id=t, architecture=a, prompt_variant=p, model=m, repeat_index=r)
        for r in range(cfg.repeats) for t in task_ids for a in cfg.architectures
        for p in cfg.prompt_variants for m in cfg.models
    ]
    random.Random(cfg.seed).shuffle(trials)
    return trials


def environment_snapshot(cfg: ExperimentConfig) -> dict[str, Any]:
    def ver(pkg: str) -> str | None:
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {p: ver(p) for p in ("crewai", "google-adk", "a2a-sdk", "mcp", "litellm", "pydantic", "sqlalchemy")},
        "config_hash": cfg.config_hash,
        "started_at": datetime.now(UTC).isoformat(),
    }


def model_provider(m: ModelSpec) -> str:
    from backend.agents.config import infer_provider
    return infer_provider(m.model, m.provider)


def key_source(m: ModelSpec, api_key: str | None, settings: AgentSettings | None = None) -> str | None:
    """Where the key for this model comes from: job | server | env:<VAR> | None (missing).

    The server's VEXA_LLM_API_KEY only counts for the provider it was configured
    for; sending a Groq key to OpenAI fails every trial.
    """
    import os

    from backend.agents.config import _PROVIDER_KEY_ENV, infer_provider
    s = settings or AgentSettings()
    provider = model_provider(m)
    if api_key:
        return "job"
    if s.llm_api_key and infer_provider(s.llm_model, s.llm_provider) == provider:
        return "server"
    env = _PROVIDER_KEY_ENV.get(provider)
    if env and os.environ.get(env):
        return f"env:{env}"
    return None


def job_key_usable(cfg: ExperimentConfig, api_key: str | None) -> bool:
    """One key typed for the job can only belong to one provider."""
    return bool(api_key) and len({model_provider(m) for m in cfg.models}) == 1


def models_missing_keys(cfg: ExperimentConfig, api_key: str | None) -> list[str]:
    s = AgentSettings()
    key = api_key if job_key_usable(cfg, api_key) else None
    missing = [m.label for m in cfg.models if key_source(m, key, s) is None]
    if api_key and key is None and missing:
        missing = [f"{label} (the experiment key is ignored: models use several providers)" for label in missing]
    return missing


def _settings_for(cfg: ExperimentConfig, trial: Trial, api_key: str | None = None) -> AgentSettings:
    s = AgentSettings()
    api_key = api_key if job_key_usable(cfg, api_key) else None
    source = key_source(trial.model, api_key, s)
    if api_key:  # supplied for this job only; never persisted
        s.llm_api_key = api_key
    elif source != "server":
        s.llm_api_key = None  # server key belongs to another provider; LiteLLM reads the provider's env var
    s.llm_provider, s.llm_model = trial.model.provider, trial.model.model
    s.llm_input_cost_per_1m, s.llm_output_cost_per_1m = trial.model.input_cost_per_1m, trial.model.output_cost_per_1m
    s.llm_temperature = cfg.temperature
    s.debug_max_iter = max(cfg.debug_max_iter, 1)
    s.max_run_seconds = cfg.max_run_seconds
    s.tool_transport = cfg.tool_transport
    s.verifier_backend = cfg.verifier_backend
    s.manager_revision_budget = cfg.manager_revision_budget
    s.prompt_variant = trial.prompt_variant
    s.prompt_version_pin = cfg.prompt_version_pins.get(trial.prompt_variant)
    return s


class ExperimentCancelled(Exception):
    pass


def validate_config(cfg: ExperimentConfig, *, api_key_available: bool | None = None,
                    missing_key_models: list[str] | None = None) -> dict[str, Any]:
    """Static checks before starting. Returns {valid, errors, warnings, total_trials}."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        task_ids = [t.id for t in load_tasks(cfg.tasks_dir or DEFAULT_TASKS_DIR,
                                             None if cfg.tasks == "all" else list(cfg.tasks))]
    except ValueError as exc:
        errors.append(str(exc))
        task_ids = []
    if not cfg.architectures:
        errors.append("choose at least one architecture")
    if cfg.prompt_version_pins:
        from backend.agents.prompt_variants import get_prompt_set
        from backend.db.registry import get_registry
        for variant, version in cfg.prompt_version_pins.items():
            if version == get_prompt_set(variant).version:
                continue
            if get_registry().get_archived_prompt(version) is None:
                errors.append(f"prompt version {version} ({variant}) is not archived; it cannot be rerun exactly")
            else:
                warnings.append(f"{variant}: rerunning archived prompt version {version} "
                                f"(current is {get_prompt_set(variant).version})")
    if not cfg.prompt_variants:
        errors.append("choose at least one prompt variant")
    if cfg.execution_mode == "real":
        if missing_key_models:
            errors.append("no API key for " + ", ".join(missing_key_models) + " (set the provider's key in .env, "
                          "or enter one for this experiment)")
        elif missing_key_models is None and not api_key_available:
            errors.append("real mode needs an LLM API key (VEXA_LLM_API_KEY in .env, or enter one for this experiment)")
        if cfg.max_cost_usd is not None and any(m.input_cost_per_1m is None or m.output_cost_per_1m is None
                                                for m in cfg.models):
            errors.append("max_cost_usd needs input/output prices for every model")
        if all(m.input_cost_per_1m is None for m in cfg.models):
            warnings.append("no prices configured: cost will be reported as unavailable")
    else:
        warnings.append("mock mode: agents make no code changes, so tasks fail grading by design")
    total = len(task_ids) * len(cfg.architectures) * len(cfg.prompt_variants) * len(cfg.models) * cfg.repeats
    if total > 200:
        warnings.append(f"{total} trials is a large experiment")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "total_trials": total,
            "tasks": task_ids}


def run_experiment(
    cfg: ExperimentConfig,
    *,
    registry: RunRegistry | None = None,
    svc: ToolService | None = None,
    resume: str | None = None,
    crew_factory=None,
    out_dir: Path | None = None,
    experiment_id: str | None = None,
    cancel_event: Any = None,
    api_key: str | None = None,
) -> str:
    """
    Run (or resume) an experiment. Returns the experiment id.

    experiment_id: an already-created experiment record (job manager) to execute.
    cancel_event:  threading.Event; checked between trials (status 'cancelled').
    api_key:       LLM key for this job only (never stored).
    """
    registry = registry or get_registry()
    svc = svc or ToolService()
    tasks = {t.id: t for t in load_tasks(cfg.tasks_dir or DEFAULT_TASKS_DIR,
                                         None if cfg.tasks == "all" else list(cfg.tasks))}
    if cfg.execution_mode == "real" and cfg.max_cost_usd is not None and any(
            m.input_cost_per_1m is None or m.output_cost_per_1m is None for m in cfg.models):
        raise ValueError("max_cost_usd needs input/output prices for every model, otherwise it cannot be enforced")

    trials = plan_trials(cfg, list(tasks))
    exp_id = resume or experiment_id or new_experiment_id()
    if resume or experiment_id:
        if registry.get_experiment(exp_id) is None:
            raise ValueError(f"no experiment '{exp_id}' to run")
        registry.set_experiment_status(exp_id, "running")
    else:
        registry.create_experiment(exp_id, cfg.name, cfg.model_dump(mode="json"), environment_snapshot(cfg),
                                   description=cfg.description, total_trials=len(trials))

    out = (out_dir or _default_out_dir()) / exp_id
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "raw_runs.jsonl"

    done = {(r["grading"] or {}).get("trial_key") for r in registry.list_runs(experiment_id=exp_id, limit=100_000)}
    spent = sum((r["estimated_cost_usd"] or 0.0) for r in registry.list_runs(experiment_id=exp_id, limit=100_000))
    registry.update_progress(exp_id, total=len(trials))
    logger.info("experiment_start | id=%s trials=%d already_done=%d", exp_id, len(trials), len(done))

    status, error = "completed", None
    try:
        _run_trials(cfg, trials, tasks, done, registry, svc, crew_factory, raw_path, exp_id, cancel_event,
                    api_key, spent)
    except ExperimentCancelled:
        status = "cancelled"
    except _BudgetReached:
        status = "stopped_budget"
    except Exception as exc:  # recorded on the experiment, re-raised for the caller
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        registry.update_progress(exp_id)
        registry.finish_experiment(exp_id, status, error)
        raise
    registry.update_progress(exp_id)
    registry.finish_experiment(exp_id, status, error)
    return exp_id


class _BudgetReached(Exception):
    pass


def new_experiment_id() -> str:
    return f"exp-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def _run_trials(cfg, trials, tasks, done, registry, svc, crew_factory, raw_path, exp_id, cancel_event, api_key,
                spent) -> None:
    for i, trial in enumerate(trials, 1):
        if trial.key in done:
            continue
        if cancel_event is not None and cancel_event.is_set():
            raise ExperimentCancelled()
        if cfg.max_cost_usd is not None and spent >= cfg.max_cost_usd:
            logger.warning("experiment_budget_reached | id=%s spent=%.4f", exp_id, spent)
            raise _BudgetReached()
        task = tasks[trial.task_id]
        ws = materialise(task, svc)
        settings = _settings_for(cfg, trial, api_key)
        crew = crew_factory(svc, settings, trial, task) if crew_factory else SoftwareEngineeringCrew(
            tool_service=svc, settings=settings)
        meta = {"experiment_id": exp_id, "trial_key": trial.key, "task_id": task.id,
                "repeat_index": trial.repeat_index, "config_hash": cfg.config_hash, "task_category": task.category,
                "task_content_hash": task.content_hash}
        result = crew.run_task(ws, task.requirement, cfg.execution_mode, architecture=trial.architecture,
                               metadata=meta)
        g = grade(task, svc, ws)
        model_condition = trial.model.label if cfg.execution_mode == "real" else "mock:scripted"
        grading = {**g.model_dump(mode="json"), "trial_key": trial.key, "model_condition": model_condition,
                   "category": task.category, "difficulty": task.difficulty}
        registry.save_run(result, experiment_id=exp_id, task_id=task.id, repeat_index=trial.repeat_index,
                          grading=grading)
        spent += result.estimated_cost_usd or 0.0
        row = {"experiment_id": exp_id, "trial": trial.key, "run_id": result.run_id,
               "category": task.category, "grading": g.model_dump(mode="json"),
               **registry.get_run_row(result.run_id)}
        with raw_path.open("a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        svc.destroy_workspace(ws)
        registry.update_progress(exp_id)
        logger.info("trial_done | %d/%d %s success=%s", i, len(trials), trial.key, g.task_success)


def main() -> None:
    p = argparse.ArgumentParser(description="Run a VEXA benchmark experiment")
    p.add_argument("config", help="Path to an experiment JSON config")
    p.add_argument("--resume", help="Experiment id to resume")
    a = p.parse_args()
    cfg = ExperimentConfig.model_validate_json(Path(a.config).read_text())
    exp_id = run_experiment(cfg, resume=a.resume)
    from backend.evaluation.stats import summarise_experiment
    summary = summarise_experiment(exp_id)
    print(json.dumps({"experiment_id": exp_id, "conditions": summary["conditions"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
