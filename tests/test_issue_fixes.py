"""
Regression tests for the six reported problems (reports, tracing/metrics/guardrails,
A2A/MCP, hierarchical routing, experiments, cross-cutting failures).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from backend.agents.config import AgentSettings, infer_provider
from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew
from backend.agents.reporting import build_run_report, render_markdown
from backend.tools.service import ToolService
from tests.fakes import ScriptedLLM, action, final

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture()
def ws(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path / "root"))
    ws_id = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws_id)), dirs_exist_ok=True)
    return svc, ws_id


def _mock(svc, **overrides):
    s = AgentSettings(tool_transport="direct", verifier_backend="crewai")
    for k, v in overrides.items():
        setattr(s, k, v)
    return SoftwareEngineeringCrew(tool_service=svc, settings=s)


# ---------------------------------------------------------------------------
# Issue 1 — reports
# ---------------------------------------------------------------------------


def test_preflight_failure_still_produces_a_report(ws, monkeypatch):
    svc, ws_id = ws
    for k in ("VEXA_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    r = _mock(svc).run_task(ws_id, "Add a modulo function", "real")
    assert r.status == AgentStatus.failed and "not configured" in r.errors[0]
    md = render_markdown(build_run_report(r))
    assert "**failed**" in md and "not configured" in md


def test_api_real_without_key_is_reportable(client, monkeypatch):
    for k in ("VEXA_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ws = client.post("/workspaces", json={}).json()["workspace_id"]
    rid = client.post("/agent-runs/async", json={"workspace_id": ws, "requirement": "Add a modulo function",
                                                 "execution_mode": "real"}).json()["run_id"]
    for _ in range(100):
        if client.get(f"/agent-runs/{rid}").json()["status"] != "running":
            break
        time.sleep(0.05)
    rep = client.get(f"/agent-runs/{rid}/report")
    assert rep.status_code == 200 and rep.json()["status"] == "failed"
    assert any("not configured" in e for e in rep.json()["errors"])


def test_report_contains_real_diff_and_provenance(ws):
    svc, ws_id = ws
    original = svc.read_file(ws_id, "src/calculator.py").data["content"]
    llm = ScriptedLLM({
        "Requirements Analyst": [final({"task_summary": "Add modulo", "acceptance_criteria": ["modulo(10, 3) == 1"]})],
        "Project Analyst": [final({"total_files": 4, "project_context": "calculator"})],
        "Implementation Planner": [final({"objective": "Add modulo", "steps": [
            {"step_number": 1, "description": "add", "files_affected": ["src/calculator.py"], "action": "patch"}]})],
        "Software Engineer": [action("write_file", {"path": "src/calculator.py",
                                                    "content": original + "\n\ndef modulo(a, b):\n    return a % b\n"}),
                              final({"files_changed": [{"path": "src/calculator.py", "action": "patched"}]})],
        "Requirements Verifier": [final({"verified": True, "requirements_satisfied": ["modulo(10, 3) == 1"]})],
    })
    s = AgentSettings(agent_max_iter=4, tool_transport="direct", verifier_backend="crewai")
    r = SoftwareEngineeringCrew(tool_service=svc, settings=s, llm=llm).run_task(ws_id, "Add a modulo function", "real")
    report = build_run_report(r)
    change = next(c for c in report.code_changes if c.path == "src/calculator.py")
    assert change.change == "modified" and change.lines_added == 4 and change.lines_removed == 0 and "+def modulo(a, b):" in change.diff
    assert change.written_by == ["Coder:write_file"]
    md = render_markdown(report)
    assert "```diff" in md and "## Implementation plan" in md and "## Agents" in md
    assert report.agents and all(a.framework for a in report.agents)


# ---------------------------------------------------------------------------
# Issue 2 — tracing, per-agent metrics, guardrails
# ---------------------------------------------------------------------------


def test_guardrail_decisions_recorded_in_normal_run(ws):
    svc, ws_id = ws
    r = _mock(svc).run_task(ws_id, "Add a modulo function")
    decisions = {(g["rule"], g["decision"]) for g in r.guardrail_events}
    assert ("G1", "allowed") in decisions                       # requirement screening ran
    assert ("G2", "allowed") in decisions                       # tool calls authorised
    assert ("G6", "sanitized") in decisions                     # tool output spotlighted
    assert ("G8", "allowed") in decisions                       # every output schema-checked
    assert all(g["run_id"] == r.run_id and g["at"] and g["rule_name"] for g in r.guardrail_events)


def test_trace_has_state_and_guardrail_events_and_test_attributes(ws):
    svc, ws_id = ws
    r = _mock(svc).run_task(ws_id, "Add a modulo function")
    names = {e["name"] for s in r.trace["spans"] for e in s["events"]}
    assert {"state.write", "guardrail.allowed", "guardrail.sanitized"} <= names
    tester = next(s for s in r.trace["spans"] if s["kind"] == "agent" and s["attributes"]["vexa.agent"] == "Tester")
    assert tester["attributes"]["vexa.verdict"] == "passed" and tester["attributes"]["vexa.tests_passed"] > 0
    origins = {s["attributes"].get("vexa.origin") for s in r.trace["spans"] if s["kind"] == "tool"}
    assert origins == {"scripted", "orchestrator"}


def test_per_agent_metrics_mark_unavailable_tokens(ws):
    svc, ws_id = ws
    r = _mock(svc).run_task(ws_id, "Add a modulo function")
    m = r.agent_metrics["Planner"]
    assert m["input_tokens"] is None and m["usage_available"] is False and "no LLM calls" in m["usage_note"]
    assert m["first_started_at"] and m["last_finished_at"] and m["status"] == "completed"
    assert m["framework"] == "crewai" and m["tool_calls"] >= 1
    assert m["estimated_cost_usd"] is None


def test_real_mode_usage_attributed_per_agent(ws):
    svc, ws_id = ws
    llm = ScriptedLLM({
        "Requirements Analyst": [final({"task_summary": "x", "acceptance_criteria": ["tests pass"]})],
        "Project Analyst": [final({"total_files": 1, "project_context": "c"})],
        "Implementation Planner": [final({"objective": "o", "steps": [{"step_number": 1, "description": "d", "action": "verify"}]})],
        "Software Engineer": [final({"files_changed": []})],
        "Requirements Verifier": [final({"verified": True})],
    })
    s = AgentSettings(agent_max_iter=3, tool_transport="direct", verifier_backend="crewai",
                      llm_input_cost_per_1m=1.0, llm_output_cost_per_1m=2.0)
    r = SoftwareEngineeringCrew(tool_service=svc, settings=s, llm=llm).run_task(ws_id, "Keep tests green", "real")
    m = r.agent_metrics["Planner"]
    assert m["usage_available"] and m["input_tokens"] > 0 and m["estimated_cost_usd"] > 0
    assert r.agent_metrics["Tester"]["input_tokens"] is None  # no LLM call needed: tests passed


# ---------------------------------------------------------------------------
# Issue 3 — MCP and A2A visible in normal runs
# ---------------------------------------------------------------------------


def test_mock_run_uses_mcp_tools(ws):
    svc, ws_id = ws
    r = _mock(svc, tool_transport="mcp").run_task(ws_id, "Add a modulo function")
    assert {m["name"]: m["status"] for m in r.mcp_servers}["vexa-workspace"] == "connected"
    mcp_spans = [s for s in r.trace["spans"] if s["attributes"].get("vexa.transport") == "mcp"]
    assert {s["attributes"]["vexa.tool"] for s in mcp_spans} >= {"inspect_project", "list_files", "search_code"}
    assert any(c["kind"] == "message" and c["target"] == "mcp:vexa-workspace" for c in r.coordination_log)


def test_default_verifier_is_adk_over_embedded_a2a(ws):
    svc, ws_id = ws
    r = _mock(svc, verifier_backend="adk_a2a").run_task(ws_id, "Add a modulo function")
    v = r.verification_result
    assert r.status == AgentStatus.partial, r.errors  # mock agents changed nothing (audit fix)
    assert v.verified
    assert v.backend == "adk_a2a" and v.remote["state"] == "TASK_STATE_COMPLETED" and v.remote["agent"] == "vexa_verifier"
    assert r.agent_metrics["Verifier"]["framework"] == "google-adk"
    span = next(s for s in r.trace["spans"] if s["attributes"].get("vexa.transport") == "a2a")
    assert span["status"] != "error"
    assert AgentSettings.model_fields["verifier_backend"].default == "adk_a2a"


def test_embedded_credentials_never_cross_a2a():
    from backend.a2a_bridge.embedded import register_credentials, release_credentials, resolve_credentials
    h = register_credentials("groq/x", "secret-key-123")
    assert "secret" not in h and resolve_credentials(h) == ("groq/x", "secret-key-123")
    release_credentials(h)
    assert resolve_credentials(h) is None


# ---------------------------------------------------------------------------
# Issue 6 — provider inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model,configured,expected", [
    ("groq/llama-3.3-70b-versatile", "openai", "groq"), ("gpt-4o-mini", "openai", "openai"),
    ("gemini/gemini-2.0-flash", None, "gemini"), ("anthropic/claude-x", "openai", "anthropic"),
])
def test_infer_provider(model, configured, expected):
    assert infer_provider(model, configured) == expected
