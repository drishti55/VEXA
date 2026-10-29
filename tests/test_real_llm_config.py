import os
import pytest
from backend.agents.config import AgentSettings, LLMFactory
from backend.agents.context import RunContext
from backend.agents.contracts import RunResult

class TestLLMFactory:
    def test_mock_mode_default(self):
        settings = AgentSettings(llm_mode="mock")
        assert settings.llm_mode == "mock"

    def test_build_openai_without_key_raises(self, monkeypatch):
        # Ensure no key in environment
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("VEXA_LLM_API_KEY", raising=False)
        
        settings = AgentSettings(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_api_key=None,
        )
        
        with pytest.raises(ValueError, match="VEXA_LLM_API_KEY.*is not configured"):
            LLMFactory.build(settings)

    def test_build_anthropic_without_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("VEXA_LLM_API_KEY", raising=False)
        
        settings = AgentSettings(
            llm_provider="anthropic",
            llm_model="anthropic/claude-3-5-haiku-20241022",
            llm_api_key=None,
        )
        
        with pytest.raises(ValueError, match="VEXA_LLM_API_KEY.*is not configured"):
            LLMFactory.build(settings)

    def test_build_with_explicit_key_succeeds(self):
        settings = AgentSettings(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_api_key="sk-fake-key",
        )
        llm = LLMFactory.build(settings)
        # Should return a CrewAI LLM wrapper where the internal model is "gpt-4o-mini"
        assert llm.model == "gpt-4o-mini"

class TestRunContextUsage:
    def test_context_usage_initialization(self):
        ctx = RunContext("ws-123", "req")
        assert not ctx.usage_available
        assert ctx.execution_mode == "mock"
        assert ctx.input_tokens == 0
        
    def test_context_to_dict_includes_usage(self):
        ctx = RunContext("ws-123", "req")
        ctx.execution_mode = "real"
        ctx.usage_available = True
        ctx.input_tokens = 1500
        ctx.estimated_cost_usd = 0.05
        
        d = ctx.to_dict()
        assert d["execution_mode"] == "real"
        assert d["usage_available"] is True
        assert d["input_tokens"] == 1500
        assert d["estimated_cost_usd"] == 0.05

class TestRunResultUsage:
    def test_run_result_usage_fields(self):
        res = RunResult(
            run_id="run-1",
            workspace_id="ws-1",
            requirement="req",
            execution_mode="real",
            provider="openai",
            model="gpt-4o",
            usage_available=True,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            estimated_cost_usd=0.01,
        )
        
        assert res.execution_mode == "real"
        assert res.provider == "openai"
        assert res.model == "gpt-4o"
        assert res.usage_available is True
        assert res.total_tokens == 30
        assert res.estimated_cost_usd == 0.01
