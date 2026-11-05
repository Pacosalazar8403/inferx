"""End-to-end tests for the total time budget per request."""

import logging
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inferx.app import app

StartClient = Callable[..., TestClient]


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


@pytest.fixture
def start_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StartClient:
    """Return a function that starts the app with given latencies and a budget."""

    def start(
        request_timeout_seconds: float = 0.2,
        small_latency: float = 0.0,
        small_fails: bool = False,
        large_latency: float = 0.0,
    ) -> TestClient:
        text = f"""
        [routing]
        small_backend = "small"
        large_backend = "large"
        max_small_prompt_chars = 200
        fallback_backends = ["large", "small"]

        [retry]
        max_attempts = 1

        [limits]
        request_timeout_seconds = {request_timeout_seconds}

        [[backends]]
        type = "mock"
        name = "small"
        latency_seconds = {small_latency}
        fail = {toml_bool(small_fails)}

        [[backends]]
        type = "mock"
        name = "large"
        latency_seconds = {large_latency}
        """
        config_path = tmp_path / "gateway.toml"
        config_path.write_text(textwrap.dedent(text))
        monkeypatch.setenv("INFERX_CONFIG_PATH", str(config_path))
        return TestClient(app)

    return start


def chat(client: TestClient):
    return client.post(
        "/v1/chat/completions",
        headers={"X-Request-ID": "deadline-test"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )


def test_fast_request_is_not_affected(start_client: StartClient) -> None:
    with start_client(request_timeout_seconds=1.0) as client:
        response = chat(client)

    assert response.status_code == 200


def test_slow_backend_returns_504_within_the_budget(start_client: StartClient) -> None:
    with start_client(request_timeout_seconds=0.2, small_latency=5.0) as client:
        start = time.perf_counter()
        response = chat(client)
        elapsed = time.perf_counter() - start

    assert response.status_code == 504
    assert response.headers["X-InferX-Backend"] == "small"
    # The backend would take 5 seconds, but the client waited about 0.2.
    assert elapsed < 1.0


def test_deadline_is_logged_with_the_request_id(
    start_client: StartClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    with start_client(request_timeout_seconds=0.2, small_latency=5.0) as client:
        chat(client)

    (record,) = [r for r in caplog.records if r.getMessage() == "request deadline exceeded"]
    assert record.request_id == "deadline-test"
    assert record.backend == "small"
    assert record.request_timeout_seconds == 0.2


def test_budget_covers_fallbacks_too(start_client: StartClient) -> None:
    # The small backend fails instantly, so the request falls back to the
    # large one, which is too slow. The budget is for the whole request.
    with start_client(
        request_timeout_seconds=0.2,
        small_fails=True,
        large_latency=5.0,
    ) as client:
        response = chat(client)

    assert response.status_code == 504
    assert response.headers["X-InferX-Backend"] == "large"
    assert response.headers["X-InferX-Fallback-From"] == "small"