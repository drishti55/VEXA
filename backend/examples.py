"""
Starter workspaces shipped with VEXA (examples/workspaces/<name>/).

Hosts with an ephemeral disk (e.g. Render's free plan) start every deploy with an empty
workspace root, so the Studio would have nothing to open. On startup, if the workspace root
has no workspaces at all, these examples are copied in. Existing workspaces are never touched.
Set VEXA_SEED_EXAMPLES=0 to disable.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.core.logging import get_logger

logger = get_logger(__name__)
EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "workspaces"


def seed_example_workspaces(svc, examples_dir: Path = EXAMPLES_DIR) -> list[str]:
    """Copy the example workspaces into an empty workspace root. Returns the names created."""
    if os.environ.get("VEXA_SEED_EXAMPLES", "1") == "0" or not examples_dir.is_dir():
        return []
    if svc.list_workspaces():
        return []
    created = []
    for src in sorted(p for p in examples_dir.iterdir() if p.is_dir()):
        try:
            ws = svc.create_workspace(src.name)
            shutil.copytree(src, svc._manager.require(ws), dirs_exist_ok=True)
            created.append(ws)
        except Exception as exc:  # one bad example must not stop startup
            logger.warning("example_workspace_skipped | name=%s error=%s", src.name, exc)
    if created:
        logger.info("example_workspaces_seeded | count=%d", len(created))
    return created
