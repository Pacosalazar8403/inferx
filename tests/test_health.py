"""Tests for the health check endpoint."""

from importlib.metadata import version

from fastapi.testclient import TestClient

from inferx.app import app

# TestClient calls the app directly in memory, without starting a server.
client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_package_version() -> None:
    response = client.get("/health")

    assert response.json()["version"] == version("inferx")