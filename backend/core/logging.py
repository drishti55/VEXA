"""
VEXA Structured Logging

Provides a simple, consistent logger factory.
Each logger is named after the calling module and emits structured records.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from backend.core.config import get_settings


def _configure_root_logger() -> None:
    """Configure the root logger once at import time."""
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    if not logging.root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        fmt = (
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S"))

        logging.root.setLevel(level)
        logging.root.addHandler(handler)


_configure_root_logger()


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Usage:
        logger = get_logger(__name__)
        logger.info("message", extra={"run_id": run_id})
    """
    return logging.getLogger(name)
