"""Phase 1: structured outputs and the final run report."""

from __future__ import annotations

import json

import pytest

from backend.agents.contracts import AgentStatus
from backend.agents.crew import (
    parse_coding_result,
    parse_implementation_plan,
    parse_requirement_analysis,
    parse_verification_result,
)
from backend.agents.reporting import build_run_report, render_markdown
from backend.agents.schemas import (
    ImplementationPlanOutput,
    RequirementAnalysisOutput,
    extract_json_object,
    make_guardrail,
    validate_output,
)


class TestExtraction:
    def test_prose_around_json(self):
        assert extract_json_object('Sure! {"a": 1} hope that helps {"b": 2}') == {"a": 1}

    def test_braces_in_prose_before_json(self):
        assert extract_json_object('use {curly} then {"a": {"b": 1}}') == {"a": {"b": 1}}

    def test_no_json(self):
        assert extract_json_object("nothing here") is None


class TestSchemaValidation:
    def test_missing_acceptance_criteria_is_invalid(self):
        out, errs = validate_output(json.dumps({"task_summary": "x"}), RequirementAnalysisOutput)
        assert out is None and any("acceptance_criteria" in e for e in errs)

    def test_bad_step_action_is_invalid(self):
        raw = json.dumps({"objective": "o", "steps": [{"step_number": 1, "description": "d", "action": "patch | write"}]})
        out, errs = validate_output(raw, ImplementationPlanOutput)
        assert out is None and any("action" in e for e in errs)

    def test_single_string_coerced_to_list(self):
        out, _ = validate_output(json.dumps({"task_summary": "x", "acceptance_criteria": "works"}), RequirementAnalysisOutput)
        assert out.acceptance_criteria == ["works"]

    def test_invalid_output_marked_not_silently_defaulted(self):
        r = parse_requirement_analysis(json.dumps({"task_summary": "x"}), "req", 1.0)
        assert r.output_valid is False and r.status == AgentStatus.partial
        assert r.validation_errors

    def test_invalid_verifier_is_never_a_pass(self):
        r = parse_verification_result('{"verified": "maybe?"}', 1.0)
        assert r.verified is False and r.status == AgentStatus.failed and r.output_valid is False

    def test_plan_valid(self):
        raw = json.dumps({"objective": "o", "steps": [{"step_number": 1, "description": "d", "action": "write"}]})
        assert parse_implementation_plan(raw, 1.0).output_valid

    def test_coder_bad_action_flagged(self):
        r = parse_coding_result(json.dumps({"files_changed": [{"path": "a.py", "action": "frobbed"}]}), 1.0)
        assert r.output_valid is False

    def test_guardrail_contract(self):
        g = make_guardrail(RequirementAnalysisOutput)

        class Out:
            raw = '{"task_summary": "x", "acceptance_criteria": ["y"], "extra": 1}'

        ok, value = g(Out())
        assert ok and json.loads(value)["acceptance_criteria"] == ["y"] and "extra" not in value
        Out.raw = "nope"
        ok, value = g(Out())
        assert not ok and "JSON Schema" in value


@pytest.fixture()
def mock_result(tmp_path):
    import shutil
    from pathlib import Path

    from backend.agents.crew import SoftwareEngineeringCrew
    from backend.tools.service import ToolService

    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(Path(__file__).parent / "fixtures" / "sample_project"),
                    str(svc._manager.require(ws)), dirs_exist_ok=True)
    return SoftwareEngineeringCrew(tool_service=svc).run_task(ws, "Add a modulo function", "mock")


class TestRunReport:
    def test_report_reflects_run(self, mock_result):
        report = build_run_report(mock_result)
        assert report.status == "partial" and any("capped" in l for l in report.limitations)
        assert report.tests.verdict_source == "sandbox_exit_code" and report.tests.passed
        assert [c.status for c in report.acceptance_criteria] == ["satisfied"]
        assert report.usage.estimated_cost_usd.value is None and report.usage.estimated_cost_usd.unavailable_reason
        assert {a.agent for a in report.agents} >= {"RequirementAnalyst", "Verifier", "Tester"}
        json.loads(report.model_dump_json())  # serialisable

    def test_markdown_rendering(self, mock_result):
        md = render_markdown(build_run_report(mock_result))
        assert md.startswith("# VEXA run")
        assert "| Existing test suite passes | satisfied |" in md
        assert "Tokens in / out / total: n/a (mock mode: no LLM calls)" in md
        for section in ("## Execution sequence", "## Code changes", "## Guardrails", "## Agents", "## Limitations"):
            assert section in md

    def test_report_endpoint(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        client.post(f"/workspaces/{ws}/write", json={"path": "test_ok.py", "content": "def test_ok():\n    assert True\n"})
        run = client.post("/agent-runs", json={"workspace_id": ws, "requirement": "Keep tests green please"}).json()
        r = client.get(f"/agent-runs/{run['run_id']}/report")
        assert r.status_code == 200 and r.json()["status"] == "partial"
        md = client.get(f"/agent-runs/{run['run_id']}/report?format=md")
        assert md.headers["content-type"].startswith("text/markdown")
