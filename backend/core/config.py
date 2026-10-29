"""
VEXA Backend Configuration

Reads all settings from environment variables.
No secrets are hardcoded.
"""

from __future__ import annotations

import os

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    development = "development"
    testing = "testing"
    production = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=os.environ.get("VEXA_ENV_FILE", ".env") or None,  # VEXA_ENV_FILE="" disables (tests)
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_name: str = "VEXA"
    app_version: str = "0.1.0"
    environment: Environment = Environment.development
    debug: bool = False

    # -------------------------------------------------------------------------
    # API server
    # -------------------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # -------------------------------------------------------------------------
    # API security
    # -------------------------------------------------------------------------
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of browser origins allowed to call the API.",
    )
    api_token: str | None = Field(
        default=None,
        description=(
            "Optional shared secret. When set, every request (except /health and "
            "workspace preview files) must send 'Authorization: Bearer <token>'."
        ),
    )

    # -------------------------------------------------------------------------
    # Database (optional — app starts without it)
    # -------------------------------------------------------------------------
    database_url: str | None = Field(
        default=None,
        description=(
            "Optional SQLAlchemy URL for the run registry, e.g. "
            "postgresql+psycopg://user:password@localhost:5432/vexa. Empty = SQLite at VEXA_DB_PATH."
        ),
    )

    vexa_db_path: str = Field(
        default="data/vexa.sqlite3",
        description="SQLite file for the run registry (used when DATABASE_URL is empty).",
    )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    # -------------------------------------------------------------------------
    # VEXA research settings
    # -------------------------------------------------------------------------
    max_iterations: int = Field(
        default=5,
        description="Maximum debug/repair iterations per run before giving up",
    )

    # -------------------------------------------------------------------------
    # M2 — Workspace & Tool Layer
    # -------------------------------------------------------------------------
    workspace_root: str = Field(
        default="workspaces",
        description=(
            "Root directory for isolated project workspaces. "
            "Relative paths are resolved from the current working directory. "
            "Set an absolute path in production."
        ),
    )

    workspace_allowed_output_roots: str = Field(
        default="",
        description=(
            "Comma-separated absolute directories under which a workspace may use a "
            "custom output_path. Empty = custom output paths are disabled."
        ),
    )

    sandbox_backend: str = Field(
        default="local",
        description="Execution sandbox backend. 'local' = subprocess on host. "
                    "'docker' = throwaway container with no network.",
    )
    sandbox_docker_binary: str = Field(
        default="docker",
        description="docker CLI name or absolute path (e.g. "
                    "/Applications/Docker.app/Contents/Resources/bin/docker).",
    )
    sandbox_docker_image: str = Field(
        default="vexa-sandbox:latest",
        description="Image used by the docker sandbox. Must contain python + pytest.",
    )
    sandbox_docker_cpus: float = Field(default=1.0, gt=0)
    tool_max_memory_mb: int = Field(
        default=1024,
        description="Memory cap for sandboxed commands (docker: hard; local: RLIMIT_AS where supported).",
    )
    tool_max_file_write_mb: int = Field(
        default=64,
        description="Largest file a sandboxed command may write (local: RLIMIT_FSIZE).",
    )

    # Execution limits
    tool_exec_timeout_seconds: int = Field(
        default=120,
        description="Maximum seconds a sandboxed command may run before it is killed.",
    )
    tool_max_output_bytes: int = Field(
        default=1_048_576,  # 1 MiB
        description="Maximum captured stdout+stderr bytes per execution.",
    )
    tool_max_file_bytes: int = Field(
        default=524_288,  # 512 KiB
        description="Maximum file size that read_file will load.",
    )
    tool_max_list_files: int = Field(
        default=500,
        description="Maximum number of files returned by list_files.",
    )
    tool_max_search_results: int = Field(
        default=200,
        description="Maximum number of matches returned by search_code.",
    )

    # -------------------------------------------------------------------------
    # M3 — Agent system (see also backend/agents/config.py for full agent settings)
    # -------------------------------------------------------------------------
    # These mirror AgentSettings for documentation purposes.
    # AgentSettings is loaded independently with VEXA_ prefix.
    vexa_llm_model: str = Field(
        default="gpt-4o-mini",
        description="LiteLLM model string for all agents",
    )
    vexa_debug_max_iter: int = Field(
        default=3,
        description="Maximum repair iterations in the Debugger loop",
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @field_validator("sandbox_backend")
    @classmethod
    def _validate_sandbox_backend(cls, v: str) -> str:
        allowed = {"local", "docker"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"sandbox_backend must be one of {allowed}")
        return lower


    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_output_roots(self) -> list[Path]:
        return [
            Path(p.strip()).expanduser().resolve()
            for p in self.workspace_allowed_output_roots.split(",")
            if p.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()

