"""Starter workspaces are copied in only when the workspace root is empty (fresh deploy)."""

from backend.examples import EXAMPLES_DIR, seed_example_workspaces
from backend.tools.service import ToolService


def test_empty_root_gets_every_example(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path))
    created = seed_example_workspaces(svc)
    expected = sorted(p.name for p in EXAMPLES_DIR.iterdir() if p.is_dir())
    assert sorted(created) == expected and len(created) >= 40
    assert svc.read_file("Python Calculator", "calculator.py").success


def test_existing_workspaces_are_left_alone(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace("mine")
    assert seed_example_workspaces(svc) == [] and svc.list_workspaces() == [ws]


def test_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("VEXA_SEED_EXAMPLES", "0")
    assert seed_example_workspaces(ToolService(workspace_root=str(tmp_path))) == []


def test_preview_adds_storage_shim_to_html_only(tmp_path, monkeypatch):
    """Sandboxed previews have no localStorage; served HTML gets a shim, other files are untouched."""
    from fastapi.testclient import TestClient

    import backend.api.workspaces as wsapi
    from backend.main import app
    svc = ToolService(workspace_root=str(tmp_path))
    monkeypatch.setattr(wsapi, "_svc", svc)
    ws = svc.create_workspace("notes")
    svc.write_file(ws, "index.html", "<!doctype html><html><head><title>t</title></head><body></body></html>")
    svc.write_file(ws, "app.js", "localStorage.setItem('a', '1');")
    c = TestClient(app)
    html = c.get(f"/workspaces/{ws}/serve/index.html")
    assert html.status_code == 200 and "sandbox" in html.headers["content-security-policy"]
    assert html.text.index("data-vexa-preview-shim") < html.text.index("<title>")
    assert c.get(f"/workspaces/{ws}/serve/app.js").text == "localStorage.setItem('a', '1');"
    assert svc.read_file(ws, "index.html").data["content"].count("vexa-preview-shim") == 0
