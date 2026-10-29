"""
A2A client used by the CrewAI runtime to delegate work to remote agents.

``A2AAgentClient.send_json`` resolves the remote agent card, sends one
``message/send`` request carrying a JSON text part, follows the returned task
until it reaches a terminal state, and returns the agent's text output together
with protocol metadata (task id, context id, final state, agent card name and
skills) for the coordination log.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

_TERMINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED",
             "TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}


class A2AError(RuntimeError):
    pass


@dataclass
class A2AExchange:
    text: str
    task_id: str | None
    context_id: str | None
    state: str
    agent_name: str
    agent_skills: list[str]
    protocol_version: str | None
    duration_ms: float
    states_seen: list[str] = field(default_factory=list)


class A2AAgentClient:
    def __init__(self, url: str, token: str | None = None, timeout: float = 300.0,
                 transport: httpx.AsyncBaseTransport | None = None, extra_headers: dict[str, str] | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self._transport = transport  # tests can inject an ASGI transport

    def send_json(self, payload: dict[str, Any]) -> A2AExchange:
        """Synchronous wrapper (the CrewAI runtime is synchronous)."""
        return asyncio.run(self._send(json.dumps(payload)))

    async def _send(self, text: str) -> A2AExchange:
        from a2a.client import ClientConfig, ClientFactory
        from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

        headers = {**self.extra_headers, **({"Authorization": f"Bearer {self.token}"} if self.token else {})}
        t0 = time.perf_counter()
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout, transport=self._transport) as http:
            factory = ClientFactory(ClientConfig(httpx_client=http, streaming=False))
            try:
                client = await factory.create_from_url(self.url)
            except Exception as exc:
                raise A2AError(f"could not resolve agent card at {self.url}: {exc}") from exc
            card = client._card if hasattr(client, "_card") else None
            request = SendMessageRequest(message=Message(
                role=Role.ROLE_USER, message_id=uuid.uuid4().hex, parts=[Part(text=text)],
            ))
            texts: list[str] = []
            task_id = context_id = None
            states: list[str] = []
            try:
                async for event in client.send_message(request):
                    if event.HasField("task"):
                        task = event.task
                        task_id, context_id = task.id or task_id, task.context_id or context_id
                        states.append(TaskState.Name(task.status.state))
                        for art in task.artifacts:
                            texts += [p.text for p in art.parts if p.text]
                        if not task.artifacts and task.status.message.parts:
                            texts += [p.text for p in task.status.message.parts if p.text]
                    elif event.HasField("message"):
                        texts += [p.text for p in event.message.parts if p.text]
                        states.append("MESSAGE")
                # Follow the task if the server returned before completion.
                deadline = time.monotonic() + self.timeout
                from a2a.types import GetTaskRequest
                while task_id and states and states[-1] not in _TERMINAL and time.monotonic() < deadline:
                    await asyncio.sleep(0.5)
                    task = await client.get_task(GetTaskRequest(id=task_id))
                    states.append(TaskState.Name(task.status.state))
                    if states[-1] in _TERMINAL:
                        texts = [p.text for art in task.artifacts for p in art.parts if p.text] or texts
            except httpx.HTTPStatusError as exc:
                raise A2AError(f"A2A request rejected: HTTP {exc.response.status_code}") from exc
            except A2AError:
                raise
            except Exception as exc:
                raise A2AError(f"A2A request failed: {type(exc).__name__}: {exc}") from exc
            finally:
                await client.close()

        final = states[-1] if states else "UNKNOWN"
        if final in {"TASK_STATE_FAILED", "TASK_STATE_REJECTED", "TASK_STATE_CANCELED", "TASK_STATE_AUTH_REQUIRED"}:
            raise A2AError(f"remote task ended in {final}: {' '.join(texts)[:300]}")
        return A2AExchange(
            text="\n".join(texts), task_id=task_id, context_id=context_id, state=final,
            agent_name=card.name if card else "", agent_skills=[s.name for s in card.skills] if card else [],
            protocol_version=getattr(card, "protocol_version", None) if card else None,
            duration_ms=(time.perf_counter() - t0) * 1000, states_seen=states,
        )
