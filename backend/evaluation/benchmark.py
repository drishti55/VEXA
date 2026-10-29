"""
Benchmark tasks and independent grading.

Task layout (benchmarks/tasks/<id>/)::

    task.json        id, title, category, difficulty, requirement, acceptance_criteria
    repo/            starting repository given to the agents (visible tests included)
    hidden_tests/    grading tests — never copied into an agent workspace
    solution/        reference solution (whole-file replacements) used only to
                     validate the task itself

Grading is independent of everything the agents report: the final workspace
is copied into a fresh grading workspace, the hidden tests are added there,
and both hidden and visible suites run in the configured sandbox.

    task_success   = all hidden tests pass AND all visible tests pass
    hidden_pass_rate = hidden tests passed / hidden tests collected
    regression     = a visible test that passed on the starting repo now fails
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.agents.crew import summarise_pytest_output
from backend.tools.service import ToolService

DEFAULT_TASKS_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "tasks"
HIDDEN_DIR = "vexa_hidden_tests"


class BenchmarkTask(BaseModel):
    id: str
    title: str
    category: str
    difficulty: str
    requirement: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    ground_truth: str = ""
    timeout_seconds: int = 120
    path: Path = Field(exclude=True)

    @property
    def repo_dir(self) -> Path:
        return self.path / "repo"

    @property
    def hidden_dir(self) -> Path:
        return self.path / "hidden_tests"

    @property
    def solution_dir(self) -> Path:
        return self.path / "solution"

    @property
    def content_hash(self) -> str:
        """Hash of everything that defines the task (task.json, starting repo, hidden tests, solution)."""
        import hashlib
        h = hashlib.sha256()
        for f in sorted(p for p in self.path.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            h.update(str(f.relative_to(self.path)).encode())
            h.update(f.read_bytes())
        return h.hexdigest()[:16]


class SuiteResult(BaseModel):
    exit_code: int | None
    collected: int
    passed: int
    failed: int
    timed_out: bool
    failures: list[str] = Field(default_factory=list)


class Grade(BaseModel):
    task_id: str
    task_success: bool
    hidden: SuiteResult
    visible: SuiteResult
    hidden_pass_rate: float | None
    regression: bool
    grader: str = "hidden_tests_v1"


def load_tasks(tasks_dir: Path | str = DEFAULT_TASKS_DIR, ids: list[str] | None = None) -> list[BenchmarkTask]:
    tasks_dir = Path(tasks_dir)
    tasks = []
    for d in sorted(p for p in tasks_dir.iterdir() if (p / "task.json").is_file()):
        t = BenchmarkTask(**json.loads((d / "task.json").read_text()), path=d)
        if ids is None or t.id in ids:
            tasks.append(t)
    missing = set(ids or []) - {t.id for t in tasks}
    if missing:
        raise ValueError(f"Unknown benchmark task(s): {sorted(missing)}")
    return tasks


def materialise(task: BenchmarkTask, svc: ToolService, workspace_id: str | None = None) -> str:
    """Create a fresh workspace containing only the task's starting repository."""
    ws = svc.create_workspace(workspace_id or f"bench-{task.id}-{uuid.uuid4().hex[:8]}")
    shutil.copytree(task.repo_dir, svc._manager.require(ws), dirs_exist_ok=True)
    return ws


def cleanup_orphan_workspaces(svc: ToolService) -> list[str]:
    """Remove trial/grading workspaces left by a process that died mid-experiment.

    Experiments always destroy these in ``finally``; leftovers only exist after a
    crash or kill. Call at startup, before any experiment job can run.
    """
    removed = []
    for ws in svc.list_workspaces():
        if ws.startswith(("bench-", "grade-")):
            svc.destroy_workspace(ws)
            removed.append(ws)
    return removed


def apply_solution(task: BenchmarkTask, svc: ToolService, workspace_id: str) -> None:
    repo = svc._manager.require(workspace_id)
    shutil.copytree(task.solution_dir, repo, dirs_exist_ok=True)


def _suite(svc: ToolService, ws: str, path: str, timeout: int) -> SuiteResult:
    r = svc.run_tests(ws, test_path=path, extra_args=["-q", "-rA"], timeout=timeout)
    s = summarise_pytest_output(r.stdout)
    return SuiteResult(exit_code=r.exit_code, collected=s["tests_found"], passed=s["tests_passed"],
                       failed=s["tests_failed"], timed_out=r.timed_out, failures=s["failures"][:20])


def grade(task: BenchmarkTask, svc: ToolService, workspace_id: str) -> Grade:
    """Grade a finished workspace without touching it."""
    grading_ws = svc.create_workspace(f"grade-{uuid.uuid4().hex[:12]}")
    try:
        target = svc._manager.require(grading_ws)
        shutil.copytree(svc._manager.require(workspace_id), target, dirs_exist_ok=True)
        # Drop anything the agents may have put under the hidden-test path.
        shutil.rmtree(target / HIDDEN_DIR, ignore_errors=True)
        shutil.copytree(task.hidden_dir, target / HIDDEN_DIR)
        hidden = _suite(svc, grading_ws, HIDDEN_DIR, task.timeout_seconds)
        visible = _suite(svc, grading_ws, "tests", task.timeout_seconds)
    finally:
        svc.destroy_workspace(grading_ws)
    hidden_ok = hidden.exit_code == 0 and hidden.collected > 0
    visible_ok = visible.exit_code in (0, 5)
    return Grade(
        task_id=task.id,
        task_success=hidden_ok and visible_ok,
        hidden=hidden,
        visible=visible,
        hidden_pass_rate=(hidden.passed / hidden.collected) if hidden.collected else None,
        regression=visible.failed > 0 or visible.exit_code not in (0, 5),
    )


def validate_task(task: BenchmarkTask, svc: ToolService) -> dict[str, Any]:
    """Benchmark self-check: starting repo fails hidden tests; reference solution passes everything."""
    ws = materialise(task, svc)
    try:
        before = grade(task, svc, ws)
        apply_solution(task, svc, ws)
        after = grade(task, svc, ws)
    finally:
        svc.destroy_workspace(ws)
    return {
        "task_id": task.id,
        "visible_pass_initially": not before.regression,
        "hidden_fail_initially": not before.task_success and (before.hidden.failed > 0 or before.hidden.timed_out),
        "solution_passes": after.task_success,
        "hidden_tests": after.hidden.collected,
    }
