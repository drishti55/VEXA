"""
VEXA Core Domain Models

Pydantic models for the three primary domain objects:
  Project — a software project that VEXA works on
  Task    — a single software-engineering task within a project
  Run     — one execution of a Task under a specific architecture/config

These models are designed to evolve into ORM models without a full redesign.
All identifiers use UUID strings for database compatibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class OperatingMode(str, Enum):
    """VEXA operating mode."""
    build = "build"
    modify = "modify"


class Architecture(str, Enum):
    """Multi-agent orchestration architecture."""
    sequential = "sequential"
    hierarchical = "hierarchical"
    event_driven = "event_driven"


class RunStatus(str, Enum):
    """Lifecycle state of a single Run."""
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class TaskStatus(str, Enum):
    """Lifecycle state of a Task."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    """Input schema for creating a new Project."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    repository_url: str | None = Field(
        default=None,
        description="Optional URL to an existing repository (MODIFY mode)",
    )
    mode: OperatingMode = OperatingMode.build


class Project(ProjectCreate):
    """Full Project domain model, including system-generated fields."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    """Input schema for creating a new Task."""
    project_id: str = Field(..., description="Parent project ID")
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(
        ...,
        min_length=1,
        description="Natural-language requirement or issue description",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Conditions that define task success",
    )


class Task(TaskCreate):
    """Full Task domain model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------


class LLMConfig(BaseModel):
    """LLM model configuration for a Run.

    Intentionally minimal in M1 — will grow as agent integration develops.
    """
    provider: str = Field(
        default="openai",
        description="LLM provider identifier, e.g. 'openai', 'anthropic', 'google'",
    )
    model: str = Field(
        default="gpt-4o",
        description="Model name/identifier as understood by the provider",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class RunCreate(BaseModel):
    """Input schema for starting a new Run."""
    task_id: str = Field(..., description="Task to execute")
    architecture: Architecture
    llm_config: LLMConfig = Field(default_factory=LLMConfig)


class Run(RunCreate):
    """Full Run domain model.

    A Run represents one execution of a Task under a specific architecture
    and LLM configuration. It captures all research metrics needed for
    the evaluation framework.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: RunStatus = RunStatus.pending

    # Timing
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # Outcome
    success: bool | None = None
    iterations: int = 0
    error_message: str | None = None

    # Metrics (populated progressively during/after the run)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _validate_timing(self) -> "Run":
        if self.finished_at and self.started_at:
            if self.finished_at < self.started_at:
                raise ValueError("finished_at must not be before started_at")
        return self

    @property
    def latency_seconds(self) -> float | None:
        """Wall-clock duration of the run in seconds, or None if not finished."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
