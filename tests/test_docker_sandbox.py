"""
DockerSandboxExecutor without a Docker daemon: a fake `docker` binary records
its argv so the isolation flags can be checked. A live run needs Docker
running (see README) and is not part of this suite.
"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from backend.core.config import get_settings
from backend.tools.execution import DockerSandboxExecutor
from backend.tools.workspace import WorkspaceManager


@pytest.fixture()
def fake_docker(tmp_path, monkeypatch):
    log = tmp_path / "argv.json"
    script = tmp_path / "docker"
    script.write_text(f"#!{sys.executable}\nimport json, sys\njson.dump(sys.argv[1:], open({str(log)!r}, 'w'))\nprint('1 passed')\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SANDBOX_DOCKER_BINARY", str(script))
    monkeypatch.setenv("TOOL_MAX_MEMORY_MB", "512")
    get_settings.cache_clear()
    yield log
    get_settings.cache_clear()


@pytest.mark.skipif(os.name != "posix", reason="fake binary uses a shebang")
def test_isolation_flags(tmp_path, fake_docker):
    mgr = WorkspaceManager(tmp_path / "root")
    ws = mgr.create("w1")
    r = DockerSandboxExecutor(mgr).run([sys.executable, "-m", "pytest", ".", "-q"], ws)
    assert r.success and "1 passed" in r.stdout
    argv = json.loads(fake_docker.read_text())
    joined = " ".join(argv)
    for flag in ("--rm", "--network none", "--cap-drop ALL", "--security-opt no-new-privileges", "--read-only",
                 "--memory 512m", "--pids-limit 256"):
        assert flag in joined, flag
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert mounts == [f"{mgr.require(ws).resolve()}:/workspace:rw"]  # only the workspace is mounted
    assert argv[-4:] == ["python", "-m", "pytest", "."] or argv[-5:] == ["python", "-m", "pytest", ".", "-q"]
    assert not any("API_KEY" in a for a in argv)


def test_policy_still_applies(tmp_path, fake_docker):
    mgr = WorkspaceManager(tmp_path / "root")
    ws = mgr.create("w1")
    r = DockerSandboxExecutor(mgr).run([sys.executable, "-c", "print(1)"], ws)
    assert r.exit_code is None and not fake_docker.exists()


def test_missing_docker_is_an_error_not_a_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_DOCKER_BINARY", str(tmp_path / "no-such-docker"))
    get_settings.cache_clear()
    try:
        mgr = WorkspaceManager(tmp_path / "root")
        ws = mgr.create("w1")
        r = DockerSandboxExecutor(mgr).run(["pytest", "."], ws)
        assert r.success is False and r.exit_code is None and "not found" in r.message
    finally:
        get_settings.cache_clear()
