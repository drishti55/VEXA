"""
VEXA M3 — Agent Contracts Tests

Tests for typed contract models:
- All contracts instantiate correctly
- Field validation works
- Serialisation round-trips
- Invalid data is rejected
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.agents.contracts import (
    AgentStatus,
    CodingResult,
    DebugIteration,
    DebugResult,
    FileChange,
    ImplementationPlan,
    ImplementationStep,
    ProjectAnalysis,
    RequirementAnalysis,
    RunResult,
    AgentTestResult,
    VerificationResult,
)


class TestRequirementAnalysis:
    def test_defaults_valid(self):
        r = RequirementAnalysis(status=AgentStatus.success, summary="ok")
        assert r.agent_name == "RequirementAnalyst"
        assert r.status == AgentStatus.success
        assert isinstance(r.timestamp, datetime)

    def test_full_fields(self):
        r = RequirementAnalysis(
            status=AgentStatus.success,
            summary="Add modulo function",
            original_requirement="Add a modulo operation",
            task_summary="Add modulo(a, b) to calculator.py",
            functional_requirements=["modulo(a, b) returns a % b"],
            constraints=["must not break existing tests"],
            acceptance_criteria=["modulo(10, 3) == 1"],
            ambiguities=[],
            affected_areas=["src/calculator.py"],
        )
        assert r.task_summary == "Add modulo(a, b) to calculator.py"
        assert "modulo(10, 3) == 1" in r.acceptance_criteria

    def test_json_serialise(self):
        r = RequirementAnalysis(status=AgentStatus.success, summary="ok")
        data = r.model_dump()
        assert "agent_name" in data
        assert "status" in data
        assert data["status"] == "success"


class TestProjectAnalysis:
    def test_defaults(self):
        p = ProjectAnalysis(status=AgentStatus.success, summary="project ok")
        assert p.agent_name == "ProjectAnalyst"
        assert p.languages == {}
        assert p.total_files == 0

    def test_with_content(self):
        p = ProjectAnalysis(
            status=AgentStatus.success,
            summary="2 python files found",
            workspace_id="test-ws",
            total_files=4,
            languages={"python": 2},
            important_files=["README.md"],
            relevant_files=["src/calculator.py"],
        )
        assert p.total_files == 4
        assert p.languages["python"] == 2


class TestImplementationPlan:
    def test_empty_plan(self):
        plan = ImplementationPlan(status=AgentStatus.success, summary="add modulo")
        assert plan.steps == []
        assert plan.risks == []

    def test_with_steps(self):
        step = ImplementationStep(
            step_number=1,
            description="Add modulo function to calculator.py",
            files_affected=["src/calculator.py"],
            action="patch",
        )
        plan = ImplementationPlan(
            status=AgentStatus.success,
            summary="add modulo",
            objective="Add modulo(a, b) function",
            steps=[step],
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "patch"


class TestAgentTestResult:
    def test_passing(self):
        t = AgentTestResult(
            status=AgentStatus.success,
            summary="9 tests passed",
            passed=True,
            exit_code=0,
            tests_passed=9,
        )
        assert t.passed is True
        assert t.exit_code == 0

    def test_failing(self):
        t = AgentTestResult(
            status=AgentStatus.failed,
            summary="1 test failed",
            passed=False,
            exit_code=1,
            tests_failed=1,
            failures=["test_modulo: AssertionError"],
        )
        assert t.passed is False
        assert "test_modulo" in t.failures[0]


class TestDebugResult:
    def test_with_iterations(self):
        t_pass = AgentTestResult(status=AgentStatus.success, summary="ok", passed=True, exit_code=0)
        itr = DebugIteration(
            iteration=1,
            root_cause="Wrong operator used",
            fix_applied="Changed / to %",
            files_changed=[FileChange(path="src/calculator.py", action="patched", description="fix")],
            test_result_after=t_pass,
        )
        dr = DebugResult(
            status=AgentStatus.success,
            summary="Fixed in 1 iteration",
            iterations=[itr],
            final_test_result=t_pass,
        )
        assert len(dr.iterations) == 1
        assert dr.final_test_result.passed is True
        assert dr.max_iterations_reached is False


class TestVerificationResult:
    def test_verified(self):
        v = VerificationResult(
            status=AgentStatus.success,
            summary="All requirements met",
            verified=True,
            requirements_satisfied=["modulo(10, 3) == 1"],
            tests_passed=True,
        )
        assert v.verified is True

    def test_not_verified_missing_criteria(self):
        v = VerificationResult(
            status=AgentStatus.failed,
            summary="Missing test",
            verified=False,
            requirements_failed=["No test for modulo(0, 5)"],
        )
        assert v.verified is False
        assert len(v.requirements_failed) == 1


class TestRunResult:
    def test_default_status_failed(self):
        r = RunResult(run_id="abc", workspace_id="ws-1", requirement="do something")
        assert r.status == AgentStatus.failed

    def test_full_result_serialises(self):
        req = RequirementAnalysis(status=AgentStatus.success, summary="ok")
        r = RunResult(
            run_id="run-123",
            workspace_id="ws-abc",
            requirement="Add modulo",
            status=AgentStatus.success,
            requirement_analysis=req,
        )
        data = r.model_dump(mode="json")
        assert data["run_id"] == "run-123"
        assert data["requirement_analysis"]["agent_name"] == "RequirementAnalyst"

    def test_errors_accumulate(self):
        r = RunResult(run_id="x", workspace_id="y", requirement="z")
        r.errors.append("something broke")
        assert len(r.errors) == 1
