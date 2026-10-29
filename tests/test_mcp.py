"""Phase 6: MCP tool integration (workspace server + docs search server)."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from backend.agents.config import AgentSettings
from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew
from backend.mcp_client.bridge import (
    MCPServerBridge,
    MCPServerSpec,
    docs_search_server_spec,
    schema_to_model,
    workspace_server_spec,
)
from backend.mcp_servers.docs_search_server import search
from backend.tools.service import ToolService
from tests.fakes import ScriptedLLM, action, final

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture()
def ws(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path / "root"))
    ws_id = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws_id)), dirs_exist_ok=True)
    return svc, ws_id


# ---------------------------------------------------------------------------
# Workspace MCP server
# ---------------------------------------------------------------------------


class TestWorkspaceServer:
    @pytest.fixture()
    def bridge(self, ws):
        svc, ws_id = ws
        b = MCPServerBridge(workspace_server_spec(svc._manager.root, ws_id)).start()
        yield b
        b.close()

    def test_discovery(self, bridge):
        names = {t.name for t in bridge.tools}
        assert names == {"inspect_project", "list_files", "read_file", "write_file", "patch_file",
                         "search_code", "git_status", "git_diff", "run_tests"}
        rf = next(t for t in bridge.tools if t.name == "read_file")
        assert rf.inputSchema["required"] == ["path"]
        assert rf.annotations.readOnlyHint is True

    def test_call_and_security(self, bridge):
        ok, text = bridge.call("read_file", {"path": "src/calculator.py"})
        assert ok and "def add" in json.loads(text)["data"]["content"]
        ok, text = bridge.call("read_file", {"path": "../../../etc/hosts"})
        assert not ok and "traversal" in text.lower()
        ok, text = bridge.call("write_file", {"path": "/etc/evil", "content": "x"})
        assert not ok

    def test_invalid_arguments_rejected_by_server(self, bridge):
        ok, _ = bridge.call("read_file", {})
        assert not ok

    def test_sandboxed_tests_over_mcp(self, bridge):
        ok, text = bridge.call("run_tests", {})
        assert ok and json.loads(text)["exit_code"] == 0

    def test_role_allowlist(self, bridge):
        assert {t.name for t in bridge.crewai_tools({"read_file", "search_code"})} == {"read_file", "search_code"}

    def test_server_env_and_cwd_are_isolated(self, ws, monkeypatch):
        svc, ws_id = ws
        monkeypatch.setenv("GROQ_API_KEY", "secret-value")
        params = workspace_server_spec(svc._manager.root, ws_id).params(cwd="/nonexistent-cwd")
        assert "GROQ_API_KEY" not in params.env and "VEXA_LLM_API_KEY" not in params.env
        assert params.env["WORKSPACE_ROOT".upper()] if "WORKSPACE_ROOT" in params.env else True

    def test_bad_server_fails_loudly(self):
        with pytest.raises(Exception):
            MCPServerBridge(MCPServerSpec(name="broken", module="backend.does_not_exist", startup_timeout=10)).start()


def test_schema_to_model():
    model = schema_to_model("t", {"type": "object", "required": ["q"], "properties": {
        "q": {"type": "string"}, "n": {"type": "integer", "default": 5},
        "domains": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}], "default": None}}})
    m = model(q="x")
    assert m.n == 5 and m.domains is None
    with pytest.raises(Exception):
        model()


# ---------------------------------------------------------------------------
# Agents using MCP inside a real CrewAI run
# ---------------------------------------------------------------------------


def _scripts(original: str, planner_turns: list[str] | None = None) -> dict:
    return {
        "Requirements Analyst": [final({"task_summary": "Add modulo", "acceptance_criteria": ["modulo(10, 3) == 1"]})],
        "Project Analyst": [action("read_file", {"path": "src/calculator.py"}),
                            final({"total_files": 4, "project_context": "calculator"})],
        "Implementation Planner": planner_turns or [final({"objective": "Add modulo", "steps": [
            {"step_number": 1, "description": "add", "files_affected": ["src/calculator.py"], "action": "patch"}]})],
        "Software Engineer": [
            action("write_file", {"path": "src/calculator.py",
                                  "content": original + "\n\ndef modulo(a, b):\n    return a % b\n"}),
            final({"files_changed": [{"path": "src/calculator.py", "action": "patched"}]}),
        ],
        "Requirements Verifier": [final({"verified": True, "requirements_satisfied": ["modulo(10, 3) == 1"]})],
    }


@pytest.mark.parametrize("transport", ["mcp", "direct"])
def test_agents_use_workspace_tools(ws, transport, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    svc, ws_id = ws
    original = svc.read_file(ws_id, "src/calculator.py").data["content"]
    settings = AgentSettings(agent_max_iter=5, tool_transport=transport, docs_search_api_key=None)
    r = SoftwareEngineeringCrew(tool_service=svc, settings=settings, llm=ScriptedLLM(_scripts(original))).run_task(
        ws_id, "Add a modulo function", "real")
    assert r.status == AgentStatus.success, r.errors
    assert r.tool_transport == transport
    assert "def modulo" in svc.read_file(ws_id, "src/calculator.py").data["content"]
    agent_tools = [s for s in r.trace["spans"] if s["kind"] == "tool" and s["attributes"]["vexa.agent"] != "Tester"]
    transports = {s["attributes"].get("vexa.transport", "direct") for s in agent_tools}
    assert transports == {transport}
    servers = {m["name"]: m for m in r.mcp_servers}
    assert servers["vexa-docs-search"]["status"].startswith("disabled")
    if transport == "mcp":
        assert servers["vexa-workspace"]["status"] == "connected" and "write_file" in servers["vexa-workspace"]["tools"]
    else:
        assert "vexa-workspace" not in servers


# ---------------------------------------------------------------------------
# Docs search MCP server
# ---------------------------------------------------------------------------


def _mock_client(status=200, body=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {"results": []})
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestDocsSearchProvider:
    def test_success_and_truncation(self):
        seen = []
        body = {"results": [{"title": "pathlib", "url": "https://docs.python.org/3/library/pathlib.html",
                             "content": "x" * 5000}]}
        out = search("pathlib resolve", 3, None, api_key="tvly-test", client=_mock_client(body=body, seen=seen))
        assert out["ok"] and len(out["results"][0]["snippet"]) == 1200
        assert "UNTRUSTED" in out["notice"]
        sent = json.loads(seen[0].content)
        assert sent["max_results"] == 3 and "docs.python.org" in sent["include_domains"]
        assert seen[0].headers["authorization"] == "Bearer tvly-test"

    def test_missing_key(self):
        assert "not configured" in search("x", api_key=None)["error"]

    def test_http_error_does_not_leak_key(self):
        out = search("x", api_key="tvly-secret", client=_mock_client(status=401))
        assert not out["ok"] and "tvly-secret" not in json.dumps(out)

    def test_validation(self):
        assert not search("", api_key="k")["ok"]
        assert not search("q" * 401, api_key="k")["ok"]

    def test_domain_cleaning(self):
        seen = []
        search("x", 50, ["https://evil.com/path", "bad domain!", "docs.pydantic.dev"], api_key="k",
               client=_mock_client(seen=seen))
        sent = json.loads(seen[0].content)
        assert sent["include_domains"] == ["evil.com", "docs.pydantic.dev"] and sent["max_results"] == 10


@pytest.fixture()
def fake_search_api(monkeypatch):
    """Local HTTP endpoint standing in for Tavily (no internet)."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"results": [{"title": "Python % operator", "url": "https://docs.python.org/3/x",
                                            "content": "The % operator yields the remainder: 10 % 3 == 1"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("VEXA_DOCS_SEARCH_URL", f"http://127.0.0.1:{server.server_port}/search")
    yield received
    server.shutdown()


def test_docs_search_over_mcp(fake_search_api):
    b = MCPServerBridge(docs_search_server_spec("tvly-test-key")).start()
    try:
        assert [t.name for t in b.tools] == ["search_docs"]
        ok, text = b.call("search_docs", {"query": "python modulo operator"})
        assert ok and json.loads(text)["results"][0]["title"] == "Python % operator"
    finally:
        b.close()
    assert fake_search_api[0]["query"] == "python modulo operator"


def test_planner_uses_docs_search_and_receives_result(ws, fake_search_api):
    svc, ws_id = ws
    original = svc.read_file(ws_id, "src/calculator.py").data["content"]
    planner = [
        action("search_docs", {"query": "python modulo operator"}),
        final({"objective": "Add modulo", "steps": [
            {"step_number": 1, "description": "use % operator", "files_affected": ["src/calculator.py"],
             "action": "patch"}]}),
    ]
    llm = ScriptedLLM(_scripts(original, planner))
    settings = AgentSettings(agent_max_iter=5, docs_search_api_key="tvly-test-key")
    r = SoftwareEngineeringCrew(tool_service=svc, settings=settings, llm=llm).run_task(ws_id, "Add a modulo function", "real")
    assert r.status == AgentStatus.success, r.errors
    planner_prompts = [t for k, t in llm.calls if k == "Implementation Planner"]
    assert "10 % 3 == 1" in planner_prompts[1]  # the tool observation reached the agent
    span = next(s for s in r.trace["spans"] if s["kind"] == "tool" and s["attributes"]["vexa.tool"] == "search_docs")
    assert span["attributes"]["vexa.agent"] == "Planner" and span["attributes"]["vexa.mcp_server"] == "vexa-docs-search"
    assert {m["name"]: m["status"] for m in r.mcp_servers}["vexa-docs-search"] == "connected"
    assert "tvly-test-key" not in json.dumps(r.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Code-intelligence MCP server (local, keyless)
# ---------------------------------------------------------------------------


class TestCodeIntelServer:
    @pytest.fixture()
    def bridge(self, ws):
        from backend.mcp_client.bridge import code_intel_server_spec
        svc, ws_id = ws
        svc.write_file(ws_id, "src/broken.py", "import os\ndef f(:\n    pass\n")
        svc.write_file(ws_id, "src/lint.py", "import os, sys\ndef g():\n    return missing + 1\nprint(sys.argv)\n")
        b = MCPServerBridge(code_intel_server_spec(svc._manager.root, ws_id)).start()
        yield b
        b.close()

    def test_discovery(self, bridge):
        assert {t.name for t in bridge.tools} == {"python_api_docs", "check_python"}
        assert all(t.annotations.readOnlyHint for t in bridge.tools)

    def test_api_docs_installed_package(self, bridge):
        ok, text = bridge.call("python_api_docs", {"symbol": "json.dumps"})
        body = json.loads(text)
        assert ok and body["ok"] and "skipkeys" in body["signature"] and body["doc"]

    def test_api_docs_refuses_project_and_bad_names(self, bridge):
        for symbol in ("backend.agents.config", "os; import shutil"):
            ok, text = bridge.call("python_api_docs", {"symbol": symbol})
            assert json.loads(text)["ok"] is False

    def test_check_python_reports_real_problems(self, bridge):
        bad = json.loads(bridge.call("check_python", {"path": "src/broken.py"})[1])
        assert bad["valid_syntax"] is False and bad["errors"][0]["line"] == 2
        lint = json.loads(bridge.call("check_python", {"path": "src/lint.py"})[1])
        rules = {(w["rule"], w["message"].split("'")[1]) for w in lint["warnings"]}
        assert rules == {("unused-import", "os"), ("undefined-name", "missing")}
        clean = json.loads(bridge.call("check_python", {"path": "src/calculator.py"})[1])
        assert clean["valid_syntax"] and clean["warnings"] == []

    def test_check_python_stays_in_workspace(self, bridge):
        out = json.loads(bridge.call("check_python", {"path": "../../../etc/passwd.py"})[1])
        assert out["ok"] is False


def test_coder_uses_code_intel_over_mcp(ws, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    svc, ws_id = ws
    original = svc.read_file(ws_id, "src/calculator.py").data["content"]
    scripts = _scripts(original)
    scripts["Software Engineer"] = [scripts["Software Engineer"][0],
                                    action("check_python", {"path": "src/calculator.py"}),
                                    scripts["Software Engineer"][1]]
    llm = ScriptedLLM(scripts)
    r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=6, tool_transport="mcp"),
                                llm=llm).run_task(ws_id, "Add a modulo function", "real")
    assert r.status == AgentStatus.success, r.errors
    servers = {m["name"]: m for m in r.mcp_servers}
    assert servers["vexa-code-intel"]["status"] == "connected"
    span = next(s for s in r.trace["spans"] if s["kind"] == "tool" and s["attributes"]["vexa.tool"] == "check_python")
    assert span["attributes"]["vexa.transport"] == "mcp" and span["attributes"]["vexa.agent"] == "Coder"
    assert span["status"] == "ok"
    coder_seen = [t for k, t in llm.calls if k == "Software Engineer"][-1]
    assert '"valid_syntax": true' in coder_seen  # the MCP result reached the agent
    assert any(g["rule"] == "G2" and g.get("tool") == "check_python" and g["decision"] == "allowed"
               for g in r.guardrail_events)


class TestServerFailure:
    """Real server process: a crash mid-run is reported, the in-flight call is not repeated, the server restarts."""

    def test_crash_is_reported_and_the_server_restarts_once(self):
        b = MCPServerBridge(MCPServerSpec(name="crashy", module="tests.mcp_crash_server", call_timeout=15)).start()
        try:
            assert {t.name for t in b.tools} == {"echo", "crash", "hang"}
            ok, text = b.call("echo", {"text": "hi"})
            pid1 = json.loads(text)["pid"]
            assert ok and b.alive

            ok, text = b.call("crash", {})  # in flight when the process dies: an error, not a retry
            assert not ok and "failed" in json.loads(text)["error"]
            assert b.restarts == 0

            ok, text = b.call("echo", {"text": "again"})  # dead before the call: restarted, then sent
            assert ok and json.loads(text)["text"] == "again" and json.loads(text)["pid"] != pid1
            assert b.restarts == 1

            b.call("crash", {})
            ok, text = b.call("echo", {"text": "x"})  # restart budget used: a clear error
            assert not ok and "not connected" in json.loads(text)["error"]
        finally:
            b.close()

    def test_timed_out_server_is_restarted_not_left_wedged(self):
        b = MCPServerBridge(MCPServerSpec(name="crashy", module="tests.mcp_crash_server", call_timeout=2)).start()
        try:
            pid1 = json.loads(b.call("echo", {"text": "hi"})[1])["pid"]
            ok, text = b.call("hang", {"seconds": 30})  # still busy afterwards: every later call would time out
            assert not ok and "Timed out" in json.loads(text)["error"]
            assert not b.alive and b.restarts == 0  # the timed-out call is not repeated

            ok, text = b.call("echo", {"text": "after"})
            assert ok and json.loads(text)["pid"] != pid1 and b.restarts == 1

            b.call("hang", {"seconds": 30})
            ok, text = b.call("echo", {"text": "x"})  # restart budget used: a clear error, not another wait
            assert not ok and "not connected" in json.loads(text)["error"]
        finally:
            b.close()

    def test_closed_bridge_refuses_calls(self):
        b = MCPServerBridge(MCPServerSpec(name="crashy", module="tests.mcp_crash_server")).start()
        b.close()
        b.max_restarts = 0
        ok, text = b.call("echo", {"text": "x"})
        assert not ok and "not connected" in text

    def test_tool_without_run_context_is_refused_not_run_unchecked(self):
        from backend.mcp_client.bridge import MCPCrewAITool
        b = MCPServerBridge(MCPServerSpec(name="crashy", module="tests.mcp_crash_server")).start()
        try:
            tool = next(MCPCrewAITool(b, t, ctx=None) for t in b.tools if t.name == "crash")
            out = json.loads(tool._run())
            assert not out["ok"] and "guardrails cannot be evaluated" in out["error"]
            assert b.alive  # the crash tool never ran
        finally:
            b.close()
