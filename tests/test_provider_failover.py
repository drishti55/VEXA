"""LLM failover wrapper: quota fallback, provider-guided rate-limit waits, no retry on auth errors (no network)."""

from __future__ import annotations

import pytest

from backend.agents.config import AgentSettings, LLMFactory, retry_after_seconds


def _build(monkeypatch, behaviour, **extra):
    import crewai
    calls = []

    def fake_call(self, messages, *a, **k):
        calls.append(self.model)
        return behaviour(len(calls), self.model)
    monkeypatch.setattr(crewai.LLM, "call", fake_call)
    sleeps = []
    monkeypatch.setattr("backend.agents.config.time.sleep", lambda s: sleeps.append(s))
    settings = AgentSettings(llm_model="groq/openai/gpt-oss-120b", llm_api_key="gsk-test", **extra)
    return LLMFactory.build(settings), calls, sleeps


def test_daily_quota_switches_to_fallback(monkeypatch):
    def behaviour(n, model):
        if n == 1:
            raise RuntimeError("RateLimitError: Limit reached on tokens per day (TPD)")
        return f"answer from {model}"
    llm, calls, _ = _build(monkeypatch, behaviour, llm_fallback_provider="groq",
                           llm_fallback_model="groq/openai/gpt-oss-20b", llm_fallback_api_key="gsk-fb")
    assert llm.call("hi") == "answer from groq/openai/gpt-oss-20b"
    assert llm.vexa_state["using_fallback"] is True and calls[0].endswith("120b")


def test_rate_limit_waits_what_the_provider_asks(monkeypatch):
    def behaviour(n, model):
        if n < 3:
            raise RuntimeError("Rate limit reached for model on tokens per minute (TPM). Please try again in 2.25s.")
        return "ok"
    llm, calls, sleeps = _build(monkeypatch, behaviour)
    assert llm.call("hi") == "ok" and len(calls) == 3
    assert sleeps == [2.75, 2.75] and llm.vexa_state["rate_limit_retries"] == 2


def test_authentication_error_is_not_retried(monkeypatch):
    def behaviour(n, model):
        raise RuntimeError("AuthenticationError: Invalid API Key")
    llm, calls, sleeps = _build(monkeypatch, behaviour)
    with pytest.raises(RuntimeError, match="Invalid API Key"):
        llm.call("hi")
    assert len(calls) == 1 and sleeps == []


def test_retry_after_parsing():
    assert retry_after_seconds("try again in 14.6s") == pytest.approx(15.1)
    assert retry_after_seconds("try again in 1m2.5s") == pytest.approx(63.0)
    assert retry_after_seconds("no hint", default=7) == 7
    assert retry_after_seconds("try again in 10m0s") == 65.0  # capped


def test_provider_status_never_contains_key_values(monkeypatch):
    from backend.agents.config import provider_status
    monkeypatch.setenv("GROQ_API_KEY", "gsk-super-secret-value")
    st = provider_status(AgentSettings(llm_model="groq/openai/gpt-oss-120b"))
    assert st["api_key_configured"] is True and st["key_source"] == "GROQ_API_KEY"
    assert "gsk-super-secret-value" not in repr(st)
    monkeypatch.delenv("GROQ_API_KEY")
    st = provider_status(AgentSettings(llm_model="groq/openai/gpt-oss-120b"))
    assert st["api_key_configured"] is False and st["required_env"] == "GROQ_API_KEY"


def test_daily_quota_without_fallback_fails_fast(monkeypatch):
    def behaviour(n, model):
        raise RuntimeError("Rate limit reached on tokens per day (TPD). Please try again in 8m44.88s.")
    llm, calls, sleeps = _build(monkeypatch, behaviour)
    with pytest.raises(RuntimeError, match="tokens per day"):
        llm.call("hi")
    assert len(calls) == 1 and sleeps == [] and llm.vexa_state["quota_exhausted"] is True


def test_token_budget_stops_the_run(tmp_path):
    import shutil
    from pathlib import Path

    from backend.agents.crew import SoftwareEngineeringCrew
    from backend.tools.service import ToolService
    from tests.test_audit_fixes import NOOP_SCRIPTS, _FixedUsageLLM
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(Path(__file__).parent / "fixtures" / "sample_project"), str(svc._manager.require(ws)),
                    dirs_exist_ok=True)
    settings = AgentSettings(agent_max_iter=3, tool_transport="direct", verifier_backend="crewai", max_run_tokens=1000)
    from tests.fakes import final
    scripts = {**NOOP_SCRIPTS, "Engineering Manager": [final({"next_agent": a}) for a in [
        "RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier", "FINISH"]]}
    llm = _FixedUsageLLM(scripts)  # 110 tokens per call; the full run needs ~13 calls (~1,430 tokens)
    r = SoftwareEngineeringCrew(tool_service=svc, settings=settings, llm=llm).run_task(
        ws, "Keep tests passing", "real", architecture="hierarchical")
    assert r.status.value == "failed" and any("token budget" in e for e in r.errors)
    g = [e for e in r.guardrail_events if e["kind"] == "run_token_budget"]
    assert g and g[0]["rule"] == "G7" and g[0]["decision"] == "blocked"
    assert r.total_tokens <= 1000 + 110 * 3  # stopped within one agent's calls of the budget


def test_transient_network_error_is_retried_briefly(monkeypatch):
    def behaviour(n, model):
        if n == 1:
            raise RuntimeError("litellm.InternalServerError: [Errno 8] nodename nor servname provided, or not known")
        return "ok"
    llm, calls, sleeps = _build(monkeypatch, behaviour)
    assert llm.call("hi") == "ok" and sleeps == [2.0] and llm.vexa_state["transient_retries"] == 1


def test_persistent_network_error_gives_up(monkeypatch):
    def behaviour(n, model):
        raise RuntimeError("APIConnectionError: Connection error.")
    llm, calls, sleeps = _build(monkeypatch, behaviour)
    with pytest.raises(RuntimeError):
        llm.call("hi")
    assert len(calls) == 3 and sleeps == [2.0, 4.0]


def test_failed_calls_do_not_make_usage_unavailable():
    from backend.observability.tracing import RunObserver
    obs = RunObserver("run-u")
    obs.agent_started("Coder")
    obs.llm_started("c1", "Coder", "m")
    obs.llm_finished("c1", "Coder", None, error="RateLimitError")       # rejected: no tokens consumed
    obs.llm_started("c2", "Coder", "m")
    obs.llm_finished("c2", "Coder", {"prompt_tokens": 50, "completion_tokens": 5})
    obs.agent_finished("Coder", 1.0)
    m = obs.export()["agent_metrics"]["Coder"]
    assert m["usage_available"] and m["input_tokens"] == 50 and m["llm_failures"] == 1
    assert obs.usage_totals()["total_tokens"] == 55
    obs.llm_started("c3", "Coder", "m")
    obs.llm_finished("c3", "Coder", None)                               # answered without usage → unknown
    assert obs.usage_totals()["usage_available"] is False


# --- per-request input budget, invalid tool calls, repeated provider failures ------------------------

def _history(n_tool_outputs=12, size=3000):
    msgs = [{"role": "system", "content": "You are the Coder."}, {"role": "user", "content": "Build a notes app."}]
    for i in range(n_tool_outputs):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function",
                     "function": {"name": "write_file", "arguments": '{"path": "f%d.js", "content": "%s"}' % (i, "x" * size)}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"output {i} " + "y" * size})
    return msgs


def test_history_is_shortened_to_the_budget_oldest_first_and_marked():
    import json
    from backend.agents.config import _estimate_tokens, fit_messages_to_budget
    msgs = _history()
    original = json.dumps(msgs)
    out, elided = fit_messages_to_budget(msgs, 5500)
    assert _estimate_tokens(out) <= 5500 and elided > 0
    assert json.dumps(msgs) == original  # caller's history untouched
    assert out[0] == msgs[0] and out[1] == msgs[1] and out[-1] == msgs[-1]  # system, task, newest kept whole
    assert "characters of earlier output elided" in out[3]["content"]  # oldest tool output shortened, and says so
    for m in out:  # past tool-call arguments stay valid JSON
        for tc in m.get("tool_calls", []):
            json.loads(tc["function"]["arguments"])
    assert fit_messages_to_budget(msgs[:4], 5500) == (msgs[:4], 0)  # small requests are sent unchanged
    assert fit_messages_to_budget(msgs, 0)[1] == 0  # 0 disables


def test_groq_requests_are_sent_within_the_default_budget(monkeypatch):
    from backend.agents.config import _estimate_tokens
    sent = []
    import crewai
    monkeypatch.setattr(crewai.LLM, "call", lambda self, messages, *a, **k: sent.append(messages) or "ok")
    llm = LLMFactory.build(AgentSettings(llm_model="groq/openai/gpt-oss-120b", llm_api_key="gsk-test"))
    assert llm.call(_history()) == "ok"
    assert _estimate_tokens(sent[0]) <= 5500 and llm.vexa_state["context_trims"] == 1


def test_request_too_large_retries_once_with_a_smaller_budget(monkeypatch):
    from backend.agents.config import _estimate_tokens
    sizes = []

    def behaviour(n, model):
        if n == 1:
            raise RuntimeError("Request too large for model on tokens per minute (TPM): Limit 8000, Requested 8702")
        return "ok"
    import crewai
    monkeypatch.setattr(crewai.LLM, "call", lambda self, m, *a, **k: sizes.append(_estimate_tokens(m)) or behaviour(len(sizes), ""))
    monkeypatch.setattr("backend.agents.config.time.sleep", lambda s: None)
    llm = LLMFactory.build(AgentSettings(llm_model="groq/openai/gpt-oss-120b", llm_api_key="gsk-test"))
    assert llm.call(_history()) == "ok"
    assert sizes[1] < sizes[0] * 0.95


def test_invalid_tool_call_is_retried_with_a_correction(monkeypatch):
    seen = []

    def behaviour(n, model):
        if n == 1:
            raise RuntimeError("tool_use_failed: attempted to call tool 'json' which was not in request.tools")
        return "final answer"
    import crewai
    monkeypatch.setattr(crewai.LLM, "call", lambda self, m, *a, **k: seen.append(m) or behaviour(len(seen), ""))
    llm = LLMFactory.build(AgentSettings(llm_model="groq/openai/gpt-oss-120b", llm_api_key="gsk-test"))
    tools = [{"type": "function", "function": {"name": "write_file"}}]
    assert llm.call([{"role": "user", "content": "go"}], tools=tools) == "final answer"
    assert "Only these tools exist: write_file" in seen[1][-1]["content"]
    assert llm.vexa_state["invalid_tool_call_retries"] == 1


def test_invalid_tool_call_gives_up_after_two_retries(monkeypatch):
    def behaviour(n, model):
        raise RuntimeError("Tool choice is none, but model called a tool")
    llm, calls, _ = _build(monkeypatch, behaviour)
    with pytest.raises(RuntimeError, match="Tool choice is none"):
        llm.call([{"role": "user", "content": "go"}])
    assert len(calls) == 3


def test_same_provider_failure_signature_ignores_numbers():
    from backend.orchestration.hierarchical import provider_failure_signature as sig
    a = sig("Coder", "AI Provider Error: Request too large ... Limit 7000, Requested 8708")
    b = sig("Coder", "AI Provider Error: Request too large ... Limit 7000, Requested 7194")
    assert a == b and a is not None
    assert sig("Coder", "Agent output failed schema validation") is None
    assert sig("Tester", "AI Provider Error: Request too large ... Requested 1") != a


def test_output_cap_error_lowers_max_tokens_and_retries(monkeypatch):
    seen = []

    def fake_call(self, messages, *a, **k):
        seen.append(self.max_tokens)
        if len(seen) == 1:
            raise RuntimeError("Request too large for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): "
                               "Limit 1000, Requested 1179. reduce max_tokens")
        return "ok"
    import crewai
    monkeypatch.setattr(crewai.LLM, "call", fake_call)
    monkeypatch.setattr("backend.agents.config.time.sleep", lambda s: None)
    llm = LLMFactory.build(AgentSettings(llm_model="groq/qwen/qwen3.8-27b", llm_api_key="gsk-test"))
    assert llm.call([{"role": "user", "content": "go"}]) == "ok"
    assert seen == [None, 900] and llm.vexa_state["max_tokens_capped"] == 900


def test_adk_history_drops_replayed_reasoning():
    """Groq rejects assistant 'reasoning_content', which ADK builds from earlier thought parts."""
    from google.genai import types

    from backend.adk_agents.verifier import drop_replayed_reasoning
    req = type("Req", (), {})()
    req.contents = [
        types.Content(role="user", parts=[types.Part(text="verify")]),
        types.Content(role="model", parts=[types.Part(text="thinking...", thought=True),
                                           types.Part(function_call=types.FunctionCall(name="read_file", args={}))]),
        types.Content(role="model", parts=[types.Part(text="only reasoning", thought=True)]),
        types.Content(role="user", parts=[types.Part(text="tool result")]),
    ]
    assert drop_replayed_reasoning(req) == 2
    assert [c.role for c in req.contents] == ["user", "model", "user"]
    assert req.contents[1].parts[0].function_call.name == "read_file"
    assert not any(getattr(p, "thought", False) for c in req.contents for p in c.parts)


def test_no_tool_request_gets_plain_text_history(monkeypatch):
    """Forced final answer (no tools offered) must not carry native tool calls (Groq: 'Tool choice is none')."""
    seen = []
    import crewai
    monkeypatch.setattr(crewai.LLM, "call", lambda self, m, *a, **k: seen.append(m) or "final")
    llm = LLMFactory.build(AgentSettings(llm_model="groq/openai/gpt-oss-120b", llm_api_key="gsk-test"))
    hist = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "app.js"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "code"},
            {"role": "user", "content": "give your final answer"}]
    assert llm.call(hist) == "final"
    sent = seen[0]
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in sent)
    assert 'read_file({"path": "app.js"})' in sent[2]["content"] and "code" in sent[3]["content"]
    assert "Tools are disabled" in sent[-1]["content"] and hist[2]["tool_calls"]  # caller's list untouched
    # with tools offered, the native history is sent as-is
    llm.call(hist, tools=[{"type": "function", "function": {"name": "read_file"}}])
    assert seen[1][2].get("tool_calls")


def test_gemini_per_minute_quota_is_a_rate_limit_not_a_daily_quota():
    """Real run: Gemini's free tier answers 429 'exceeded your current quota' for its 5 requests/minute limit;
    treating it as a daily quota stopped the run instead of waiting the 32s it asked for."""
    from backend.agents.config import _is_quota, _is_rate_limit
    err = ("429 resource_exhausted. {'error': {'code': 429, 'message': 'you exceeded your current quota', "
           "'quotaid': 'generaterequestsperminuteperprojectpermodel-freetier', 'retrydelay': '32s'}}")
    assert _is_rate_limit(err) and not _is_quota(err)
    assert retry_after_seconds(err) == pytest.approx(32.5)
    assert _is_quota("rate limit reached on tokens per day (tpd)")
