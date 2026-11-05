"""Tests for the /metrics endpoint and HTTP request metrics."""

import logging

import pytest
from fastapi.testclient import TestClient


def sample(client: TestClient, name: str, labels: dict[str, str]) -> float | None:
    """Read one metric value straight from the app's registry."""
    return client.app.state.metrics.registry.get_sample_value(name, labels)


def chat(client: TestClient) -> None:
    client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )


def test_metrics_endpoint_serves_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "inferx_http_requests_total" in response.text


def test_counts_requests_by_method_route_and_status(client: TestClient) -> None:
    chat(client)
    chat(client)

    count = sample(
        client,
        "inferx_http_requests_total",
        {"method": "POST", "route": "/v1/chat/completions", "status": "200"},
    )
    assert count == 2


def test_unknown_paths_share_one_unmatched_series(client: TestClient) -> None:
    client.get("/no-such-page")
    client.get("/another-random-path")

    count = sample(
        client,
        "inferx_http_requests_total",
        {"method": "GET", "route": "unmatched", "status": "404"},
    )
    assert count == 2


def test_records_request_duration(client: TestClient) -> None:
    chat(client)

    observations = sample(
        client,
        "inferx_http_request_duration_seconds_count",
        {"method": "POST", "route": "/v1/chat/completions"},
    )
    assert observations == 1


def test_probe_requests_are_not_logged_at_info(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    client.get("/health")
    client.get("/metrics")

    completed = [r for r in caplog.records if r.getMessage() == "request completed"]
    assert completed == []