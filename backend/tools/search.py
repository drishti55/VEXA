"""
VEXA Tool Layer — Source Code Search

Deterministic text search across workspace source files.
Semantic / vector search belongs to the RAG milestone.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.tools.filesystem import _BINARY_EXTENSIONS, _should_skip_dir
from backend.tools.models import FileMatch, ToolResult
from backend.tools.workspace import WorkspaceManager, WorkspaceSecurityError

logger = get_logger(__name__)


class SearchTools:
    """Text search across workspace files."""

    def __init__(self, manager: WorkspaceManager) -> None:
        self._mgr = manager
        self._settings = get_settings()

    def search_code(
        self,
        workspace_id: str,
        query: str,
        *,
        case_sensitive: bool = True,
        file_glob: str = "*",
        context_lines: int = 1,
    ) -> ToolResult:
        """
        Search for *query* across all text files in the workspace.

        Parameters
        ----------
        query:
            Plain text or regex pattern to search for.
        case_sensitive:
            Whether the search is case-sensitive (default: True).
        file_glob:
            Glob pattern to restrict which files are searched, e.g. "*.py".
        context_lines:
            Number of surrounding lines to include with each match.

        Returns
        -------
        ToolResult whose ``data`` is a list of FileMatch dicts.
        """
        t0 = time.monotonic()
        try:
            repo_dir = self._mgr.require(workspace_id)
        except Exception as exc:
            return ToolResult.fail("search_code", "Workspace error", str(exc))

        if not query:
            return ToolResult.fail("search_code", "Query must not be empty")

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(re.escape(query), flags)
        except re.error as exc:
            return ToolResult.fail("search_code", "Invalid search pattern", str(exc))

        limit = self._settings.tool_max_search_results
        max_file_bytes = self._settings.tool_max_file_bytes
        matches: list[dict] = []

        for entry in repo_dir.rglob(file_glob):
            if len(matches) >= limit:
                break
            if not entry.is_file():
                continue
            if any(_should_skip_dir(part) for part in entry.parts):
                continue
            if entry.suffix.lower() in _BINARY_EXTENSIONS:
                continue
            if entry.stat().st_size > max_file_bytes:
                continue

            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = text.splitlines()
            rel = entry.relative_to(repo_dir).as_posix()

            for i, line in enumerate(lines):
                if len(matches) >= limit:
                    break
                if pattern.search(line):
                    before = lines[max(0, i - context_lines): i]
                    after = lines[i + 1: i + 1 + context_lines]
                    m = FileMatch(
                        file=rel,
                        line_number=i + 1,
                        matched_line=line,
                        context_before="\n".join(before),
                        context_after="\n".join(after),
                    )
                    matches.append(m.model_dump())

        ms = (time.monotonic() - t0) * 1000
        truncated = len(matches) >= limit
        return ToolResult.ok(
            "search_code",
            f"Found {len(matches)} match(es){' (truncated)' if truncated else ''}",
            data={"matches": matches, "truncated": truncated},
            duration_ms=ms,
        )
