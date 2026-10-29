"""
Real-mode integration test through genuine CrewAI objects.

No network: the LLM is tests.fakes.ScriptedLLM. What is real: CrewAI Agent /
Task / Crew construction, the ReAct loop, VEXA's tool adapters (the Coder's
write is executed by CrewAI through _AdaptedTool), and the sandboxed pytest
run that decides the verdict. This is the coverage gap that hid audit
defects D1, D2 and D6.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.agents.config import AgentSettings
from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew
from backend.tools.service import ToolService
from tests.fakes import ScriptedLLM, action, final

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "sample_project"

MODULO_SRC = (
    '"""Simple calculator module."""\n\n'
    "def add(a, b):\n    return a + b\n\n"
    "def subtract(a, b):\n    return a - b\n\n"
    "def multiply(a, b):\n    return a * b\n\n"
    "def divide(a, b):\n    if b == 0:\n        raise ValueError(\"Cannot divide by zero\")\n    return a / b\n\n"
    "def modulo(a, b):\n    return a % b\n"
)


@pytest.fixture()
def ws(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path / "root"))
    ws_id = svc.create_workspace()
    shutil.copytree(str(FIXTURE_PROJECT), str(svc._manager.require(ws_id)), dirs_exist_ok=True)
    return svc, ws_id


def test_real_mode_through_crewai(ws):
    svc, ws_id = ws
    original = svc.read_file(ws_id, "src/calculator.py").data["content"]
    llm = ScriptedLLM({
        "Requirements Analyst": [final({
            "task_summary": "Add modulo", "functional_requirements": ["modulo(a,b)"],
            "constraints": [], "acceptance_criteria": ["modulo(10, 3) == 1"],
            "ambiguities": [], "affected_areas": ["src/calculator.py"],
        })],
        "Project Analyst": [final({"total_files": 4, "project_context": "calculator"})],
        "Implementation Planner": [final({
            "objective": "Add modulo",
            "steps": [{"step_number": 1, "description": "add fn", "files_affected": ["src/calculator.py"], "action": "patch"}],
        })],
        "Software Engineer": [
            action("write_file", {"path": "src/calculator.py", "content": original + "\n\ndef modulo(a, b):\n    return a % b\n"}),
            final({"files_changed": [{"path": "src/calculator.py", "action": "patched", "description": "modulo"}],
                   "implementation_notes": "added modulo"}),
        ],
        "Requirements Verifier": [final({"verified": True, "requirements_satisfied": ["modulo(10, 3) == 1"]})],
    })
    crew = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=4), llm=llm)
    result = crew.run_task(ws_id, "Add a modulo function to the calculator", "real")

    assert result.errors == [], result.errors
    # The tool call issued by the scripted Coder was executed by CrewAI
    assert "def modulo" in svc.read_file(ws_id, "src/calculator.py").data["content"]
    assert result.final_test_result.passed and result.final_test_result.verdict_source == "sandbox_exit_code"
    assert result.status == AgentStatus.success
    assert result.execution_mode == "real"
    roles_called = [k for k, _ in llm.calls]
    assert roles_called.count("Software Engineer") == 2  # tool turn + final answer


def _req_analyst_script(*turns):
    rest = {
        "Project Analyst": [final({"total_files": 4, "project_context": "calculator"})],
        "Implementation Planner": [final({
            "objective": "noop", "steps": [{"step_number": 1, "description": "verify", "action": "verify"}],
        })],
        "Software Engineer": [final({"files_changed": [], "implementation_notes": "none"})],
        "Requirements Verifier": [final({"verified": True})],
    }
    return {"Requirements Analyst": list(turns), **rest}


def test_schema_guardrail_reprompts_invalid_output(ws):
    """An answer missing acceptance_criteria is rejected and the agent retries."""
    svc, ws_id = ws
    invalid = final({"task_summary": "x", "functional_requirements": []})
    valid = final({"task_summary": "x", "acceptance_criteria": ["existing tests pass"]})
    llm = ScriptedLLM(_req_analyst_script(invalid, valid))
    crew = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=3), llm=llm)
    result = crew.run_task(ws_id, "Keep the calculator working", "real")

    analyst_calls = [t for k, t in llm.calls if k == "Requirements Analyst"]
    assert len(analyst_calls) == 2
    assert "acceptance_criteria" in analyst_calls[1]  # validation error fed back
    assert result.requirement_analysis.output_valid is True
    assert result.requirement_analysis.acceptance_criteria == ["existing tests pass"]


def test_schema_guardrail_exhaustion_fails_loudly(ws):
    svc, ws_id = ws
    invalid = final({"task_summary": "x"})
    llm = ScriptedLLM(_req_analyst_script(invalid))
    settings = AgentSettings(agent_max_iter=3, output_validation_retries=1)
    result = SoftwareEngineeringCrew(tool_service=svc, settings=settings, llm=llm).run_task(
        ws_id, "Keep the calculator working", "real")
    assert result.status == AgentStatus.failed
    assert any("schema validation" in e for e in result.errors)
