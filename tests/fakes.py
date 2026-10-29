"""
Test doubles shared across the suite.

ScriptedLLM is a real ``crewai.llms.base_llm.BaseLLM`` subclass. Passing it to
SoftwareEngineeringCrew in *real* mode exercises the genuine CrewAI path —
Agent, Task, Crew.kickoff(), ReAct parsing and tool execution — without any
network access. Each agent role gets its own script of ReAct turns, e.g.::

    "Action: write_file\nAction Input: {...}"   # CrewAI executes the tool
    "Final Answer: {...json...}"                # ends the agent's task
"""

from __future__ import annotations

import json
from typing import Any

from crewai.events.types.llm_events import LLMCallType
from crewai.llms.base_llm import BaseLLM, llm_call_context
from pydantic import PrivateAttr


def final(payload: dict[str, Any]) -> str:
    return "Thought: I now know the final answer\nFinal Answer: " + json.dumps(payload)


def action(tool: str, args: dict[str, Any]) -> str:
    return f"Thought: I need to use a tool\nAction: {tool}\nAction Input: {json.dumps(args)}"


class ScriptedLLM(BaseLLM):
    """Returns scripted ReAct turns keyed by a substring of the agent's role."""

    _scripts: dict[str, list[str]] = PrivateAttr(default_factory=dict)
    _calls: list[tuple[str, str]] = PrivateAttr(default_factory=list)

    def __init__(self, scripts: dict[str, list[str]], **kwargs: Any) -> None:
        super().__init__(model="scripted-test-llm", **kwargs)
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._calls = []

    @property
    def calls(self) -> list[tuple[str, str]]:
        """(role_key, last prompt text) for every call, in order."""
        return self._calls

    def _key_for(self, from_agent: Any) -> str:
        role = getattr(from_agent, "role", "") or ""
        for key in self._scripts:
            if key.lower() in role.lower():
                return key
        raise AssertionError(f"No script for agent role {role!r}")

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        key = self._key_for(from_agent)
        # The whole conversation, so tests can check what reached the agent
        # (tool observations live in earlier messages than the last one).
        text = messages if isinstance(messages, str) else "\n".join(str(m.get("content", "")) for m in messages)
        self._calls.append((key, text))
        queue = self._scripts[key]
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        # Emit the same CrewAI events a real provider does. Token counts are a
        # deterministic stand-in (chars/4) so usage plumbing can be tested.
        with llm_call_context():
            self._emit_call_started_event(messages=messages, from_task=from_task, from_agent=from_agent)
            self._emit_call_completed_event(
                response=response, call_type=LLMCallType.LLM_CALL, from_task=from_task,
                from_agent=from_agent, messages=messages,
                usage={"prompt_tokens": len(str(messages)) // 4, "completion_tokens": len(response) // 4},
            )
        return response

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 128_000
