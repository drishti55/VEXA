"""
VEXA M3 — LLM Configuration

Centralised LLM/model configuration for all VEXA agents.

Environment variables:
    VEXA_LLM_MODEL            LLM model string (default: gpt-4o-mini)
    VEXA_LLM_TEMPERATURE      Sampling temperature (default: 0.1)
    VEXA_LLM_API_KEY          API key (overrides provider default, e.g. OPENAI_API_KEY)
    VEXA_LLM_BASE_URL         Optional base URL for custom endpoints / proxies
    VEXA_AGENT_MAX_ITER       Max ReAct iterations per agent (default: 10)
    VEXA_DEBUG_MAX_ITER       Max debug/repair iterations in the debug loop (default: 3)
    VEXA_AGENT_VERBOSE        Enable agent step logging (default: False)

Secrets are read from environment; none are logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """LLM and agent configuration — isolated from main Settings to keep separation clean."""

    model_config = SettingsConfigDict(
        env_file=os.environ.get("VEXA_ENV_FILE", ".env") or None,  # VEXA_ENV_FILE="" disables (tests)
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="VEXA_",  # All agent settings prefixed with VEXA_
        populate_by_name=True,  # allow AgentSettings(docs_search_api_key=...) despite the env alias
    )

    # -----------------------------------------------------------------------
    # LLM configuration
    # -----------------------------------------------------------------------
    llm_mode: str = Field(
        default="mock",
        description="Execution mode: 'mock' for deterministic tests, 'real' for live LLM.",
    )
    llm_provider: str = Field(
        default="openai",
        description="Provider mapping (e.g. 'openai', 'anthropic', 'mistral', 'gemini', 'groq').",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description=(
            "LiteLLM-compatible model string. Examples: "
            "'gpt-4o-mini', 'gpt-4o', 'anthropic/claude-3-5-haiku-20241022', "
            "'ollama/llama3.2', 'gemini/gemini-1.5-flash'"
        ),
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Lower = more deterministic.",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="Override API key. If None, falls back to provider env vars (OPENAI_API_KEY etc.).",
    )
    llm_base_url: str | None = Field(
        default=None,
        description="Custom base URL for API endpoint (proxy / local model server).",
    )
    llm_max_tokens: int | None = Field(
        default=None,
        description="Maximum response token limit. None = provider default.",
    )
    llm_max_input_tokens: int | None = Field(
        default=None,
        description="Per-request input budget (estimated tokens, incl. tool schemas). Older tool outputs "
                    "in an agent's history are shortened to stay under it. None = 5500 for Groq "
                    "(free-tier per-minute caps are 6-8k), no limit otherwise; 0 disables.",
    )
    llm_input_cost_per_1m: float | None = Field(
        default=None,
        description="Cost in USD per 1M input tokens. Example: 0.15 for gpt-4o-mini.",
    )
    llm_output_cost_per_1m: float | None = Field(
        default=None,
        description="Cost in USD per 1M output tokens. Example: 0.60 for gpt-4o-mini.",
    )

    # -----------------------------------------------------------------------
    # Fallback LLM (used when primary hits rate limits or quota)
    # -----------------------------------------------------------------------
    llm_fallback_provider: str | None = Field(
        default=None,
        description="Fallback provider (e.g. 'mistral'). None = no fallback.",
    )
    llm_fallback_model: str | None = Field(
        default=None,
        description="Fallback model string (e.g. 'mistral/mistral-small-latest').",
    )
    llm_fallback_api_key: str | None = Field(
        default=None,
        description="API key for the fallback provider.",
    )

    # -----------------------------------------------------------------------
    # Agent execution controls
    # -----------------------------------------------------------------------
    agent_max_iter: int = Field(
        default=10,
        ge=1,
        description="Maximum ReAct tool-use iterations per agent before stopping.",
    )
    debug_max_iter: int = Field(
        default=3,
        ge=1,
        description="Maximum debug/repair iterations in the Debugger loop.",
    )
    agent_verbose: bool = Field(
        default=False,
        description="Enable verbose step-by-step logging from CrewAI agents.",
    )
    output_validation_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Times an agent is re-prompted when its output fails schema validation.",
    )
    max_tool_calls_per_agent: int = Field(
        default=25, ge=1, description="Guardrail G3: tool calls allowed per agent invocation.",
    )
    max_run_seconds: float = Field(
        default=1800.0, gt=0, description="Guardrail G7: wall-clock budget for one run.",
    )
    injection_classifier: str = Field(
        default="auto", pattern="^(auto|on|off)$",
        description="G6 model classifier: auto = real mode with GROQ_API_KEY set; on; off.",
    )
    injection_classifier_model: str = Field(default="groq/meta-llama/llama-prompt-guard-2-86m")
    prompt_version_pin: str | None = Field(
        default=None,
        description="Rerun with an archived prompt version (16-hex hash). Fails the run if it is not archived.",
    )
    max_run_tokens: int | None = Field(
        default=None, ge=1000,
        description="Guardrail G7: stop a run once its LLM calls have used this many tokens (unset = no limit).",
    )
    manager_mock_policy: str | None = Field(
        default=None,
        description='Hierarchical mock mode: JSON overrides of category → strategy, e.g. {"refactoring": "plan_first"}',
    )
    manager_revision_budget: int = Field(
        default=2, ge=0, le=5, description="Hierarchical: revisions the Manager may order (re-plan / re-code / rework).",
    )
    prompt_variant: str = Field(
        default="baseline",
        pattern="^(baseline|react|few_shot|minimal_persona)$",
        description="Prompt strategy (backend.agents.prompt_variants). Held constant across architectures.",
    )

    # -----------------------------------------------------------------------
    # Tools / MCP
    # -----------------------------------------------------------------------
    tool_transport: str = Field(
        default="mcp",
        pattern="^(mcp|direct)$",
        description="How agents reach workspace tools in real mode: 'mcp' (stdio MCP server) or 'direct'.",
    )
    docs_search_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TAVILY_API_KEY", "VEXA_DOCS_SEARCH_API_KEY"),
        description="Tavily API key for the docs-search MCP server. Unset = docs search disabled.",
    )
    docs_search_roles: str = Field(
        default="Planner,Coder,Debugger",
        description="Comma-separated agent ids that get the search_docs MCP tool.",
    )
    # -----------------------------------------------------------------------
    # Cross-framework Verifier (Google ADK agent over A2A)
    # -----------------------------------------------------------------------
    verifier_backend: str = Field(
        default="adk_a2a",
        pattern="^(crewai|adk_a2a)$",
        description="'crewai' = in-process CrewAI Verifier; 'adk_a2a' = remote Google ADK Verifier over A2A.",
    )
    a2a_embedded: bool = Field(
        default=True,
        description="Start the ADK Verifier A2A server inside the backend process (real HTTP A2A on localhost). "
                    "Set false to use an external server at a2a_verifier_url.",
    )
    a2a_embedded_port: int = Field(default=8101, ge=0, le=65535, description="0 = pick a free port")
    a2a_verifier_url: str = Field(default="http://127.0.0.1:8101", description="Base URL of an external ADK Verifier.")
    a2a_token: str | None = Field(default=None, description="Bearer token shared with the A2A server (VEXA_A2A_TOKEN).")
    a2a_timeout_seconds: float = Field(default=300.0, gt=0)
    adk_model: str | None = Field(default=None, description="LiteLLM model for the ADK verifier (VEXA_ADK_MODEL)")
    adk_api_key: str | None = Field(default=None, description="Key for the ADK verifier model (VEXA_ADK_API_KEY)")
    mock_step_delay_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Artificial delay per agent step in mock mode (useful for UI demos).",
    )


logger = logging.getLogger(__name__)


_MODEL_PREFIX_PROVIDERS = ("openai", "anthropic", "groq", "gemini", "mistral", "ollama", "openrouter",
                           "deepseek", "together_ai", "azure", "bedrock", "vertex_ai", "cohere", "xai")


def infer_provider(model: str | None, configured: str | None = None) -> str:
    """
    Provider implied by a LiteLLM model string ("groq/llama-3.3-70b" → "groq").
    Bare model names keep the configured provider (default openai).
    """
    prefix = (model or "").split("/", 1)[0].lower() if "/" in (model or "") else ""
    if prefix in _MODEL_PREFIX_PROVIDERS:
        return prefix
    return (configured or "openai").lower()


def get_agent_settings() -> AgentSettings:
    """Return an AgentSettings instance (not cached — allows test override)."""
    return AgentSettings()


_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
}


def export_provider_keys_from_env_file() -> list[str]:
    """
    Make provider keys written in .env (GROQ_API_KEY, TAVILY_API_KEY, ...) visible to
    LiteLLM / MCP servers, which read os.environ (pydantic-settings does not export
    them). Only allowlisted key names are exported; existing environment values win.
    Returns the exported variable *names* (never values); each value is registered
    for redaction.
    """
    path = os.environ.get("VEXA_ENV_FILE", ".env")
    if not path or not os.path.exists(path):
        return []
    from dotenv import dotenv_values

    from backend.observability.redaction import register_secret

    allowed = {*_PROVIDER_KEY_ENV.values(), "TAVILY_API_KEY"}
    exported = []
    for name, value in dotenv_values(path).items():
        if name in allowed and value and not os.environ.get(name):
            os.environ[name] = value
            exported.append(name)
        if name in allowed and value:
            register_secret(value)
    return exported


def provider_status(settings: AgentSettings | None = None) -> dict[str, Any]:
    """Whether the configured model has a key — names and booleans only, never values."""
    s = settings or AgentSettings()
    provider = infer_provider(s.llm_model, s.llm_provider)
    env_key = _PROVIDER_KEY_ENV.get(provider)
    source = ("VEXA_LLM_API_KEY" if s.llm_api_key else env_key if env_key and os.environ.get(env_key) else None)
    fb_provider = infer_provider(s.llm_fallback_model, s.llm_fallback_provider) if s.llm_fallback_model else None
    return {
        "model": s.llm_model, "provider": provider, "api_key_configured": source is not None,
        "key_source": source, "required_env": env_key or "VEXA_LLM_API_KEY",
        "fallback_model": s.llm_fallback_model or None, "fallback_provider": fb_provider,
        "fallback_key_configured": bool(s.llm_fallback_api_key or (
            fb_provider and os.environ.get(_PROVIDER_KEY_ENV.get(fb_provider, "_")))) if fb_provider else None,
        "docs_search_configured": bool(s.docs_search_api_key or os.environ.get("TAVILY_API_KEY")),
        "adk_model": s.adk_model or s.llm_model,
    }


def _is_rate_limit(err: str) -> bool:
    return "rate limit" in err or "429" in err


_TRANSIENT = ("internalservererror", "serviceunavailable", "apiconnectionerror", "connection error",
              "connection reset", "nodename nor servname", "name or service not known", "temporary failure in name",
              "502", "503", "504", "timed out", "timeout")


def _is_transient(err: str) -> bool:
    """Network / provider hiccups worth a short, bounded retry (never auth or validation errors)."""
    return any(t in err for t in _TRANSIENT) and "invalid api key" not in err and "authentication" not in err


def _is_quota(err: str) -> bool:
    if "perminute" in err:  # Gemini free tier: "...RequestsPerMinute..." quota ids are per-minute rate limits
        return False
    return "tokens per day" in err or "tpd" in err or "quota" in err


def retry_after_seconds(err: str, default: float = 20.0, cap: float = 65.0) -> float:
    """Wait time a provider asks for ("try again in 14.6s" / "in 1m2.5s"), else *default*."""
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)\b", err)
    if not m:
        m = re.search(r"retrydelay['\"]?\s*:\s*['\"]([\d.]+)s", err)  # Gemini: 'retryDelay': '32s'
        if not m:
            return default
        return min(cap, float(m.group(1)) + 0.5)
    minutes = int(m.group(1) or 0)
    value = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
    return min(cap, minutes * 60 + value + 0.5)


def _output_cap_exceeded(err: str) -> int | None:
    """The provider's per-request output cap ("output tokens per minute (OTPM): Limit 1000"), if that is the error."""
    if "output tokens per minute" not in err and "otpm" not in err:
        return None
    m = re.search(r"limit\s+(\d+)", err)
    return int(m.group(1)) if m else None


def _prompt_permanently_too_large(err: str) -> bool:
    m = re.search(r"limit\s+(\d+),\s*requested\s+(\d+)", err)
    return bool(m and int(m.group(2)) > int(m.group(1)))


def _is_invalid_tool_call(err: str) -> bool:
    return any(t in err for t in ("tool_use_failed", "tool call validation failed", "tool choice is none",
                                  "failed to parse tool call arguments", "which was not in request.tools"))


_ELIDED = ("[VEXA: {n} characters of earlier output elided to keep this request within the "
           "{budget}-token input budget. Re-read the file or re-run the tool if you need it.]")


def _estimate_tokens(messages: list, tools: Any = None) -> int:
    """Deliberately conservative (about 3 characters per token)."""
    chars = sum(len(json.dumps(m, default=str)) for m in messages)
    if tools:
        chars += len(json.dumps(tools, default=str))
    return chars // 3


def _shorten_args(arguments: str, keep: int, budget: int) -> str:
    """Shorten long string values inside a past tool call's JSON arguments (keeps valid JSON)."""
    try:
        args = json.loads(arguments)
    except (TypeError, ValueError):
        return arguments
    if not isinstance(args, dict):
        return arguments
    changed = False
    for k, v in args.items():
        if isinstance(v, str) and len(v) > keep + 200:
            args[k] = v[:keep] + "\n" + _ELIDED.format(n=len(v) - keep, budget=budget)
            changed = True
    return json.dumps(args) if changed else arguments


def flatten_tool_history(messages: Any) -> Any:
    """
    Rewrite earlier tool calls/results as plain text, for a request that offers no tools.

    CrewAI's forced final answer (after max_iter) sends the native tool-call
    history without tools; gpt-oss on Groq then often emits another tool call
    and the provider rejects the request ("Tool choice is none, but model called
    a tool"). Measured against Groq: 3/5 such requests failed as-is, 0/5 once the
    history was plain text. Nothing is lost: calls and results stay in the text.
    """
    if not isinstance(messages, list):
        return messages
    out: list = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            calls = "; ".join(f'{tc["function"].get("name")}({tc["function"].get("arguments", "")})'
                              for tc in m["tool_calls"]
                              if isinstance(tc, dict) and isinstance(tc.get("function"), dict))
            text = m.get("content") if isinstance(m.get("content"), str) else ""
            out.append({"role": "assistant", "content": (text.strip() + "\n" if text and text.strip() else "")
                        + f"[I called: {calls}]"})
        elif m.get("role") == "tool":
            out.append({"role": "user", "content": f"[Result of {m.get('name') or 'the tool call'}]\n"
                                                   f"{m.get('content') or ''}"})
        else:
            out.append(m)
    return out


_NO_TOOLS_NOTE = ("Tools are disabled for this reply: do not call any tool. "
                  "Give your final answer now as plain text.")


def fit_messages_to_budget(messages: Any, budget: int | None, tools: Any = None) -> tuple[Any, int]:
    """
    Return (messages, elided_chars) with the request under *budget* estimated tokens.

    Oldest content is shortened first; system messages, the task (first user
    message) and the newest message are kept whole unless nothing else is left.
    Each shortened part says how much was removed, so the model can re-read it.
    The caller's list is not modified.
    """
    if not budget or not isinstance(messages, list) or _estimate_tokens(messages, tools) <= budget:
        return messages, 0
    out = [dict(m) if isinstance(m, dict) else m for m in messages]
    first_user = next((i for i, m in enumerate(out) if isinstance(m, dict) and m.get("role") == "user"), None)
    protected = {i for i, m in enumerate(out) if isinstance(m, dict) and m.get("role") == "system"}
    protected |= {first_user, len(out) - 1}
    elided = 0

    def shrink(i: int, keep: int) -> bool:
        nonlocal elided
        m = out[i]
        if not isinstance(m, dict):
            return False
        changed = False
        c = m.get("content")
        if isinstance(c, str) and len(c) > keep + 200:
            m["content"] = c[:keep] + "\n" + _ELIDED.format(n=len(c) - keep, budget=budget)
            elided += len(c) - keep
            changed = True
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                tc = dict(tc) if isinstance(tc, dict) else tc
                fn = tc.get("function") if isinstance(tc, dict) else None
                if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                    new = _shorten_args(fn["arguments"], keep, budget)
                    if new != fn["arguments"]:
                        elided += len(fn["arguments"]) - len(new)
                        tc["function"] = {**fn, "arguments": new}
                        changed = True
                calls.append(tc)
            m["tool_calls"] = calls
        return changed

    for keep in (600, 150):
        for i in range(len(out)):
            if i not in protected and shrink(i, keep) and _estimate_tokens(out, tools) <= budget:
                return out, elided
    # Last resort: the newest message (often a large tool result) and the system prompt's tail.
    for i in sorted(protected - {first_user}, reverse=True) + ([first_user] if first_user is not None else []):
        if i is not None and shrink(i, max(1500, budget)) and _estimate_tokens(out, tools) <= budget:
            break
    return out, elided


class LLMFactory:
    """
    Validates configuration and instantiates the real LLM for CrewAI.

    Rate limits are retried with a back-off. If a fallback model is configured,
    a daily-quota error switches *this LLM instance* to the fallback for the rest
    of the run. Nothing is patched globally and no keys are written to
    ``os.environ`` (which would leak them into sandboxed subprocesses and race
    between concurrent runs).

    The returned object exposes ``vexa_state`` with the model actually used, so
    usage can be attributed and priced correctly.
    """

    @staticmethod
    def build(settings: AgentSettings | None = None) -> Any:
        if settings is None:
            settings = get_agent_settings()

        provider = infer_provider(settings.llm_model, settings.llm_provider)
        env_key = _PROVIDER_KEY_ENV.get(provider)
        if env_key and not settings.llm_api_key and not os.environ.get(env_key):
            raise ValueError(f"VEXA_LLM_API_KEY (or {env_key}) is not configured.")

        try:
            from crewai import LLM
        except ImportError:
            raise RuntimeError("crewai package is not installed.")

        # Workaround for CrewAI bug where cache_breakpoint is sent to non-Anthropic providers
        if provider != "anthropic":
            try:
                import crewai.llms.cache as _crewai_cache
                _crewai_cache.mark_cache_breakpoint = lambda msg: msg
            except ImportError:
                pass

        kwargs: dict = {
            "model": settings.llm_model,
            "temperature": settings.llm_temperature,
            "max_retries": 3,
        }
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        if settings.llm_max_tokens:
            kwargs["max_tokens"] = settings.llm_max_tokens
        primary = LLM(**kwargs)

        fallback = None
        if settings.llm_fallback_model and settings.llm_fallback_provider:
            fb_kwargs: dict = {
                "model": settings.llm_fallback_model,
                "temperature": settings.llm_temperature,
                "max_retries": 3,
            }
            if settings.llm_fallback_api_key:
                fb_kwargs["api_key"] = settings.llm_fallback_api_key
            fallback = LLM(**fb_kwargs)
            logger.info("LLM fallback configured | primary=%s fallback=%s",
                        settings.llm_model, settings.llm_fallback_model)

        state = {"active_model": settings.llm_model, "using_fallback": False, "rate_limit_retries": 0}
        primary_call = primary.call

        budget = settings.llm_max_input_tokens
        if budget is None and provider == "groq":
            budget = 5500
        state["input_budget_tokens"] = budget or None

        def call_with_failover(messages, *args, **call_kwargs):
            from backend.observability.callbacks import (
                begin_llm_capture,
                close_uncompleted_llm_calls,
            )
            retries = 5
            call_budget = budget
            tool_retries = 0
            shrunk_after_too_large = False
            rate_limited = transient = 0
            if (not call_kwargs.get("tools") and isinstance(messages, list)
                    and any(isinstance(m, dict) and (m.get("tool_calls") or m.get("role") == "tool") for m in messages)):
                messages = [*flatten_tool_history(messages), {"role": "user", "content": _NO_TOOLS_NOTE}]
                state["flattened_tool_history"] = state.get("flattened_tool_history", 0) + 1
            # Each failure kind has its own cap, so the loop always ends in a return or a raise.
            while True:
                target = fallback.call if state["using_fallback"] and fallback else primary_call
                sent, elided = fit_messages_to_budget(messages, call_budget, call_kwargs.get("tools"))
                if elided:
                    state["context_trims"] = state.get("context_trims", 0) + 1
                    state["elided_chars"] = state.get("elided_chars", 0) + elided
                    logger.info("LLM request shortened to fit %s-token budget (%d chars of old output elided)",
                                call_budget, elided)
                begin_llm_capture()
                try:
                    return target(sent, *args, **call_kwargs)
                except Exception as e:
                    err = str(e).lower()
                    if _is_invalid_tool_call(err) and tool_retries < 2 and isinstance(messages, list):
                        # Models (notably gpt-oss on Groq) sometimes call a tool that does not exist or
                        # call one when none are offered. Tell the model what went wrong and ask again.
                        tool_retries += 1
                        state["invalid_tool_call_retries"] = state.get("invalid_tool_call_retries", 0) + 1
                        offered = [t.get("function", {}).get("name") for t in (call_kwargs.get("tools") or [])
                                   if isinstance(t, dict)]
                        hint = ("Only these tools exist: " + ", ".join(n for n in offered if n) + ". "
                                if offered else "No tools are available in this step. ")
                        messages = [*messages, {"role": "user", "content": (
                            "Your previous reply was rejected by the provider because of an invalid tool call. "
                            + hint + "Call tools only by those exact names with JSON arguments; when you are "
                            "done, give the final answer as plain text without a tool call.")}]
                        logger.warning("LLM produced an invalid tool call; retrying (%d/2): %s",
                                       tool_retries, err[:160])
                        continue
                    if _is_transient(err) and not (_is_rate_limit(err) or _is_quota(err)):
                        if transient >= 2:
                            raise
                        transient += 1
                        state["transient_retries"] = state.get("transient_retries", 0) + 1
                        wait = 2.0 * (2 ** (transient - 1))
                        logger.warning("LLM transient error (attempt %d); retrying in %.0fs: %s",
                                       transient, wait, err[:120])
                        time.sleep(wait)
                        continue
                    out_cap = _output_cap_exceeded(err)
                    if out_cap and not state.get("max_tokens_capped"):
                        # Groq expects max_tokens to fit the per-minute output cap (e.g. qwen: 1000 on the
                        # free tier). Cap it on this model for the rest of the run and try again.
                        llm_obj = fallback if state["using_fallback"] and fallback else primary
                        object.__setattr__(llm_obj, "max_tokens", max(64, int(out_cap * 0.9)))
                        state["max_tokens_capped"] = llm_obj.max_tokens
                        logger.warning("Provider output cap %d tokens/min: max_tokens set to %d",
                                       out_cap, llm_obj.max_tokens)
                        time.sleep(retry_after_seconds(err, default=5))
                        continue
                    if out_cap:
                        raise
                    if _prompt_permanently_too_large(err):
                        # One retry with a budget scaled to the provider's stated limit.
                        m = re.search(r"limit\s+(\d+),\s*requested\s+(\d+)", err)
                        if shrunk_after_too_large or not m or not isinstance(messages, list):
                            raise
                        shrunk_after_too_large = True
                        current = call_budget or _estimate_tokens(messages, call_kwargs.get("tools"))
                        call_budget = max(1000, int(current * int(m.group(1)) / int(m.group(2)) * 0.8))
                        logger.warning("LLM request too large for the provider's per-minute cap; "
                                       "retrying with a %d-token budget", call_budget)
                        time.sleep(retry_after_seconds(err, default=5))
                        continue
                    if not (_is_rate_limit(err) or _is_quota(err)):
                        raise
                    if _is_quota(err) and fallback and not state["using_fallback"]:
                        logger.warning("Primary LLM quota exhausted; switching to fallback %s",
                                       settings.llm_fallback_model)
                        state["using_fallback"] = True
                        state["active_model"] = settings.llm_fallback_model
                        continue
                    if _is_quota(err):
                        # Daily quota with no (further) fallback: waiting minutes per retry cannot help.
                        state["quota_exhausted"] = True
                        raise
                    if rate_limited >= retries - 1:
                        raise
                    rate_limited += 1
                    state["rate_limit_retries"] += 1
                    wait = retry_after_seconds(err, default=2 if state["using_fallback"] else 20)
                    logger.warning("LLM rate limit (attempt %d/%d); sleeping %.1fs", rate_limited, retries, wait)
                    time.sleep(wait)
                finally:
                    close_uncompleted_llm_calls()

        # CrewAI calls llm.call(); wrap it on this instance only.
        object.__setattr__(primary, "call", call_with_failover)
        object.__setattr__(primary, "vexa_state", state)
        return primary
