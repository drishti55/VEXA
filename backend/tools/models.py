"""
VEXA Tool Layer — Structured Result Models

All tool operations return a ToolResult or ExecResult so that future agents
can reason over outcomes programmatically instead of parsing raw strings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard result returned by filesystem, search, and git tools."""

    success: bool
    operation: str = Field(description="Name of the operation that was performed")
    message: str = Field(description="Human-readable outcome summary")
    data: Any = Field(default=None, description="Operation-specific payload")
    error: str | None = Field(default=None, description="Error detail on failure")
    duration_ms: float = Field(default=0.0, description="Wall-clock time in milliseconds")

    @classmethod
    def ok(cls, operation: str, message: str, data: Any = None, duration_ms: float = 0.0) -> "ToolResult":
        return cls(success=True, operation=operation, message=message, data=data, duration_ms=duration_ms)

    @classmethod
    def fail(cls, operation: str, message: str, error: str | None = None, duration_ms: float = 0.0) -> "ToolResult":
        return cls(success=False, operation=operation, message=message, error=error, duration_ms=duration_ms)


class ExecResult(BaseModel):
    """Result returned by execution (test runner, command) tools."""

    success: bool
    operation: str
    message: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: float = 0.0
    error: str | None = None


class FileMatch(BaseModel):
    """A single search result within a source file."""

    file: str = Field(description="Relative path within the workspace")
    line_number: int
    matched_line: str
    context_before: str = ""
    context_after: str = ""


class FileInfo(BaseModel):
    """Metadata about a single file in a workspace listing."""

    path: str = Field(description="Relative path within the workspace")
    size_bytes: int
    is_dir: bool = False


class ProjectOverview(BaseModel):
    """Compact project inspection result."""

    root: str
    total_files: int
    total_dirs: int
    languages: dict[str, int] = Field(default_factory=dict)
    important_files: list[str] = Field(default_factory=list)
