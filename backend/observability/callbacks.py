"""
CrewAI callback integration.

``VexaCrewAIListener`` subscribes to CrewAI's event bus (the framework's
supported callback mechanism) and forwards events to the RunObserver of the
run that owns the CrewAI Agent/Task:

    task started / completed (intermediate output, redacted) / failed
    LLM call started / completed (model, token usage, finish reason) / failed
    guardrail (schema validation) passed / failed  → validation retries
    tool selection / input-validation / usage errors

CrewAI dispatches handlers on a thread pool, so the runtime calls
``flush_events()`` after each kickoff before reading results.
"""

from __future__ import annotations

import threading
from typing import Any

from backend.observability.tracing import RunObserver

_lock = threading.Lock()
_by_crewai_id: dict[str, tuple[RunObserver, str]] = {}
_listener: Any = None


def register_crewai_objects(observer: RunObserver, agent_id: str, *objects: Any) -> None:
    """Map CrewAI Agent/Task ids to (observer, VEXA agent id)."""
    with _lock:
        for obj in objects:
            oid = getattr(obj, "id", None)
            if oid is not None:
                _by_crewai_id[str(oid)] = (observer, agent_id)


def unregister_crewai_objects(*objects: Any) -> None:
    with _lock:
        for obj in objects:
            _by_crewai_id.pop(str(getattr(obj, "id", "")), None)


def _resolve(event: Any) -> tuple[RunObserver, str] | tuple[None, None]:
    candidates = [getattr(event, "task_id", None), getattr(event, "agent_id", None)]
    for attr in ("from_task", "from_agent", "task", "agent"):
        obj = getattr(event, attr, None)
        if obj is not None:
            candidates.append(getattr(obj, "id", None))
    with _lock:
        for c in candidates:
            if c is not None and str(c) in _by_crewai_id:
                return _by_crewai_id[str(c)]
    return None, None


def flush_events(timeout: float = 10.0) -> None:
    try:
        from crewai.events.event_bus import crewai_event_bus
        crewai_event_bus.flush(timeout=timeout)
    except Exception:
        pass


def ensure_listener() -> None:
    """Register the listener once per process (no-op without crewai)."""
    global _listener
    with _lock:
        if _listener is not None:
            return
        try:
            _listener = _build_listener()
        except ImportError:
            _listener = False
    install_litellm_capture()


# ---------------------------------------------------------------------------
# CrewAI 1.15 gap: when a provider answers with native tool calls,
# LLM._handle_non_streaming_response returns them WITHOUT emitting
# LLMCallCompletedEvent, so the call's span never closes and its token usage is
# lost. VEXA records every litellm.completion response under CrewAI's call id
# and, after llm.call returns, closes only the spans CrewAI left open (the
# observer ignores a second close of the same call id, so nothing is counted
# twice).
# ---------------------------------------------------------------------------

_capture = threading.local()
_litellm_installed = False


def install_litellm_capture() -> None:
    global _litellm_installed
    with _lock:
        if _litellm_installed:
            return
        try:
            import litellm
            from crewai.llms.base_llm import _current_call_id
        except ImportError:
            return
        original = litellm.completion

        def completion(*args: Any, **kwargs: Any) -> Any:
            response = original(*args, **kwargs)
            records = getattr(_capture, "records", None)
            call_id = _current_call_id.get()
            if records is not None and call_id and not kwargs.get("stream"):
                usage = getattr(response, "usage", None)
                choices = getattr(response, "choices", None) or []
                finish = getattr(choices[0], "finish_reason", None) if choices else None
                records.append((call_id, {"prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                                          "completion_tokens": getattr(usage, "completion_tokens", 0) or 0}
                                if usage is not None else None, finish))
            return response

        completion.__wrapped__ = original  # type: ignore[attr-defined]
        litellm.completion = completion
        _litellm_installed = True


def begin_llm_capture() -> None:
    _capture.records = []


def close_uncompleted_llm_calls() -> int:
    """Close LLM spans CrewAI never completed, with the usage LiteLLM returned. Returns how many."""
    from backend.observability.tracing import _collector

    records = getattr(_capture, "records", None) or []
    _capture.records = None
    if not records:
        return 0
    flush_events()  # let queued CrewAI events close what they will
    closed = 0
    for call_id, usage, finish in records:
        for obs in _collector.observers():
            if obs.has_open_llm_call(call_id):
                obs.llm_finished(call_id, obs.open_llm_agent(call_id), usage,
                                 finish_reason=f"{finish or 'unknown'} (closed by VEXA: no CrewAI completion event)")
                closed += 1
    return closed


def _build_listener() -> Any:
    from crewai.events import BaseEventListener
    from crewai.events.types.llm_events import LLMCallCompletedEvent, LLMCallFailedEvent, LLMCallStartedEvent
    from crewai.events.types.llm_guardrail_events import LLMGuardrailCompletedEvent
    from crewai.events.types.task_events import TaskCompletedEvent, TaskFailedEvent, TaskStartedEvent
    from crewai.events.types.tool_usage_events import (
        ToolSelectionErrorEvent,
        ToolUsageErrorEvent,
        ToolValidateInputErrorEvent,
    )

    class VexaCrewAIListener(BaseEventListener):
        def setup_listeners(self, bus) -> None:
            @bus.on(TaskStartedEvent)
            def _task_started(source, event):
                obs, agent = _resolve(event)
                if obs:
                    obs.callback_event("task_started", agent, task=getattr(event, "task_name", None))

            @bus.on(TaskCompletedEvent)
            def _task_completed(source, event):
                obs, agent = _resolve(event)
                if obs:
                    raw = getattr(getattr(event, "output", None), "raw", "")
                    obs.callback_event("task_completed", agent, output=raw)

            @bus.on(TaskFailedEvent)
            def _task_failed(source, event):
                obs, agent = _resolve(event)
                if obs:
                    obs.callback_event("task_failed", agent, error=str(getattr(event, "error", "")))

            @bus.on(LLMCallStartedEvent)
            def _llm_started(source, event):
                obs, agent = _resolve(event)
                if obs:
                    obs.llm_started(event.call_id, agent, getattr(event, "model", None))

            @bus.on(LLMCallCompletedEvent)
            def _llm_completed(source, event):
                obs, agent = _resolve(event)
                if obs:
                    obs.llm_finished(event.call_id, agent, getattr(event, "usage", None),
                                     finish_reason=getattr(event, "finish_reason", None))

            @bus.on(LLMCallFailedEvent)
            def _llm_failed(source, event):
                obs, agent = _resolve(event)
                if obs:
                    obs.llm_finished(event.call_id, agent, None, error=str(getattr(event, "error", "")))

            @bus.on(LLMGuardrailCompletedEvent)
            def _guardrail(source, event):
                obs, agent = _resolve(event)
                if obs:
                    kind = "guardrail_passed" if event.success else "guardrail_failed"
                    obs.callback_event(kind, agent, retry_count=event.retry_count, error=event.error)

            def _tool_error(source, event):
                obs, agent = _resolve(event)
                if obs:
                    obs.callback_event("tool_error", agent, tool=getattr(event, "tool_name", None),
                                       error=str(getattr(event, "error", "")))

            for ev in (ToolUsageErrorEvent, ToolValidateInputErrorEvent, ToolSelectionErrorEvent):
                bus.on(ev)(_tool_error)

    return VexaCrewAIListener()
