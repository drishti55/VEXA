"""
VEXA Tool Layer — Filesystem Tools

Provides safe, workspace-bounded file operations:
  list_files   — enumerate files in the workspace
  read_file    — read a text file
  write_file   — create or overwrite a file
  patch_file   — replace a substring within a file
  delete_file  — remove a file (destructive, explicit)
  inspect_project — lightweight project overview

All paths are relative to the workspace repository directory.
Binary files and files exceeding the configured size limit are rejected.
"""

from __future__ import annotations

import time
from pathlib import Path

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.tools.models import FileInfo, ProjectOverview, ToolResult
from backend.tools.workspace import WorkspaceManager, WorkspaceSecurityError

logger = get_logger(__name__)

# Directories to skip when listing or inspecting
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    "*.egg-info",
})

# Extensions that are almost certainly binary
_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".dat",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".pdf", ".zip", ".tar",
    ".gz", ".bz2", ".7z", ".whl", ".egg",
})

# Well-known important filenames
_IMPORTANT_FILES: frozenset[str] = frozenset({
    "README.md", "README.rst", "README.txt",
    "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "requirements-dev.txt",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".env.example", "CHANGELOG.md",
})

# Extension → language label mapping (for project overview)
_EXT_LANGUAGE: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".java": "java", ".go": "go", ".rs": "rust", ".cpp": "cpp",
    ".c": "c", ".h": "c", ".cs": "csharp", ".rb": "ruby",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".toml": "toml", ".ini": "ini", ".cfg": "config",
    ".html": "html", ".css": "css", ".sh": "shell",
    ".dockerfile": "docker",
}


def _should_skip_dir(name: str) -> bool:
    return name in _SKIP_DIRS or name.endswith(".egg-info")


def _is_likely_binary(path: Path) -> bool:
    return path.suffix.lower() in _BINARY_EXTENSIONS


class FilesystemTools:
    """
    Workspace-bounded filesystem operations.

    All methods accept *relative* paths. Absolute paths and traversal
    sequences are rejected by the WorkspaceManager.
    """

    def __init__(self, manager: WorkspaceManager) -> None:
        self._mgr = manager
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # list_files
    # ------------------------------------------------------------------

    def list_files(
        self,
        workspace_id: str,
        relative_path: str = ".",
        recursive: bool = True,
    ) -> ToolResult:
        """List files within the workspace (or a sub-directory of it)."""
        t0 = time.monotonic()
        try:
            base = self._mgr.resolve_path(workspace_id, relative_path)
        except WorkspaceSecurityError as exc:
            return ToolResult.fail("list_files", "Path traversal rejected", str(exc))
        except Exception as exc:
            return ToolResult.fail("list_files", "Workspace error", str(exc))

        if not base.exists():
            return ToolResult.fail("list_files", f"Path does not exist: {relative_path}")

        repo_dir = self._mgr.require(workspace_id)
        files: list[FileInfo] = []
        limit = self._settings.tool_max_list_files

        try:
            iterator = base.rglob("*") if recursive else base.iterdir()
            for entry in iterator:
                if len(files) >= limit:
                    break
                # Skip unwanted dirs
                if any(_should_skip_dir(part) for part in entry.parts):
                    continue
                if entry.is_dir() and _should_skip_dir(entry.name):
                    continue
                rel = entry.relative_to(repo_dir).as_posix()
                files.append(FileInfo(
                    path=rel,
                    size_bytes=entry.stat().st_size if entry.is_file() else 0,
                    is_dir=entry.is_dir(),
                ))
        except Exception as exc:
            return ToolResult.fail("list_files", "Failed to enumerate files", str(exc))

        ms = (time.monotonic() - t0) * 1000
        return ToolResult.ok(
            "list_files",
            f"Found {len(files)} entries",
            data=[f.model_dump() for f in files],
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # read_file
    # ------------------------------------------------------------------

    def read_file(self, workspace_id: str, relative_path: str) -> ToolResult:
        """Read a text file from the workspace."""
        t0 = time.monotonic()
        try:
            abs_path = self._mgr.resolve_path(workspace_id, relative_path)
        except WorkspaceSecurityError as exc:
            return ToolResult.fail("read_file", "Path traversal rejected", str(exc))
        except Exception as exc:
            return ToolResult.fail("read_file", "Workspace error", str(exc))

        if not abs_path.exists():
            return ToolResult.fail("read_file", f"File not found: {relative_path}")
        if not abs_path.is_file():
            return ToolResult.fail("read_file", f"Not a file: {relative_path}")
        if _is_likely_binary(abs_path):
            return ToolResult.fail("read_file", f"Binary file not supported: {relative_path}")

        size = abs_path.stat().st_size
        if size > self._settings.tool_max_file_bytes:
            limit_kb = self._settings.tool_max_file_bytes // 1024
            return ToolResult.fail(
                "read_file",
                f"File too large ({size} bytes). Limit is {limit_kb} KiB.",
            )

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult.fail("read_file", "Could not read file", str(exc))

        ms = (time.monotonic() - t0) * 1000
        return ToolResult.ok(
            "read_file",
            f"Read {size} bytes from {relative_path}",
            data={"path": relative_path, "content": content, "size_bytes": size},
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # write_file
    # ------------------------------------------------------------------

    def write_file(
        self,
        workspace_id: str,
        relative_path: str,
        content: str,
    ) -> ToolResult:
        """Write (create or overwrite) a text file in the workspace."""
        t0 = time.monotonic()
        try:
            abs_path = self._mgr.resolve_path(workspace_id, relative_path)
        except WorkspaceSecurityError as exc:
            return ToolResult.fail("write_file", "Path traversal rejected", str(exc))
        except Exception as exc:
            return ToolResult.fail("write_file", "Workspace error", str(exc))

        existed = abs_path.exists()
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return ToolResult.fail("write_file", "Could not write file", str(exc))

        verb = "overwritten" if existed else "created"
        ms = (time.monotonic() - t0) * 1000
        return ToolResult.ok(
            "write_file",
            f"File {verb}: {relative_path}",
            data={"path": relative_path, "created": not existed, "size_bytes": len(content.encode())},
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # patch_file
    # ------------------------------------------------------------------

    def patch_file(
        self,
        workspace_id: str,
        relative_path: str,
        old_text: str,
        new_text: str,
        allow_multiple: bool = False,
    ) -> ToolResult:
        """
        Replace an exact substring in a text file.

        Parameters
        ----------
        old_text:
            The exact text to find. Must exist exactly once unless
            allow_multiple is True.
        new_text:
            The replacement text.
        allow_multiple:
            If False (default), reject the operation when old_text appears
            more than once (ambiguous replacement).
        """
        t0 = time.monotonic()
        read_result = self.read_file(workspace_id, relative_path)
        if not read_result.success:
            return ToolResult.fail("patch_file", read_result.message, read_result.error)

        original: str = read_result.data["content"]

        count = original.count(old_text)
        if count == 0:
            return ToolResult.fail(
                "patch_file",
                f"Expected text not found in {relative_path}. No changes made.",
                error=f"old_text not present: {old_text[:80]!r}",
            )
        if count > 1 and not allow_multiple:
            return ToolResult.fail(
                "patch_file",
                f"old_text appears {count} times in {relative_path}. "
                "Set allow_multiple=True to replace all occurrences.",
            )

        patched = original.replace(old_text, new_text, 0 if allow_multiple else 1)
        write_result = self.write_file(workspace_id, relative_path, patched)
        if not write_result.success:
            return ToolResult.fail("patch_file", write_result.message, write_result.error)

        ms = (time.monotonic() - t0) * 1000
        replacements = count if allow_multiple else 1
        return ToolResult.ok(
            "patch_file",
            f"Patched {relative_path} ({replacements} replacement(s))",
            data={"path": relative_path, "replacements": replacements},
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # delete_file
    # ------------------------------------------------------------------

    def delete_file(self, workspace_id: str, relative_path: str) -> ToolResult:
        """Delete a single file within the workspace."""
        t0 = time.monotonic()
        try:
            abs_path = self._mgr.resolve_path(workspace_id, relative_path)
        except WorkspaceSecurityError as exc:
            return ToolResult.fail("delete_file", "Path traversal rejected", str(exc))
        except Exception as exc:
            return ToolResult.fail("delete_file", "Workspace error", str(exc))

        if not abs_path.exists():
            return ToolResult.fail("delete_file", f"File not found: {relative_path}")
        if not abs_path.is_file():
            return ToolResult.fail("delete_file", "Only files can be deleted; use destroy workspace for directories")

        try:
            abs_path.unlink()
        except Exception as exc:
            return ToolResult.fail("delete_file", "Could not delete file", str(exc))

        ms = (time.monotonic() - t0) * 1000
        return ToolResult.ok(
            "delete_file",
            f"Deleted {relative_path}",
            data={"path": relative_path},
            duration_ms=ms,
        )

    # ------------------------------------------------------------------
    # inspect_project
    # ------------------------------------------------------------------

    def inspect_project(self, workspace_id: str) -> ToolResult:
        """Return a compact overview of the workspace project."""
        t0 = time.monotonic()
        try:
            repo_dir = self._mgr.require(workspace_id)
        except Exception as exc:
            return ToolResult.fail("inspect_project", "Workspace error", str(exc))

        total_files = 0
        total_dirs = 0
        languages: dict[str, int] = {}
        important: list[str] = []

        try:
            for entry in repo_dir.rglob("*"):
                if any(_should_skip_dir(part) for part in entry.parts):
                    continue
                if entry.is_dir():
                    if not _should_skip_dir(entry.name):
                        total_dirs += 1
                    continue
                total_files += 1
                lang = _EXT_LANGUAGE.get(entry.suffix.lower())
                if lang:
                    languages[lang] = languages.get(lang, 0) + 1
                if entry.name in _IMPORTANT_FILES:
                    rel = entry.relative_to(repo_dir).as_posix()
                    important.append(rel)
        except Exception as exc:
            return ToolResult.fail("inspect_project", "Failed to inspect project", str(exc))

        overview = ProjectOverview(
            root=repo_dir.as_posix(),
            total_files=total_files,
            total_dirs=total_dirs,
            languages=languages,
            important_files=sorted(important),
        )
        ms = (time.monotonic() - t0) * 1000
        return ToolResult.ok(
            "inspect_project",
            f"Project has {total_files} files across {total_dirs} directories",
            data=overview.model_dump(),
            duration_ms=ms,
        )
