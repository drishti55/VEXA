"""
VEXA FastAPI Application

Entry point for the backend service.
Registers all routers and configures middleware.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.agent_runs import router as agent_runs_router
from backend.api.experiments import router as experiments_router
from backend.api.health import router as health_router
from backend.api.workspaces import router as workspaces_router
from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Handle startup and shutdown events."""
    settings = get_settings()
    from backend.observability.redaction import install_log_redaction, register_secret
    install_log_redaction()
    register_secret(settings.api_token)
    from backend.agents.config import export_provider_keys_from_env_file, provider_status
    exported = export_provider_keys_from_env_file()
    status = provider_status()
    logger.info("provider_config | model=%s provider=%s key_configured=%s key_source=%s docs_search=%s "
                "exported_from_env_file=%s", status["model"], status["provider"], status["api_key_configured"],
                status["key_source"], status["docs_search_configured"], exported)
    try:  # experiments a previous process left 'running' can be resumed
        from backend.db.registry import get_registry
        from backend.evaluation.jobs import jobs
        stale = get_registry().mark_interrupted(jobs.active())
        lost_runs = get_registry().mark_interrupted_runs()
        if lost_runs:
            logger.warning("runs_interrupted | ids=%s", lost_runs)
        if stale:
            logger.warning("experiments_interrupted | ids=%s", stale)
        from backend.evaluation.benchmark import cleanup_orphan_workspaces
        from backend.tools.service import ToolService
        orphans = cleanup_orphan_workspaces(ToolService())
        if orphans:
            logger.warning("orphan_benchmark_workspaces_removed | ids=%s", orphans)
    except Exception as exc:
        logger.error("registry_startup_check_failed | %s", exc)
    logger.info(
        "VEXA backend starting | version=%s env=%s",
        settings.app_version,
        settings.environment.value,
    )
    yield
    logger.info("VEXA backend shutting down")


def create_app() -> FastAPI:
    """Factory function that creates and configures the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "VEXA — Architecture-Aware Autonomous Multi-Agent "
            "Software Engineering System"
        ),
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Optional shared-secret auth. /health, CORS preflights and the sandboxed
    # preview (loaded by an iframe that cannot send headers) are exempt.
    @app.middleware("http")
    async def _require_token(request: Request, call_next):
        token = settings.api_token
        path = request.url.path
        if (
            token
            and request.method != "OPTIONS"
            and path != "/health"
            and "/serve/" not in path
        ):
            supplied = request.headers.get("authorization", "")
            if not supplied and path.endswith("/stream"):  # EventSource cannot send headers
                supplied = f"Bearer {request.query_params.get('token', '')}"
            if not hmac.compare_digest(supplied, f"Bearer {token}"):
                return JSONResponse(status_code=401, content={"detail": "Missing or invalid API token"})
        return await call_next(request)

    # CORS — only the configured dashboard origins may call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # Routers
    app.include_router(health_router)
    app.include_router(workspaces_router)
    app.include_router(agent_runs_router)
    app.include_router(experiments_router)

    return app


app = create_app()

