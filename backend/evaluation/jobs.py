"""
Background experiment jobs.

Experiments run in a worker thread so API requests never block. Each job has a
cancel flag checked between trials. On startup, experiments a previous process
left 'running' are marked 'interrupted' and can be resumed (completed trials
are skipped; the factorial design and seeds are unchanged).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from backend.core.logging import get_logger
from backend.db.registry import get_registry
from backend.evaluation.experiment import (
    ExperimentConfig,
    environment_snapshot,
    new_experiment_id,
    plan_trials,
    run_experiment,
)
from backend.evaluation.benchmark import DEFAULT_TASKS_DIR, load_tasks

logger = get_logger(__name__)


@dataclass
class _Job:
    experiment_id: str
    cfg: ExperimentConfig
    config_hash: str
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class ExperimentJobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}

    def active(self) -> set[str]:
        with self._lock:
            return {k for k, j in self._jobs.items() if j.thread and j.thread.is_alive()}

    def running_with_hash(self, config_hash: str) -> str | None:
        with self._lock:
            for k, j in self._jobs.items():
                if j.config_hash == config_hash and j.thread and j.thread.is_alive():
                    return k
        return None

    def start(self, cfg: ExperimentConfig, *, api_key: str | None = None) -> tuple[str, int]:
        """Create the experiment record now (so the caller gets its id) and run it in the background."""
        registry = get_registry()
        tasks = load_tasks(cfg.tasks_dir or DEFAULT_TASKS_DIR, None if cfg.tasks == "all" else list(cfg.tasks))
        total = len(plan_trials(cfg, [t.id for t in tasks]))
        exp_id = new_experiment_id()
        registry.create_experiment(exp_id, cfg.name, cfg.model_dump(mode="json"), environment_snapshot(cfg),
                                   description=cfg.description, total_trials=total, status="queued")
        self._launch(exp_id, cfg, api_key, resume=False)
        return exp_id, total

    def resume(self, experiment_id: str, *, api_key: str | None = None) -> None:
        exp = get_registry().get_experiment(experiment_id)
        if exp is None:
            raise KeyError(experiment_id)
        if experiment_id in self.active():
            raise RuntimeError("experiment is already running")
        if exp["status"] == "completed":
            raise RuntimeError("experiment already completed")
        self._launch(experiment_id, ExperimentConfig.model_validate(exp["config"]), api_key, resume=True)

    def cancel(self, experiment_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(experiment_id)
        if job is None or not (job.thread and job.thread.is_alive()):
            return False
        job.cancel.set()
        return True

    def _launch(self, exp_id: str, cfg: ExperimentConfig, api_key: str | None, *, resume: bool) -> None:
        job = _Job(exp_id, cfg, cfg.config_hash)

        def work() -> None:
            try:
                run_experiment(cfg, experiment_id=None if resume else exp_id, resume=exp_id if resume else None,
                               cancel_event=job.cancel, api_key=api_key)
            except Exception:
                logger.exception("experiment_job_failed | id=%s", exp_id)

        job.thread = threading.Thread(target=work, name=f"experiment-{exp_id}", daemon=True)
        with self._lock:
            self._jobs[exp_id] = job
        job.thread.start()

    def wait(self, experiment_id: str, timeout: float | None = None) -> None:
        with self._lock:
            job = self._jobs.get(experiment_id)
        if job and job.thread:
            job.thread.join(timeout)


jobs = ExperimentJobs()
