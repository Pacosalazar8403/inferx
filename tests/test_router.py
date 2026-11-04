"""Tests for the length-based router."""

import pytest

from inferx.router import AUTO_MODEL, LengthRouter, UnknownModelError
from inferx.schemas import ChatCompletionRequest, ChatMessage

BACKENDS = {"small", "large"}


def make_router(max_small_prompt_chars: int = 10) -> LengthRouter:
    return LengthRouter(
        small_backend="small",
        large_backend="large",
        max_small_prompt_chars=max_small_prompt_chars,
        available_backends=BACKENDS,
    )


def make_request(content: str, model: str = AUTO_MODEL) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content=content)],
    )


def test_short_prompt_goes_to_small_backend() -> None:
    decision = make_router().route(make_request("hi"))

    assert decision.backend == "small"
    assert decision.reason == "short_prompt"


def test_long_prompt_goes_to_large_backend() -> None:
    decision = make_router().route(make_request("x" * 11))

    assert decision.backend == "large"
    assert decision.reason == "long_prompt"


def test_prompt_exactly_at_limit_goes_to_small_backend() -> None:
    decision = make_router(max_small_prompt_chars=10).route(make_request("x" * 10))

    assert decision.backend == "small"


def test_length_counts_every_message() -> None:
    request = ChatCompletionRequest(
        model=AUTO_MODEL,
        messages=[
            ChatMessage(role="system", content="x" * 6),
            ChatMessage(role="user", content="x" * 6),
        ],
    )

    decision = make_router(max_small_prompt_chars=10).route(request)

    assert decision.backend == "large"


def test_named_backend_skips_routing() -> None:
    decision = make_router().route(make_request("x" * 1000, model="small"))

    assert decision.backend == "small"
    assert decision.reason == "requested"


def test_unknown_backend_raises() -> None:
    with pytest.raises(UnknownModelError):
        make_router().route(make_request("hi", model="does-not-exist"))


def test_rejects_router_pointing_at_missing_backend() -> None:
    with pytest.raises(ValueError, match="unknown backends"):
        LengthRouter(
            small_backend="small",
            large_backend="typo-backend",
            max_small_prompt_chars=10,
            available_backends=BACKENDS,
        )


def test_rejects_non_positive_threshold() -> None:
    with pytest.raises(ValueError):
        make_router(max_small_prompt_chars=0)