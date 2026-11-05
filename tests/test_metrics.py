"""Tests for the /metrics endpoint, HTTP metrics, and gateway metrics."""

import logging
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inferx.app import app

StartClient = Callable[[str], TestClient]


def sample(client: TestClient, name: str, labels: dict[str, str]) -> float | None:
    """Read one metric value straight from the app's registry."""
    return client.app.state.metrics.registry.get_sample_value(name, labels)


def chat(client: TestClient, content: str = "hi") -> None:
    client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": content}]},
    )


@pytest.fixture
def start_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StartClient:
    """Return a function that starts the app with the given config text."""

    def start(config_text: str) -> TestClient:
        config_path = tmp_path / "gateway.toml"
        config_path.write_text(textwrap.dedent(config_text))
        monkeypatch.setenv("INFERX_CONFIG_PATH", str(config_path))
        return TestClient(app)

    return start


# The small backend always fails, the large one works, and the small
# backend's circuit opens after 2 failures.
FAILING_SMALL_BACKEND = """
[routing]
small_backend = "small"
large_backend = "large"
max_small_prompt_chars = 200
fallback_backends = ["large", "small"]

[retry]
max_attempts = 2
base_delay_seconds = 0
max_delay_seconds = 0

[circuit_breaker]
failure_threshold = 2
cooldown_seconds = 60.0

[[backends]]
type = "mock"
name = "small"
fail = true

[[backends]]
type = "mock"
name = "large"
"""

SLOW_BACKEND = """
[routing]
small_backend = "small"
large_backend = "small"
max_small_prompt_chars = 200

[limits]
request_timeout_seconds = 0.2

[[backends]]
type = "mock"
name = "small"
latency_seconds = 5.0
"""


def test_metrics_endpoint_serves_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "inferx_http_requests_total" in response.text
    assert "_created" not in response.text


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


def test_counts_successful_backend_attempts(client: TestClient) -> None:
    chat(client)

    count = sample(
        client,
        "inferx_backend_attempts_total",
        {"backend": "mock-small", "outcome": "success"},
    )
    assert count == 1


def test_counts_failures_retries_fallbacks_and_open_circuits(start_client: StartClient) -> None:
    with start_client(FAILING_SMALL_BACKEND) as client:
        for _ in range(3):
            chat(client)

        # The first two requests tried "small" (with one retry each) and fell back.
        assert sample(client, "inferx_backend_retries_total", {"backend": "small"}) == 2
        assert sample(
            client,
            "inferx_backend_attempts_total",
            {"backend": "small", "outcome": "retryable_failure"},
        ) == 2

        # After 2 failures the circuit opened, so the third request skipped "small".
        assert sample(
            client,
            "inferx_backend_attempts_total",
            {"backend": "small", "outcome": "circuit_open"},
        ) == 1

        # All three requests fell back to "large", which answered every time.
        assert sample(
            client,
            "inferx_fallbacks_total",
            {"from_backend": "small", "to_backend": "large"},
        ) == 3
        assert sample(
            client,
            "inferx_backend_attempts_total",
            {"backend": "large", "outcome": "success"},
        ) == 3


def test_reports_circuit_breaker_states(start_client: StartClient) -> None:
    with start_client(FAILING_SMALL_BACKEND) as client:
        chat(client)
        chat(client)

        small_open = sample(
            client, "inferx_circuit_breaker_state", {"backend": "small", "state": "open"}
        )
        small_closed = sample(
            client, "inferx_circuit_breaker_state", {"backend": "small", "state": "closed"}
        )
        large_closed = sample(
            client, "inferx_circuit_breaker_state", {"backend": "large", "state": "closed"}
        )

    assert small_open == 1
    assert small_closed == 0
    assert large_closed == 1


def test_counts_deadlines_exceeded(start_client: StartClient) -> None:
    with start_client(SLOW_BACKEND) as client:
        chat(client)

        count = sample(client, "inferx_deadline_exceeded_total", {"backend": "small"})

    assert count == 1