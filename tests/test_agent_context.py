"""
VEXA M3 — RunContext Tests
"""

from __future__ import annotations

import time

import pytest

from backend.agents.context import AgentEvent, RunContext


class TestRunContextCreation:
    def test_generates_run_id(self):
        ctx = RunContext("ws-1", "do something")
        assert len(ctx.run_id) > 0

    def test_custom_run_id(self):
        ctx = RunContext("ws-1", "do something", run_id="custom-id")
        assert ctx.run_id == "custom-id"

    def test_initial_state(self):
        ctx = RunContext("ws-1", "requirement")
        assert ctx.workspace_id == "ws-1"
        assert ctx.requirement == "requirement"
        assert ctx.architecture == "sequential"
        assert ctx.test_attempts == 0
        assert ctx.debug_iterations == 0
        assert ctx.files_changed == []
        assert ctx.errors == []
        assert ctx.current_agent == "none"

    def test_architecture_parameter(self):
        ctx = RunContext("ws-1", "req", architecture="hierarchical")
        assert ctx.architecture == "hierarchical"


class TestEventRecording:
    def test_record_event(self):
        ctx = RunContext("ws-1", "req")
        ctx.record("TestAgent", "started")
        assert len(ctx.events) == 1
        assert ctx.events[0].agent == "TestAgent"
        assert ctx.events[0].event == "started"

    def test_record_with_detail(self):
        ctx = RunContext("ws-1", "req")
        ctx.record("Coder", "tool_invoked", "read_file: src/main.py")
        assert "read_file" in ctx.events[0].detail

    def test_agent_started_sets_current(self):
        ctx = RunContext("ws-1", "req")
        ctx.agent_started("Planner")
        assert ctx.current_agent == "Planner"

    def test_tool_failed_adds_to_errors(self):
        ctx = RunContext("ws-1", "req")
        ctx.tool_failed("Coder", "write_file", "Permission denied")
        assert len(ctx.errors) == 1
        assert "Permission denied" in ctx.errors[0]

    def test_file_changed_deduplicates(self):
        ctx = RunContext("ws-1", "req")
        ctx.file_changed("src/main.py")
        ctx.file_changed("src/main.py")
        ctx.file_changed("tests/test_main.py")
        assert len(ctx.files_changed) == 2

    def test_test_attempted_increments(self):
        ctx = RunContext("ws-1", "req")
        ctx.test_attempted()
        ctx.test_attempted()
        assert ctx.test_attempts == 2

    def test_debug_iterated_increments(self):
        ctx = RunContext("ws-1", "req")
        ctx.debug_iterated()
        ctx.debug_iterated()
        ctx.debug_iterated()
        assert ctx.debug_iterations == 3

    def test_finish_sets_timestamp(self):
        ctx = RunContext("ws-1", "req")
        assert ctx.finished_at is None
        ctx.finish()
        assert ctx.finished_at is not None


class TestContextSerialisation:
    def test_to_dict_has_required_keys(self):
        ctx = RunContext("ws-abc", "do something", run_id="run-123")
        ctx.agent_started("RequirementAnalyst")
        ctx.agent_completed("RequirementAnalyst", 500.0)
        ctx.finish()
        d = ctx.to_dict()
        assert d["run_id"] == "run-123"
        assert d["workspace_id"] == "ws-abc"
        assert d["architecture"] == "sequential"
        assert len(d["events"]) >= 2  # started + completed
        assert d["finished_at"] is not None

    def test_events_serialise_to_list_of_dicts(self):
        ctx = RunContext("ws-1", "req")
        ctx.record("Coder", "started")
        d = ctx.to_dict()
        assert isinstance(d["events"], list)
        assert isinstance(d["events"][0], dict)


def test_live_snapshot_shows_usage_and_mcp_servers_while_running():
    """The run view polls RunContext.to_dict(); tokens and MCP servers must not wait for the end of the run."""
    from types import SimpleNamespace

    from backend.agents.context import RunContext
    from backend.api.agent_runs import _format_run_response
    ctx = RunContext("ws-1", "notes app")
    ctx.observer = SimpleNamespace(
        usage_totals=lambda: {"usage_available": True, "input_tokens": 900, "output_tokens": 100, "total_tokens": 1000},
        export=lambda: {})
    ctx.mcp_servers.append({"name": "vexa-workspace", "status": "connected", "tools": ["read_file"]})
    live = ctx.to_dict()
    assert live["usage_available"] is True and live["total_tokens"] == 1000
    assert live["mcp_servers"][0]["name"] == "vexa-workspace"
    ctx.errors.append("boom")
    ctx.finish()  # finished but not yet replaced by the final RunResult: still "running" for pollers
    assert _format_run_response(ctx.run_id, ctx).status == "running"
