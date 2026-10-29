"""
VEXA workspace MCP server (stdio).

Exposes the M2 tool layer — file I/O, code search, read-only git and the
sandboxed test runner — as MCP tools. One server process is started per run
and is bound to exactly ONE workspace given on the command line, so a client
cannot reach any other workspace through it (least privilege). All path,
command and sandbox checks of ToolService still apply inside the server.

Run manually (for MCP inspectors):
    python -m backend.mcp_servers.workspace_server --workspace-root workspaces --workspace-id my-ws
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


def build_server(workspace_root: str, workspace_id: str) -> FastMCP:
    os.environ["WORKSPACE_ROOT"] = workspace_root
    from backend.tools.service import ToolService

    svc = ToolService(workspace_root=workspace_root)
    if not svc.workspace_exists(workspace_id):
        raise SystemExit(f"workspace '{workspace_id}' does not exist under {workspace_root}")

    mcp = FastMCP(
        "vexa-workspace",
        instructions=f"Tools operating on a single VEXA workspace ({workspace_id}). Paths are workspace-relative.",
    )
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    writes = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    def _result(op: str, res: Any) -> dict[str, Any]:
        if getattr(res, "success", False):
            return {"ok": True, "operation": op, "data": res.data}
        return {"ok": False, "operation": op, "error": res.message}

    @mcp.tool(annotations=read_only)
    def inspect_project() -> dict[str, Any]:
        """Structured overview of the project: file counts, languages, important files."""
        return _result("inspect_project", svc.inspect_project(workspace_id))

    @mcp.tool(annotations=read_only)
    def list_files(path: str = ".", recursive: bool = True) -> dict[str, Any]:
        """List files in the workspace. Use path='.' and recursive=True for everything."""
        return _result("list_files", svc.list_files(workspace_id, path, recursive))

    @mcp.tool(annotations=read_only)
    def read_file(path: str) -> dict[str, Any]:
        """Read a text file given its workspace-relative path."""
        return _result("read_file", svc.read_file(workspace_id, path))

    @mcp.tool(annotations=writes)
    def write_file(path: str, content: str) -> dict[str, Any]:
        """Create or overwrite a text file with the full new content."""
        return _result("write_file", svc.write_file(workspace_id, path, content))

    @mcp.tool(annotations=writes)
    def patch_file(path: str, old_text: str, new_text: str) -> dict[str, Any]:
        """Replace the single exact occurrence of old_text with new_text in a file."""
        return _result("patch_file", svc.patch_file(workspace_id, path, old_text, new_text))

    @mcp.tool(annotations=read_only)
    def search_code(query: str, case_sensitive: bool = True) -> dict[str, Any]:
        """Search source files for a text/regex pattern; returns file, line number and line."""
        return _result("search_code", svc.search_code(workspace_id, query, case_sensitive=case_sensitive))

    @mcp.tool(annotations=read_only)
    def git_status() -> dict[str, Any]:
        """Short git status of the workspace (if it is a git repository)."""
        return _result("git_status", svc.git_status(workspace_id))

    @mcp.tool(annotations=read_only)
    def git_diff(staged: bool = False) -> dict[str, Any]:
        """git diff of the workspace (unstaged by default)."""
        return _result("git_diff", svc.git_diff(workspace_id, staged))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def run_tests(test_path: str = ".", detailed_report: bool = False) -> dict[str, Any]:
        """Run the test suite with pytest in the sandbox. exit_code 0 = all passed, 5 = no tests.

        detailed_report=True adds per-test outcome lines (-q --tb=short -rA)."""
        r = svc.run_tests(workspace_id, test_path=test_path,
                          extra_args=["-q", "--tb=short", "-rA"] if detailed_report else [])
        return {
            "ok": r.exit_code is not None, "operation": "run_tests", "exit_code": r.exit_code,
            "success": r.success, "stdout": r.stdout, "stderr": r.stderr,
            "duration_ms": r.duration_ms, "timed_out": r.timed_out,
        }

    return mcp


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace-root", required=True)
    p.add_argument("--workspace-id", required=True)
    args = p.parse_args()
    build_server(os.path.abspath(args.workspace_root), args.workspace_id).run("stdio")


if __name__ == "__main__":
    main()
