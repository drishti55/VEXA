"""
VEXA M3 — Tool Adapter Tests

Tests for WorkspaceToolKit and all individual tool adapters.
These test the adapter layer against a real ToolService (no LLM needed).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.agents.tools import (
    WorkspaceToolKit,
    _InspectProjectTool,
    _ListFilesTool,
    _PatchFileTool,
    _ReadFileTool,
    _RunTestsTool,
    _SearchCodeTool,
    _WriteFileTool,
    _GitStatusTool,
    _GitDiffTool,
)
from backend.tools.service import ToolService

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture(scope="module")
def svc_and_ws(tmp_path_factory):
    """Shared ToolService + workspace for all tool adapter tests."""
    root = tmp_path_factory.mktemp("adapter_tests")
    svc = ToolService(workspace_root=str(root))
    ws_id = svc.create_workspace()
    from backend.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager(workspace_root=root)
    repo = mgr.require(ws_id)
    shutil.copytree(str(FIXTURE_PROJECT), str(repo), dirs_exist_ok=True)
    return svc, ws_id


@pytest.fixture(scope="module")
def kit(svc_and_ws):
    svc, ws_id = svc_and_ws
    return WorkspaceToolKit(svc, ws_id)


# ---------------------------------------------------------------------------
# WorkspaceToolKit capability bundles
# ---------------------------------------------------------------------------


class TestWorkspaceToolKitBundles:
    def test_for_project_analyst(self, kit):
        tools = kit.for_project_analyst()
        names = {t.name for t in tools}
        assert "inspect_project" in names
        assert "list_files" in names
        assert "read_file" in names
        assert "search_code" in names
        assert "git_status" in names
        # Should NOT have write tools
        assert "write_file" not in names
        assert "patch_file" not in names

    def test_for_coder_has_write_tools(self, kit):
        tools = kit.for_coder()
        names = {t.name for t in tools}
        assert "write_file" in names
        assert "patch_file" in names
        assert "read_file" in names

    def test_for_tester_has_run_tests(self, kit):
        tools = kit.for_tester()
        names = {t.name for t in tools}
        assert "run_tests" in names
        # Tester should NOT have write access
        assert "write_file" not in names
        assert "patch_file" not in names

    def test_for_debugger_has_patch_and_tests(self, kit):
        tools = kit.for_debugger()
        names = {t.name for t in tools}
        assert "patch_file" in names
        assert "run_tests" in names
        assert "read_file" in names

    def test_for_verifier_has_inspect_and_diff(self, kit):
        tools = kit.for_verifier()
        names = {t.name for t in tools}
        assert "inspect_project" in names
        assert "git_diff" in names
        assert "run_tests" in names


# ---------------------------------------------------------------------------
# Individual tool tests
# ---------------------------------------------------------------------------


class TestInspectProjectTool:
    def test_returns_json_ok(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _InspectProjectTool(svc, ws_id)
        result = json.loads(tool.run())
        assert result["ok"] is True
        assert "data" in result

    def test_data_has_language_info(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _InspectProjectTool(svc, ws_id)
        result = json.loads(tool.run())
        data = result["data"]
        assert "languages" in data
        assert "python" in data["languages"]


class TestListFilesTool:
    def test_finds_fixture_files(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _ListFilesTool(svc, ws_id)
        result = json.loads(tool.run())
        assert result["ok"] is True
        paths = [f["path"] for f in result["data"]]
        assert any("calculator.py" in p for p in paths)

    def test_nonrecursive_flag(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _ListFilesTool(svc, ws_id)
        result = json.loads(tool.run(".", False))
        assert result["ok"] is True


class TestReadFileTool:
    def test_reads_calculator(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _ReadFileTool(svc, ws_id)
        result = json.loads(tool.run("src/calculator.py"))
        assert result["ok"] is True
        assert "def add" in result["data"]["content"]

    def test_nonexistent_returns_error(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _ReadFileTool(svc, ws_id)
        result = json.loads(tool.run("does_not_exist.py"))
        assert result["ok"] is False

    def test_traversal_rejected(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _ReadFileTool(svc, ws_id)
        result = json.loads(tool.run("../../secrets.txt"))
        assert result["ok"] is False


class TestWriteFileTool:
    def test_creates_new_file(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _WriteFileTool(svc, ws_id)
        result = json.loads(tool.run("test_write_adapter.txt", "hello from adapter"))
        assert result["ok"] is True

    def test_traversal_rejected(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _WriteFileTool(svc, ws_id)
        result = json.loads(tool.run("../escape.txt", "bad"))
        assert result["ok"] is False


class TestPatchFileTool:
    def test_patches_successfully(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        # Write a target file
        svc.write_file(ws_id, "patch_target.py", "x = 1\ny = 2\n")
        tool = _PatchFileTool(svc, ws_id)
        result = json.loads(tool.run("patch_target.py", "x = 1", "x = 99"))
        assert result["ok"] is True

    def test_missing_old_text_fails(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        svc.write_file(ws_id, "nopatch.py", "a = 1\n")
        tool = _PatchFileTool(svc, ws_id)
        result = json.loads(tool.run("nopatch.py", "NOTHERE", "x"))
        assert result["ok"] is False


class TestSearchCodeTool:
    def test_finds_function(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _SearchCodeTool(svc, ws_id)
        result = json.loads(tool.run("def add"))
        assert result["ok"] is True
        assert len(result["data"]["matches"]) >= 1

    def test_no_match(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _SearchCodeTool(svc, ws_id)
        result = json.loads(tool.run("UNLIKELY_SYMBOL_XYZ123"))
        assert result["ok"] is True
        assert len(result["data"]["matches"]) == 0


class TestRunTestsTool:
    def test_runs_sample_tests(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        tool = _RunTestsTool(svc, ws_id)
        result = json.loads(tool.run("tests/"))
        assert result["exit_code"] == 0
        assert result["success"] is True

    def test_failing_test_captured(self, svc_and_ws):
        svc, ws_id = svc_and_ws
        svc.write_file(ws_id, "test_fail_adapter.py", "def test_fail(): assert False\n")
        tool = _RunTestsTool(svc, ws_id)
        result = json.loads(tool.run("test_fail_adapter.py"))
        assert result["exit_code"] != 0
        assert result["success"] is False
