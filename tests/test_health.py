"""Tests for the health check endpoint."""

from importlib.metadata import version

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_package_version(client: TestClient) -> None:
    response = client.get("/health")

    assert response.json()["version"] == version("inferx")