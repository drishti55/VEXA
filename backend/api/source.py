"""
VEXA API — read-only access to VEXA's own source code (VEXA Studio: agent anatomy, extensions,
guardrail inspector). Workspaces are served by /workspaces; this serves the platform itself.

GET /source/tree            allow-listed files of the VEXA repository
GET /source/file?path=...   one text file (read-only, redacted)

Only these roots are served, and never a file that looks like configuration with secrets,
a database, a key or a certificate. Content passes through the same redaction as logs and traces.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/source", tags=["source"])

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_DIRS = ("backend", "frontend/src", "frontend/e2e", "benchmarks", "docs", "tests", "scripts", "docker")
ALLOWED_FILES = ("README.md", "pyproject.toml", "Dockerfile", "docker-compose.yml", "render.yaml", ".env.example",
                 "frontend/package.json", "frontend/vite.config.ts", "frontend/index.html")
_SKIP_DIRS = {"__pycache__", "node_modules", ".pytest_cache", ".ruff_cache", ".git", "dist", ".venv"}
_DENY = re.compile(r"(^|/)(\.env(?!\.example$)[^/]*|.*\.(sqlite3?|db|pem|key|p12|pfx|crt)(-\w+)?|.*secret.*|.*credential.*|id_rsa.*)$",
                   re.IGNORECASE)
_TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".toml", ".yml", ".yaml", ".css", ".html",
             ".cfg", ".ini", ".sh", ".example", ""}
MAX_BYTES = 1_000_000


def _allowed(rel: str) -> bool:
    if _DENY.search(rel) or any(part in _SKIP_DIRS for part in rel.split("/")):
        return False
    return rel in ALLOWED_FILES or any(rel == d or rel.startswith(d + "/") for d in ALLOWED_DIRS)


def resolve_source(rel: str) -> Path:
    """Resolve a repository-relative path, refusing anything outside the allow-list."""
    candidate = (REPO_ROOT / rel).resolve()
    try:
        norm = candidate.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="path is outside the VEXA repository")
    if not _allowed(norm):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"'{norm}' is not served by the source viewer")
    return candidate


def source_ref(obj: Any) -> dict[str, Any] | None:
    """{path, line} of a Python object, relative to the repository (for "open in editor" links)."""
    try:
        target = inspect.unwrap(obj)
        file = Path(inspect.getsourcefile(target) or "").resolve()
        line = inspect.getsourcelines(target)[1]
        rel = file.relative_to(REPO_ROOT).as_posix()
    except (TypeError, OSError, ValueError):
        return None
    return {"path": rel, "line": line} if _allowed(rel) else None


def find_line(rel: str, pattern: str) -> dict[str, Any] | None:
    """{path, line} of the first line matching a regex in a repository file (for constants)."""
    try:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    except OSError:
        return None
    rx = re.compile(pattern, re.MULTILINE)
    m = rx.search(text)
    return {"path": rel, "line": text.count("\n", 0, m.start()) + 1} if m else None


@router.get("/tree")
def source_tree() -> dict:
    files: list[dict[str, Any]] = []
    for d in ALLOWED_DIRS:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if p.is_file() and _allowed(rel) and p.suffix in _TEXT_EXT:
                files.append({"path": rel, "size_bytes": p.stat().st_size})
    for f in ALLOWED_FILES:
        if (REPO_ROOT / f).is_file():
            files.append({"path": f, "size_bytes": (REPO_ROOT / f).stat().st_size})
    return {"root": "vexa", "files": files}


@router.get("/file")
def source_file(path: str = Query(min_length=1, max_length=512)) -> dict:
    from backend.observability.redaction import redact_text

    target = resolve_source(path)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"'{path}' not found")
    if target.suffix not in _TEXT_EXT:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="not a text source file")
    if target.stat().st_size > MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file too large for the viewer")
    text = target.read_text(encoding="utf-8", errors="replace")
    return {"path": target.relative_to(REPO_ROOT).as_posix(), "content": redact_text(text), "read_only": True,
            "lines": text.count("\n") + 1}
