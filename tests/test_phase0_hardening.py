"""
Phase 0 regression tests: one test (or more) per defect found in the audit.

D1/D2  mock mode builds no LLM and completes deterministically
D3     unknown execution modes are rejected
D7     run events survive completion
D9     LLM factory does not mutate os.environ / litellm globals
D10    cost is None (not 0.0) when unknown
S1     CORS allowlist + optional token auth
S2     command policy blocks inline code, pip, git writes; env has no secrets
S3     workspace ids / output paths cannot escape the workspace root
S4     preview responses carry a CSP sandbox
S5     pytest arguments are restricted
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew, estimate_cost
from backend.tools.execution import build_sandbox_env, check_command
from backend.tools.service import ToolService
from backend.tools.workspace import WorkspaceManager, WorkspaceSecurityError

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture()
def svc(tmp_path):
    return ToolService(workspace_root=str(tmp_path / "root"))


@pytest.fixture()
def sample_ws(svc):
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE_PROJECT), str(svc._manager.require(ws)), dirs_exist_ok=True)
    return ws


# ---------------------------------------------------------------------------
# Mock mode (D1, D2, D3, D7, D10)
# ---------------------------------------------------------------------------


class TestMockMode:
    def test_mock_run_needs_no_api_key_and_succeeds(self, svc, sample_ws, monkeypatch):
        for k in ("VEXA_LLM_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"):
            monkeypatch.delenv(k, raising=False)

        def _no_llm(*a, **k):
            raise AssertionError("LLMFactory.build must not run in mock mode")

        monkeypatch.setattr("backend.agents.crew.LLMFactory.build", _no_llm)
        result = SoftwareEngineeringCrew(tool_service=svc).run_task(sample_ws, "Add a modulo function", "mock")
        assert result.status == AgentStatus.partial, result.errors  # mock: nothing implemented
        assert result.provider == "mock"
        assert result.final_test_result.passed  # real sandboxed pytest on the fixture
        assert result.debug_result is None

    def test_unknown_mode_is_rejected(self, svc, sample_ws):
        with pytest.raises(ValueError):
            SoftwareEngineeringCrew(tool_service=svc).run_task(sample_ws, "Add a modulo function", "bogus")

    def test_events_present_in_final_result(self, svc, sample_ws):
        result = SoftwareEngineeringCrew(tool_service=svc).run_task(sample_ws, "Add a modulo function")
        assert any(e["agent"] == "Verifier" and e["event"] == "completed" for e in result.events)

    def test_mock_cost_is_unavailable_not_zero(self, svc, sample_ws):
        result = SoftwareEngineeringCrew(tool_service=svc).run_task(sample_ws, "Add a modulo function")
        assert result.estimated_cost_usd is None
        assert result.cost_basis.startswith("unavailable")


class TestCostEstimate:
    def test_no_pricing_gives_none(self):
        cost, basis = estimate_cost(True, 1000, 500, None, None, model="m", used_fallback=False)
        assert cost is None and "no pricing" in basis

    def test_priced_usage(self):
        cost, _ = estimate_cost(True, 1_000_000, 1_000_000, 0.15, 0.60, model="m", used_fallback=False)
        assert cost == pytest.approx(0.75)

    def test_fallback_usage_not_priced_as_primary(self):
        cost, basis = estimate_cost(True, 10, 10, 1.0, 1.0, model="m", used_fallback=True)
        assert cost is None and "fallback" in basis


class TestLLMFactoryIsolation:
    def test_build_does_not_touch_environment(self, monkeypatch):
        from backend.agents.config import AgentSettings, LLMFactory
        import litellm

        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        before = litellm.completion
        llm = LLMFactory.build(AgentSettings(
            llm_api_key="sk-test", llm_fallback_provider="mistral",
            llm_fallback_model="mistral/mistral-small-latest", llm_fallback_api_key="fb-key",
        ))
        assert "MISTRAL_API_KEY" not in os.environ
        assert litellm.completion is before
        assert llm.vexa_state["using_fallback"] is False


# ---------------------------------------------------------------------------
# Command policy and environment (S2, S5)
# ---------------------------------------------------------------------------


class TestCommandPolicy:
    @pytest.mark.parametrize("argv", [
        [sys.executable, "-c", "print(1)"],
        ["python", "script.py"],
        ["pip", "install", "requests"],
        [sys.executable, "-m", "pip", "install", "x"],
        ["git", "commit", "-m", "x"],
        ["git", "-c", "core.pager=sh", "log"],
        ["git", "diff", "--output=/tmp/x"],
        ["pytest", "-p", "evil_plugin"],
        ["pytest", "--rootdir=/"],
        ["pytest", "/etc"],
        ["pytest", "../other"],
        ["rm", "-rf", "/"],
        ["bash", "-c", "id"],
    ])
    def test_rejected(self, argv):
        assert check_command(argv) is not None

    @pytest.mark.parametrize("argv", [
        [sys.executable, "-m", "pytest", ".", "-q", "--tb=short"],
        ["pytest", "tests/test_x.py", "-k", "modulo"],
        ["git", "status", "--short"],
        ["git", "diff"],
        ["ruff", "check"],
    ])
    def test_allowed(self, argv):
        assert check_command(argv) is None

    def test_inline_python_cannot_execute(self, svc, sample_ws):
        r = svc.run_command(sample_ws, [sys.executable, "-c", "open('../../escape.txt','w')"])
        assert r.success is False and r.exit_code is None

    def test_env_has_no_secrets(self, monkeypatch):
        for k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "VEXA_LLM_API_KEY", "TAVILY_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.setenv(k, "secret")
        env = build_sandbox_env()
        assert not any("KEY" in k or "TOKEN" in k or "SECRET" in k for k in env)
        assert "PATH" in env

    def test_test_code_cannot_read_host_secrets(self, svc, sample_ws, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "leak-me")
        svc.write_file(sample_ws, "tests/test_env.py",
                       "import os\ndef test_env():\n    assert os.environ.get('GROQ_API_KEY') is None\n")
        r = svc.run_tests(sample_ws, test_path="tests/test_env.py")
        assert r.success, r.stdout + r.stderr

    def test_run_tests_rejects_dangerous_args(self, svc, sample_ws):
        r = svc.run_tests(sample_ws, extra_args=["-p", "anything"])
        assert r.exit_code is None and "not permitted" in r.message
        r = svc.run_tests(sample_ws, test_path="/etc")
        assert r.exit_code is None


# ---------------------------------------------------------------------------
# Workspace boundary (S3)
# ---------------------------------------------------------------------------


class TestWorkspaceBoundary:
    @pytest.mark.parametrize("bad", ["../escape", "a/b", "..", ".hidden", "x\\..\\y", " lead", ""])
    def test_invalid_ids_rejected(self, tmp_path, bad):
        mgr = WorkspaceManager(tmp_path / "root")
        with pytest.raises(WorkspaceSecurityError):
            mgr.create(bad or "..")
        assert not (tmp_path / "escape").exists()

    def test_exists_is_false_for_invalid_id(self, tmp_path):
        assert WorkspaceManager(tmp_path).exists("../x") is False

    def test_existing_style_ids_still_valid(self, tmp_path):
        mgr = WorkspaceManager(tmp_path)
        assert mgr.create("Rock paper scissors") == "Rock paper scissors"
        assert mgr.create("To-do") == "To-do"

    def test_output_path_disabled_by_default(self, tmp_path):
        mgr = WorkspaceManager(tmp_path / "root")
        with pytest.raises(WorkspaceSecurityError):
            mgr.create("ws", output_path=str(tmp_path / "elsewhere"))

    def test_output_path_allowed_root(self, tmp_path, monkeypatch):
        from backend.core.config import get_settings
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setenv("WORKSPACE_ALLOWED_OUTPUT_ROOTS", str(allowed))
        get_settings.cache_clear()
        try:
            mgr = WorkspaceManager(tmp_path / "root")
            mgr.create("ok", output_path=str(allowed / "proj"))
            assert mgr.require("ok") == (allowed / "proj").resolve()
            with pytest.raises(WorkspaceSecurityError):
                mgr.create("bad", output_path=str(tmp_path / "not-allowed"))
        finally:
            monkeypatch.delenv("WORKSPACE_ALLOWED_OUTPUT_ROOTS")
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# HTTP layer (D3, S1, S3, S4)
# ---------------------------------------------------------------------------


class TestHttpHardening:
    def test_bogus_execution_mode_is_422(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        r = client.post("/agent-runs", json={
            "workspace_id": ws, "requirement": "Add a modulo function", "execution_mode": "bogus",
        })
        assert r.status_code == 422

    def test_traversal_workspace_id_rejected(self, client):
        r = client.post("/workspaces", json={"workspace_id": "../../escaped"})
        assert r.status_code == 403

    def test_output_path_rejected_by_default(self, client, tmp_path):
        r = client.post("/workspaces", json={"output_path": str(tmp_path)})
        assert r.status_code == 403

    def test_cors_rejects_unknown_origin(self, client):
        r = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers

    def test_cors_allows_dashboard(self, client):
        r = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_preview_is_csp_sandboxed(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        client.post(f"/workspaces/{ws}/write", json={"path": "index.html", "content": "<p>x</p>"})
        r = client.get(f"/workspaces/{ws}/serve/index.html")
        assert r.status_code == 200
        assert r.headers["content-security-policy"].startswith("sandbox")
        assert "allow-same-origin" not in r.headers["content-security-policy"]

    def test_preview_traversal_blocked(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        r = client.get(f"/workspaces/{ws}/serve/..%2F..%2Fsecret")
        assert r.status_code in (403, 404)

    def test_tests_endpoint_rejects_plugin_flag(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        r = client.post(f"/workspaces/{ws}/tests", json={"extra_args": ["-p", "x"]})
        assert r.status_code == 403


class TestApiToken:
    def test_token_required_when_configured(self, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.core.config import get_settings
        from backend.main import create_app

        monkeypatch.setenv("API_TOKEN", "s3cret")
        get_settings.cache_clear()
        try:
            c = TestClient(create_app())
            assert c.get("/health").status_code == 200
            assert c.get("/workspaces").status_code == 401
            assert c.get("/workspaces", headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert c.get("/workspaces", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        finally:
            monkeypatch.delenv("API_TOKEN")
            get_settings.cache_clear()
