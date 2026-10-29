"""
VEXA M3 — Agent Tool Adapters

Bridge between CrewAI tool-calling and the M2 ToolService.

Architecture:

    CrewAI Agent
          |
    VexaTool (crewai.tools.BaseTool subclass)
          |
    ToolService (M2)
          |
    WorkspaceManager / Filesystem / Search / Git / Execution

Design:
- Each tool is scoped to a specific workspace_id (set at agent creation time)
- Tools are grouped into capability sets: InspectTools, ReadTools, WriteTools,
  SearchTools, ExecutionTools
- Agents are given ONLY the capability sets they need
- Tool errors produce safe string messages; they never expose host paths or secrets

NOTE: CrewAI tools use a synchronous string-in/string-out interface.
      We return JSON-serialised dicts so agents can parse structured data.
"""

from __future__ import annotations

import json
from typing import Any


from backend.core.logging import get_logger
from backend.tools.service import ToolService

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(obj: Any) -> str:
    """Serialise to compact JSON, falling back to str() on error."""
    try:
        if hasattr(obj, "model_dump"):
            return json.dumps(obj.model_dump(), default=str)
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _tool_ok(operation: str, data: Any) -> str:
    return json.dumps({"ok": True, "operation": operation, "data": data}, default=str)


def _tool_err(operation: str, message: str) -> str:
    return json.dumps({"ok": False, "operation": operation, "error": message})


# ---------------------------------------------------------------------------
# We use a lazy import strategy: crewai is only imported when these adapters
# are actually instantiated, so the rest of the codebase can be tested
# (for contracts, context, etc.) without requiring crewai to be installed.
# ---------------------------------------------------------------------------


def _get_base_tool():
    """Lazily import BaseTool so unit tests without crewai still work."""
    try:
        from crewai.tools import BaseTool
        return BaseTool
    except ImportError:
        # Fallback stub for environments without crewai (test imports only)
        class _StubBaseTool:
            name: str = ""
            description: str = ""
            def _run(self, *args, **kwargs): return ""
        return _StubBaseTool


# ---------------------------------------------------------------------------
# Individual tool implementations
# ---------------------------------------------------------------------------


class _InspectProjectTool:
    """Inspect project overview (languages, important files, counts)."""
    name = "inspect_project"
    description = (
        "Inspect the software project and return a structured overview of "
        "files, directories, languages, and important configuration files."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self) -> str:
        logger.debug("tool:inspect_project ws=%s", self._ws)
        result = self._svc.inspect_project(self._ws)
        if result.success:
            return _tool_ok("inspect_project", result.data)
        return _tool_err("inspect_project", result.message)


class _ListFilesTool:
    """List files in the workspace."""
    name = "list_files"
    description = (
        "List all files in the workspace. Returns a list of relative paths. "
        "Use path='.' and recursive=True for a full listing."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, path: str = ".", recursive: bool = True) -> str:
        logger.debug("tool:list_files ws=%s path=%s", self._ws, path)
        result = self._svc.list_files(self._ws, path, recursive)
        if result.success:
            return _tool_ok("list_files", result.data)
        return _tool_err("list_files", result.message)


class _ReadFileTool:
    """Read a file from the workspace."""
    name = "read_file"
    description = (
        "Read the text content of a file in the workspace. "
        "Provide the relative path from the workspace root."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, path: str) -> str:
        logger.debug("tool:read_file ws=%s path=%s", self._ws, path)
        result = self._svc.read_file(self._ws, path)
        if result.success:
            return _tool_ok("read_file", result.data)
        return _tool_err("read_file", result.message)


class _WriteFileTool:
    """Write (create or overwrite) a file in the workspace."""
    name = "write_file"
    description = (
        "Create or overwrite a text file in the workspace. "
        "Provide the relative path and the full new content. "
        "Prefer patch_file for targeted edits."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, path: str, content: str) -> str:
        logger.debug("tool:write_file ws=%s path=%s", self._ws, path)
        result = self._svc.write_file(self._ws, path, content)
        if result.success:
            return _tool_ok("write_file", result.data)
        return _tool_err("write_file", result.message)


class _PatchFileTool:
    """Replace an exact substring in a workspace file."""
    name = "patch_file"
    description = (
        "Replace an exact occurrence of old_text with new_text in a workspace file. "
        "The old_text must exist exactly once in the file. "
        "Use this for targeted edits rather than full rewrites."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, path: str, old_text: str, new_text: str) -> str:
        logger.debug("tool:patch_file ws=%s path=%s", self._ws, path)
        result = self._svc.patch_file(self._ws, path, old_text, new_text)
        if result.success:
            return _tool_ok("patch_file", result.data)
        return _tool_err("patch_file", result.message)


class _SearchCodeTool:
    """Search for text patterns across workspace source files."""
    name = "search_code"
    description = (
        "Search for a text pattern across all source files in the workspace. "
        "Returns matching lines with file path and line number. "
        "Use for locating functions, classes, variable usage, etc."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, query: str, case_sensitive: bool = True) -> str:
        logger.debug("tool:search_code ws=%s query=%s", self._ws, query)
        result = self._svc.search_code(self._ws, query, case_sensitive=case_sensitive)
        if result.success:
            return _tool_ok("search_code", result.data)
        return _tool_err("search_code", result.message)


class _GitStatusTool:
    """Get git status of the workspace."""
    name = "git_status"
    description = (
        "Return the current git status of the workspace repository. "
        "Shows modified, untracked, and staged files."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self) -> str:
        logger.debug("tool:git_status ws=%s", self._ws)
        result = self._svc.git_status(self._ws)
        if result.success:
            return _tool_ok("git_status", result.data)
        return _tool_err("git_status", result.message)


class _GitDiffTool:
    """Get git diff of the workspace."""
    name = "git_diff"
    description = "Return the git diff showing what has changed in the workspace."

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, staged: bool = False) -> str:
        logger.debug("tool:git_diff ws=%s", self._ws)
        result = self._svc.git_diff(self._ws, staged)
        if result.success:
            return _tool_ok("git_diff", result.data)
        return _tool_err("git_diff", result.message)


class _RunTestsTool:
    """Execute pytest inside the workspace."""
    name = "run_tests"
    description = (
        "Run the project test suite using pytest. "
        "Returns exit_code, stdout, stderr, and duration_ms. "
        "exit_code 0 means all tests passed."
    )

    def __init__(self, svc: ToolService, workspace_id: str) -> None:
        self._svc = svc
        self._ws = workspace_id

    def run(self, test_path: str = ".") -> str:
        logger.debug("tool:run_tests ws=%s path=%s", self._ws, test_path)
        result = self._svc.run_tests(self._ws, test_path=test_path, extra_args=[])
        return json.dumps({
            "ok": result.success,
            "operation": "run_tests",
            "exit_code": result.exit_code,
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
        })


# ---------------------------------------------------------------------------
# Tool capability bundles (grouped by agent role)
# ---------------------------------------------------------------------------


class WorkspaceToolKit:
    """
    A bundle of tool instances scoped to a specific workspace.

    Each agent receives only the tools it needs:
    - ProjectAnalyst: inspect, list, read, search, git_status
    - Planner: inspect, list, read, search
    - Coder: read, search, write, patch
    - Tester: run_tests
    - Debugger: read, search, patch, run_tests
    - Verifier: inspect, read, git_diff, (run_tests for final check)
    """

    def __init__(self, svc: ToolService, workspace_id: str, ctx: Any = None) -> None:
        self._svc = svc
        self._ws = workspace_id
        self.ctx = ctx  # RunContext: tool calls are traced against its observer
        self.mcp: dict[str, Any] = {}  # server name → MCPServerBridge (real mode, transport=mcp)

        # Instantiate all tools
        self.inspect_project = _InspectProjectTool(svc, workspace_id)
        self.list_files = _ListFilesTool(svc, workspace_id)
        self.read_file = _ReadFileTool(svc, workspace_id)
        self.write_file = _WriteFileTool(svc, workspace_id)
        self.patch_file = _PatchFileTool(svc, workspace_id)
        self.search_code = _SearchCodeTool(svc, workspace_id)
        self.git_status = _GitStatusTool(svc, workspace_id)
        self.git_diff = _GitDiffTool(svc, workspace_id)
        self.run_tests = _RunTestsTool(svc, workspace_id)
        for tool in (self.inspect_project, self.list_files, self.read_file, self.write_file, self.patch_file,
                     self.search_code, self.git_status, self.git_diff, self.run_tests):
            tool.ctx = ctx

    def _for(self, agent: str) -> list:
        from backend.guardrails import TOOL_POLICY
        allowed = TOOL_POLICY[agent]
        return [t for t in (self.inspect_project, self.list_files, self.read_file, self.write_file,
                            self.patch_file, self.search_code, self.git_status, self.git_diff, self.run_tests)
                if t.name in allowed]

    # Bundles are derived from guardrails.TOOL_POLICY (single source of truth).
    def for_project_analyst(self) -> list:
        return self._for("ProjectAnalyst")

    def for_planner(self) -> list:
        return self._for("Planner")

    def for_coder(self) -> list:
        return self._for("Coder")

    def for_tester(self) -> list:
        return self._for("Tester")

    def for_debugger(self) -> list:
        return self._for("Debugger")

    def for_verifier(self) -> list:
        return self._for("Verifier")
