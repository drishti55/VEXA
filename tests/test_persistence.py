"""SQLite persistence: restart recovery, interrupted runs, transactions, concurrency and schema migration."""

from __future__ import annotations

import shutil
import sqlite3
import threading
from pathlib import Path

import pytest

from backend.agents.config import AgentSettings
from backend.agents.contracts import AgentStatus, RunResult
from backend.agents.crew import SoftwareEngineeringCrew
from backend.agents.reporting import build_run_report, render_markdown
from backend.db.models import Span
from backend.db.registry import RunRegistry
from backend.tools.service import ToolService

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'vexa.sqlite3'}"


def _mock_run(tmp_path, arch="hierarchical"):
    svc = ToolService(workspace_root=str(tmp_path / "ws"))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    return SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(tool_transport="direct",
                                                                            verifier_backend="crewai")).run_task(
        ws, "Keep tests passing", "mock", architecture=arch, metadata={"task_category": "feature"})


def test_everything_survives_a_restart(tmp_path, db_url):
    r = _mock_run(tmp_path)
    reg = RunRegistry(db_url)
    reg.create_experiment("exp-1", "persist", {"architectures": ["hierarchical"]}, total_trials=1)
    reg.save_run(r, experiment_id="exp-1", task_id="t1", repeat_index=0,
                 grading={"task_success": False, "hidden_pass_rate": 0.5})
    reg.engine.dispose()

    again = RunRegistry(db_url)  # a new process opening the same file
    stored = again.get_run(r.run_id)
    row = again.get_run_row(r.run_id)
    assert stored.model_dump(mode="json") == r.model_dump(mode="json")  # full result incl. trace and state
    assert row["config_fingerprint"] == r.config_fingerprint and row["prompt_versions"] == r.prompt_versions
    assert row["run_config"]["architecture"] == "hierarchical" and row["grading"]["hidden_pass_rate"] == 0.5
    assert again.get_experiment("exp-1")["run_count"] == 1
    assert "RequirementAnalyst" in {m["agent"] for m in again.agent_metrics([r.run_id])}
    with again.session() as s:
        assert s.query(Span).filter(Span.run_id == r.run_id).count() == len(r.trace["spans"])
    md = render_markdown(build_run_report(stored))  # the report is regenerated from storage alone
    assert r.run_id in md and "deterministic mock policy" in md


def test_interrupted_run_is_recorded_and_others_untouched(tmp_path, db_url):
    done = _mock_run(tmp_path)
    reg = RunRegistry(db_url)
    reg.save_run(done)
    reg.record_run_started(RunResult(run_id="lost-1", workspace_id="w", requirement="r", architecture="sequential",
                                     execution_mode="mock", status=AgentStatus.failed, errors=["Run in progress"]))
    reg.engine.dispose()

    restarted = RunRegistry(db_url)
    assert restarted.mark_interrupted_runs() == ["lost-1"]
    lost = restarted.get_run_row("lost-1")
    assert lost["status"] == "interrupted"
    assert "Interrupted" in restarted.get_run("lost-1").errors[-1]
    assert restarted.get_run(done.run_id).model_dump(mode="json") == done.model_dump(mode="json")
    assert restarted.mark_interrupted_runs() == []  # idempotent


def test_failed_write_rolls_back_and_keeps_previous_data(tmp_path, db_url, monkeypatch):
    r = _mock_run(tmp_path)
    reg = RunRegistry(db_url)
    reg.save_run(r)
    before = reg.get_run(r.run_id).model_dump(mode="json")
    broken = r.model_copy(update={"errors": ["second write"]})

    def boom(_result):
        raise RuntimeError("disk full (simulated)")
    monkeypatch.setattr(RunRegistry, "_children", staticmethod(boom))
    with pytest.raises(RuntimeError):
        reg.save_run(broken)
    assert reg.get_run(r.run_id).model_dump(mode="json") == before  # transaction rolled back as a whole


def test_concurrent_writers(tmp_path, db_url):
    base = _mock_run(tmp_path, "sequential")
    reg = RunRegistry(db_url)
    errors: list[str] = []

    def write(i):
        try:
            other = RunRegistry(db_url)  # separate engine = separate connection, like separate threads/jobs
            other.save_run(base.model_copy(update={"run_id": f"run-{i}"}))
        except Exception as exc:
            errors.append(repr(exc))
    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert {f"run-{i}" for i in range(8)} <= {r["run_id"] for r in reg.list_runs(limit=100)}


def test_legacy_database_is_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)  # a database created before fingerprints / prompt archive existed
    con.executescript("""
        CREATE TABLE runs (run_id VARCHAR(64) PRIMARY KEY, experiment_id VARCHAR(64), task_id VARCHAR(128),
            repeat_index INTEGER, architecture VARCHAR(64), prompt_variant VARCHAR(64), prompt_version VARCHAR(64),
            execution_mode VARCHAR(16), provider VARCHAR(64), model VARCHAR(200), sandbox_backend VARCHAR(32),
            tool_transport VARCHAR(16), verifier_backend VARCHAR(16), workspace_id VARCHAR(200), requirement TEXT,
            status VARCHAR(16), started_at DATETIME, finished_at DATETIME, duration_ms FLOAT, tests_passed BOOLEAN,
            no_tests BOOLEAN, tests_found INTEGER, tests_failed INTEGER, verified BOOLEAN, debug_iterations INTEGER,
            test_attempts INTEGER, files_changed INTEGER, error_count INTEGER, usage_available BOOLEAN,
            input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, estimated_cost_usd FLOAT,
            cost_basis VARCHAR(200), llm_calls INTEGER, tool_calls INTEGER, agent_invocations INTEGER,
            trace_id VARCHAR(32), grading JSON, result_json JSON, created_at DATETIME);
        INSERT INTO runs (run_id, architecture, prompt_version, execution_mode, workspace_id, requirement, status,
            started_at, duration_ms, result_json)
        VALUES ('old-run', 'sequential', 'deadbeefdeadbeef', 'mock', 'w', 'r', 'success', '2026-10-01 10:00:00', 1.0,
            '{"run_id": "old-run", "workspace_id": "w", "requirement": "r", "status": "success"}');
    """)
    con.commit()
    con.close()

    reg = RunRegistry(f"sqlite:///{path}")
    row = reg.get_run_row("old-run")
    assert row["prompt_version"] == "deadbeefdeadbeef"  # historical hash preserved, never rewritten
    assert row["config_fingerprint"] is None and row["run_config"] is None  # honest: predates fingerprints
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(runs)")}
    assert {"config_fingerprint", "run_config", "prompt_versions"} <= cols
    assert reg.list_prompt_versions() == []  # new table created, empty
