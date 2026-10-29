"""
Tests for filesystem tools, search, git tools, and execution engine.

Uses the session-scoped sample_project_workspace fixture which is pre-populated
with the tests/fixtures/sample_project files.
"""

from __future__ import annotations

import sys
import time

import pytest


# ---------------------------------------------------------------------------
# Filesystem — list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_returns_success(self, tool_service, sample_project_workspace):
        result = tool_service.list_files(sample_project_workspace)
        assert result.success is True

    def test_finds_calculator_py(self, tool_service, sample_project_workspace):
        result = tool_service.list_files(sample_project_workspace)
        paths = [f["path"] for f in result.data]
        assert any("calculator.py" in p for p in paths)

    def test_finds_test_file(self, tool_service, sample_project_workspace):
        result = tool_service.list_files(sample_project_workspace)
        paths = [f["path"] for f in result.data]
        assert any("test_calculator.py" in p for p in paths)

    def test_non_recursive_root_only(self, tool_service, sample_project_workspace):
        result = tool_service.list_files(sample_project_workspace, ".", recursive=False)
        assert result.success is True
        # Entries should only be direct children
        for f in result.data:
            assert "/" not in f["path"] or f["is_dir"]

    def test_blank_workspace_returns_empty(self, tool_service, workspace_id):
        result = tool_service.list_files(workspace_id)
        assert result.success is True
        assert result.data == []

    def test_unknown_workspace_fails(self, tool_service):
        result = tool_service.list_files("no-such-ws")
        assert result.success is False


# ---------------------------------------------------------------------------
# Filesystem — read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_reads_calculator(self, tool_service, sample_project_workspace):
        result = tool_service.read_file(sample_project_workspace, "src/calculator.py")
        assert result.success is True
        assert "def add" in result.data["content"]

    def test_reads_readme(self, tool_service, sample_project_workspace):
        result = tool_service.read_file(sample_project_workspace, "README.md")
        assert result.success is True
        assert "calculator" in result.data["content"].lower()

    def test_nonexistent_file_fails(self, tool_service, sample_project_workspace):
        result = tool_service.read_file(sample_project_workspace, "doesnotexist.py")
        assert result.success is False

    def test_traversal_rejected(self, tool_service, sample_project_workspace):
        result = tool_service.read_file(sample_project_workspace, "../../secrets.txt")
        assert result.success is False
        assert result.error is not None

    def test_unknown_workspace_fails(self, tool_service):
        result = tool_service.read_file("no-such-ws", "file.py")
        assert result.success is False

    def test_binary_extension_rejected(self, tool_service, sample_project_workspace):
        # Write a fake .pyc file
        tool_service.write_file(sample_project_workspace, "module.pyc", "binary content")
        result = tool_service.read_file(sample_project_workspace, "module.pyc")
        assert result.success is False
        assert "binary" in result.message.lower()


# ---------------------------------------------------------------------------
# Filesystem — write_file / patch_file / delete_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    def test_creates_new_file(self, tool_service, workspace_id):
        result = tool_service.write_file(workspace_id, "hello.txt", "Hello VEXA")
        assert result.success is True
        assert result.data["created"] is True

    def test_overwrites_existing_file(self, tool_service, workspace_id):
        tool_service.write_file(workspace_id, "overwrite.txt", "v1")
        result = tool_service.write_file(workspace_id, "overwrite.txt", "v2")
        assert result.success is True
        assert result.data["created"] is False

    def test_creates_parent_dirs(self, tool_service, workspace_id):
        result = tool_service.write_file(workspace_id, "deep/nested/dir/file.py", "# ok")
        assert result.success is True

    def test_traversal_rejected(self, tool_service, workspace_id):
        result = tool_service.write_file(workspace_id, "../../evil.txt", "bad")
        assert result.success is False


class TestPatchFile:
    def test_basic_patch(self, tool_service, workspace_id):
        tool_service.write_file(workspace_id, "patch_me.py", "x = 1\ny = 2\n")
        result = tool_service.patch_file(workspace_id, "patch_me.py", "x = 1", "x = 99")
        assert result.success is True
        # Verify content changed
        read = tool_service.read_file(workspace_id, "patch_me.py")
        assert "x = 99" in read.data["content"]

    def test_old_text_not_found_fails(self, tool_service, workspace_id):
        tool_service.write_file(workspace_id, "nopatch.py", "a = 1\n")
        result = tool_service.patch_file(workspace_id, "nopatch.py", "NOTHERE", "x")
        assert result.success is False

    def test_ambiguous_multiple_occurrences_rejected(self, tool_service, workspace_id):
        tool_service.write_file(workspace_id, "ambig.py", "x = 1\nx = 1\n")
        result = tool_service.patch_file(workspace_id, "ambig.py", "x = 1", "x = 99")
        assert result.success is False

    def test_allow_multiple_flag(self, tool_service, workspace_id):
        tool_service.write_file(workspace_id, "multi.py", "x = 1\nx = 1\n")
        result = tool_service.patch_file(workspace_id, "multi.py", "x = 1", "x = 99", allow_multiple=True)
        assert result.success is True
        assert result.data["replacements"] == 2


class TestDeleteFile:
    def test_delete_existing_file(self, tool_service, workspace_id):
        tool_service.write_file(workspace_id, "todelete.txt", "bye")
        result = tool_service.delete_file(workspace_id, "todelete.txt")
        assert result.success is True

    def test_delete_nonexistent_fails(self, tool_service, workspace_id):
        result = tool_service.delete_file(workspace_id, "ghost.txt")
        assert result.success is False

    def test_delete_traversal_rejected(self, tool_service, workspace_id):
        result = tool_service.delete_file(workspace_id, "../../important.txt")
        assert result.success is False


# ---------------------------------------------------------------------------
# Project inspection
# ---------------------------------------------------------------------------


class TestInspectProject:
    def test_returns_success(self, tool_service, sample_project_workspace):
        result = tool_service.inspect_project(sample_project_workspace)
        assert result.success is True

    def test_detects_python_files(self, tool_service, sample_project_workspace):
        result = tool_service.inspect_project(sample_project_workspace)
        langs = result.data["languages"]
        assert "python" in langs
        assert langs["python"] >= 2  # calculator.py + test_calculator.py

    def test_detects_important_files(self, tool_service, sample_project_workspace):
        result = tool_service.inspect_project(sample_project_workspace)
        important = result.data["important_files"]
        assert any("README" in f for f in important)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearchCode:
    def test_finds_function_name(self, tool_service, sample_project_workspace):
        result = tool_service.search_code(sample_project_workspace, "def add")
        assert result.success is True
        matches = result.data["matches"]
        assert len(matches) >= 1
        assert any("calculator.py" in m["file"] for m in matches)

    def test_finds_in_tests(self, tool_service, sample_project_workspace):
        result = tool_service.search_code(sample_project_workspace, "ZeroDivisionError")
        assert result.success is True
        assert len(result.data["matches"]) >= 1

    def test_no_results_for_missing_term(self, tool_service, sample_project_workspace):
        result = tool_service.search_code(sample_project_workspace, "DOES_NOT_EXIST_XYZ123")
        assert result.success is True
        assert len(result.data["matches"]) == 0

    def test_case_insensitive_search(self, tool_service, sample_project_workspace):
        result = tool_service.search_code(
            sample_project_workspace, "DEF ADD", case_sensitive=False
        )
        assert result.success is True
        assert len(result.data["matches"]) >= 1

    def test_file_glob_filter(self, tool_service, sample_project_workspace):
        result = tool_service.search_code(
            sample_project_workspace, "import", file_glob="*.md"
        )
        # README.md doesn't have "import", test_calculator.py does — glob should exclude .py
        for m in result.data["matches"]:
            assert m["file"].endswith(".md")

    def test_empty_query_fails(self, tool_service, sample_project_workspace):
        result = tool_service.search_code(sample_project_workspace, "")
        assert result.success is False


# ---------------------------------------------------------------------------
# Git tools
# ---------------------------------------------------------------------------


class TestGitTools:
    def test_status_non_git_repo(self, tool_service, sample_project_workspace):
        """sample_project has no .git dir — should return graceful response."""
        result = tool_service.git_status(sample_project_workspace)
        # Either it's not a git repo (ok) or it succeeds (if git init was run)
        assert result.success is True  # should succeed either way (graceful)

    def test_diff_non_git_repo(self, tool_service, sample_project_workspace):
        result = tool_service.git_diff(sample_project_workspace)
        assert result.success is True

    def test_log_non_git_repo(self, tool_service, sample_project_workspace):
        result = tool_service.git_log(sample_project_workspace)
        assert result.success is True


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------


class TestRunTests:
    def test_runs_sample_project_tests(self, tool_service, sample_project_workspace):
        result = tool_service.run_tests(sample_project_workspace, test_path="tests/")
        # All 9 sample tests should pass
        assert result.exit_code == 0
        assert result.success is True
        assert "passed" in result.stdout.lower()

    def test_captures_stdout(self, tool_service, sample_project_workspace):
        result = tool_service.run_tests(sample_project_workspace, test_path="tests/")
        assert len(result.stdout) > 0

    def test_captures_duration(self, tool_service, sample_project_workspace):
        result = tool_service.run_tests(sample_project_workspace, test_path="tests/")
        assert result.duration_ms > 0

    def test_failing_test_captured(self, tool_service, workspace_id):
        """Write a deliberately failing test and confirm exit_code != 0."""
        tool_service.write_file(
            workspace_id,
            "test_fail.py",
            "def test_always_fail():\n    assert False, 'intentional failure'\n",
        )
        result = tool_service.run_tests(workspace_id, test_path="test_fail.py")
        assert result.exit_code != 0
        assert result.success is False
        assert "failed" in result.stdout.lower() or "FAILED" in result.stdout


# ---------------------------------------------------------------------------
# Execution — allowlist / timeout
# ---------------------------------------------------------------------------


class TestExecution:
    def test_blocked_command_rejected(self, tool_service, workspace_id):
        result = tool_service.run_command(workspace_id, ["rm", "-rf", "/"])
        assert result.success is False
        assert result.exit_code is None  # rejected before execution

    def test_blocked_powershell_rejected(self, tool_service, workspace_id):
        result = tool_service.run_command(workspace_id, ["powershell", "-Command", "echo hi"])
        assert result.success is False

    def test_timeout_triggers(self, tool_service, workspace_id):
        # A test that sleeps longer than the timeout (inline `python -c` is blocked)
        tool_service.write_file(workspace_id, "test_sleep.py",
                                "import time\ndef test_sleep():\n    time.sleep(30)\n")
        result = tool_service.run_tests(workspace_id, test_path="test_sleep.py", timeout=2)
        tool_service.delete_file(workspace_id, "test_sleep.py")
        assert result.timed_out is True
        assert result.success is False
