"""backend package"""

import os as _os

# Opt out of CrewAI's anonymous telemetry before crewai is imported anywhere.
# Set CREWAI_DISABLE_TELEMETRY=false explicitly to re-enable it.
_os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
_os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")

import os as _os

# Third-party libraries load the whole .env into os.environ on import: LiteLLM
# (in its default "DEV" mode) and CrewAI (crewai/llm.py, unconditionally; its
# upward search finds VEXA's .env because .venv lives in the project). VEXA owns
# configuration instead: settings are read by pydantic-settings, and only
# allowlisted provider keys are exported (agents.config.export_provider_keys_from_env_file).
# Implicit load_dotenv() calls (no path / stream) are therefore ignored.
_os.environ.setdefault("LITELLM_MODE", "PRODUCTION")


def _disable_implicit_dotenv() -> None:
    try:
        import dotenv
    except ImportError:
        return
    original = dotenv.load_dotenv
    if getattr(original, "_vexa_guard", False):
        return

    def load_dotenv(dotenv_path=None, stream=None, *args, **kwargs):
        if dotenv_path is None and stream is None:
            return False
        return original(dotenv_path, stream, *args, **kwargs)

    load_dotenv._vexa_guard = True  # type: ignore[attr-defined]
    dotenv.load_dotenv = load_dotenv
    try:
        import dotenv.main
        dotenv.main.load_dotenv = load_dotenv
    except ImportError:
        pass


_disable_implicit_dotenv()
