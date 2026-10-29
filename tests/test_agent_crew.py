"""
VEXA M3 — Sequential Crew Orchestration Tests (Mock LLM)

These tests use a deterministic mock LLM to:
1. Verify the sequential agent pipeline executes in order
2. Verify the debug loop triggers and retries
3. Verify the retry limit is enforced
4. Verify file changes reach the workspace
5. Verify verification fails when requirements are not met

The mock LLM is injected at the SoftwareEngineeringCrew level.
The REAL LLM integration path is preserved and tested in validate_m3.py.

IMPORTANT: These tests make REAL tool calls (file I/O, pytest execution)
against a real workspace. Only the LLM is mocked.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.config import AgentSettings
from backend.agents.contracts import AgentStatus, RunResult
from backend.agents.crew import (
    SoftwareEngineeringCrew,
    parse_coding_result,
    parse_implementation_plan,
    parse_project_analysis,
    parse_requirement_analysis,
    parse_test_result,
    parse_verification_result,
)
from backend.tools.service import ToolService

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "sample_project"


# ---------------------------------------------------------------------------
# Mock LLM that returns deterministic canned responses
# ---------------------------------------------------------------------------


def _make_settings(debug_max_iter: int = 3) -> AgentSettings:
    return AgentSettings(
        llm_model="gpt-4o-mini",
        llm_temperature=0.1,
        agent_max_iter=1,
        debug_max_iter=debug_max_iter,
        agent_verbose=False,
    )


class ScriptedResponder:
    """
    Mock-mode responder: returns canned text per agent id, in order.

    Unlike a single positional queue, each agent has its own script, so tests
    do not depend on how many times other agents are consulted. ``calls``
    records (agent_id, task_description) for assertions on context passing.
    """

    def __init__(self, scripts: dict[str, list[str]], on_call=None) -> None:
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._on_call = on_call
        self.calls: list[tuple[str, str]] = []

    def __call__(self, agent_id: str, description: str) -> str:
        self.calls.append((agent_id, description))
        if self._on_call:
            self._on_call(agent_id, len(self.calls))
        queue = self._scripts.get(agent_id)
        if not queue:
            raise AssertionError(f"Unexpected call to agent {agent_id}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _make_crew(svc: ToolService, scripts: dict[str, list[str]], debug_max_iter: int = 3, on_call=None):
    responder = ScriptedResponder(scripts, on_call)
    crew = SoftwareEngineeringCrew(
        tool_service=svc, settings=_make_settings(debug_max_iter), responder=responder,
    )
    return crew, responder


# ---------------------------------------------------------------------------
# JSON parser unit tests
# ---------------------------------------------------------------------------


class TestParsers:
    def test_parse_requirement_analysis_good_json(self):
        raw = json.dumps({
            "task_summary": "Add modulo",
            "functional_requirements": ["modulo(a, b) returns a % b"],
            "constraints": [],
            "acceptance_criteria": ["modulo(10, 3) == 1"],
            "ambiguities": [],
            "affected_areas": ["src/calculator.py"],
        })
        result = parse_requirement_analysis(raw, "Add modulo function", 100.0)
        assert result.status == AgentStatus.success
        assert result.task_summary == "Add modulo"
        assert "modulo(10, 3) == 1" in result.acceptance_criteria

    def test_parse_requirement_analysis_bad_json_returns_partial(self):
        result = parse_requirement_analysis("not json at all", "req", 0.0)
        assert result.status == AgentStatus.partial
        assert len(result.errors) > 0

    def test_parse_requirement_analysis_markdown_wrapped(self):
        raw = "```json\n" + json.dumps({"task_summary": "wrapped", "functional_requirements": [], "constraints": [], "acceptance_criteria": [], "ambiguities": [], "affected_areas": []}) + "\n```"
        result = parse_requirement_analysis(raw, "req", 0.0)
        assert result.task_summary == "wrapped"

    def test_parse_project_analysis(self):
        raw = json.dumps({
            "total_files": 5,
            "languages": {"python": 2},
            "important_files": ["README.md"],
            "relevant_files": ["src/calculator.py"],
            "relevant_file_contents": {},
            "existing_tests": ["tests/test_calculator.py"],
            "git_status": "not a git repo",
            "project_context": "Simple calculator project",
        })
        result = parse_project_analysis(raw, "ws-1", 200.0)
        assert result.total_files == 5
        assert result.languages["python"] == 2
        assert result.project_context == "Simple calculator project"

    def test_parse_implementation_plan(self):
        raw = json.dumps({
            "objective": "Add modulo",
            "steps": [{"step_number": 1, "description": "Add function", "files_affected": ["src/calculator.py"], "action": "patch"}],
            "files_to_modify": ["src/calculator.py"],
            "files_to_create": [],
            "test_strategy": "run pytest",
            "risks": [],
        })
        result = parse_implementation_plan(raw, 150.0)
        assert result.objective == "Add modulo"
        assert len(result.steps) == 1
        assert result.steps[0].action == "patch"

    def test_parse_test_result_passed(self):
        raw = json.dumps({
            "passed": True, "exit_code": 0, "tests_found": 9,
            "tests_passed": 9, "tests_failed": 0, "failures": [],
            "stdout": "9 passed", "stderr": "", "duration_ms": 300.0,
        })
        result = parse_test_result(raw, 300.0)
        assert result.passed is True
        assert result.exit_code == 0

    def test_parse_test_result_failed(self):
        raw = json.dumps({
            "passed": False, "exit_code": 1, "failures": ["test_modulo: assert 1 == 2"],
            "stdout": "FAILED", "stderr": "", "duration_ms": 100.0,
        })
        result = parse_test_result(raw, 100.0)
        assert result.passed is False

    def test_parse_verification_verified(self):
        raw = json.dumps({
            "verified": True,
            "requirements_satisfied": ["modulo works"],
            "requirements_failed": [],
            "tests_passed": True,
            "files_changed": ["src/calculator.py"],
            "remaining_risks": [],
            "evidence": "All tests pass",
        })
        result = parse_verification_result(raw, 50.0)
        assert result.verified is True

    def test_parse_coding_result(self):
        raw = json.dumps({
            "files_changed": [{"path": "src/calculator.py", "action": "patched", "description": "Added modulo"}],
            "implementation_notes": "Used % operator",
        })
        result = parse_coding_result(raw, 400.0)
        assert len(result.files_changed) == 1
        assert result.files_changed[0].path == "src/calculator.py"


# ---------------------------------------------------------------------------
# Mock LLM integration tests — full pipeline
# ---------------------------------------------------------------------------


CANNED_REQ = json.dumps({
    "task_summary": "Add modulo(a, b) function to calculator",
    "functional_requirements": ["modulo(a, b) returns a % b"],
    "constraints": ["preserve existing tests"],
    "acceptance_criteria": ["modulo(10, 3) == 1"],
    "ambiguities": [],
    "affected_areas": ["src/calculator.py"],
})

CANNED_PROJ = json.dumps({
    "total_files": 5,
    "languages": {"python": 2},
    "important_files": ["README.md"],
    "relevant_files": ["src/calculator.py"],
    "relevant_file_contents": {"src/calculator.py": "def add(a, b): return a + b"},
    "existing_tests": ["tests/test_calculator.py"],
    "git_status": "not a git repo",
    "project_context": "Simple calculator; needs modulo function",
})

CANNED_PLAN = json.dumps({
    "objective": "Add modulo(a, b) function",
    "steps": [{"step_number": 1, "description": "Patch calculator.py", "files_affected": ["src/calculator.py"], "action": "patch"}],
    "files_to_modify": ["src/calculator.py"],
    "files_to_create": [],
    "test_strategy": "run existing pytest suite",
    "risks": [],
})

# The coder's mock response — we describe what it "did"
# Note: the actual file changes are performed by mock_coder_action fixture
CANNED_CODE = json.dumps({
    "files_changed": [{"path": "src/calculator.py", "action": "patched", "description": "Added modulo function"}],
    "implementation_notes": "Used % operator",
})

CANNED_TEST_PASS = json.dumps({
    "passed": True, "exit_code": 0, "tests_found": 10, "tests_passed": 10,
    "tests_failed": 0, "failures": [], "stdout": "10 passed", "stderr": "", "duration_ms": 300.0,
})

CANNED_TEST_FAIL = json.dumps({
    "passed": False, "exit_code": 1, "tests_found": 10, "tests_passed": 9,
    "tests_failed": 1, "failures": ["test_modulo: AssertionError"],
    "stdout": "FAILED", "stderr": "", "duration_ms": 100.0,
})

CANNED_DEBUG = json.dumps({
    "root_cause": "Wrong return statement in modulo",
    "root_cause_category": "implementation_bug",
    "fix_applied": "Changed return to a % b",
    "files_changed": [{"path": "src/calculator.py", "action": "patched", "description": "Fixed modulo"}],
})

CANNED_VERIFY = json.dumps({
    "verified": True,
    "requirements_satisfied": ["modulo(10, 3) == 1"],
    "requirements_failed": [],
    "tests_passed": True,
    "files_changed": ["src/calculator.py"],
    "remaining_risks": [],
    "evidence": "All 10 tests pass, modulo function present in source",
})

CANNED_VERIFY_FAIL = json.dumps({
    "verified": False,
    "requirements_satisfied": [],
    "requirements_failed": ["modulo function not found in calculator.py"],
    "tests_passed": False,
    "files_changed": [],
    "remaining_risks": ["Implementation not complete"],
    "evidence": "File not modified",
})


@pytest.fixture(scope="module")
def seq_svc_ws(tmp_path_factory):
    """Shared ToolService + sample workspace for orchestration tests."""
    root = tmp_path_factory.mktemp("seq_crew_tests")
    svc = ToolService(workspace_root=str(root))
    ws_id = svc.create_workspace()
    from backend.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager(workspace_root=root)
    repo = mgr.require(ws_id)
    shutil.copytree(str(FIXTURE_PROJECT), str(repo), dirs_exist_ok=True)
    return svc, ws_id, root


HAPPY_SCRIPTS = {
    "RequirementAnalyst": [CANNED_REQ],
    "ProjectAnalyst": [CANNED_PROJ],
    "Planner": [CANNED_PLAN],
    "Coder": [CANNED_CODE],
    "Verifier": [CANNED_VERIFY],
}


def _ensure_modulo(svc: ToolService, ws_id: str) -> None:
    content = svc.read_file(ws_id, "src/calculator.py").data["content"]
    if "def modulo" not in content:
        svc.write_file(ws_id, "src/calculator.py",
                       content + "\n\ndef modulo(a: float, b: float) -> float:\n    return a % b\n")


class TestSequentialPipelineHappyPath:
    """
    Happy path: the workspace tests really pass (sandboxed pytest), so the
    Tester agent is never consulted and no debug loop runs.
    """

    @pytest.fixture(autouse=True)
    def _prepare(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        _ensure_modulo(svc, ws_id)

    def test_full_pipeline_produces_run_result(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        crew, _ = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Add modulo(a, b) function to calculator.py")
        assert isinstance(result, RunResult)
        assert result.workspace_id == ws_id
        assert result.execution_mode == "mock"

    def test_pipeline_collects_agent_outputs(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        crew, _ = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Add modulo")
        assert result.requirement_analysis.task_summary == "Add modulo(a, b) function to calculator"
        assert result.project_analysis.total_files == 5
        assert result.implementation_plan.objective == "Add modulo(a, b) function"
        assert len(result.coding_result.files_changed) == 1

    def test_tests_are_executed_not_reported(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        crew, responder = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Add modulo")
        t = result.final_test_result
        assert t.verdict_source == "sandbox_exit_code"
        assert t.exit_code == 0 and t.passed
        assert t.tests_passed > 0 and t.tests_found >= t.tests_passed
        # Tester LLM only explains failures; it must not be consulted on success
        assert "Tester" not in [a for a, _ in responder.calls]

    def test_pipeline_success_status(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        crew, _ = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Add modulo")
        assert result.status == AgentStatus.success
        assert result.debug_result is None

    def test_events_survive_completion(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        crew, _ = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Add modulo")
        agents = {e["agent"] for e in result.events if e["event"] == "completed"}
        assert {"RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier"} <= agents
        assert result.test_attempts == 1

    def test_project_analyst_receives_real_file_tree(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        crew, responder = _make_crew(svc, HAPPY_SCRIPTS)
        crew.run_task(ws_id, "Add modulo")
        desc = next(d for a, d in responder.calls if a == "ProjectAnalyst")
        assert "- src/calculator.py" in desc
        assert "Could not retrieve file tree" not in desc


@pytest.fixture()
def broken_ws(tmp_path_factory):
    """Workspace whose modulo implementation is wrong, with a test that catches it."""
    root = tmp_path_factory.mktemp("debug_loop_tests")
    svc = ToolService(workspace_root=str(root))
    ws_id = svc.create_workspace()
    from backend.tools.workspace import WorkspaceManager
    repo = WorkspaceManager(workspace_root=root).require(ws_id)
    shutil.copytree(str(FIXTURE_PROJECT), str(repo), dirs_exist_ok=True)
    content = svc.read_file(ws_id, "src/calculator.py").data["content"]
    svc.write_file(ws_id, "src/calculator.py",
                   content + "\n\ndef modulo(a: float, b: float) -> float:\n    return a + b  # BUG: should be %\n")
    svc.write_file(ws_id, "tests/test_modulo.py",
                   "import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
                   "from calculator import modulo\ndef test_modulo_basic(): assert modulo(10, 3) == 1\n")
    return svc, ws_id


class TestDebugLoop:
    """fail → debug → re-test, with the verdict always taken from real pytest."""

    def test_debug_loop_repairs_and_passes(self, broken_ws):
        svc, ws_id = broken_ws

        def fix_on_debug(agent_id, _n):
            if agent_id == "Debugger":  # simulate the Debugger's patch_file call
                svc.patch_file(ws_id, "src/calculator.py", "return a + b  # BUG: should be %", "return a % b")

        crew, responder = _make_crew(svc, {
            **HAPPY_SCRIPTS,
            "Tester": [json.dumps({"failures": ["test_modulo_basic: assert 13 == 1"]})],
            "Debugger": [CANNED_DEBUG],
        }, on_call=fix_on_debug)
        result = crew.run_task(ws_id, "Add modulo(a, b) function")

        assert result.initial_test_result.passed is False
        assert result.initial_test_result.failures == ["test_modulo_basic: assert 13 == 1"]
        assert result.debug_iterations == 1
        assert result.final_test_result.passed is True
        assert result.status == AgentStatus.success

    def test_failures_fall_back_to_pytest_output(self, broken_ws):
        svc, ws_id = broken_ws
        crew, _ = _make_crew(svc, {
            **HAPPY_SCRIPTS,
            "Tester": [json.dumps({"failures": []})],
            "Debugger": [CANNED_DEBUG],
            "Verifier": [CANNED_VERIFY_FAIL],
        }, debug_max_iter=1)
        result = crew.run_task(ws_id, "Add modulo")
        assert any("test_modulo_basic" in f for f in result.initial_test_result.failures)

    def test_max_iterations_enforced(self, broken_ws):
        svc, ws_id = broken_ws
        crew, responder = _make_crew(svc, {
            **HAPPY_SCRIPTS,
            "Tester": [json.dumps({"failures": ["still failing"]})],
            "Debugger": [CANNED_DEBUG],  # claims a fix but changes nothing
            "Verifier": [CANNED_VERIFY_FAIL],
        }, debug_max_iter=2)
        result = crew.run_task(ws_id, "Add modulo (will fail)")
        assert result.debug_result.max_iterations_reached is True
        assert len(result.debug_result.iterations) == 2
        assert result.test_attempts == 3
        assert result.status == AgentStatus.failed

    def test_fabricated_tester_pass_is_ignored(self, broken_ws):
        """A Tester LLM that claims success cannot flip the sandbox verdict."""
        svc, ws_id = broken_ws
        crew, _ = _make_crew(svc, {
            **HAPPY_SCRIPTS,
            "Tester": [CANNED_TEST_PASS],
            "Debugger": [CANNED_DEBUG],
        }, debug_max_iter=1)
        result = crew.run_task(ws_id, "Add modulo")
        assert result.final_test_result.passed is False

    def test_fabricated_verifier_claim_is_overridden(self, broken_ws):
        svc, ws_id = broken_ws
        crew, _ = _make_crew(svc, {
            **HAPPY_SCRIPTS,
            "Tester": [json.dumps({"failures": ["x"]})],
            "Debugger": [CANNED_DEBUG],
        }, debug_max_iter=1)
        result = crew.run_task(ws_id, "Add modulo")
        v = result.verification_result
        assert v.llm_claimed_verified is True
        assert v.verified is False and v.tests_passed is False
        assert result.status == AgentStatus.failed


class TestVerifier:
    def test_verified_false_when_requirements_not_met(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        _ensure_modulo(svc, ws_id)
        crew, _ = _make_crew(svc, {**HAPPY_SCRIPTS, "Verifier": [CANNED_VERIFY_FAIL]})
        result = crew.run_task(ws_id, "Add modulo")
        assert result.verification_result.verified is False
        assert result.status == AgentStatus.partial  # tests pass, requirements not met

    def test_verified_true_leads_to_success(self, seq_svc_ws):
        svc, ws_id, _ = seq_svc_ws
        _ensure_modulo(svc, ws_id)
        crew, _ = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Add modulo")
        assert result.verification_result.verified is True
        assert result.verification_result.tests_passed is True


class TestNoTests:
    def test_project_without_tests_is_not_a_pass(self, tmp_path_factory):
        svc = ToolService(workspace_root=str(tmp_path_factory.mktemp("no_tests")))
        ws_id = svc.create_workspace()
        svc.write_file(ws_id, "index.html", "<h1>hi</h1>")
        crew, responder = _make_crew(svc, HAPPY_SCRIPTS)
        result = crew.run_task(ws_id, "Build a static page")
        assert result.final_test_result.no_tests is True
        assert result.final_test_result.passed is False
        assert result.debug_result is None  # nothing for the Debugger to fix
        assert result.status == AgentStatus.partial


class TestWorkspaceIsolation:
    """Security regression: agent pipeline must not escape workspace."""

    def test_invalid_workspace_raises(self, seq_svc_ws):
        svc, _, _ = seq_svc_ws
        crew, _ = _make_crew(svc, {})
        result = crew.run_task("workspace-does-not-exist", "do something")
        assert result.status == AgentStatus.failed
        assert len(result.errors) > 0


def test_debugger_receives_requirements_and_plan(broken_ws):
    svc, ws_id = broken_ws
    crew, responder = _make_crew(svc, {
        **HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})], "Debugger": [CANNED_DEBUG],
        "Verifier": [CANNED_VERIFY_FAIL],
    }, debug_max_iter=1)
    crew.run_task(ws_id, "Add modulo")
    prompt = next(d for a, d in responder.calls if a == "Debugger")
    assert "modulo(10, 3) == 1" in prompt and "Add modulo(a, b) function" in prompt
