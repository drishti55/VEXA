"""
Tests for the FastAPI application and /health endpoint.
"""

from __future__ import annotations


def test_app_starts(client):
    """The application must start without raising an exception."""
    # TestClient construction already proves this; just assert something real.
    assert client is not None


def test_health_returns_200(client):
    """GET /health must return HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_structure(client):
    """GET /health must return required JSON fields."""
    response = client.get("/health")
    body = response.json()

    assert body["status"] == "ok"
    assert "service" in body
    assert "version" in body
    assert "environment" in body


def test_health_service_name(client):
    """Service name must match configuration."""
    response = client.get("/health")
    body = response.json()
    assert body["service"] == "VEXA"


def test_health_environment_is_testing(client):
    """Environment must be 'testing' during the test run."""
    response = client.get("/health")
    body = response.json()
    assert body["environment"] == "testing"
