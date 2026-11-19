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
