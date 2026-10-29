"""
Workspace snapshots and diffs.

Workspaces are usually not git repositories, so the runtime snapshots text
files before a run and diffs them afterwards. This is what reports show as
"code changes": the real before/after content, not what an agent claims.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from pydantic import BaseModel

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache",
              ".ruff_cache", "dist", "build"}
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_DIFF_CHARS = 20_000


class FileDiff(BaseModel):
    path: str
    change: str  # added | modified | deleted
    lines_added: int
    lines_removed: int
    diff: str
    truncated: bool = False


def snapshot(repo: Path) -> dict[str, str | None]:
    """path → text content (None = binary/oversized, tracked for existence only)."""
    out: dict[str, str | None] = {}
    total = 0
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in p.relative_to(repo).parts):
            continue
        rel = p.relative_to(repo).as_posix()
        size = p.stat().st_size
        if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
            out[rel] = None
            continue
        try:
            out[rel] = p.read_text(encoding="utf-8")
            total += size
        except (UnicodeDecodeError, OSError):
            out[rel] = None
    return out


def diff_snapshots(before: dict[str, str | None], after: dict[str, str | None]) -> list[FileDiff]:
    changes: list[FileDiff] = []
    for path in sorted(set(before) | set(after)):
        a, b = before.get(path, ""), after.get(path, "")
        if path in before and path in after and a == b:
            continue
        change = "added" if path not in before else "deleted" if path not in after else "modified"
        if a is None or b is None:
            changes.append(FileDiff(path=path, change=change, lines_added=0, lines_removed=0,
                                    diff="(binary or oversized file — content not diffed)"))
            continue
        lines = list(difflib.unified_diff(
            (a or "").splitlines(keepends=True), (b or "").splitlines(keepends=True),
            fromfile=f"a/{path}" if path in before else "/dev/null",
            tofile=f"b/{path}" if path in after else "/dev/null",
        ))
        text = "".join(lines)
        added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
        changes.append(FileDiff(path=path, change=change, lines_added=added, lines_removed=removed,
                                diff=text[:MAX_DIFF_CHARS], truncated=len(text) > MAX_DIFF_CHARS))
    return changes
