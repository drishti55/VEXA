"""
VEXA API — System status (VEXA Studio status bar and dashboard health panel).

GET /system/status

Reports what is actually known, never more:

* ``database``   — a live query against the run registry.
* ``llm``        — whether a model and key are *configured* (names/booleans only). Reachability is
                   not probed here (that costs a request); ``POST /agent-runs/test-model`` does that.
* ``a2a``        — the embedded ADK verifier starts lazily on the first run that uses it, so
                   "not_started" is a normal state, not an error.
* ``mcp``        — MCP servers are spawned per run (one set per workspace) and closed afterwards,
                   so there is no long-running server to ping; we report availability and config.
* ``runs`` / ``experiments`` — live counts from this process.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


def _database() -> dict:
    try:
        from sqlalchemy import func, select

        from backend.db.models import Experiment, Run
        from backend.db.registry import get_registry

        reg = get_registry()
        with reg._session() as s:
            runs = s.scalar(select(func.count()).select_from(Run)) or 0
            experiments = s.scalar(select(func.count()).select_from(Experiment)) or 0
        return {"status": "ok", "dialect": reg.engine.dialect.name, "runs": runs, "experiments": experiments}
    except Exception as exc:  # reported, never raised: the status bar must still render
        return {"status": "error", "error": type(exc).__name__}


def _llm() -> dict:
    try:
        from backend.agents.config import provider_status

        p = provider_status()
        return {
            "status": "configured" if p["api_key_configured"] else "no_key",
            "model": p["model"], "provider": p["provider"], "key_source": p["key_source"],
            "fallback_model": p["fallback_model"], "docs_search_configured": p["docs_search_configured"],
            "reachability": "not_probed",
        }
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


def _a2a() -> dict:
    from backend.a2a_bridge import embedded

    info = embedded._info
    if info is None:
        return {"status": "not_started", "note": "starts on the first run that uses the ADK verifier over A2A"}
    server = embedded._server
    alive = bool(server is not None and getattr(server, "started", False) and not getattr(server, "should_exit", False))
    return {"status": "running" if alive else "stopped", "url": info[0]}


def _mcp() -> dict:
    from backend.mcp_client.bridge import docs_search_api_key

    available = importlib.util.find_spec("mcp") is not None
    return {
        "status": "available" if available else "unavailable",
        "lifecycle": "spawned per run, closed when the run ends",
        "servers": [
            {"name": "vexa-workspace", "configured": available},
            {"name": "vexa-code-intel", "configured": available},
            {"name": "vexa-docs-search", "configured": available and bool(docs_search_api_key())},
        ],
    }


def _activity() -> dict:
    from backend.agents.context import RunContext
    from backend.api.agent_runs import _run_store
    from backend.evaluation.jobs import jobs

    active = [rid for rid, rec in list(_run_store.items()) if isinstance(rec, RunContext)]
    return {"active_runs": active, "active_experiments": sorted(jobs.active())}


@router.get("/status")
def system_status() -> dict:
    from backend.core.config import get_settings

    settings = get_settings()
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "backend": {"status": "ok", "version": settings.app_version, "environment": settings.environment.value},
        "database": _database(),
        "llm": _llm(),
        "a2a": _a2a(),
        "mcp": _mcp(),
        "sandbox": {"backend": settings.sandbox_backend},
        "sse": {"status": "available", "endpoint": "/agent-runs/{run_id}/stream"},
        **_activity(),
    }
