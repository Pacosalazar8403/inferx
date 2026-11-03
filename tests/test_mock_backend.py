"""Tests for the mock backend."""

import time

import pytest

from inferx.backends.base import BackendError
from inferx.backends.mock import MockBackend
from inferx.schemas import ChatCompletionRequest, ChatMessage


def make_request(content: str = "Hello there") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="mock",
        messages=[ChatMessage(role="user", content=content)],
    )


@pytest.mark.anyio
async def test_returns_reply_to_last_message() -> None:
    backend = MockBackend()

    response = await backend.complete(make_request("Hello there"))

    assert response.model == "mock"
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].message.content == "Mock reply to: Hello there"
    assert response.choices[0].finish_reason == "stop"


@pytest.mark.anyio
async def test_usage_totals_add_up() -> None:
    backend = MockBackend()

    response = await backend.complete(make_request("one two three"))

    usage = response.usage
    assert usage.prompt_tokens == 3
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


@pytest.mark.anyio
async def test_waits_for_configured_latency() -> None:
    backend = MockBackend(latency_seconds=0.05)

    start = time.perf_counter()
    await backend.complete(make_request())
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.05


@pytest.mark.anyio
async def test_raises_backend_error_when_configured_to_fail() -> None:
    backend = MockBackend(name="broken", fail=True)

    with pytest.raises(BackendError, match="broken"):
        await backend.complete(make_request())


def test_rejects_negative_latency() -> None:
    with pytest.raises(ValueError):
        MockBackend(latency_seconds=-1)