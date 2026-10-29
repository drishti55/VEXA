"""
VEXA Tool Layer — Workspace Manager

The WorkspaceManager is the single authority over isolated project workspaces.

Security model
--------------
- Every workspace lives under a configurable root directory.
- No caller can supply an arbitrary host path.
- Path resolution always calls Path.resolve() and asserts containment.
- Any traversal attempt raises WorkspaceSecurityError.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class WorkspaceSecurityError(Exception):
    """Raised when a path escapes the workspace boundary."""


class WorkspaceNotFoundError(Exception):
    """Raised when a referenced workspace does not exist."""


class WorkspaceExistsError(Exception):
    """Raised when creating a workspace whose name is already taken."""


# Workspace IDs become directory names: letters, digits, space, '_', '-', '.',
# must start with a letter/digit, and may never contain path separators or '..'.
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,127}$")


def validate_workspace_id(workspace_id: str) -> str:
    """Return *workspace_id* if it is a safe single path component, else raise."""
    if (
        not isinstance(workspace_id, str)
        or not _WORKSPACE_ID_RE.match(workspace_id)
        or ".." in workspace_id
        or workspace_id != workspace_id.strip()
    ):
        raise WorkspaceSecurityError(f"Invalid workspace id: {workspace_id!r}")
    return workspace_id


class WorkspaceManager:
    """
    Creates and manages isolated per-run project workspaces.

    Directory layout::

        <workspace_root>/
            <workspace_id>/
                repository/   ← all file operations happen here

    The manager enforces that every resolved path is strictly contained
    within the workspace's repository directory.
    """

    REPO_SUBDIR = "repository"

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        if workspace_root is None:
            workspace_root = get_settings().workspace_root
        self._root = Path(workspace_root).resolve()

    # ------------------------------------------------------------------
    # Workspace lifecycle
    # ------------------------------------------------------------------

    def create(self, workspace_id: str | None = None, output_path: str | None = None) -> str:
        """
        Create a new workspace.

        Parameters
        ----------
        workspace_id:
            Optional custom ID. A UUID is generated if omitted.
        output_path:
            Optional absolute path to an existing directory on the host
            that VEXA should use as the repository root.  When supplied,
            the workspace metadata is stored inside the VEXA workspace
            root but all file operations are directed to `output_path`.

        Returns the workspace_id (a UUID string).
        """
        ws_id = validate_workspace_id(workspace_id or str(uuid.uuid4()))
        if (self._root / ws_id).exists():
            # Never silently reuse (and write into) someone else's workspace.
            raise WorkspaceExistsError(f"Workspace '{ws_id}' already exists")

        if output_path:
            # Custom output paths must live under an explicitly allowed root.
            resolved = self._check_output_path(output_path)
            if not resolved.exists():
                resolved.mkdir(parents=True, exist_ok=True)
            # Store metadata so later calls know where the repo lives
            meta_dir = self._root / ws_id
            meta_dir.mkdir(parents=True, exist_ok=True)
            meta_file = meta_dir / "metadata.json"
            meta_file.write_text(
                json.dumps({"custom_output_path": str(resolved)}),
                encoding="utf-8",
            )
            logger.info(
                "Workspace created | id=%s custom_path=%s", ws_id, resolved
            )
        else:
            repo_dir = self._repo_dir(ws_id)
            repo_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Workspace created | id=%s path=%s", ws_id, repo_dir)

        return ws_id

    def exists(self, workspace_id: str) -> bool:
        """Return True if the workspace (and its repository dir) exist."""
        try:
            return self._repo_dir(workspace_id).is_dir()
        except WorkspaceSecurityError:
            return False

    def get_custom_output_path(self, workspace_id: str) -> str | None:
        """Return the custom output path for a workspace, if one was set."""
        meta_file = self._root / validate_workspace_id(workspace_id) / "metadata.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                return data.get("custom_output_path")
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def require(self, workspace_id: str) -> Path:
        """
        Return the repository Path for a workspace, asserting it exists.

        Raises WorkspaceNotFoundError if the workspace is missing.
        """
        repo = self._repo_dir(workspace_id)
        if not repo.is_dir():
            raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' does not exist")
        return repo

    def destroy(self, workspace_id: str) -> None:
        """
        Permanently delete a workspace directory.

        This is an explicit, destructive operation. Callers must confirm intent.
        """
        ws_dir = self._root / validate_workspace_id(workspace_id)
        if ws_dir.exists():
            shutil.rmtree(ws_dir)
            logger.info("Workspace destroyed | id=%s", workspace_id)

    def list_workspaces(self) -> list[str]:
        """Return IDs of all existing workspaces."""
        if not self._root.exists():
            return []
        return [
            d.name for d in self._root.iterdir()
            if d.is_dir() and _WORKSPACE_ID_RE.match(d.name)
        ]

    # ------------------------------------------------------------------
    # Safe path resolution — the security boundary
    # ------------------------------------------------------------------

    def resolve_path(self, workspace_id: str, relative_path: str) -> Path:
        """
        Resolve a caller-supplied relative path to an absolute Path inside
        the workspace repository directory.

        Raises
        ------
        WorkspaceNotFoundError
            If the workspace does not exist.
        WorkspaceSecurityError
            If the resolved path escapes the workspace boundary.
        """
        repo_dir = self.require(workspace_id).resolve()
        cleaned = self._normalise_relative(repo_dir, relative_path)
        candidate = (repo_dir / cleaned).resolve()

        # Strict containment check — must be equal to or under repo_dir
        try:
            candidate.relative_to(repo_dir)
        except ValueError:
            raise WorkspaceSecurityError(
                f"Path '{relative_path}' escapes workspace boundary. "
                f"Resolved to '{candidate}', allowed root is '{repo_dir}'."
            )

        return candidate

    def resolve_path_unchecked(self, workspace_id: str, relative_path: str) -> Path:
        """
        Like resolve_path but does NOT require the workspace to exist first.
        Used during workspace creation before the directory is created.
        Internal use only.
        """
        repo_dir = self._repo_dir(workspace_id)
        cleaned = relative_path.lstrip("/\\")
        candidate = (repo_dir / cleaned).resolve()
        try:
            candidate.relative_to(repo_dir.resolve())
        except ValueError:
            raise WorkspaceSecurityError(
                f"Path '{relative_path}' escapes workspace boundary."
            )
        return candidate

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_relative(repo_dir: Path, path: str) -> str:
        """
        Turn a caller path into a workspace-relative one.

        - An absolute path already inside the repository is made relative.
        - An absolute path naming a real host location (e.g. /etc, /Users,
          C:\\) is rejected outright.
        - Other leading slashes (LLMs often write "/src/app.py") are treated as
          workspace-root relative.
        """
        p = path.replace("\\", "/")
        if p.startswith("~"):
            raise WorkspaceSecurityError(f"Path '{path}' refers to a home directory, not the workspace.")
        if re.match(r"^[A-Za-z]:", p):
            raise WorkspaceSecurityError(f"Path '{path}' is an absolute host path.")
        if p.startswith("/"):
            try:
                return str(Path(p).resolve().relative_to(repo_dir))
            except ValueError:
                pass
            parts = PurePosixPath(p).parts
            first = parts[1] if len(parts) > 1 else ""
            if first and Path("/" + first).exists():
                raise WorkspaceSecurityError(f"Path '{path}' is an absolute host path.")
        return p.lstrip("/")

    def _check_output_path(self, output_path: str) -> Path:
        from backend.core.config import get_settings

        resolved = Path(output_path).expanduser().resolve()
        roots = get_settings().allowed_output_roots
        if not roots:
            raise WorkspaceSecurityError(
                "Custom output paths are disabled. Set WORKSPACE_ALLOWED_OUTPUT_ROOTS to enable them."
            )
        if not any(resolved == r or r in resolved.parents for r in roots):
            raise WorkspaceSecurityError(
                f"Output path '{output_path}' is outside WORKSPACE_ALLOWED_OUTPUT_ROOTS."
            )
        return resolved

    def _repo_dir(self, workspace_id: str) -> Path:
        """Return the absolute path to the repository sub-directory."""
        validate_workspace_id(workspace_id)
        # Check for custom output path stored in metadata
        meta_file = self._root / workspace_id / "metadata.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                custom = data.get("custom_output_path")
                if custom:
                    # Re-check on every use: the allowlist may have changed.
                    return self._check_output_path(custom)
            except (json.JSONDecodeError, OSError):
                pass
        return self._root / workspace_id / self.REPO_SUBDIR

    @property
    def root(self) -> Path:
        return self._root
