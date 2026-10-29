"""
Embedded ADK Verifier A2A server.

By default the backend starts the Google ADK Verifier as a second ASGI app on
localhost (its own uvicorn server, its own port, a random bearer token). The
CrewAI runtime still talks to it over real A2A JSON-RPC/HTTP — the embedding
only removes the need to start a separate process by hand.

Credential handles: when a run supplies an API key through the UI, the key is
kept in this process and only an opaque handle id is put in the A2A payload.
The embedded verifier resolves the handle; an external verifier cannot, and
uses its own environment instead.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
from dataclasses import dataclass

from backend.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_server = None
_info: tuple[str, str] | None = None
_credentials: dict[str, tuple[str, str | None]] = {}


@dataclass(frozen=True)
class EmbeddedVerifier:
    url: str
    token: str


def register_credentials(model: str, api_key: str | None) -> str:
    handle = secrets.token_hex(12)
    with _lock:
        _credentials[handle] = (model, api_key)
    return handle


def resolve_credentials(handle: str | None) -> tuple[str, str | None] | None:
    if not handle:
        return None
    with _lock:
        return _credentials.get(handle)


def release_credentials(handle: str | None) -> None:
    with _lock:
        _credentials.pop(handle or "", None)


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_embedded_verifier(preferred_port: int = 8101, timeout: float = 20.0) -> EmbeddedVerifier:
    """Start the embedded A2A verifier once per process; return its URL and token."""
    global _server, _info
    with _lock:
        if _info is not None:
            return EmbeddedVerifier(*_info)
        import uvicorn

        from backend.a2a_bridge.verifier_server import create_verifier_app

        port = preferred_port if preferred_port and _port_free(preferred_port) else _free_port()
        token = secrets.token_urlsafe(24)
        app = create_verifier_app("router", host="127.0.0.1", port=port, token=token)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, name="vexa-a2a-verifier", daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive():
                raise RuntimeError("embedded A2A verifier did not start")
            time.sleep(0.05)
        _server, _info = server, (f"http://127.0.0.1:{port}", token)
        from backend.observability.redaction import register_secret
        register_secret(token)
        logger.info("embedded_a2a_verifier_started | url=%s", _info[0])
        return EmbeddedVerifier(*_info)


def stop_embedded_verifier() -> None:
    global _server, _info
    with _lock:
        if _server is not None:
            _server.should_exit = True
        _server, _info = None, None
