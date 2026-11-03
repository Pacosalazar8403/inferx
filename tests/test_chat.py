"""Tests for the chat completions endpoint."""

from typing import Any

from fastapi.testclient import TestClient

from inferx.app import app, get_backend
from inferx.backends.mock import MockBackend


def chat_payload(content: str = "Hello InferX") -> dict[str, Any]:
    return {
        "model": "mock",
        "messages": [{"role": "user", "content": content}],
    }


def test_chat_returns_backend_reply(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=chat_payload("Hello InferX"))

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Mock reply to: Hello InferX"


def test_chat_rejects_invalid_request(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "mock", "messages": []},
    )

    assert response.status_code == 422


def test_chat_returns_502_when_backend_fails(client: TestClient) -> None:
    app.dependency_overrides[get_backend] = lambda: MockBackend(
        name="internal-backend-7", fail=True
    )

    response = client.post("/v1/chat/completions", json=chat_payload())

    assert response.status_code == 502
    # Internal backend details must not leak to the client.
    assert "internal-backend-7" not in response.text