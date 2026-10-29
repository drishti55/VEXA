"""
A2A server for the ADK Verifier.

Serves the Google ADK verifier agent over the Agent2Agent protocol using ADK's
``to_a2a`` (JSON-RPC transport, agent card at /.well-known/agent-card.json).

Security
--------
ADK only *advertises* security schemes in the agent card. This module also
*enforces* them: when VEXA_A2A_TOKEN is set every request except the public
agent card must carry ``Authorization: Bearer <token>``.

Run (separate process / container):
    VEXA_A2A_TOKEN=... python -m backend.a2a_bridge.verifier_server --port 8101 --mode real
"""

from __future__ import annotations

import argparse
import hmac
import os
from typing import Any

from a2a.types import HTTPAuthSecurityScheme, SecurityScheme
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.adk_agents.verifier import build_verifier

PUBLIC_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")


class TraceContextMiddleware:
    """Continue the caller's W3C trace (traceparent) for everything ADK does in this request.

    Pure ASGI (not BaseHTTPMiddleware) so the attached context is the one the
    A2A handler and the ADK runner execute in.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        from opentelemetry import context as otel_context
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        carrier = {k: headers[k] for k in ("traceparent", "tracestate") if k in headers}
        if not carrier:
            return await self.app(scope, receive, send)
        token = otel_context.attach(TraceContextTextMapPropagator().extract(carrier))
        try:
            return await self.app(scope, receive, send)
        finally:
            otel_context.detach(token)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._expected = f"Bearer {token}"

    async def dispatch(self, request: Request, call_next):
        if request.method == "GET" and request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if not hmac.compare_digest(request.headers.get("authorization", ""), self._expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def make_adk_model(model: str, api_key: str | None = None) -> Any:
    """ADK LiteLLM model with provider-guided rate-limit retries (see RetryingLiteLlm)."""
    from backend.adk_agents.verifier import RetryingLiteLlm
    return RetryingLiteLlm(model=model, **({"api_key": api_key} if api_key else {}))


def adk_model_from_env() -> Any:
    """LiteLLM-backed ADK model from VEXA_ADK_MODEL / VEXA_ADK_API_KEY (falls back to VEXA_LLM_*; .env is read)."""
    from backend.agents.config import get_agent_settings

    s = get_agent_settings()
    model = s.adk_model or s.llm_model
    if not model:
        raise RuntimeError("no model configured: set VEXA_ADK_MODEL or VEXA_LLM_MODEL")
    key = s.adk_api_key or s.llm_api_key
    return make_adk_model(model, key)


def create_verifier_app(
    mode: str = "mock",
    *,
    host: str = "127.0.0.1",
    port: int = 8101,
    token: str | None = None,
    model: Any = None,
) -> Starlette:
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    # Spans of this process reach VEXA's collector; ADK must not copy prompts/responses into them.
    os.environ.setdefault("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "false")
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
    from backend.observability.tracing import ensure_tracing
    ensure_tracing()

    if mode == "real" and model is None:
        model = adk_model_from_env()  # router mode resolves models per request
    agent = build_verifier(mode, model=model)
    schemes = None
    if token:
        schemes = {"bearer": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer"))}
    app = to_a2a(agent, host=host, port=port, security_schemes=schemes,
                 default_skill_security=[{"bearer": []}] if token else None)
    if token:
        app.add_middleware(BearerAuthMiddleware, token=token)
    app.add_middleware(TraceContextMiddleware)  # outermost: the context covers auth + handler
    return app


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="VEXA ADK Verifier over A2A")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8101)
    p.add_argument("--mode", choices=["mock", "real", "router"], default="router",
                   help="router = mock or real per request (execution_mode in the payload)")
    a = p.parse_args()
    token = os.environ.get("VEXA_A2A_TOKEN")
    if not token and a.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("Refusing to listen on a non-local interface without VEXA_A2A_TOKEN")
    uvicorn.run(create_verifier_app(a.mode, host=a.host, port=a.port, token=token), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
