"""Tests for the chat completions endpoint."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from inferx.app import app, get_backend
from inferx.backends.mock import MockBackend

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_dependency_overrides() -> Iterator[None]:
    """Make sure no test leaves a swapped-in backend behind."""
    yield
    app.dependency_overrides.clear()


def chat_payload(content: str = "Hello InferX") -> dict:
    return {
        "model": "mock",
        "messages": [{"role": "user", "content": content}],
    }


def test_chat_returns_backend_reply() -> None:
    response = client.post("/v1/chat/completions", json=chat_payload("Hello InferX"))

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Mock reply to: Hello InferX"


def test_chat_rejects_invalid_request() -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "mock", "messages": []},
    )

    assert response.status_code == 422


def test_chat_returns_502_when_backend_fails() -> None:
    app.dependency_overrides[get_backend] = lambda: MockBackend(
        name="internal-backend-7", fail=True
    )

    response = client.post("/v1/chat/completions", json=chat_payload())

    assert response.status_code == 502
    # Internal backend details must not leak to the client.
    assert "internal-backend-7" not in response.text