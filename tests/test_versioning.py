"""Prompt versioning, configuration fingerprints, comparability warnings and reruns."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from backend.agents.config import AgentSettings
from backend.agents.crew import SoftwareEngineeringCrew, config_fingerprint
from backend.agents.prompt_variants import PromptSet, get_prompt_set
from backend.db.registry import get_registry
from backend.evaluation.stats import summarise_rows
from backend.tools.service import ToolService

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _run(tmp_path, **settings):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    s = AgentSettings(tool_transport="direct", verifier_backend="crewai", **settings)
    return SoftwareEngineeringCrew(tool_service=svc, settings=s).run_task(ws, "Keep tests passing", "mock")


def test_run_records_prompt_versions_config_and_fingerprint(tmp_path):
    r = _run(tmp_path)
    ps = get_prompt_set("baseline")
    assert r.prompt_version == ps.version and r.prompt_versions == ps.agent_versions
    assert set(r.prompt_versions) >= {"MANAGER", "CODER", "VERIFIER"}
    assert r.config["prompts"]["version"] == ps.version and r.config["guardrails"]["version"]
    assert r.config_fingerprint == config_fingerprint(r.config)
    assert get_registry().get_archived_prompt(ps.version)["texts"] == ps.texts  # exact texts kept


def test_fingerprint_changes_only_with_relevant_settings(tmp_path):
    a, b = _run(tmp_path / "a"), _run(tmp_path / "b")
    c = _run(tmp_path / "c", debug_max_iter=1)
    assert a.config_fingerprint == b.config_fingerprint != c.config_fingerprint


def test_changing_one_agent_prompt_changes_only_that_agent_hash():
    base = get_prompt_set("baseline")
    texts = dict(base.texts)
    texts["MANAGER_TASK"] += "\n(edited)"
    edited = PromptSet.from_archive("baseline", texts)
    diff = {k for k in base.agent_versions if base.agent_versions[k] != edited.agent_versions[k]}
    assert diff == {"MANAGER"} and edited.version != base.version


def test_rerun_with_archived_prompt_version(tmp_path):
    texts = dict(get_prompt_set("baseline").texts)
    texts["CODER_TASK"] += "\n(historical wording)"
    old = PromptSet.from_archive("baseline", texts)
    get_registry().archive_prompt_set(old)
    r = _run(tmp_path, prompt_version_pin=old.version)
    assert r.prompt_version == old.version and r.status.value != "failed"


def test_unarchived_prompt_version_fails_honestly(tmp_path):
    r = _run(tmp_path, prompt_version_pin="0123456789abcdef")
    assert r.status.value == "failed" and "not in the prompt archive" in r.errors[0]


def _row(arch, version, fp, cfg, success=True):
    return {"architecture": arch, "prompt_variant": "baseline", "prompt_version": version, "model_condition": "m",
            "config_fingerprint": fp, "run_config": cfg, "task_id": "t", "task_success": success, "verified": success,
            "regression": False, "status": "success", "timed_out": False, "hidden_pass_rate": 1.0,
            "duration_ms": 1.0, "debug_iterations": 0, "agent_invocations": 1, "llm_calls": 0, "tool_calls": 0,
            "usage_available": False, "total_tokens": 0, "estimated_cost_usd": None, "guard_blocked": 0,
            "guard_flagged": 0, "agent_metrics": {}}


def test_mixed_prompt_versions_are_not_merged_silently():
    cfg = {"budgets": {"debug_max_iter": 3}, "prompts": {"variant": "baseline"}}
    s = summarise_rows([_row("sequential", "v1", "f1", cfg), _row("sequential", "v2", "f2", cfg)])
    cond = s["conditions"][0]
    assert cond["prompt_versions"] == ["v1", "v2"] and cond["comparable"] is False
    assert any("same variant, different texts" in w for w in s["warnings"])


def test_architecture_comparison_warns_on_other_changed_variables():
    s = summarise_rows([_row("sequential", "v1", "f1", {"budgets": {"debug_max_iter": 3}, "architecture": "sequential"}),
                        _row("hierarchical", "v1", "f2", {"budgets": {"debug_max_iter": 1},
                                                          "architecture": "hierarchical"})])
    comp = s["architecture_comparisons"][0]
    assert comp["comparable"] is False and any("budgets.debug_max_iter" in w for w in comp["warnings"])
    clean = summarise_rows([_row("sequential", "v1", "f1", {"architecture": "sequential", "x": 1}),
                            _row("hierarchical", "v1", "f2", {"architecture": "hierarchical", "x": 1})])
    assert clean["comparable"] is True  # the architecture itself is the experimental variable


def test_legacy_rows_without_config_remain_usable():
    s = summarise_rows([_row("sequential", "v1", None, None), _row("sequential", "v1", "f1", {"x": 1})])
    assert s["conditions"][0]["runs"] == 2
    assert any("predate configuration fingerprints" in w for w in s["warnings"])


def test_rerun_endpoint_keeps_original_and_pins_prompts(client):
    cfg = {"name": "orig", "execution_mode": "mock", "tasks": ["feature_modulo"], "architectures": ["sequential"],
           "prompt_variants": ["baseline"], "repeats": 1}
    eid = client.post("/experiments", json={"config": cfg}).json()["experiment_id"]
    for _ in range(300):
        if client.get(f"/experiments/{eid}").json()["status"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    original_runs = client.get(f"/experiments/{eid}/runs").json()
    r = client.post(f"/experiments/{eid}/rerun", json={})
    assert r.status_code == 202, r.text
    new_id = r.json()["experiment_id"]
    for _ in range(300):
        if client.get(f"/experiments/{new_id}").json()["status"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    new = client.get(f"/experiments/{new_id}").json()
    assert new["config"]["rerun_of"] == eid
    assert new["config"]["prompt_version_pins"] == {"baseline": original_runs[0]["prompt_version"]}
    new_runs = client.get(f"/experiments/{new_id}/runs").json()
    assert new_runs[0]["config_fingerprint"] and new_runs[0]["prompt_version"] == original_runs[0]["prompt_version"]
    assert client.get(f"/experiments/{eid}/runs").json() == original_runs  # original untouched
    pv = client.get("/experiments/prompt-versions").json()
    assert any(a["version"] == original_runs[0]["prompt_version"] for a in pv["archived"])


def test_prompt_variants_endpoint_returns_agent_versions(client):
    r = client.get("/agent-runs/prompt-variants")
    assert r.status_code == 200
    assert all(len(v["agent_versions"]) == 8 and len(v["version"]) == 16 for v in r.json())
