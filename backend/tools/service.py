"""
VEXA Tool Layer — ToolService

Façade that wires together all tool implementations.

Future CrewAI agents and MCP wrappers will interact with this service
rather than instantiating individual tool classes.

Usage::

    svc = ToolService()
    ws_id = svc.create_workspace()
    result = svc.read_file(ws_id, "src/main.py")
    exec_result = svc.run_tests(ws_id)
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.core.logging import get_logger
from backend.tools.execution import ExecResult, check_pytest_args, create_executor
from backend.tools.filesystem import FilesystemTools
from backend.tools.git import GitTools
from backend.tools.models import ToolResult
from backend.tools.search import SearchTools
from backend.tools.workspace import WorkspaceManager, WorkspaceNotFoundError, WorkspaceSecurityError

logger = get_logger(__name__)


class ToolService:
    """
    Central service for all VEXA tool operations.

    One instance is created per application lifetime (or per test).
    The workspace_root may be overridden in tests without touching settings.
    """

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._manager = WorkspaceManager(workspace_root)
        self._fs = FilesystemTools(self._manager)
        self._search = SearchTools(self._manager)
        self._git = GitTools(self._manager)
        self._executor = create_executor(self._manager)

    # ------------------------------------------------------------------
    # Workspace lifecycle
    # ------------------------------------------------------------------

    def create_workspace(self, workspace_id: str | None = None, output_path: str | None = None) -> str:
        return self._manager.create(workspace_id, output_path=output_path)

    def workspace_exists(self, workspace_id: str) -> bool:
        return self._manager.exists(workspace_id)

    def destroy_workspace(self, workspace_id: str) -> None:
        self._manager.destroy(workspace_id)

    def list_workspaces(self) -> list[str]:
        return self._manager.list_workspaces()

    def workspace_info(self, workspace_id: str) -> dict:
        """Return basic info about a workspace."""
        if not self._manager.exists(workspace_id):
            raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' does not exist")
        repo_dir = self._manager.require(workspace_id)
        return {
            "workspace_id": workspace_id,
            "repository_path_relative": str(Path(workspace_id) / WorkspaceManager.REPO_SUBDIR),
            "exists": True,
        }

    # ------------------------------------------------------------------
    # Filesystem delegation
    # ------------------------------------------------------------------

    def list_files(self, workspace_id: str, path: str = ".", recursive: bool = True) -> ToolResult:
        return self._fs.list_files(workspace_id, path, recursive)

    def read_file(self, workspace_id: str, path: str) -> ToolResult:
        return self._fs.read_file(workspace_id, path)

    def write_file(self, workspace_id: str, path: str, content: str) -> ToolResult:
        return self._fs.write_file(workspace_id, path, content)

    def patch_file(
        self,
        workspace_id: str,
        path: str,
        old_text: str,
        new_text: str,
        allow_multiple: bool = False,
    ) -> ToolResult:
        return self._fs.patch_file(workspace_id, path, old_text, new_text, allow_multiple)

    def delete_file(self, workspace_id: str, path: str) -> ToolResult:
        return self._fs.delete_file(workspace_id, path)

    def inspect_project(self, workspace_id: str) -> ToolResult:
        return self._fs.inspect_project(workspace_id)

    # ------------------------------------------------------------------
    # Search delegation
    # ------------------------------------------------------------------

    def search_code(
        self,
        workspace_id: str,
        query: str,
        *,
        case_sensitive: bool = True,
        file_glob: str = "*",
        context_lines: int = 1,
    ) -> ToolResult:
        return self._search.search_code(
            workspace_id, query,
            case_sensitive=case_sensitive,
            file_glob=file_glob,
            context_lines=context_lines,
        )

    # ------------------------------------------------------------------
    # Git delegation
    # ------------------------------------------------------------------

    def git_status(self, workspace_id: str) -> ToolResult:
        return self._git.git_status(workspace_id)

    def git_diff(self, workspace_id: str, staged: bool = False) -> ToolResult:
        return self._git.git_diff(workspace_id, staged)

    def git_log(self, workspace_id: str, max_entries: int = 10) -> ToolResult:
        return self._git.git_log(workspace_id, max_entries)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_tests(
        self,
        workspace_id: str,
        test_path: str = ".",
        extra_args: list[str] | None = None,
        timeout: int | None = None,
    ) -> ExecResult:
        """
        Run pytest inside the workspace.

        Parameters
        ----------
        test_path:
            Relative path to tests directory or test file. Defaults to workspace root.
        extra_args:
            Additional pytest arguments, e.g. ["-v", "--tb=short"].
        timeout:
            Seconds before the test run is killed. Uses config default if None.
        """
        extra_args = list(extra_args or [])
        deny = check_pytest_args([test_path, *extra_args])
        if deny is None:
            try:
                self._manager.resolve_path(workspace_id, test_path)
            except WorkspaceSecurityError as exc:
                deny = str(exc)
        if deny:
            return ExecResult(
                success=False, operation="run_tests", message=f"Command rejected: {deny}",
                exit_code=None, error=deny,
            )

        # Prefer the venv python / pytest if present, fall back to system pytest
        repo_dir = self._manager.require(workspace_id)
        venv_pytest = self._find_venv_executable(repo_dir, "pytest")
        if venv_pytest:
            argv = [str(venv_pytest), test_path]
        else:
            argv = [sys.executable, "-m", "pytest", test_path]

        argv += extra_args

        # For pytest we use python or the venv executable — allowlist check
        # uses executable name. sys.executable name should be "python*".
        result = self._executor.run(argv, workspace_id, timeout=timeout)
        result.operation = "run_tests"
        return result

    def run_command(
        self,
        workspace_id: str,
        argv: list[str],
        timeout: int | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> ExecResult:
        """
        Run a policy-checked command inside the workspace.

        Not exposed to agents or the HTTP API. Only ``python -m pytest|ruff|mypy``,
        ``pytest``/``ruff``/``mypy`` and read-only git sub-commands pass the policy
        (see ``backend.tools.execution.check_command``).
        """
        return self._executor.run(argv, workspace_id, timeout=timeout, env_extra=env_extra)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @property
    def sandbox_backend(self) -> str:
        return self._executor.name

    @staticmethod
    def _find_venv_executable(repo_dir: Path, name: str) -> Path | None:
        """Look for a virtualenv-installed executable next to the repo dir."""
        # Common venv locations relative to repo parent
        parent = repo_dir.parent
        candidates = [
            parent / ".venv" / "Scripts" / name,          # Windows
            parent / ".venv" / "Scripts" / f"{name}.exe",
            parent / ".venv" / "bin" / name,               # Unix
            parent / "venv" / "Scripts" / name,
            parent / "venv" / "bin" / name,
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None
