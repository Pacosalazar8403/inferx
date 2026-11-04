"""Tests for the chat completions endpoint."""

from typing import Any

from fastapi.testclient import TestClient

from inferx.app import app, get_backends
from inferx.backends.mock import MockBackend


def chat_payload(content: str = "Hello InferX", model: str = "auto") -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }


def test_chat_returns_backend_reply(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=chat_payload("Hello InferX"))

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Mock reply to: Hello InferX"


def test_short_prompt_is_routed_to_small_backend(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=chat_payload("hi"))

    assert response.headers["X-InferX-Backend"] == "mock-small"
    assert response.headers["X-InferX-Route-Reason"] == "short_prompt"


def test_long_prompt_is_routed_to_large_backend(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=chat_payload("x" * 201))

    assert response.headers["X-InferX-Backend"] == "mock-large"
    assert response.headers["X-InferX-Route-Reason"] == "long_prompt"


def test_named_backend_is_used_directly(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json=chat_payload("hi", model="mock-large"),
    )

    assert response.status_code == 200
    assert response.headers["X-InferX-Backend"] == "mock-large"
    assert response.headers["X-InferX-Route-Reason"] == "requested"


def test_unknown_model_returns_404(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json=chat_payload(model="gpt-9000"),
    )

    assert response.status_code == 404


def test_chat_rejects_invalid_request(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": []},
    )

    assert response.status_code == 422


def test_chat_returns_502_when_backend_fails(client: TestClient) -> None:
    failing = MockBackend(name="internal-backend-7", fail=True)
    app.dependency_overrides[get_backends] = lambda: {
        "mock-small": failing,
        "mock-large": failing,
    }

    response = client.post("/v1/chat/completions", json=chat_payload())

    assert response.status_code == 502
    assert response.headers["X-InferX-Backend"] == "mock-small"
    # Internal backend details must not leak to the client.
    assert "internal-backend-7" not in response.text