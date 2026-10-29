"""Phase 10: benchmark validity, grading, experiment runner, statistics, export."""

from __future__ import annotations

import csv
import io
import json
import shutil

import pytest

from backend.agents.crew import SoftwareEngineeringCrew
from backend.db.registry import RunRegistry
from backend.evaluation.benchmark import grade, load_tasks, materialise, validate_task
from backend.evaluation.experiment import ExperimentConfig, plan_trials, run_experiment
from backend.evaluation.stats import (
    RAW_COLUMNS,
    load_rows,
    newcombe_diff,
    rows_to_csv,
    summarise_rows,
    summary_markdown,
    wilson,
)
from backend.tools.service import ToolService
from tests.test_agent_crew import ScriptedResponder, _make_settings


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    return ToolService(workspace_root=str(tmp_path_factory.mktemp("eval_ws")))


# ---------------------------------------------------------------------------
# Benchmark validity
# ---------------------------------------------------------------------------


def test_task_set_shape():
    tasks = load_tasks()
    assert len(tasks) == 10
    assert len({t.category for t in tasks}) >= 8
    for t in tasks:
        assert t.requirement and t.acceptance_criteria and t.hidden_dir.is_dir() and t.solution_dir.is_dir()


@pytest.mark.parametrize("task_id", [t.id for t in load_tasks()])
def test_every_task_is_valid(svc, task_id):
    """Starting repo: visible pass, hidden fail. Reference solution: everything passes."""
    report = validate_task(load_tasks(ids=[task_id])[0], svc)
    assert report["visible_pass_initially"] and report["hidden_fail_initially"] and report["solution_passes"], report


def test_hidden_tests_never_reach_agent_workspace(svc):
    task = load_tasks(ids=["feature_modulo"])[0]
    ws = materialise(task, svc)
    files = [f["path"] for f in svc.list_files(ws).data]
    assert not any("hidden" in f for f in files)
    grade(task, svc, ws)  # grading must not modify the agent workspace either
    assert [f["path"] for f in svc.list_files(ws).data] == files


def test_grading_ignores_planted_hidden_dir(svc):
    """An agent cannot pass by writing its own 'hidden' tests."""
    task = load_tasks(ids=["feature_modulo"])[0]
    ws = materialise(task, svc)
    svc.write_file(ws, "vexa_hidden_tests/test_fake.py", "def test_ok():\n    assert True\n")
    assert grade(task, svc, ws).task_success is False


def test_regression_detected(svc):
    task = load_tasks(ids=["feature_modulo"])[0]
    ws = materialise(task, svc)
    svc.write_file(ws, "calculator.py", "def modulo(a, b):\n    return a % b\n")  # deletes add/divide
    g = grade(task, svc, ws)
    assert g.regression and not g.task_success


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_wilson_reference_values():
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    assert wilson(0, 0) == (None, None)
    assert wilson(0, 10)[0] == 0.0


def test_newcombe_reference_values():
    # Newcombe (1998) Stat Med 17:873, example (a): 56/70 vs 48/80, method 10 → 0.2000 [0.0524, 0.3339]
    r = newcombe_diff(56, 70, 48, 80)
    assert r["diff"] == pytest.approx(0.2, abs=1e-9)
    assert r["low"] == pytest.approx(0.0524, abs=1e-4) and r["high"] == pytest.approx(0.3339, abs=1e-4)


def test_trial_plan_is_full_factorial_and_seeded():
    cfg = ExperimentConfig(name="x", architectures=["sequential", "blackboard"], prompt_variants=["baseline", "react"],
                           repeats=3, seed=7)
    a, b = plan_trials(cfg, ["t1", "t2"]), plan_trials(cfg, ["t1", "t2"])
    assert len(a) == 2 * 2 * 2 * 3 and len({t.key for t in a}) == len(a)
    assert [t.key for t in a] == [t.key for t in b]


def test_config_rejects_unknown_factors():
    with pytest.raises(ValueError):
        ExperimentConfig(name="x", architectures=["warp_drive"])
    with pytest.raises(ValueError):
        ExperimentConfig(name="x", prompt_variants=["vibes"])


# ---------------------------------------------------------------------------
# End-to-end experiment (mock agents + an oracle Coder for some architectures)
# ---------------------------------------------------------------------------

ORACLE_ARCHS = {"sequential", "blackboard"}


def _oracle_factory(svc_, settings, trial, task):
    """Coder applies the reference solution only for ORACLE_ARCHS, so grading must separate them."""
    def on_call(agent_id, _n):
        if agent_id == "Coder" and trial.architecture in ORACLE_ARCHS:
            ws = svc_._manager.require(current["ws"])
            shutil.copytree(task.solution_dir, ws, dirs_exist_ok=True)

    current = {}
    crew = SoftwareEngineeringCrew(tool_service=svc_, settings=_make_settings(), responder=None)
    original = crew.run_task

    def run_task(ws, requirement, mode, architecture, metadata=None):
        current["ws"] = ws
        from backend.agents.crew import MOCK_RESPONSES
        crew._responder = ScriptedResponder({k: [json.dumps(v)] for k, v in MOCK_RESPONSES.items()}, on_call)
        return original(ws, requirement, mode, architecture=architecture, metadata=metadata)

    crew.run_task = run_task
    return crew


@pytest.fixture(scope="module")
def experiment(tmp_path_factory, svc):
    reg = RunRegistry(f"sqlite:///{tmp_path_factory.mktemp('db') / 'exp.sqlite3'}")
    cfg = ExperimentConfig(name="oracle-pilot", tasks=["feature_modulo", "bugfix_pagination"],
                           architectures=["sequential", "hierarchical", "event_driven", "blackboard"],
                           repeats=2, tool_transport="direct")
    out = tmp_path_factory.mktemp("out")
    exp_id = run_experiment(cfg, registry=reg, svc=svc, crew_factory=_oracle_factory, out_dir=out)
    return exp_id, reg, out, cfg


def test_experiment_records_all_trials(experiment):
    exp_id, reg, out, cfg = experiment
    rows = load_rows(exp_id, reg)
    assert len(rows) == 2 * 4 * 2
    assert reg.get_experiment(exp_id)["status"] == "completed"
    assert reg.get_experiment(exp_id)["environment"]["packages"]["crewai"]
    lines = (out / exp_id / "raw_runs.jsonl").read_text().splitlines()
    assert len(lines) == len(rows)


def test_grading_separates_conditions(experiment):
    exp_id, reg, _, _ = experiment
    summary = summarise_rows(load_rows(exp_id, reg))
    rates = {c["architecture"]: c["task_success"]["rate"] for c in summary["conditions"]}
    assert rates == {"sequential": 1.0, "blackboard": 1.0, "hierarchical": 0.0, "event_driven": 0.0}
    seq_vs_hier = next(c for c in summary["architecture_comparisons"] if {c["a"], c["b"]} == {"hierarchical", "sequential"})
    assert abs(seq_vs_hier["success_diff_a_minus_b"]["diff"]) == 1.0
    cond = summary["conditions"][0]
    assert cond["repeatability"]["tasks_with_repeats"] == 2 and cond["repeatability"]["consistent_tasks"] == 2
    assert cond["estimated_cost_usd"]["runs_with_cost"] == 0  # mock: never a fabricated $0
    mock_rows = [r for r in load_rows(exp_id, reg) if r["architecture"] == "hierarchical"]
    assert all(r["verified"] and not r["task_success"] for r in mock_rows)  # self-report vs ground truth
    assert summary["conditions"][1]["verifier_false_positive"]["rate"] in (0.0, 1.0)


def test_resume_does_not_repeat_trials(experiment, svc):
    exp_id, reg, out, cfg = experiment
    before = len(load_rows(exp_id, reg))
    run_experiment(cfg, registry=reg, svc=svc, crew_factory=_oracle_factory, out_dir=out, resume=exp_id)
    assert len(load_rows(exp_id, reg)) == before


def test_exports(experiment):
    exp_id, reg, _, _ = experiment
    rows = load_rows(exp_id, reg)
    parsed = list(csv.DictReader(io.StringIO(rows_to_csv(rows))))
    assert len(parsed) == len(rows) and list(parsed[0]) == RAW_COLUMNS
    md = summary_markdown(summarise_rows(rows))
    assert "| sequential | baseline |" in md and "4/4 = 100.0%" in md


def test_api(client):
    assert isinstance(client.get("/experiments").json(), list)
    assert len(client.get("/experiments/benchmark/tasks").json()) == 10
    r = client.post("/experiments", json={"config": {"name": "x", "execution_mode": "real"}})
    assert r.status_code == 422 and "API key" in r.json()["detail"]  # validated before anything starts
    r = client.post("/experiments", json={"config": {"name": "x", "execution_mode": "real"}, "llm_api_key": "sk-test-abcdefgh"})
    assert r.status_code == 400 and "confirm_real_cost" in r.json()["detail"]
    assert client.get("/experiments/nope/summary").status_code == 404
