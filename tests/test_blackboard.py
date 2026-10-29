"""Phase 3: Blackboard architecture."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

import pytest

from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew
from backend.orchestration.blackboard import DEFAULT_KNOWLEDGE_SOURCES
from backend.tools.service import ToolService
from tests.test_agent_crew import (
    CANNED_DEBUG,
    CANNED_VERIFY_FAIL,
    HAPPY_SCRIPTS,
    ScriptedResponder,
    _make_settings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


def _workspace(tmp_path, broken: bool = False):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    if broken:
        src = svc.read_file(ws, "src/calculator.py").data["content"]
        svc.write_file(ws, "src/calculator.py", src + "\n\ndef modulo(a, b):\n    return a + b  # BUG\n")
        svc.write_file(ws, "tests/test_modulo.py",
                       "import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
                       "from calculator import modulo\ndef test_modulo_basic(): assert modulo(10, 3) == 1\n")
    return svc, ws


def _run(svc, ws, scripts, architecture, debug_max_iter=3, on_call=None):
    responder = ScriptedResponder(scripts, on_call)
    crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(debug_max_iter), responder=responder)
    return crew.run_task(ws, "Add modulo", architecture=architecture), responder


class TestBlackboardHappyPath:
    @pytest.fixture()
    def result(self, tmp_path):
        svc, ws = _workspace(tmp_path)
        return _run(svc, ws, HAPPY_SCRIPTS, "blackboard")[0]

    def test_outcome(self, result):
        assert result.architecture == "blackboard"
        assert result.status == AgentStatus.success, result.errors
        assert result.final_test_result.passed

    def test_agents_obtain_inputs_only_via_blackboard_reads(self, result):
        reads = defaultdict(set)
        for a in result.state["access_log"]:
            if a["kind"] == "read":
                reads[a["agent"]].add(a["key"])
        assert reads["RequirementAnalyst"] == {"requirement"}
        assert reads["ProjectAnalyst"] == {"requirement_analysis"}
        assert reads["Planner"] == {"requirement_analysis", "project_analysis"}
        assert reads["Coder"] == {"implementation_plan", "project_analysis", "requirement_analysis"}
        assert "code_changes" in reads["Tester"]
        assert reads["Verifier"] == {"requirement_analysis", "test_result"}

    def test_every_write_is_authored_by_a_knowledge_source(self, result):
        authors = {e["author"] for e in result.state["entries"]}
        assert authors <= {"user"} | {ks.name for ks in DEFAULT_KNOWLEDGE_SOURCES}

    def test_controller_decisions_logged(self, result):
        decisions = [c for c in result.coordination_log if c["kind"] == "decision"]
        assert [d["target"] for d in decisions] == [
            "RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier"]
        assert all(d["actor"] == "controller" and d["data"]["triggered"] for d in decisions)
        assert result.coordination_log[-1]["kind"] == "stop"

    def test_writes_wake_agenda(self, result):
        wakes = [c for c in result.coordination_log if c["kind"] == "event"]
        test_wake = next(c for c in wakes if c["data"]["key"] == "test_result")
        assert "Debugger" in test_wake["data"]["woke"]
        # Verifier reads requirement_analysis too, so it was already queued (agenda is de-duplicated)
        req_wake = next(c for c in wakes if c["data"]["key"] == "requirement_analysis")
        assert "Verifier" in req_wake["data"]["woke"]


class TestBlackboardDebugLoopEmerges:
    def test_failing_test_triggers_debugger_then_retest(self, tmp_path):
        svc, ws = _workspace(tmp_path, broken=True)

        def fix(agent_id, _n):
            if agent_id == "Debugger":
                svc.patch_file(ws, "src/calculator.py", "return a + b  # BUG", "return a % b")

        result, _ = _run(svc, ws, {**HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})],
                                  "Debugger": [CANNED_DEBUG]}, "blackboard", on_call=fix)
        order = [c["target"] for c in result.coordination_log if c["kind"] == "decision"]
        assert order[-4:] == ["Tester", "Debugger", "Tester", "Verifier"]
        assert result.debug_iterations == 1
        assert result.debug_result.iterations[0].test_result_after.passed
        assert result.status == AgentStatus.success
        assert [e["version"] for e in result.state["entries"] if e["key"] == "test_result"] == [1, 2]

    def test_debug_budget_respected(self, tmp_path):
        svc, ws = _workspace(tmp_path, broken=True)
        result, _ = _run(svc, ws, {**HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})],
                                  "Debugger": [CANNED_DEBUG], "Verifier": [CANNED_VERIFY_FAIL]},
                         "blackboard", debug_max_iter=2)
        assert result.debug_iterations == 2
        assert result.debug_result.max_iterations_reached
        assert result.test_attempts == 3
        assert result.status == AgentStatus.failed


class TestParityWithSequential:
    """Same agents/scripts → same outcome; only the coordination differs."""

    @pytest.mark.parametrize("broken", [False, True])
    def test_same_outcome(self, tmp_path, broken):
        outcomes = {}
        for arch in ("sequential", "blackboard"):
            svc, ws = _workspace(tmp_path / arch, broken=broken)

            def fix(agent_id, _n, svc=svc, ws=ws):
                if agent_id == "Debugger":
                    svc.patch_file(ws, "src/calculator.py", "return a + b  # BUG", "return a % b")

            scripts = {**HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})], "Debugger": [CANNED_DEBUG]}
            r, _ = _run(svc, ws, scripts, arch, on_call=fix)
            outcomes[arch] = (r.status, r.final_test_result.passed, r.debug_iterations, r.test_attempts)
        assert outcomes["sequential"] == outcomes["blackboard"]

    def test_failed_requirements_stop_both(self, tmp_path):
        for arch in ("sequential", "blackboard"):
            svc, ws = _workspace(tmp_path / arch)
            crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(),
                                           responder=lambda a, d: (_ for _ in ()).throw(RuntimeError("LLM down")))
            r = crew.run_task(ws, "Add modulo", architecture=arch)
            assert r.status == AgentStatus.failed and r.project_analysis is None
