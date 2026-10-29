"""
VEXA Tool Layer — Git Tools

Safe, read-only Git inspection within a workspace.

Supported operations:
  git_status  — working tree status
  git_diff    — unstaged or staged diff
  git_log     — recent commit history

No write operations (push, commit, checkout) are exposed.
Arbitrary Git commands are NOT allowed.
"""

from __future__ import annotations

import time

from backend.core.logging import get_logger
from backend.tools.execution import LocalSandboxExecutor
from backend.tools.models import ToolResult
from backend.tools.workspace import WorkspaceManager

logger = get_logger(__name__)


class GitTools:
    """Git inspection tools for a workspace repository."""

    def __init__(self, manager: WorkspaceManager) -> None:
        self._mgr = manager
        # Git is always run via the local executor — it is a read-only
        # inspection tool and does not need Docker isolation.
        self._exec = LocalSandboxExecutor(manager)

    # ------------------------------------------------------------------
    # git_status
    # ------------------------------------------------------------------

    def git_status(self, workspace_id: str) -> ToolResult:
        """Return the short working-tree status of the workspace."""
        t0 = time.monotonic()
        result = self._exec.run(["git", "status", "--short"], workspace_id)
        ms = (time.monotonic() - t0) * 1000

        if not result.success and "not a git repository" in (result.stderr + result.stdout).lower():
            return ToolResult.ok(
                "git_status",
                "Workspace is not a Git repository",
                data={"is_git_repo": False},
                duration_ms=ms,
            )

        if result.timed_out:
            return ToolResult.fail("git_status", "Git status timed out", duration_ms=ms)

        return ToolResult.ok(
            "git_status",
            "Git status retrieved",
            data={
                "is_git_repo": True,
                "output": result.stdout,
                "exit_code": result.exit_code,
            },
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # git_diff
    # ------------------------------------------------------------------

    def git_diff(self, workspace_id: str, staged: bool = False) -> ToolResult:
        """Return the current diff (unstaged by default, or staged)."""
        t0 = time.monotonic()
        argv = ["git", "diff"]
        if staged:
            argv.append("--cached")

        result = self._exec.run(argv, workspace_id)
        ms = (time.monotonic() - t0) * 1000

        if not result.success and "not a git repository" in (result.stderr + result.stdout).lower():
            return ToolResult.ok(
                "git_diff",
                "Workspace is not a Git repository",
                data={"is_git_repo": False},
                duration_ms=ms,
            )

        if result.timed_out:
            return ToolResult.fail("git_diff", "Git diff timed out", duration_ms=ms)

        return ToolResult.ok(
            "git_diff",
            "Git diff retrieved",
            data={
                "is_git_repo": True,
                "staged": staged,
                "diff": result.stdout,
                "exit_code": result.exit_code,
            },
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # git_log
    # ------------------------------------------------------------------

    def git_log(self, workspace_id: str, max_entries: int = 10) -> ToolResult:
        """Return the recent commit log (one-line format)."""
        t0 = time.monotonic()
        n = max(1, min(max_entries, 50))
        argv = ["git", "log", f"--max-count={n}", "--oneline"]

        result = self._exec.run(argv, workspace_id)
        ms = (time.monotonic() - t0) * 1000

        if not result.success and "not a git repository" in (result.stderr + result.stdout).lower():
            return ToolResult.ok(
                "git_log",
                "Workspace is not a Git repository",
                data={"is_git_repo": False},
                duration_ms=ms,
            )

        if result.timed_out:
            return ToolResult.fail("git_log", "Git log timed out", duration_ms=ms)

        return ToolResult.ok(
            "git_log",
            "Git log retrieved",
            data={
                "is_git_repo": True,
                "log": result.stdout,
                "exit_code": result.exit_code,
            },
            duration_ms=ms,
        )
