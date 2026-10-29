"""
MCP client bridge for CrewAI agents.

``MCPServerBridge`` launches an MCP server over stdio with the official ``mcp``
SDK, keeps ONE ClientSession open for the run on a background event loop,
discovers tools with ``list_tools`` and exposes each discovered tool to CrewAI
as a BaseTool whose argument schema is generated from the tool's MCP
``inputSchema``. Every call goes over MCP (``call_tool``) with a timeout and is
traced like any other tool (span attribute ``vexa.transport = "mcp"``).

Servers are started with a minimal environment (no host secrets except those
explicitly passed) and an empty temporary working directory, so files in the
user's project — including ``.env`` — cannot influence the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, create_model

from backend.core.logging import get_logger
from backend.tools.execution import build_sandbox_env

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MCPError(RuntimeError):
    pass


@dataclass
class MCPServerSpec:
    name: str
    module: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    startup_timeout: float = 20.0
    call_timeout: float = 180.0

    def params(self, cwd: str):
        from mcp import StdioServerParameters

        env = build_sandbox_env({
            "PYTHONPATH": str(PROJECT_ROOT),
            "CREWAI_DISABLE_TELEMETRY": "true",
            "LOG_LEVEL": "WARNING",
            **self.env,
        })
        return StdioServerParameters(command=sys.executable, args=["-m", self.module, *self.args], env=env, cwd=cwd)


def _connection_lost(exc: BaseException) -> bool:
    name = type(exc).__name__
    return (name in ("ClosedResourceError", "BrokenResourceError", "EndOfStream", "BrokenPipeError")
            or "connection closed" in str(exc).lower())


def _timed_out(exc: BaseException) -> bool:
    """The call got no answer in time (MCP read timeout, code 408, or our own future timeout)."""
    return isinstance(exc, TimeoutError) or getattr(getattr(exc, "error", None), "code", None) == 408


class MCPServerBridge:
    """Owns one MCP stdio server process + client session for the duration of a run."""

    def __init__(self, spec: MCPServerSpec) -> None:
        self.spec = spec
        self.tools: list[Any] = []  # mcp.types.Tool
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._ready = threading.Event()
        self._closing: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._cwd = tempfile.mkdtemp(prefix=f"vexa-mcp-{spec.name}-")
        self._errlog = tempfile.TemporaryFile(mode="w+")
        self.restarts = 0
        self.max_restarts = 1

    # -- lifecycle ---------------------------------------------------------

    @property
    def alive(self) -> bool:
        """The server process and its session are up (False after a crash or close)."""
        return (self._session is not None and self._thread is not None and self._thread.is_alive()
                and self._loop is not None and not self._loop.is_closed())

    def start(self) -> MCPServerBridge:
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run_loop, name=f"mcp-{self.spec.name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(self.spec.startup_timeout):
            self.close()
            raise MCPError(f"MCP server '{self.spec.name}' did not start within {self.spec.startup_timeout}s")
        if self._error is not None:
            raise MCPError(f"MCP server '{self.spec.name}' failed to start: {self._error}; {self.stderr_tail()}")
        logger.info("mcp_connected | server=%s tools=%s", self.spec.name, [t.name for t in self.tools])
        return self

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        except BaseException as exc:  # surfaced through start()
            self._error = self._error or exc
            self._ready.set()
        finally:
            self._loop.close()

    async def _main(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        self._closing = asyncio.Event()
        try:
            async with stdio_client(self.spec.params(self._cwd), errlog=self._errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.tools = (await session.list_tools()).tools
                    self._session = session
                    self._ready.set()
                    await self._closing.wait()
        finally:
            self._session = None  # the server exited (closed or crashed): no stale session

    def close(self) -> None:
        if self._loop is not None and self._closing is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._closing.set)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._session = None

    def stderr_tail(self, n: int = 800) -> str:
        try:
            self._errlog.seek(0)
            return self._errlog.read()[-n:]
        except Exception:
            return ""

    # -- calls ---------------------------------------------------------------

    def call(self, tool: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Invoke a tool over MCP. Returns (ok, text) where text is what the agent sees.

        A server found dead *before* the call is restarted (at most ``max_restarts``
        times per run): the call has not been sent, so it is safe to send it to
        the new process. A call that was in flight when the server died is NOT
        repeated: it may already have had side effects.
        """
        if not self.alive:
            if self._thread is None or self.restarts >= self.max_restarts:
                return False, json.dumps({"ok": False, "error": f"MCP server '{self.spec.name}' is not connected"})
            self.restarts += 1
            logger.warning("mcp_server_down | server=%s restarting (%d/%d); stderr=%s", self.spec.name,
                           self.restarts, self.max_restarts, self.stderr_tail(300))
            try:
                self.close()
                self.start()
            except MCPError as exc:
                return False, json.dumps({"ok": False, "error": f"MCP server '{self.spec.name}' is down and "
                                                                 f"could not be restarted: {exc}"})
        timeout = self.spec.call_timeout
        fut = None
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._session.call_tool(tool, arguments, read_timeout_seconds=timedelta(seconds=timeout)), self._loop,
            )
            result = fut.result(timeout + 5)
        except Exception as exc:
            if fut is not None:
                fut.cancel()
            if _connection_lost(exc) or _timed_out(exc):
                # Gone, or still busy with the timed-out call (every later call would time out too):
                # drop the session so the next call restarts the server within the restart budget.
                self._session = None
                if self._loop is not None and self._closing is not None and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._closing.set)
            return False, json.dumps({"ok": False, "error": f"MCP call to '{self.spec.name}' failed: "
                                                            f"{type(exc).__name__}: {exc}"})
        if result.structuredContent is not None:
            payload = result.structuredContent.get("result", result.structuredContent)
            text = json.dumps(payload, default=str)
            ok = not result.isError and (not isinstance(payload, dict) or payload.get("ok", True) is not False)
        else:
            text = "\n".join(getattr(c, "text", "") for c in result.content)
            ok = not result.isError
        return ok, text

    # -- CrewAI exposure -------------------------------------------------------

    def crewai_tools(self, allowed: set[str] | None, ctx: Any = None) -> list[Any]:
        """CrewAI tools for the discovered MCP tools, filtered by an allowlist."""
        return [
            MCPCrewAITool(self, t, ctx)
            for t in self.tools
            if allowed is None or t.name in allowed
        ]


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic (the subset MCP servers use for tool inputs)
# ---------------------------------------------------------------------------

_JSON_TYPES: dict[str, Any] = {"string": str, "integer": int, "number": float, "boolean": bool,
                               "object": dict, "array": list}


def _py_type(prop: dict[str, Any]) -> Any:
    if "anyOf" in prop:
        types = [_py_type(p) for p in prop["anyOf"] if p.get("type") != "null"]
        base = types[0] if types else Any
        nullable = any(p.get("type") == "null" for p in prop["anyOf"])
        return base | None if nullable and base is not Any else base
    t = prop.get("type")
    if t == "array":
        return list[_py_type(prop.get("items", {}))] if prop.get("items") else list
    return _JSON_TYPES.get(t, Any)


def schema_to_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    props = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    fields: dict[str, Any] = {}
    for pname, prop in props.items():
        default = ... if pname in required else prop.get("default", None)
        fields[pname] = (_py_type(prop), Field(default=default, description=prop.get("description", "")))
    if not fields:
        fields["dummy"] = (str, Field(default="ignored", description="unused"))
    return create_model(f"{name}_mcp_args", **fields)


try:
    from crewai.tools import BaseTool as _BaseTool
except ImportError:  # pragma: no cover
    _BaseTool = object  # type: ignore[assignment,misc]


class MCPCrewAITool(_BaseTool):  # type: ignore[misc,valid-type]
    """A CrewAI tool whose every invocation is an MCP call_tool request."""

    name: str = ""
    description: str = ""
    _bridge: MCPServerBridge = PrivateAttr()
    _ctx: Any = PrivateAttr(default=None)

    def __init__(self, bridge: MCPServerBridge, tool: Any, ctx: Any = None) -> None:
        super().__init__(
            name=tool.name,
            description=(tool.description or tool.name) + f" (via MCP server '{bridge.spec.name}')",
            args_schema=schema_to_model(tool.name, tool.inputSchema or {}),
        )
        self._bridge = bridge
        self._ctx = ctx

    def _run(self, **kwargs: Any) -> str:
        from backend.guardrails import enforce_tool_call, enforce_tool_output
        kwargs.pop("dummy", None)
        denial = enforce_tool_call(self._ctx, self.name, kwargs)
        if denial:
            return json.dumps({"ok": False, "operation": self.name, "error": denial})
        observer = getattr(self._ctx, "observer", None)
        span = observer.tool_started(self._ctx.current_agent, self.name, kwargs,
                                     origin=getattr(self._ctx, "tool_origin", "agent")) if observer else None
        ok, text = self._bridge.call(self.name, kwargs)
        if span:
            err = ""
            if not ok:
                try:
                    err = json.loads(text).get("error", text)
                except (ValueError, AttributeError):
                    err = text
            observer.tool_finished(span, ok, str(err)[:500], transport="mcp", mcp_server=self._bridge.spec.name)
        return enforce_tool_output(self._ctx, self.name, text)


# ---------------------------------------------------------------------------
# Standard VEXA servers
# ---------------------------------------------------------------------------


def workspace_server_spec(workspace_root: str | Path, workspace_id: str) -> MCPServerSpec:
    from backend.core.config import get_settings

    s = get_settings()
    passthrough = {
        k.upper(): str(getattr(s, k)) for k in (
            "sandbox_backend", "sandbox_docker_binary", "sandbox_docker_image", "sandbox_docker_cpus",
            "tool_exec_timeout_seconds", "tool_max_output_bytes", "tool_max_file_bytes",
            "tool_max_list_files", "tool_max_search_results", "tool_max_memory_mb", "tool_max_file_write_mb",
            "workspace_allowed_output_roots",
        )
    }
    return MCPServerSpec(
        name="vexa-workspace",
        module="backend.mcp_servers.workspace_server",
        args=["--workspace-root", str(Path(workspace_root).resolve()), "--workspace-id", workspace_id],
        env=passthrough,
        call_timeout=float(s.tool_exec_timeout_seconds + 30),
    )


def code_intel_server_spec(workspace_root: str | Path, workspace_id: str) -> MCPServerSpec:
    """Local, keyless code-intelligence server bound to one workspace."""
    return MCPServerSpec(
        name="vexa-code-intel",
        module="backend.mcp_servers.code_intel_server",
        args=["--workspace-root", str(Path(workspace_root).resolve()), "--workspace-id", workspace_id],
        call_timeout=30.0,
    )


def docs_search_server_spec(api_key: str) -> MCPServerSpec:
    env = {"TAVILY_API_KEY": api_key}
    if os.environ.get("VEXA_DOCS_SEARCH_URL"):
        env["VEXA_DOCS_SEARCH_URL"] = os.environ["VEXA_DOCS_SEARCH_URL"]
    return MCPServerSpec(
        name="vexa-docs-search",
        module="backend.mcp_servers.docs_search_server",
        env=env,
        call_timeout=30.0,
    )


def docs_search_api_key() -> str | None:
    return os.environ.get("TAVILY_API_KEY") or None
