"""Phase 4: callbacks, tracing, redaction, provenance."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest

from backend.agents.config import AgentSettings
from backend.agents.crew import SoftwareEngineeringCrew
from backend.observability.redaction import REDACTED, RedactingFilter, redact, redact_text, register_secret
from backend.tools.service import ToolService
from tests.fakes import ScriptedLLM, action, final

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture()
def ws(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path / "root"))
    ws_id = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws_id)), dirs_exist_ok=True)
    return svc, ws_id


def _scripts(original: str) -> dict:
    return {
        "Requirements Analyst": [final({"task_summary": "Add modulo", "acceptance_criteria": ["modulo(10, 3) == 1"]})],
        "Project Analyst": [final({"total_files": 4, "project_context": "calculator"})],
        "Implementation Planner": [final({"objective": "Add modulo", "steps": [
            {"step_number": 1, "description": "add", "files_affected": ["src/calculator.py"], "action": "patch"}]})],
        "Software Engineer": [
            action("read_file", {"path": "src/calculator.py"}),
            action("write_file", {"path": "src/calculator.py",
                                  "content": original + "\n\ndef modulo(a, b):\n    return a % b\n"}),
            final({"files_changed": [{"path": "src/calculator.py", "action": "patched"}]}),
        ],
        "Requirements Verifier": [final({"verified": True, "requirements_satisfied": ["modulo(10, 3) == 1"]})],
    }


@pytest.fixture()
def real_run(ws):
    svc, ws_id = ws
    original = svc.read_file(ws_id, "src/calculator.py").data["content"]
    llm = ScriptedLLM(_scripts(original))
    return SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=5), llm=llm).run_task(
        ws_id, "Add a modulo function", "real", architecture="sequential")


class TestTrace:
    def test_span_tree(self, real_run):
        spans = real_run.trace["spans"]
        by_id = {s["span_id"]: s for s in spans}
        run = [s for s in spans if s["kind"] == "run"]
        assert len(run) == 1 and run[0]["parent_span_id"] is None
        assert {s["trace_id"] for s in spans} == {real_run.trace_id}
        agents = [s for s in spans if s["kind"] == "agent"]
        assert {s["attributes"]["vexa.agent"] for s in agents} >= {
            "RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier"}
        assert all(by_id[s["parent_span_id"]]["kind"] == "run" for s in agents)
        for s in spans:
            if s["kind"] in ("tool", "llm"):
                assert by_id[s["parent_span_id"]]["kind"] == "agent"

    def test_tool_spans_attributed_to_agents(self, real_run):
        tools = [(s["attributes"]["vexa.agent"], s["attributes"]["vexa.tool"])
                 for s in real_run.trace["spans"] if s["kind"] == "tool"]
        assert ("Coder", "read_file") in tools and ("Coder", "write_file") in tools
        assert ("Tester", "run_tests") in tools

    def test_llm_spans_carry_usage_per_agent(self, real_run):
        llm = [s for s in real_run.trace["spans"] if s["kind"] == "llm"]
        assert len(llm) == 7  # analyst, project, planner, coder x3, verifier
        assert all(s["attributes"]["vexa.input_tokens"] > 0 for s in llm)
        coder = real_run.agent_metrics["Coder"]
        assert coder["llm_calls"] == 3 and coder["tool_calls"] == 2 and coder["input_tokens"] > 0
        assert real_run.agent_metrics["Tester"]["tool_calls"] == 1

    def test_callback_events_include_intermediate_outputs(self, real_run):
        kinds = [(e["kind"], e["agent"]) for e in real_run.trace["callback_events"]]
        assert ("task_completed", "Planner") in kinds
        out = next(e for e in real_run.trace["callback_events"]
                   if e["kind"] == "task_completed" and e["agent"] == "Planner")["output"]
        assert json.loads(out)["objective"] == "Add modulo"

    def test_file_provenance(self, real_run):
        prov = real_run.file_provenance["src/calculator.py"]
        assert prov[0]["agent"] == "Coder" and prov[0]["tool"] == "write_file"
        span_ids = {s["span_id"] for s in real_run.trace["spans"]}
        assert prov[0]["span_id"] in span_ids

    def test_mock_mode_has_no_llm_spans(self, ws):
        svc, ws_id = ws
        r = SoftwareEngineeringCrew(tool_service=svc).run_task(ws_id, "Add a modulo function")
        kinds = {s["kind"] for s in r.trace["spans"]}
        assert "llm" not in kinds and {"run", "agent", "tool"} <= kinds

    def test_guardrail_retry_is_a_callback_event(self, ws):
        svc, ws_id = ws
        scripts = _scripts(svc.read_file(ws_id, "src/calculator.py").data["content"])
        scripts["Requirements Analyst"] = [final({"task_summary": "x"}),
                                           final({"task_summary": "x", "acceptance_criteria": ["y"]})]
        r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=5),
                                    llm=ScriptedLLM(scripts)).run_task(ws_id, "Add a modulo function", "real")
        assert ("guardrail_failed", "RequirementAnalyst") in [(e["kind"], e["agent"]) for e in r.trace["callback_events"]]
        assert r.agent_metrics["RequirementAnalyst"]["validation_retries"] == 1


class TestRedaction:
    @pytest.mark.parametrize("secret", [
        "sk-proj-abcdefghijklmnopqrstuvwx", "gsk_abcdefghijklmnopqrstuvwxyz12", "AIzaSyA1234567890abcdefghijklmnopqrstu",
        "tvly-abcdefghijklmnopqrst",
    ])
    def test_patterns(self, secret):
        assert secret not in redact_text(f"key is {secret} ok")

    def test_assignment_keeps_name(self):
        assert redact_text("api_key=supersecretvalue1") == f"api_key={REDACTED}"

    def test_registered_exact_value(self):
        register_secret("my-custom-secret-123")
        assert redact_text("x my-custom-secret-123 y") == f"x {REDACTED} y"

    def test_structures(self):
        out = redact({"llm_api_key": "anything", "nested": ["Bearer abcdefghijklmnopqrstuvwxyz"]})
        assert out["llm_api_key"] == REDACTED and REDACTED in out["nested"][0]

    def test_log_filter(self):
        rec = logging.LogRecord("x", logging.INFO, "f", 1, "key=%s", ("sk-abcdefghijklmnopqrstuvwxyz",), None)
        RedactingFilter().filter(rec)
        assert "sk-abc" not in rec.getMessage()

    def test_run_errors_are_redacted(self, ws):
        svc, ws_id = ws

        def boom(agent, desc):
            raise RuntimeError("provider said: invalid key sk-proj-abcdefghijklmnopqrstuvwxyz")

        r = SoftwareEngineeringCrew(tool_service=svc, responder=boom).run_task(ws_id, "Add a modulo function")
        blob = json.dumps(r.model_dump(mode="json"))
        assert "sk-proj-abcdefghijklmnop" not in blob
