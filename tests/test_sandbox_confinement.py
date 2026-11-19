"""
OS confinement of the local sandbox (macOS sandbox-exec).

Agent-written test code runs through the same executor as run_tests. These tests write such code
into a workspace and check what it can and cannot do. Skipped where no OS sandbox exists.
"""

from __future__ import annotations

import os
import socket
import threading
import uuid
from pathlib import Path

import pytest

from backend.tools.execution import os_confinement, seatbelt_profile
from backend.tools.service import ToolService

pytestmark = pytest.mark.skipif(os_confinement() != "seatbelt", reason="no OS sandbox on this platform")


@pytest.fixture()
def ws(tmp_path):
    svc = ToolService(workspace_root=str(tmp_path / "root"))
    return svc, svc.create_workspace()


def _run_probe(svc, ws_id, body: str):
    svc.write_file(ws_id, "tests/test_probe.py", "import os, socket, pathlib\n\n" + body)
    return svc.run_tests(ws_id, "tests/test_probe.py", ["-q"])


def test_executor_reports_confinement(ws):
    svc, _ = ws
    assert svc.sandbox_backend == "local+seatbelt"


def test_workspace_and_tmp_writes_still_work(ws):
    svc, ws_id = ws
    r = _run_probe(svc, ws_id, "def test_w(tmp_path):\n"
                               "    pathlib.Path('out.txt').write_text('x')\n"
                               "    (tmp_path / 'y').write_text('y')\n")
    assert r.exit_code == 0, r.stdout + r.stderr


def test_write_outside_workspace_is_denied(ws):
    svc, ws_id = ws
    target = Path.home() / f".vexa_sandbox_probe_{uuid.uuid4().hex[:8]}"
    r = _run_probe(svc, ws_id, f"def test_w():\n    pathlib.Path({str(target)!r}).write_text('x')\n")
    assert r.exit_code != 0 and "PermissionError" in r.stdout
    assert not target.exists()


def test_credential_files_cannot_be_read(ws, tmp_path):
    svc, ws_id = ws
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE")
    profile = seatbelt_profile(svc._manager.require(ws_id), home=str(home))
    assert str(home / ".ssh") in profile and "(deny network*)" in profile
    real_ssh = Path.home() / ".ssh"  # absolute: the sandbox gives commands their own HOME
    r = _run_probe(svc, ws_id, f"def test_r():\n    print(os.listdir({str(real_ssh)!r}))\n")
    if real_ssh.exists():
        assert r.exit_code != 0 and "PermissionError" in r.stdout, r.stdout


def test_internet_is_blocked_but_localhost_works(ws):
    svc, ws_id = ws
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    threading.Thread(target=lambda: srv.accept(), daemon=True).start()
    try:
        r = _run_probe(svc, ws_id,
                       f"def test_local():\n    socket.create_connection(('127.0.0.1', {port}), timeout=3).close()\n\n"
                       "def test_internet():\n"
                       "    try:\n        socket.create_connection(('1.1.1.1', 443), timeout=3)\n"
                       "    except OSError:\n        return\n"
                       "    raise AssertionError('internet reachable')\n\n"
                       "def test_dns():\n"
                       "    try:\n        socket.getaddrinfo('example.com', 80)\n"
                       "    except OSError:\n        return\n"
                       "    raise AssertionError('dns reachable')\n")
    finally:
        srv.close()
    assert r.exit_code == 0, r.stdout + r.stderr


def test_confinement_can_be_switched_off(monkeypatch):
    from backend.core.config import get_settings
    monkeypatch.setenv("SANDBOX_OS_CONFINEMENT", "off")
    get_settings.cache_clear()
    try:
        assert os_confinement() is None
    finally:
        get_settings.cache_clear()
    assert os.access("/usr/bin/sandbox-exec", os.X_OK)
