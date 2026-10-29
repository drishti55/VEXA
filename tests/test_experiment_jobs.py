"""Issue 5: experiment configuration, background jobs, progress, cancel/resume, persistence."""

from __future__ import annotations

import time

import pytest

from backend.db.registry import get_registry

MOCK = {"name": "jobs-test", "execution_mode": "mock", "tasks": ["feature_modulo", "bugfix_pagination"],
        "architectures": ["sequential", "hierarchical"], "prompt_variants": ["baseline", "react"], "repeats": 1,
        "tool_transport": "direct", "verifier_backend": "crewai"}


def _wait(client, exp_id, states=("completed", "cancelled", "failed", "interrupted"), timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        exp = client.get(f"/experiments/{exp_id}").json()
        if exp["status"] in states:
            return exp
        time.sleep(0.2)
    raise AssertionError(f"experiment {exp_id} stuck in {exp['status']}")


def test_options_only_lists_real_choices(client):
    o = client.get("/experiments/options").json()
    assert len(o["tasks"]) == 10
    assert {a["name"] for a in o["architectures"]} == {"sequential", "hierarchical", "event_driven", "blackboard"}
    assert {v["name"] for v in o["prompt_variants"]} == {"baseline", "react", "few_shot", "minimal_persona"}
    assert o["rag"]["available"] is False
    assert "api_key" not in str(o["configured_model"]).replace("api_key_configured", "")


def test_validate(client):
    v = client.post("/experiments/validate", json={"config": MOCK}).json()
    assert v["valid"] and v["total_trials"] == 2 * 2 * 2 and v["warnings"]
    bad = client.post("/experiments/validate", json={"config": {**MOCK, "tasks": ["nope"]}}).json()
    assert not bad["valid"] and "nope" in bad["errors"][0]
    assert client.post("/experiments/validate", json={"config": {**MOCK, "architectures": ["warp"]}}).status_code == 422


def test_start_returns_id_runs_in_background_and_persists(client):
    r = client.post("/experiments", json={"config": MOCK})
    assert r.status_code == 202
    body = r.json()
    exp_id = body["experiment_id"]
    assert body["total_trials"] == 8
    exp = _wait(client, exp_id)
    assert exp["status"] == "completed" and exp["completed_trials"] == 8 and exp["total_trials"] == 8
    runs = client.get(f"/experiments/{exp_id}/runs").json()
    assert len(runs) == 8 and {r["prompt_variant"] for r in runs} == {"baseline", "react"}
    rid = runs[0]["run_id"]
    assert client.get(f"/agent-runs/{rid}/report").status_code == 200  # per-run report reachable
    assert client.get(f"/agent-runs/{rid}/trace").json()["spans"]
    summary = client.get(f"/experiments/{exp_id}/summary").json()
    assert summary["prompt_comparisons"] and summary["architecture_comparisons"]
    md = client.get(f"/experiments/{exp_id}/export?format=md").text
    assert "# VEXA experiment report" in md and "## Runs" in md and "Prompt-strategy comparisons" in md


def test_cancel_then_resume(client):
    cfg = {**MOCK, "name": "cancel-test", "repeats": 3}
    exp_id = client.post("/experiments", json={"config": cfg}).json()["experiment_id"]
    time.sleep(0.5)
    client.post(f"/experiments/{exp_id}/cancel")
    exp = _wait(client, exp_id)
    if exp["status"] == "completed":
        pytest.skip("experiment finished before cancel took effect")
    assert exp["status"] == "cancelled" and exp["completed_trials"] < 24
    assert client.post(f"/experiments/{exp_id}/resume").status_code == 202
    exp = _wait(client, exp_id, states=("completed",))
    assert exp["completed_trials"] == 24
    keys = [r["grading"]["trial_key"] for r in get_registry().list_runs(experiment_id=exp_id, limit=1000)]
    assert len(keys) == len(set(keys)) == 24  # no trial was run twice


def test_duplicate_start_rejected_while_running(client):
    cfg = {**MOCK, "name": "dup-test", "repeats": 3}
    first = client.post("/experiments", json={"config": cfg}).json()["experiment_id"]
    second = client.post("/experiments", json={"config": cfg})
    assert second.status_code == 409 and first in second.json()["detail"]
    client.post(f"/experiments/{first}/cancel")
    _wait(client, first)


def test_interrupted_experiments_are_detected():
    reg = get_registry()
    reg.create_experiment("exp-orphan", "orphan", {"name": "orphan"}, {}, status="running")
    assert "exp-orphan" in reg.mark_interrupted(set())
    assert reg.get_experiment("exp-orphan")["status"] == "interrupted"


def test_honest_labels_in_mock_experiments(client):
    exp_id = client.post("/experiments", json={"config": {**MOCK, "name": "labels", "architectures": ["sequential"],
                                                          "prompt_variants": ["baseline"]}}).json()["experiment_id"]
    _wait(client, exp_id)
    s = client.get(f"/experiments/{exp_id}/summary").json()
    assert {c["model"] for c in s["conditions"]} == {"mock:scripted"}  # not a model that was never called
    md = client.get(f"/experiments/{exp_id}/export?format=md").text
    assert "n/a (0 runs with usage)" in md and "| 0 (0) |" not in md


def test_resume_clears_previous_error():
    reg = get_registry()
    reg.create_experiment("exp-err", "err", {"name": "err"}, {}, status="running")
    reg.mark_interrupted(set())
    assert reg.get_experiment("exp-err")["error"]
    reg.set_experiment_status("exp-err", "running")
    assert reg.get_experiment("exp-err")["error"] is None
