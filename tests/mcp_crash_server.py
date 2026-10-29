"""Minimal MCP server for bridge failure tests: ``echo`` works, ``crash`` kills the server process,
``hang`` blocks past the client's call timeout."""

from __future__ import annotations

import os
import time

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("crash-test")


@mcp.tool()
def echo(text: str) -> dict:
    """Return the text with this server's process id."""
    return {"ok": True, "text": text, "pid": os.getpid()}


@mcp.tool()
def crash() -> dict:
    """Exit the server process immediately (simulates a server crash)."""
    os._exit(3)


@mcp.tool()
def hang(seconds: float) -> dict:
    """Block for ``seconds`` (simulates a tool that never answers in time)."""
    time.sleep(seconds)
    return {"ok": True, "slept": seconds}


if __name__ == "__main__":
    mcp.run()
