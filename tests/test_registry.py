"""Phase 5: persistence and the run registry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.agents.crew import SoftwareEngineeringCrew
from backend.db.models import AgentRun, CoordinationRow, Span, StateAccessRow, StateEntryRow
from backend.db.registry import RunRegistry
from backend.tools.service import ToolService

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture()
def results(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path / "ws"))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    crew = SoftwareEngineeringCrew(tool_service=svc)
    return [crew.run_task(ws, "Add a modulo function", architecture=a) for a in ("sequential", "blackboard")]


@pytest.fixture()
def registry(tmp_path):
    return RunRegistry(f"sqlite:///{tmp_path / 'reg.sqlite3'}")


def test_roundtrip_is_lossless(registry, results):
    r = results[0]
    registry.save_run(r)
    back = registry.get_run(r.run_id)
    assert back.model_dump(mode="json") == r.model_dump(mode="json")


def test_child_rows(registry, results):
    r = results[1]
    registry.save_run(r)
    with registry.session() as s:
        def count(model):
            return s.scalar(select(func.count()).select_from(model).where(model.run_id == r.run_id))
        assert count(Span) == len(r.trace["spans"]) > 0
        assert count(StateEntryRow) == len(r.state["entries"])
        assert count(StateAccessRow) == len(r.state["access_log"])
        assert count(CoordinationRow) == len(r.coordination_log)
        assert count(AgentRun) == len(r.agent_metrics)


def test_resave_is_idempotent(registry, results):
    r = results[0]
    registry.save_run(r)
    registry.save_run(r)
    with registry.session() as s:
        assert s.scalar(select(func.count()).select_from(Span).where(Span.run_id == r.run_id)) == len(r.trace["spans"])


def test_filters_and_summary(registry, results):
    for r in results:
        registry.save_run(r, task_id="T1")
    rows = registry.list_runs(architecture="blackboard")
    assert len(rows) == 1 and rows[0]["architecture"] == "blackboard"
    assert rows[0]["tests_passed"] is True and rows[0]["estimated_cost_usd"] is None
    assert "result_json" not in rows[0]
    assert len(registry.list_runs(task_id="T1")) == 2


def test_unavailable_usage_is_not_reported_as_zero(registry, results):
    from backend.evaluation.stats import load_rows, rows_to_csv
    r = results[0]  # mock run: the provider reported no usage
    assert r.usage_available is False
    registry.create_experiment("exp1", "pilot", {}, {})
    registry.save_run(r, experiment_id="exp1")
    row = registry.get_run_row(r.run_id)
    assert row["input_tokens"] is None and row["output_tokens"] is None and row["total_tokens"] is None
    csv_row = dict(zip(*[line.split(",") for line in rows_to_csv(load_rows("exp1", registry)).splitlines()[:2]]))
    assert csv_row["usage_available"] == "False" and csv_row["total_tokens"] == "" and csv_row["input_tokens"] == ""


def test_experiments(registry, results):
    registry.create_experiment("exp1", "pilot", {"architectures": ["sequential"]}, {"python": "3.11"})
    registry.save_run(results[0], experiment_id="exp1", task_id="T1", repeat_index=0)
    registry.finish_experiment("exp1")
    exp = registry.get_experiment("exp1")
    assert exp["status"] == "completed" and exp["run_count"] == 1
    assert registry.list_runs(experiment_id="exp1")[0]["repeat_index"] == 0


def test_survives_restart(tmp_path, results):
    url = f"sqlite:///{tmp_path / 'persist.sqlite3'}"
    RunRegistry(url).save_run(results[0])
    assert RunRegistry(url).get_run(results[0].run_id) is not None


def test_api_serves_completed_runs_from_db(client):
    from backend.api import agent_runs

    ws = client.post("/workspaces", json={}).json()["workspace_id"]
    client.post(f"/workspaces/{ws}/write", json={"path": "test_ok.py", "content": "def test_ok():\n    assert True\n"})
    run_id = client.post("/agent-runs", json={"workspace_id": ws, "requirement": "Keep the tests green"}).json()["run_id"]
    assert run_id not in agent_runs._run_store  # evicted from memory after persisting
    assert client.get(f"/agent-runs/{run_id}").json()["status"] == "partial"  # mock run, no code changes
    assert client.get(f"/agent-runs/{run_id}/trace").json()["finished"] is True
    rows = client.get("/agent-runs/registry/runs", params={"architecture": "sequential"}).json()
    assert any(r["run_id"] == run_id for r in rows)
    assert any(r["run_id"] == run_id for r in client.get("/agent-runs").json()["runs"])


def test_sse_stream_for_finished_run(client):
    ws = client.post("/workspaces", json={}).json()["workspace_id"]
    client.post(f"/workspaces/{ws}/write", json={"path": "test_ok.py", "content": "def test_ok():\n    assert True\n"})
    run_id = client.post("/agent-runs", json={"workspace_id": ws, "requirement": "Keep the tests green"}).json()["run_id"]
    with client.stream("GET", f"/agent-runs/{run_id}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: snapshot" in body and body.rstrip().endswith("data: {}")
    snapshot = json.loads(body.split("event: snapshot\ndata: ")[1].split("\n\n")[0])
    assert snapshot["status"] == "partial"
