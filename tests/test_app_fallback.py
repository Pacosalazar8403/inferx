"""End-to-end tests for falling back to another backend."""

import logging
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inferx.app import app

StartClient = Callable[..., TestClient]


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def write_config(
    tmp_path: Path,
    *,
    small_fails: bool,
    large_fails: bool,
    small_failures_retryable: bool,
) -> Path:
    """Two mock backends. Fallback order is large, then small. No retries."""
    text = f"""
    [routing]
    small_backend = "small"
    large_backend = "large"
    max_small_prompt_chars = 200
    fallback_backends = ["large", "small"]

    [retry]
    max_attempts = 1

    [[backends]]
    type = "mock"
    name = "small"
    fail = {toml_bool(small_fails)}
    retryable_failures = {toml_bool(small_failures_retryable)}

    [[backends]]
    type = "mock"
    name = "large"
    fail = {toml_bool(large_fails)}
    """
    path = tmp_path / "gateway.toml"
    path.write_text(textwrap.dedent(text))
    return path


@pytest.fixture
def start_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StartClient:
    """Return a function that starts the app with a given failure setup."""

    def start(
        small_fails: bool = True,
        large_fails: bool = False,
        small_failures_retryable: bool = True,
    ) -> TestClient:
        config_path = write_config(
            tmp_path,
            small_fails=small_fails,
            large_fails=large_fails,
            small_failures_retryable=small_failures_retryable,
        )
        monkeypatch.setenv("INFERX_CONFIG_PATH", str(config_path))
        return TestClient(app)

    return start


def chat(client: TestClient, model: str = "auto") -> object:
    return client.post(
        "/v1/chat/completions",
        headers={"X-Request-ID": "fallback-test"},
        json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
    )


def test_falls_back_when_routed_backend_fails(start_client: StartClient) -> None:
    with start_client() as client:
        response = chat(client)

    assert response.status_code == 200
    assert response.json()["model"] == "large"
    assert response.headers["X-InferX-Backend"] == "large"
    assert response.headers["X-InferX-Fallback-From"] == "small"
    assert response.headers["X-InferX-Route-Reason"] == "short_prompt"


def test_fallback_is_logged(
    start_client: StartClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    with start_client() as client:
        chat(client)

    (fallback,) = [r for r in caplog.records if r.getMessage() == "falling back to another backend"]
    assert fallback.backend == "small"
    assert fallback.fallback_to == "large"
    assert fallback.request_id == "fallback-test"

    (completed,) = [r for r in caplog.records if r.getMessage() == "request completed"]
    assert completed.backend == "large"
    assert completed.fallback_from == "small"


def test_named_backend_does_not_fall_back(start_client: StartClient) -> None:
    with start_client() as client:
        response = chat(client, model="small")

    assert response.status_code == 502
    assert response.headers["X-InferX-Backend"] == "small"
    assert "X-InferX-Fallback-From" not in response.headers


def test_permanent_failure_does_not_fall_back(start_client: StartClient) -> None:
    with start_client(small_failures_retryable=False) as client:
        response = chat(client)

    assert response.status_code == 502
    assert response.headers["X-InferX-Backend"] == "small"
    assert "X-InferX-Fallback-From" not in response.headers


def test_returns_502_when_every_backend_fails(start_client: StartClient) -> None:
    with start_client(large_fails=True) as client:
        response = chat(client)

    assert response.status_code == 502
    assert response.headers["X-InferX-Backend"] == "large"
    assert response.headers["X-InferX-Fallback-From"] == "small"