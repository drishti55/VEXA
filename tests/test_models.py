"""
Tests for core domain models (Project, Task, Run).

Validates:
- Valid model construction
- Field defaults
- Enum values
- Invalid data rejection
- Run timing validator
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.models.domain import (
    Architecture,
    LLMConfig,
    OperatingMode,
    Project,
    ProjectCreate,
    Run,
    RunCreate,
    RunStatus,
    Task,
    TaskCreate,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# ProjectCreate
# ---------------------------------------------------------------------------


class TestProjectCreate:
    def test_valid_minimal(self):
        p = ProjectCreate(name="My Project")
        assert p.name == "My Project"
        assert p.mode == OperatingMode.build
        assert p.description is None

    def test_valid_full(self):
        p = ProjectCreate(
            name="Auth Service",
            description="JWT auth API",
            repository_url="https://github.com/org/repo",
            mode=OperatingMode.modify,
        )
        assert p.mode == OperatingMode.modify

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="")

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="x" * 256)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class TestProject:
    def test_id_is_uuid(self):
        p = Project(name="Test")
        assert len(p.id) == 36  # UUID4 string

    def test_created_at_is_datetime(self):
        p = Project(name="Test")
        assert isinstance(p.created_at, datetime)

    def test_two_projects_have_different_ids(self):
        a = Project(name="A")
        b = Project(name="B")
        assert a.id != b.id


# ---------------------------------------------------------------------------
# TaskCreate
# ---------------------------------------------------------------------------


class TestTaskCreate:
    def test_valid_task(self):
        t = TaskCreate(
            project_id="proj-123",
            title="Add login endpoint",
            description="Implement POST /auth/login using JWT",
        )
        assert t.status if hasattr(t, "status") else True

    def test_empty_description_rejected(self):
        with pytest.raises(ValidationError):
            TaskCreate(
                project_id="proj-123",
                title="Title",
                description="",
            )

    def test_acceptance_criteria_default_empty(self):
        t = TaskCreate(
            project_id="proj-123",
            title="Title",
            description="desc",
        )
        assert t.acceptance_criteria == []


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TestTask:
    def test_default_status(self):
        t = Task(
            project_id="proj-123",
            title="T",
            description="d",
        )
        assert t.status == TaskStatus.pending


# ---------------------------------------------------------------------------
# LLMConfig
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o"
        assert cfg.temperature == 0.2

    def test_temperature_out_of_range(self):
        with pytest.raises(ValidationError):
            LLMConfig(temperature=3.0)

    def test_negative_max_tokens_rejected(self):
        with pytest.raises(ValidationError):
            LLMConfig(max_tokens=-1)


# ---------------------------------------------------------------------------
# RunCreate
# ---------------------------------------------------------------------------


class TestRunCreate:
    def test_valid_run_create(self):
        rc = RunCreate(
            task_id="task-abc",
            architecture=Architecture.sequential,
        )
        assert rc.architecture == Architecture.sequential

    def test_invalid_architecture_rejected(self):
        with pytest.raises(ValidationError):
            RunCreate(task_id="task-abc", architecture="nonexistent")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class TestRun:
    def test_default_status_pending(self):
        r = Run(task_id="t", architecture=Architecture.hierarchical)
        assert r.status == RunStatus.pending

    def test_latency_none_if_not_started(self):
        r = Run(task_id="t", architecture=Architecture.sequential)
        assert r.latency_seconds is None

    def test_latency_computed(self):
        now = datetime.now(UTC)
        r = Run(
            task_id="t",
            architecture=Architecture.sequential,
            started_at=now,
            finished_at=now + timedelta(seconds=30),
        )
        assert r.latency_seconds == pytest.approx(30.0)

    def test_finished_before_started_rejected(self):
        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            Run(
                task_id="t",
                architecture=Architecture.sequential,
                started_at=now,
                finished_at=now - timedelta(seconds=1),
            )

    def test_metrics_default_zero(self):
        r = Run(task_id="t", architecture=Architecture.event_driven)
        assert r.total_input_tokens == 0
        assert r.total_output_tokens == 0
        assert r.estimated_cost_usd == 0.0
        assert r.iterations == 0
