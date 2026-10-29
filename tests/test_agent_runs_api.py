"""
VEXA M3 — Agent Run API Tests

Tests for:
- POST /agent-runs input validation
- Invalid workspace → 404
- Missing/short requirement → 422
- Successful run returns run_id and result
- GET /agent-runs/{id} retrieval

Uses mock crew to avoid real LLM calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.contracts import AgentStatus, RunResult


class TestAgentRunAPIValidation:
    def test_missing_workspace_returns_422(self, client):
        r = client.post("/agent-runs", json={"requirement": "Add modulo function"})
        assert r.status_code == 422

    def test_missing_requirement_returns_422(self, client):
        r = client.post("/agent-runs", json={"workspace_id": "some-ws"})
        assert r.status_code == 422

    def test_short_requirement_returns_422(self, client):
        # requirement has min_length=10
        r = client.post("/agent-runs", json={"workspace_id": "ws", "requirement": "short"})
        assert r.status_code == 422

    def test_nonexistent_workspace_returns_404(self, client):
        r = client.post("/agent-runs", json={
            "workspace_id": "workspace-that-does-not-exist-xyz",
            "requirement": "Add a modulo function to the calculator module",
        })
        assert r.status_code == 404

    def test_get_nonexistent_run_returns_404(self, client):
        r = client.get("/agent-runs/run-that-does-not-exist")
        assert r.status_code == 404


class TestAgentRunAPISuccess:
    """
    Creates a real workspace, then mocks the SoftwareEngineeringCrew to
    return a deterministic RunResult.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def api_run_ws(cls, client):
        """Create a workspace via the workspace API."""
        r = client.post("/workspaces", json={})
        return r.json()["workspace_id"]

    def test_successful_run_returns_201(self, client, api_run_ws):
        mock_result = RunResult(
            run_id="mock-run-001",
            workspace_id=api_run_ws,
            requirement="Add a modulo function to the calculator module",
            status=AgentStatus.success,
            files_changed=["src/calculator.py"],
            debug_iterations=0,
        )
        with patch("backend.api.agent_runs.SoftwareEngineeringCrew") as MockCrew:
            MockCrew.return_value.run_task.return_value = mock_result
            r = client.post("/agent-runs", json={
                "workspace_id": api_run_ws,
                "requirement": "Add a modulo function to the calculator module",
            })
        assert r.status_code == 201

    def test_run_response_has_run_id(self, client, api_run_ws):
        mock_result = RunResult(
            run_id="mock-run-002",
            workspace_id=api_run_ws,
            requirement="Add a modulo function to the calculator module",
            status=AgentStatus.success,
        )
        with patch("backend.api.agent_runs.SoftwareEngineeringCrew") as MockCrew:
            MockCrew.return_value.run_task.return_value = mock_result
            r = client.post("/agent-runs", json={
                "workspace_id": api_run_ws,
                "requirement": "Add a modulo function to the calculator module",
            })
        body = r.json()
        assert "run_id" in body
        assert body["run_id"] == "mock-run-002"

    def test_run_response_has_status(self, client, api_run_ws):
        mock_result = RunResult(
            run_id="mock-run-003",
            workspace_id=api_run_ws,
            requirement="Add a modulo function to the calculator module",
            status=AgentStatus.success,
        )
        with patch("backend.api.agent_runs.SoftwareEngineeringCrew") as MockCrew:
            MockCrew.return_value.run_task.return_value = mock_result
            r = client.post("/agent-runs", json={
                "workspace_id": api_run_ws,
                "requirement": "Add a modulo function to the calculator module",
            })
        body = r.json()
        assert body["status"] == "success"

    def test_run_response_has_result_dict(self, client, api_run_ws):
        mock_result = RunResult(
            run_id="mock-run-004",
            workspace_id=api_run_ws,
            requirement="Add a modulo function to the calculator module",
            status=AgentStatus.partial,
        )
        with patch("backend.api.agent_runs.SoftwareEngineeringCrew") as MockCrew:
            MockCrew.return_value.run_task.return_value = mock_result
            r = client.post("/agent-runs", json={
                "workspace_id": api_run_ws,
                "requirement": "Add a modulo function to the calculator module",
            })
        body = r.json()
        assert "result" in body
        assert isinstance(body["result"], dict)

    def test_get_run_after_submit(self, client, api_run_ws):
        """Verify GET /agent-runs/{id} works after a POST."""
        mock_result = RunResult(
            run_id="mock-run-get-test",
            workspace_id=api_run_ws,
            requirement="Add a modulo function to the calculator module",
            status=AgentStatus.success,
        )
        with patch("backend.api.agent_runs.SoftwareEngineeringCrew") as MockCrew:
            MockCrew.return_value.run_task.return_value = mock_result
            r_post = client.post("/agent-runs", json={
                "workspace_id": api_run_ws,
                "requirement": "Add a modulo function to the calculator module",
            })
        # Now retrieve it
        run_id = r_post.json()["run_id"]
        r_get = client.get(f"/agent-runs/{run_id}")
        assert r_get.status_code == 200
        assert r_get.json()["run_id"] == run_id
