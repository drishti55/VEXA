"""Phase 7: Google ADK Verifier over A2A, called from the CrewAI runtime."""

from __future__ import annotations

import json
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
import pytest
import uvicorn
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from backend.a2a_bridge.verifier_server import create_verifier_app
from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew
from backend.tools.service import ToolService
from tests.test_agent_crew import CANNED_DEBUG, HAPPY_SCRIPTS, ScriptedResponder, _make_settings

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"
TOKEN = "a2a-test-token-123"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    def __init__(self, app, port):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 15
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(10)


@pytest.fixture(scope="module")
def mock_verifier():
    port = _free_port()
    with _Server(create_verifier_app("mock", port=port, token=TOKEN), port) as srv:
        yield srv.url


def _crew(tmp_path, url, token=TOKEN, broken=False, scripts=None):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    if broken:
        svc.write_file(ws, "tests/test_fail.py", "def test_fail():\n    assert 1 == 2\n")
    settings = _make_settings(debug_max_iter=1)
    settings.verifier_backend, settings.a2a_verifier_url, settings.a2a_token = "adk_a2a", url, token
    settings.a2a_embedded = False  # these tests target an external A2A server
    responder = ScriptedResponder(scripts or {k: v for k, v in HAPPY_SCRIPTS.items() if k != "Verifier"})
    return SoftwareEngineeringCrew(tool_service=svc, settings=settings, responder=responder), ws, responder


class TestAgentCard:
    def test_card(self, mock_verifier):
        card = httpx.get(f"{mock_verifier}/.well-known/agent-card.json").json()
        assert card["name"] == "vexa_verifier"
        assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "Bearer"
        assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"

    def test_rpc_requires_token(self, mock_verifier):
        assert httpx.post(mock_verifier, json={"jsonrpc": "2.0", "id": 1, "method": "x"}).status_code == 401


class TestCrewAIToADK:
    def test_verification_delegated_over_a2a(self, tmp_path, mock_verifier):
        crew, ws, responder = _crew(tmp_path, mock_verifier)
        r = crew.run_task(ws, "Add a modulo function")
        v = r.verification_result
        assert r.status == AgentStatus.success, r.errors
        assert v.backend == "adk_a2a" and v.verified and v.output_valid
        assert v.remote["state"] == "TASK_STATE_COMPLETED" and v.remote["task_id"] and v.remote["agent"] == "vexa_verifier"
        assert "Verifier" not in [a for a, _ in responder.calls]  # the CrewAI verifier was not used
        msgs = [c for c in r.coordination_log if c["kind"] == "message"]
        assert [(m["actor"], m["target"]) for m in msgs] == [
            ("crewai:runtime", "adk:vexa_verifier"), ("adk:vexa_verifier", "crewai:runtime")]
        span = next(s for s in r.trace["spans"] if s["kind"] == "tool" and s["attributes"]["vexa.tool"] == "a2a:message/send")
        assert span["attributes"]["vexa.transport"] == "a2a" and span["attributes"]["vexa.agent"] == "Verifier"

    def test_failing_tests_reported_by_adk(self, tmp_path, mock_verifier):
        scripts = {**{k: v for k, v in HAPPY_SCRIPTS.items() if k != "Verifier"},
                   "Tester": [json.dumps({"failures": ["test_fail"]})], "Debugger": [CANNED_DEBUG]}
        crew, ws, _ = _crew(tmp_path, mock_verifier, broken=True, scripts=scripts)
        r = crew.run_task(ws, "Add a modulo function")
        assert r.verification_result.verified is False and r.status == AgentStatus.failed

    def test_bad_token_fails_verification_loudly(self, tmp_path, mock_verifier):
        crew, ws, _ = _crew(tmp_path, mock_verifier, token="wrong")
        r = crew.run_task(ws, "Add a modulo function")
        assert r.status != AgentStatus.success
        assert "401" in " ".join(r.verification_result.errors)

    def test_unreachable_verifier(self, tmp_path):
        crew, ws, _ = _crew(tmp_path, f"http://127.0.0.1:{_free_port()}")
        r = crew.run_task(ws, "Add a modulo function")
        assert r.verification_result.verified is False and r.verification_result.errors

    def test_works_under_blackboard(self, tmp_path, mock_verifier):
        crew, ws, _ = _crew(tmp_path, mock_verifier)
        r = crew.run_task(ws, "Add a modulo function", architecture="blackboard")
        assert r.status == AgentStatus.success and r.verification_result.backend == "adk_a2a"


# ---------------------------------------------------------------------------
# Real ADK LlmAgent path with a fake ADK model (no network)
# ---------------------------------------------------------------------------


class FakeAdkLlm(BaseLlm):
    """Turn 1: call read_file through ADK function calling. Turn 2: answer JSON."""

    _requests: list[LlmRequest] = PrivateAttr(default_factory=list)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self._requests.append(llm_request)
        if len(self._requests) == 1:
            part = types.Part(function_call=types.FunctionCall(name="read_file", args={"path": "src/calculator.py"}))
        else:
            seen = json.dumps([c.model_dump(mode="json") for c in llm_request.contents])
            verified = "def add" in seen
            part = types.Part(text=json.dumps({"verified": verified, "requirements_satisfied": ["file read"],
                                               "evidence": "read src/calculator.py via ADK tool"}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def test_adk_llm_agent_uses_workspace_tool_over_a2a(tmp_path, monkeypatch):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    from backend.core.config import get_settings
    get_settings.cache_clear()
    try:
        llm = FakeAdkLlm(model="fake-adk-model")
        port = _free_port()
        with _Server(create_verifier_app("real", port=port, token=TOKEN, model=llm), port) as srv:
            settings = _make_settings()
            settings.verifier_backend, settings.a2a_verifier_url, settings.a2a_token = "adk_a2a", srv.url, TOKEN
            settings.a2a_embedded = False
            responder = ScriptedResponder({k: v for k, v in HAPPY_SCRIPTS.items() if k != "Verifier"})
            r = SoftwareEngineeringCrew(tool_service=svc, settings=settings, responder=responder).run_task(
                ws, "Add a modulo function")
        assert r.verification_result.verified is True, r.verification_result
        assert len(llm._requests) == 2
        system = llm._requests[0].config.system_instruction
        assert "Expert Software Requirements Verifier" in str(system)  # same prompt as the CrewAI verifier
    finally:
        get_settings.cache_clear()


def test_adk_verifier_reasks_after_provider_rejected_tool_call(monkeypatch):
    """Real-mode regression: gpt-oss on Groq emitted 'read_file<|channel|>commentary'; Groq answered 400
    and the whole remote verification failed. The verifier model now re-asks, as the CrewAI agents do."""
    import asyncio

    from google.adk.models.lite_llm import LiteLlm

    from backend.adk_agents import verifier as v

    sent: list[list[str]] = []

    async def flaky(self, llm_request, stream=False):
        sent.append([p.text for c in llm_request.contents for p in c.parts if p.text])
        if len(sent) == 1:
            raise RuntimeError('litellm.BadRequestError: GroqException - {"error":{"message":"Tool call validation '
                               "failed: attempted to call tool 'read_file<|channel|>commentary' which was not in "
                               'request.tools"}}')
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))

    monkeypatch.setattr(LiteLlm, "generate_content_async", flaky)
    req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="verify")])])
    token = v._current_invocation.set("inv-test")
    try:
        out = asyncio.run(_collect(v.RetryingLiteLlm(model="groq/openai/gpt-oss-20b").generate_content_async(req)))
    finally:
        v._current_invocation.reset(token)
    assert [r.content.parts[0].text for r in out] == ["ok"]
    assert len(sent) == 2 and "invalid tool call" in sent[1][-1]
    retries = v._pop_telemetry("inv-test").retries
    assert [r["kind"] for r in retries] == ["llm_invalid_tool_call"]


async def _collect(agen):
    return [r async for r in agen]
