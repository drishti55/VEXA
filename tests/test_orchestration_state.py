"""Phase 2: architecture abstraction, shared state, provenance, coordination log."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

from backend.agents.crew import SoftwareEngineeringCrew
from backend.orchestration import get_architecture, list_architectures
from backend.orchestration.state import STANDARD_KEYS, SharedState
from backend.tools.service import ToolService
from tests.test_agent_crew import HAPPY_SCRIPTS, ScriptedResponder, _make_settings

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


class TestSharedState:
    def test_writes_are_versioned_not_overwritten(self):
        s = SharedState("r")
        s.write("test_result", {"passed": False}, "Tester")
        s.write("test_result", {"passed": True}, "Tester")
        hist = s.history("test_result")
        assert [e.version for e in hist] == [1, 2]
        assert hist[0].value == {"passed": False}
        assert s.read("test_result", "Verifier") == {"passed": True}

    def test_access_log_attributes_reads_and_writes(self):
        s = SharedState("r")
        s.write("plan", "p", "Planner")
        s.read("plan", "Coder")
        s.read("missing", "Coder")
        log = s.access_log
        assert [(a.kind, a.key, a.agent, a.version) for a in log] == [
            ("write", "plan", "Planner", 1), ("read", "plan", "Coder", 1), ("read", "missing", "Coder", None),
        ]

    def test_subscribers_notified(self):
        s, seen = SharedState("r"), []
        s.subscribe(lambda e: seen.append((e.key, e.version)))
        s.write("k", 1, "a")
        assert seen == [("k", 1)]

    def test_concurrent_writes_keep_all_versions(self):
        s = SharedState("r")
        threads = [threading.Thread(target=lambda: [s.write("k", i, "a") for i in range(50)]) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert [e.version for e in s.history("k")] == list(range(1, 201))


class TestRegistry:
    def test_unknown_architecture(self):
        with pytest.raises(ValueError):
            get_architecture("does-not-exist")

    def test_listing(self):
        assert "sequential" in {a["name"] for a in list_architectures()}

    def test_api_lists_architectures(self, client):
        assert any(a["name"] == "sequential" for a in client.get("/agent-runs/architectures").json())

    def test_api_rejects_unknown_architecture(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        r = client.post("/agent-runs/async", json={"workspace_id": ws, "requirement": "Do something useful",
                                                   "architecture": "nope"})
        assert r.status_code == 400


@pytest.fixture()
def run(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    responder = ScriptedResponder(HAPPY_SCRIPTS)
    crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(), responder=responder)
    return crew.run_task(ws, "Add modulo", architecture="sequential"), responder


class TestSequentialStateAndProvenance:
    def test_every_standard_output_is_in_state(self, run):
        result, _ = run
        keys = {e["key"] for e in result.state["entries"]}
        assert {"requirement", "requirement_analysis", "project_analysis", "implementation_plan",
                "code_changes", "test_result", "verification"} <= keys
        assert keys <= set(STANDARD_KEYS)

    def test_provenance_links(self, run):
        result, _ = run
        entries = {e["key"]: e for e in result.state["entries"]}
        assert entries["requirement_analysis"]["derived_from"] == [entries["requirement"]["entry_id"]]
        assert set(entries["verification"]["derived_from"]) == {
            entries["requirement_analysis"]["entry_id"], entries["test_result"]["entry_id"]}

    def test_sequential_passes_outputs_directly(self, run):
        """Sequential never reads the shared state — it is an audit mirror only."""
        result, _ = run
        assert all(a["kind"] == "write" for a in result.state["access_log"])

    def test_coordination_log(self, run):
        result, _ = run
        targets = [c["target"] for c in result.coordination_log if c["kind"] == "dispatch"]
        assert targets == ["RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier"]

    def test_coder_receives_acceptance_criteria(self, run):
        _, responder = run
        coder_prompt = next(d for a, d in responder.calls if a == "Coder")
        assert "modulo(10, 3) == 1" in coder_prompt
