"""Tests for request IDs and per-request logging."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inferx.app import app, get_backends
from inferx.backends.mock import MockBackend


def chat_payload(content: str = "hi", model: str = "auto") -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": content}]}


def logs_with_message(
    caplog: pytest.LogCaptureFixture, message: str
) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == message]


def test_response_includes_generated_request_id(client: TestClient) -> None:
    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)  # Raises ValueError if it isn't hexadecimal.


def test_valid_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


@pytest.mark.parametrize(
    "unsafe_id",
    ["has spaces", "x" * 65, 'quote"inside'],
    ids=["spaces", "too-long", "quote"],
)
def test_unsafe_incoming_request_id_is_replaced(client: TestClient, unsafe_id: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": unsafe_id})

    assert response.headers["X-Request-ID"] != unsafe_id


def test_logs_one_line_per_chat_request(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    response = client.post("/v1/chat/completions", json=chat_payload("hi"))

    (record,) = logs_with_message(caplog, "request completed")
    assert record.request_id == response.headers["X-Request-ID"]
    assert record.status == 200
    assert record.backend == "mock-small"
    assert record.route_reason == "short_prompt"
    assert record.latency_ms >= 0
    assert record.backend_latency_ms >= 0


def test_backend_failure_is_logged_with_details(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")
    failing = MockBackend(name="internal-backend-7", fail=True)
    app.dependency_overrides[get_backends] = lambda: {
        "mock-small": failing,
        "mock-large": failing,
    }

    response = client.post("/v1/chat/completions", json=chat_payload())

    (warning,) = logs_with_message(caplog, "backend request failed")
    assert warning.request_id == response.headers["X-Request-ID"]
    assert warning.exc_info is not None
    assert "failed on purpose" in str(warning.exc_info[1])
    assert warning.retryable is True

    (completed,) = logs_with_message(caplog, "request completed")
    assert completed.status == 502


def test_unknown_model_is_logged_without_backend(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    client.post("/v1/chat/completions", json=chat_payload(model="gpt-9000"))

    (record,) = logs_with_message(caplog, "request completed")
    assert record.status == 404
    assert record.backend is None