"""Tests for the OpenAI-compatible backend.

These use httpx2's MockTransport, so they never touch the network and
don't need a model server running.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from inferx.backends.base import BackendError
from inferx.backends.openai_compatible import OpenAICompatibleBackend
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse, ChatMessage

Handler = Callable[[httpx2.Request], httpx2.Response]


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Hello")],
    )


def openai_response(content: str = "Hi there") -> dict[str, Any]:
    """A valid response body, shaped like what Ollama or vLLM return."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        # Real servers send extra fields like this one; we should ignore them.
        "system_fingerprint": "fp_test",
    }


async def complete_with(handler: Handler, api_key: str | None = None) -> ChatCompletionResponse:
    """Create a backend wired to a fake server, send one request, and clean up."""
    backend = OpenAICompatibleBackend(
        name="test-backend",
        base_url="http://model-server.test/v1",
        model="test-model",
        api_key=api_key,
        transport=httpx2.MockTransport(handler),
    )
    try:
        return await backend.complete(make_request())
    finally:
        await backend.aclose()


@pytest.mark.anyio
async def test_sends_request_with_backend_model_name() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=openai_response())

    await complete_with(handler)

    assert seen["url"] == "http://model-server.test/v1/chat/completions"
    assert seen["body"]["model"] == "test-model"
    assert "max_tokens" not in seen["body"]


@pytest.mark.anyio
async def test_parses_reply_and_ignores_extra_fields() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=openai_response("Hi there"))

    response = await complete_with(handler)

    assert response.choices[0].message.content == "Hi there"
    assert response.usage.total_tokens == 7


@pytest.mark.anyio
async def test_sends_api_key_as_bearer_token() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx2.Response(200, json=openai_response())

    await complete_with(handler, api_key="secret-key")

    assert seen["auth"] == "Bearer secret-key"


@pytest.mark.anyio
async def test_omits_authorization_header_without_api_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx2.Response(200, json=openai_response())

    await complete_with(handler)

    assert seen["auth"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_error_status_raises_backend_error(status_code: int) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, json={"error": "something went wrong"})

    with pytest.raises(BackendError, match="test-backend"):
        await complete_with(handler)


@pytest.mark.anyio
async def test_connection_failure_raises_backend_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(BackendError, match="request failed"):
        await complete_with(handler)


@pytest.mark.anyio
async def test_invalid_json_raises_backend_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="this is not json")

    with pytest.raises(BackendError, match="invalid response"):
        await complete_with(handler)


@pytest.mark.anyio
async def test_wrong_response_shape_raises_backend_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"unexpected": "shape"})

    with pytest.raises(BackendError, match="invalid response"):
        await complete_with(handler)


def test_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleBackend(
            name="bad",
            base_url="http://model-server.test/v1",
            model="test-model",
            timeout_seconds=0,
        )