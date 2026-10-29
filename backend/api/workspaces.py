"""
VEXA API — Workspace & Tool Endpoints (Milestone 2)

All endpoints operate on workspace IDs, never on raw host paths.
The ToolService is instantiated once at module level (application scope).

Endpoints
---------
POST   /workspaces                      create workspace
GET    /workspaces                      list all workspaces
GET    /workspaces/{id}                 workspace info
DELETE /workspaces/{id}                 destroy workspace
GET    /workspaces/{id}/files           list files
POST   /workspaces/{id}/read            read a file
POST   /workspaces/{id}/write           write a file
POST   /workspaces/{id}/patch           patch a file
DELETE /workspaces/{id}/files           delete a file
POST   /workspaces/{id}/search          search source code
GET    /workspaces/{id}/inspect         project overview
GET    /workspaces/{id}/git/status      git status
GET    /workspaces/{id}/git/diff        git diff
GET    /workspaces/{id}/git/log         git log
POST   /workspaces/{id}/tests           run pytest
"""

from __future__ import annotations


from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.core.logging import get_logger
from backend.tools.service import ToolService
from backend.tools.workspace import WorkspaceExistsError, WorkspaceSecurityError

logger = get_logger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# Single service instance for the lifetime of the process
_svc = ToolService()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateWorkspaceRequest(BaseModel):
    workspace_id: str | None = Field(
        default=None,
        description="Optional custom ID. A UUID is generated if omitted.",
    )
    output_path: str | None = Field(
        default=None,
        description="Optional absolute path on the host where VEXA will generate code. "
                    "If omitted, code is generated inside the default VEXA workspaces directory.",
    )


class CreateWorkspaceResponse(BaseModel):
    workspace_id: str
    output_path: str | None = None


class WorkspaceInfoResponse(BaseModel):
    workspace_id: str
    exists: bool


class ListFilesRequest(BaseModel):
    path: str = "."
    recursive: bool = True


class ReadFileRequest(BaseModel):
    path: str


class WriteFileRequest(BaseModel):
    path: str
    content: str


class PatchFileRequest(BaseModel):
    path: str
    old_text: str
    new_text: str
    allow_multiple: bool = False


class DeleteFileRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    query: str
    case_sensitive: bool = True
    file_glob: str = "*"
    context_lines: int = 1


class RunTestsRequest(BaseModel):
    test_path: str = "."
    extra_args: list[str] = Field(default_factory=list, max_length=20)
    timeout: int | None = Field(default=None, ge=1, le=600)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _not_found(workspace_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Workspace '{workspace_id}' not found",
    )


def _security_error(msg: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Security violation: {msg}",
    )


def _tool_error(result_message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=result_message,
    )


# ---------------------------------------------------------------------------
# Workspace lifecycle
# ---------------------------------------------------------------------------


@router.post("", response_model=CreateWorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(body: CreateWorkspaceRequest) -> CreateWorkspaceResponse:
    """Create a new isolated workspace, optionally at a custom output path."""
    try:
        ws_id = _svc.create_workspace(body.workspace_id, output_path=body.output_path)
    except WorkspaceExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except WorkspaceSecurityError as exc:
        traversal = body.workspace_id and any(t in body.workspace_id for t in ("/", "\\", ".."))
        if body.workspace_id and not traversal and "Invalid workspace id" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace name: use letters, digits, spaces, '_', '-' or '.', "
                       "start with a letter or digit, max 128 characters.",
            )
        raise _security_error(str(exc))
    effective_path = _svc._ws.get_custom_output_path(ws_id) if body.output_path else None
    return CreateWorkspaceResponse(workspace_id=ws_id, output_path=effective_path)


@router.get("", response_model=list[str])
def list_workspaces() -> list[str]:
    """List all existing workspace IDs."""
    return _svc.list_workspaces()


@router.get("/{workspace_id}", response_model=WorkspaceInfoResponse)
def get_workspace(workspace_id: str) -> WorkspaceInfoResponse:
    """Get information about a specific workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    return WorkspaceInfoResponse(workspace_id=workspace_id, exists=True)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def destroy_workspace(workspace_id: str) -> None:
    """Permanently destroy a workspace and all its contents."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    _svc.destroy_workspace(workspace_id)


# Preview responses are sandboxed by CSP: the browser gives the page an opaque
# origin, so generated scripts cannot call this API with the user's privileges
# even when the preview is opened directly instead of through the iframe.
_PREVIEW_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-modals",
    "X-Content-Type-Options": "nosniff",
    "Access-Control-Allow-Origin": "*",  # lets the opaque-origin page fetch its own assets
    "Cache-Control": "no-store",
}


@router.get("/{workspace_id}/serve/{file_path:path}")
def serve_workspace_file(workspace_id: str, file_path: str):
    """Serve a raw file from the workspace for the sandboxed web preview."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)

    if not file_path:
        file_path = "index.html"

    try:
        target = _svc._manager.resolve_path(workspace_id, file_path)
    except WorkspaceSecurityError:
        raise _security_error("Path traversal attempt")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(target), headers=_PREVIEW_HEADERS)


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}/files")
def list_files(workspace_id: str, path: str = ".", recursive: bool = True) -> dict:
    """List files in the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.list_files(workspace_id, path, recursive)
    if not result.success:
        raise _tool_error(result.message)
    return result.model_dump()


@router.post("/{workspace_id}/read")
def read_file(workspace_id: str, body: ReadFileRequest) -> dict:
    """Read a text file from the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.read_file(workspace_id, body.path)
    if not result.success:
        combined = f"{result.message} {result.error or ''}"
        if "traversal" in combined.lower() or "escapes" in combined.lower():
            raise _security_error(result.error or result.message)
        raise _tool_error(result.message)
    return result.model_dump()


@router.post("/{workspace_id}/write", status_code=status.HTTP_200_OK)
def write_file(workspace_id: str, body: WriteFileRequest) -> dict:
    """Create or overwrite a file in the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.write_file(workspace_id, body.path, body.content)
    if not result.success:
        if "traversal" in (result.error or "").lower():
            raise _security_error(result.error or result.message)
        raise _tool_error(result.message)
    return result.model_dump()


@router.post("/{workspace_id}/patch")
def patch_file(workspace_id: str, body: PatchFileRequest) -> dict:
    """Patch a file by replacing an exact substring."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.patch_file(workspace_id, body.path, body.old_text, body.new_text, body.allow_multiple)
    if not result.success:
        raise _tool_error(result.message)
    return result.model_dump()


@router.delete("/{workspace_id}/files")
def delete_file(workspace_id: str, body: DeleteFileRequest) -> dict:
    """Delete a single file from the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.delete_file(workspace_id, body.path)
    if not result.success:
        raise _tool_error(result.message)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Search & Inspection
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/search")
def search_code(workspace_id: str, body: SearchRequest) -> dict:
    """Search source code across the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.search_code(
        workspace_id, body.query,
        case_sensitive=body.case_sensitive,
        file_glob=body.file_glob,
        context_lines=body.context_lines,
    )
    if not result.success:
        raise _tool_error(result.message)
    return result.model_dump()


@router.get("/{workspace_id}/inspect")
def inspect_project(workspace_id: str) -> dict:
    """Return a lightweight overview of the workspace project."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.inspect_project(workspace_id)
    if not result.success:
        raise _tool_error(result.message)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}/git/status")
def git_status(workspace_id: str) -> dict:
    """Get git status of the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    return _svc.git_status(workspace_id).model_dump()


@router.get("/{workspace_id}/git/diff")
def git_diff(workspace_id: str, staged: bool = False) -> dict:
    """Get git diff of the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    return _svc.git_diff(workspace_id, staged).model_dump()


@router.get("/{workspace_id}/git/log")
def git_log(workspace_id: str, max_entries: int = 10) -> dict:
    """Get recent git log entries."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    return _svc.git_log(workspace_id, max_entries).model_dump()


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/tests")
def run_tests(workspace_id: str, body: RunTestsRequest) -> dict:
    """Run pytest inside the workspace."""
    if not _svc.workspace_exists(workspace_id):
        raise _not_found(workspace_id)
    result = _svc.run_tests(
        workspace_id,
        test_path=body.test_path,
        extra_args=body.extra_args,
        timeout=body.timeout,
    )
    if result.exit_code is None and (result.message or "").startswith("Command rejected"):
        raise _security_error(result.error or result.message)
    return result.model_dump()
