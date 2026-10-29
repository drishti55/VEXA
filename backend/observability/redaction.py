"""
Secret redaction for logs, traces, events and stored intermediate outputs.

Two layers:
1. Exact values: every configured secret (API keys from settings / environment)
   is registered and replaced wherever it appears.
2. Patterns: common credential shapes (OpenAI/Groq/Anthropic/Google/Tavily keys,
   bearer tokens, ``api_key=...`` assignments, private key blocks).

Limits: pattern matching cannot recognise arbitrary secrets that do not look
like credentials (e.g. a password inside repository code). Repository content
is truncated rather than stored whole in traces for that reason.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(sk|rk|pk)-(proj-|ant-)?[A-Za-z0-9_\-]{16,}"),   # OpenAI / Anthropic style
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),                          # Groq
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),                       # Google
    re.compile(r"\btvly-[A-Za-z0-9_\-]{16,}"),                      # Tavily
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),                    # GitHub
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),                 # Slack
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]{6,})"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)

_SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
# Dict keys whose values are always secrets (but not e.g. "input_tokens").
_SECRET_KEY_RE = re.compile(
    r"(?i)^(.*api[_-]?key|.*secret.*|.*password|.*access[_-]?token|.*auth[_-]?token|token|authorization)$"
)

_lock = threading.Lock()
_known_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember an exact secret value so it is always redacted (min 6 chars)."""
    if value and len(value) >= 6:
        with _lock:
            _known_secrets.add(value)


def known_secrets() -> list[str]:
    with _lock:
        return list(_known_secrets)


def register_env_secrets() -> None:
    for k, v in os.environ.items():
        if any(h in k.upper() for h in _SECRET_ENV_HINTS):
            register_secret(v)


def redact_text(text: str) -> str:
    if not text:
        return text
    with _lock:
        secrets = sorted(_known_secrets, key=len, reverse=True)
    for s in secrets:
        if s in text:
            text = text.replace(s, REDACTED)
    for pat in _PATTERNS:
        if pat.groups >= 3:
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        else:
            text = pat.sub(REDACTED, text)
    return text


def redact(value: Any, max_len: int | None = None) -> Any:
    """Recursively redact strings inside dicts/lists; optionally truncate strings."""
    if isinstance(value, str):
        out = redact_text(value)
        if max_len is not None and len(out) > max_len:
            out = out[:max_len] + f"…[truncated {len(out) - max_len} chars]"
        return out
    if isinstance(value, dict):
        return {k: (REDACTED if isinstance(v, str) and v and _SECRET_KEY_RE.match(str(k)) else redact(v, max_len))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, max_len) for v in value]
    return value


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the fully formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact_text(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        if record.exc_info and not record.exc_text:
            # Pre-render the traceback so the formatter uses the redacted text.
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
        return True


_installed = False


def install_log_redaction() -> None:
    """Attach the redacting filter to every root handler (idempotent)."""
    global _installed
    if _installed:
        return
    register_env_secrets()
    f = RedactingFilter()
    for h in logging.root.handlers:
        h.addFilter(f)
    _installed = True
