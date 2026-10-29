"""
Tests for WorkspaceManager — including path traversal security.
"""

from __future__ import annotations

import pytest

from backend.tools.workspace import (
    WorkspaceManager,
    WorkspaceNotFoundError,
    WorkspaceSecurityError,
)


@pytest.fixture
def mgr(tmp_path):
    """Fresh WorkspaceManager for each test."""
    return WorkspaceManager(workspace_root=tmp_path)


class TestWorkspaceLifecycle:
    def test_create_returns_id(self, mgr):
        ws_id = mgr.create()
        assert isinstance(ws_id, str)
        assert len(ws_id) > 0

    def test_created_workspace_exists(self, mgr):
        ws_id = mgr.create()
        assert mgr.exists(ws_id)

    def test_nonexistent_workspace_does_not_exist(self, mgr):
        assert not mgr.exists("does-not-exist")

    def test_custom_id_is_used(self, mgr):
        ws_id = mgr.create("my-custom-id")
        assert ws_id == "my-custom-id"
        assert mgr.exists("my-custom-id")

    def test_require_existing_returns_path(self, mgr):
        ws_id = mgr.create()
        path = mgr.require(ws_id)
        assert path.is_dir()

    def test_require_nonexistent_raises(self, mgr):
        with pytest.raises(WorkspaceNotFoundError):
            mgr.require("nonexistent-id")

    def test_destroy_removes_workspace(self, mgr):
        ws_id = mgr.create()
        assert mgr.exists(ws_id)
        mgr.destroy(ws_id)
        assert not mgr.exists(ws_id)

    def test_list_workspaces_empty(self, mgr):
        result = mgr.list_workspaces()
        assert isinstance(result, list)

    def test_list_workspaces_shows_created(self, mgr):
        ws_id = mgr.create()
        assert ws_id in mgr.list_workspaces()


class TestPathSecurity:
    """Security tests — path traversal must always be blocked."""

    def test_valid_simple_path(self, mgr):
        ws_id = mgr.create()
        path = mgr.resolve_path(ws_id, "src/main.py")
        assert str(path).endswith("main.py")

    def test_valid_nested_path(self, mgr):
        ws_id = mgr.create()
        path = mgr.resolve_path(ws_id, "a/b/c/d.py")
        repo = mgr.require(ws_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Verify it is under the repo dir
        assert str(path).startswith(str(repo))

    def test_dot_dot_traversal_rejected(self, mgr):
        ws_id = mgr.create()
        with pytest.raises(WorkspaceSecurityError):
            mgr.resolve_path(ws_id, "../../../etc/passwd")

    def test_double_dot_in_middle_rejected(self, mgr):
        ws_id = mgr.create()
        with pytest.raises(WorkspaceSecurityError):
            mgr.resolve_path(ws_id, "src/../../secrets.txt")

    def test_leading_slash_normalised_and_safe(self, mgr):
        """A leading slash is stripped; the result must still be within workspace."""
        ws_id = mgr.create()
        repo = mgr.require(ws_id)
        # /src/main.py → workspace/repo/src/main.py (still inside)
        path = mgr.resolve_path(ws_id, "/src/main.py")
        assert str(path).startswith(str(repo))

    def test_absolute_host_path_rejected(self, mgr, tmp_path):
        """An absolute path that resolves outside workspace must be rejected."""
        ws_id = mgr.create()
        # The workspace root itself is outside the repository subdirectory
        with pytest.raises(WorkspaceSecurityError):
            mgr.resolve_path(ws_id, str(tmp_path / "escape.txt"))

    def test_nonexistent_workspace_raises_not_found(self, mgr):
        with pytest.raises(WorkspaceNotFoundError):
            mgr.resolve_path("does-not-exist", "file.py")
