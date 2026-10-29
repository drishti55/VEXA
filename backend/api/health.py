"""
Health check router.

Returns basic service status. No secrets or internals are exposed.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health() -> HealthResponse:
    """Return the service health status."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
    )
