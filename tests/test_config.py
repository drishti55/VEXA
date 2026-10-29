"""
Tests for application configuration loading.
"""

from __future__ import annotations

import os

import pytest


def test_settings_loads(settings):
    """Settings must load without error."""
    assert settings is not None


def test_settings_app_name(settings):
    """App name default is VEXA."""
    assert settings.app_name == "VEXA"


def test_settings_max_iterations_default(settings):
    """Max iterations default must be 5."""
    assert settings.max_iterations == 5


def test_settings_environment_is_testing(settings):
    """Environment must be detected as testing when env var is set."""
    from backend.core.config import Environment
    assert settings.environment == Environment.testing


def test_settings_invalid_log_level():
    """An invalid log_level must raise a validation error."""
    from pydantic import ValidationError
    from backend.core.config import Settings

    with pytest.raises((ValidationError, ValueError)):
        Settings(log_level="NONSENSE")


def test_settings_database_url_optional(settings):
    """database_url is None or empty by default (no DB required to start)."""
    # pydantic-settings reads DATABASE_URL="" as '' rather than None depending
    # on whether a .env file is present. Accept both.
    if not os.environ.get("DATABASE_URL"):
        assert settings.database_url in (None, "")

