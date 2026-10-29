"""
VEXA Milestone 2 -- End-to-End Validation Script

Demonstrates all tool layer capabilities:
  1. Create workspace
  2. Inspect project
  3. List files
  4. Read calculator.py
  5. Search for a function
  6. Modify calculator.py (add a new function)
  7. Git status (will show 'not a git repo' gracefully)
  8. Run pytest
  9. Capture test result
  10. Demonstrate path traversal rejection

Run with: python scripts/validate_m2.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Ensure the project root is on the path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.tools.service import ToolService
from backend.tools.workspace import WorkspaceManager

FIXTURE = ROOT / "tests" / "fixtures" / "sample_project"
WORKSPACE_ROOT = ROOT / "workspaces" / "_validate_m2"


def banner(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(label: str, condition: bool, detail: str = "") -> None:
    icon = "PASS" if condition else "FAIL"
    print(f"  [{icon}]  {label}")
    if detail:
        for line in detail.splitlines()[:5]:
            print(f"           {line}")
    if not condition:
        sys.exit(1)


def main() -> None:
    # Clean up any leftover validation workspace
    if WORKSPACE_ROOT.exists():
        shutil.rmtree(WORKSPACE_ROOT)

    svc = ToolService(workspace_root=str(WORKSPACE_ROOT))

    # 1. Create workspace
    banner("1. Create workspace")
    ws_id = svc.create_workspace("validate-run")
    check("Workspace created", svc.workspace_exists(ws_id), f"ID: {ws_id}")

    # Populate with fixture files
    mgr = WorkspaceManager(workspace_root=WORKSPACE_ROOT)
    repo_dir = mgr.require(ws_id)
    shutil.copytree(str(FIXTURE), str(repo_dir), dirs_exist_ok=True)
    print(f"  -> Populated with sample_project from {FIXTURE.name}/")

    # 2. Inspect project
    banner("2. Inspect project")
    r = svc.inspect_project(ws_id)
    check("inspect_project succeeded", r.success)
    check(
        f"Python files detected ({r.data['languages'].get('python', 0)})",
        r.data["languages"].get("python", 0) >= 2,
    )
    check(
        "Important files found",
        len(r.data["important_files"]) > 0,
        str(r.data["important_files"]),
    )

    # 3. List files
    banner("3. List files")
    r = svc.list_files(ws_id)
    check("list_files succeeded", r.success)
    paths = [f["path"] for f in r.data]
    check(f"Found {len(paths)} entries", len(paths) > 0)
    print(f"  -> Files: {', '.join(paths[:6])}{'...' if len(paths)>6 else ''}")

    # 4. Read calculator.py
    banner("4. Read src/calculator.py")
    r = svc.read_file(ws_id, "src/calculator.py")
    check("read_file succeeded", r.success)
    check("Content contains 'def add'", "def add" in r.data["content"])
    print(f"  -> {r.data['size_bytes']} bytes read")

    # 5. Search for function
    banner("5. Search code for 'def divide'")
    r = svc.search_code(ws_id, "def divide")
    check("search_code succeeded", r.success)
    check("Match found in calculator.py", any("calculator" in m["file"] for m in r.data["matches"]))
    print(f"  -> {len(r.data['matches'])} match(es)")

    # 6. Modify calculator.py
    banner("6. Patch src/calculator.py (add modulo function)")
    modulo_fn = "\n\ndef modulo(a: float, b: float) -> float:\n    \"\"\"Return a % b.\"\"\"\n    return a % b\n"
    r = svc.read_file(ws_id, "src/calculator.py")
    new_content = r.data["content"] + modulo_fn
    r = svc.write_file(ws_id, "src/calculator.py", new_content)
    check("write_file succeeded", r.success)

    # Verify the change
    r = svc.read_file(ws_id, "src/calculator.py")
    check("modulo function present", "def modulo" in r.data["content"])

    # 7. Git status
    banner("7. Git status (sample_project has no .git dir)")
    r = svc.git_status(ws_id)
    check("git_status returned gracefully", r.success)
    is_git = r.data.get("is_git_repo", False)
    print(f"  -> is_git_repo={is_git} (expected False for fixture)")

    # 8. Run pytest
    banner("8. Run pytest tests/")
    r = svc.run_tests(ws_id, test_path="tests/")
    check("pytest exited 0", r.exit_code == 0, r.stdout[-300:])
    check("stdout contains 'passed'", "passed" in r.stdout.lower())
    print(f"  -> Duration: {r.duration_ms:.0f} ms")
    for line in r.stdout.splitlines():
        if "passed" in line or "failed" in line:
            print(f"  -> {line.strip()}")

    # 9. Demonstrate test failure capture
    banner("9. Write a failing test, verify capture")
    svc.write_file(ws_id, "test_intentional_fail.py",
                   "def test_fail():\n    assert False, 'deliberate'\n")
    r = svc.run_tests(ws_id, test_path="test_intentional_fail.py")
    check("exit_code != 0 for failing tests", r.exit_code != 0)
    check("success=False", r.success is False)
    check("stdout has failure info", len(r.stdout) > 0)
    print(f"  -> exit_code={r.exit_code}, timed_out={r.timed_out}")

    # 10. Path traversal rejection
    banner("10. Path traversal rejection")
    r = svc.read_file(ws_id, "../../secrets.txt")
    check("Traversal rejected (success=False)", r.success is False)
    check("Error message references boundary/traversal",
          "escapes" in (r.error or "") or "traversal" in (r.message or "").lower())
    print(f"  -> error: {r.error or r.message}")

    r = svc.write_file(ws_id, "../../../evil.txt", "hacked")
    check("Write traversal rejected", r.success is False)

    # Done
    banner("ALL VALIDATIONS PASSED")
    print()
    print("  Milestone 2 tool layer is fully operational.")
    print()

    # Clean up
    svc.destroy_workspace(ws_id)


if __name__ == "__main__":
    main()
