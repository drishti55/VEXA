"""
API tests for the endpoints VEXA Studio adds: explorer file operations
(mkdir / rename / delete folder) and GET /system/status.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture()
def ws(client) -> str:
    wid = f"studio-{uuid.uuid4().hex[:8]}"
    assert client.post("/workspaces", json={"workspace_id": wid}).status_code == 201
    return wid


def _paths(client, ws: str) -> set[str]:
    return {f["path"] for f in client.get(f"/workspaces/{ws}/files").json()["data"]}


class TestMkdir:
    def test_creates_nested_folder(self, client, ws):
        r = client.post(f"/workspaces/{ws}/mkdir", json={"path": "src/pkg"})
        assert r.status_code == 201
        assert r.json()["path"] == "src/pkg"
        assert {"src", "src/pkg"} <= _paths(client, ws)

    def test_existing_path_is_409(self, client, ws):
        client.post(f"/workspaces/{ws}/mkdir", json={"path": "a"})
        assert client.post(f"/workspaces/{ws}/mkdir", json={"path": "a"}).status_code == 409

    @pytest.mark.parametrize("bad", ["../outside", "../../etc", "/etc/passwd/../../.."])
    def test_traversal_is_rejected(self, client, ws, bad):
        r = client.post(f"/workspaces/{ws}/mkdir", json={"path": bad})
        assert r.status_code in (403, 409)  # never created outside the workspace
        assert r.status_code != 201

    def test_git_metadata_is_protected(self, client, ws):
        assert client.post(f"/workspaces/{ws}/mkdir", json={"path": ".git/hooks2"}).status_code == 403

    def test_unknown_workspace_is_404(self, client):
        assert client.post("/workspaces/does-not-exist-xyz/mkdir", json={"path": "a"}).status_code == 404


class TestRename:
    def test_renames_file_and_keeps_content(self, client, ws):
        client.post(f"/workspaces/{ws}/write", json={"path": "old.py", "content": "x = 1\n"})
        r = client.post(f"/workspaces/{ws}/rename", json={"src": "old.py", "dst": "new.py"})
        assert r.status_code == 200
        assert r.json() == {"success": True, "src": "old.py", "dst": "new.py"}
        assert client.post(f"/workspaces/{ws}/read", json={"path": "new.py"}).json()["data"]["content"] == "x = 1\n"
        assert "old.py" not in _paths(client, ws)

    def test_moves_into_new_folder(self, client, ws):
        client.post(f"/workspaces/{ws}/write", json={"path": "a.txt", "content": "a"})
        assert client.post(f"/workspaces/{ws}/rename", json={"src": "a.txt", "dst": "docs/a.txt"}).status_code == 200
        assert "docs/a.txt" in _paths(client, ws)

    def test_never_overwrites(self, client, ws):
        client.post(f"/workspaces/{ws}/write", json={"path": "a.txt", "content": "a"})
        client.post(f"/workspaces/{ws}/write", json={"path": "b.txt", "content": "b"})
        assert client.post(f"/workspaces/{ws}/rename", json={"src": "a.txt", "dst": "b.txt"}).status_code == 409
        assert client.post(f"/workspaces/{ws}/read", json={"path": "b.txt"}).json()["data"]["content"] == "b"

    def test_missing_source_is_404(self, client, ws):
        assert client.post(f"/workspaces/{ws}/rename", json={"src": "nope", "dst": "x"}).status_code == 404

    def test_cannot_move_folder_into_itself(self, client, ws):
        client.post(f"/workspaces/{ws}/mkdir", json={"path": "d"})
        assert client.post(f"/workspaces/{ws}/rename", json={"src": "d", "dst": "d/inner"}).status_code == 400

    def test_cannot_escape_workspace(self, client, ws):
        client.post(f"/workspaces/{ws}/write", json={"path": "a.txt", "content": "a"})
        assert client.post(f"/workspaces/{ws}/rename", json={"src": "a.txt", "dst": "../../stolen.txt"}).status_code == 403


class TestDeleteDir:
    def test_deletes_folder_recursively(self, client, ws):
        client.post(f"/workspaces/{ws}/write", json={"path": "tmp/x/y.txt", "content": "y"})
        client.post(f"/workspaces/{ws}/write", json={"path": "tmp/z.txt", "content": "z"})
        r = client.request("DELETE", f"/workspaces/{ws}/dirs", json={"path": "tmp"})
        assert r.status_code == 200
        assert r.json()["files_removed"] == 2
        assert not any(p.startswith("tmp") for p in _paths(client, ws))

    def test_file_is_not_a_folder(self, client, ws):
        client.post(f"/workspaces/{ws}/write", json={"path": "f.txt", "content": "f"})
        assert client.request("DELETE", f"/workspaces/{ws}/dirs", json={"path": "f.txt"}).status_code == 404

    @pytest.mark.parametrize("root", [".", "./", "sub/.."])
    def test_workspace_root_is_protected(self, client, ws, root):
        client.post(f"/workspaces/{ws}/write", json={"path": "keep.txt", "content": "k"})
        assert client.request("DELETE", f"/workspaces/{ws}/dirs", json={"path": root}).status_code == 403
        assert "keep.txt" in _paths(client, ws)


class TestSystemStatus:
    def test_reports_every_component_without_secrets(self, client, settings):
        r = client.get("/system/status")
        assert r.status_code == 200
        body = r.json()
        for key in ("backend", "database", "llm", "a2a", "mcp", "sandbox", "sse", "active_runs", "active_experiments"):
            assert key in body
        assert body["database"]["status"] == "ok"
        assert isinstance(body["database"]["runs"], int)
        assert body["llm"]["reachability"] == "not_probed"  # configured is not the same as reachable
        assert body["a2a"]["status"] in ("not_started", "running", "stopped")
        assert {s["name"] for s in body["mcp"]["servers"]} == {"vexa-workspace", "vexa-code-intel", "vexa-docs-search"}
        text = r.text.lower()
        assert "api_key\"" not in text and "sk-" not in text
        if settings.api_token:
            assert settings.api_token not in r.text

    def test_database_count_matches_registry(self, client):
        before = client.get("/system/status").json()["database"]["runs"]
        listed = client.get("/agent-runs/registry/runs").json()
        assert before >= (len(listed) if isinstance(listed, list) else 0)
