"""Tests for the chat API request models."""

from typing import Any

import pytest
from pydantic import ValidationError

from inferx.schemas import ChatCompletionRequest


def valid_request_data() -> dict[str, Any]:
    """Return the smallest valid request, as a client would send it."""
    return {
        "model": "mock",
        "messages": [{"role": "user", "content": "Hello"}],
    }


def test_valid_request_uses_defaults() -> None:
    request = ChatCompletionRequest.model_validate(valid_request_data())

    assert request.model == "mock"
    assert request.messages[0].content == "Hello"
    assert request.max_tokens is None
    assert request.temperature == 1.0


@pytest.mark.parametrize(
    "changes",
    [
        {"messages": []},
        {"messages": [{"role": "robot", "content": "Hi"}]},
        {"model": ""},
        {"temperature": 3.0},
        {"max_tokens": 0},
        {"max_tokens": 100_000},
    ],
    ids=[
        "no-messages",
        "invalid-role",
        "empty-model",
        "temperature-too-high",
        "zero-max-tokens",
        "max-tokens-too-high",
    ],
)
def test_invalid_requests_are_rejected(changes: dict[str, Any]) -> None:
    data = valid_request_data() | changes

    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(data)