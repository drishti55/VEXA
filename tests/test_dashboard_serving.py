"""Single-service deployment: the backend serves the built dashboard without shadowing the API."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>VEXA</title>")
    (d / "assets" / "app.js").write_text("console.log('vexa')")
    monkeypatch.setenv("VEXA_FRONTEND_DIST", str(d))
    return d


def _client(monkeypatch, token=None):
    from backend.core.config import get_settings
    if token:
        monkeypatch.setenv("API_TOKEN", token)
    get_settings.cache_clear()
    from backend.main import create_app
    return TestClient(create_app())


def test_dashboard_and_api_share_one_origin(dist, monkeypatch):
    client = _client(monkeypatch)
    assert "<title>VEXA</title>" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/health").json()["status"] == "ok"           # API routes still win
    assert client.get("/agent-runs/architectures").status_code == 200


def test_token_protects_the_api_but_not_the_page(dist, monkeypatch):
    client = _client(monkeypatch, token="s3cret-token")
    try:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/agent-runs/architectures").status_code == 401
        ok = client.get("/agent-runs/architectures", headers={"Authorization": "Bearer s3cret-token"})
        assert ok.status_code == 200
    finally:
        monkeypatch.delenv("API_TOKEN")
        from backend.core.config import get_settings
        get_settings.cache_clear()


def test_no_dashboard_mounted_without_a_build(tmp_path, monkeypatch):
    monkeypatch.setenv("VEXA_FRONTEND_DIST", str(tmp_path / "missing"))
    client = _client(monkeypatch)
    assert client.get("/").status_code == 404
