"""Tests for the circuit breaker backend wrapper."""

import asyncio

import pytest

from inferx.backends.base import Backend, BackendError
from inferx.backends.circuit_breaking import CircuitBreakerBackend, CircuitOpenError
from inferx.backends.mock import MockBackend
from inferx.circuit_breaker import CircuitBreaker, CircuitState
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse, ChatMessage


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Hello")],
    )


class ScriptedBackend(Backend):
    """Raises the scripted errors in order (None means succeed), and counts calls."""

    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self.name = "scripted"
        self.calls = 0
        self.closed = False
        self._outcomes = list(outcomes)

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if outcome is not None:
            raise outcome
        return await MockBackend(name=self.name).complete(request)

    async def aclose(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def transient() -> BackendError:
    return BackendError("temporary failure", retryable=True, status_code=503)


def permanent() -> BackendError:
    return BackendError("bad request", retryable=False, status_code=400)


def wrap(inner: Backend, clock: FakeClock, failure_threshold: int = 2) -> CircuitBreakerBackend:
    breaker = CircuitBreaker(
        name=inner.name,
        failure_threshold=failure_threshold,
        cooldown_seconds=30.0,
        clock=clock,
    )
    return CircuitBreakerBackend(inner, breaker)


@pytest.mark.anyio
async def test_success_passes_through() -> None:
    inner = ScriptedBackend(outcomes=[None])
    backend = wrap(inner, FakeClock())

    response = await backend.complete(make_request())

    assert response.choices[0].message.content == "Mock reply to: Hello"
    assert backend.breaker.state is CircuitState.CLOSED


@pytest.mark.anyio
async def test_open_circuit_fails_fast_without_calling_the_backend() -> None:
    inner = ScriptedBackend(outcomes=[transient(), transient()])
    backend = wrap(inner, FakeClock(), failure_threshold=2)

    for _ in range(2):
        with pytest.raises(BackendError):
            await backend.complete(make_request())
    assert backend.breaker.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError) as caught:
        await backend.complete(make_request())

    assert inner.calls == 2
    assert caught.value.retryable is True


@pytest.mark.anyio
async def test_permanent_failures_do_not_open_the_circuit() -> None:
    inner = ScriptedBackend(outcomes=[permanent(), permanent(), permanent()])
    backend = wrap(inner, FakeClock(), failure_threshold=2)

    for _ in range(3):
        with pytest.raises(BackendError):
            await backend.complete(make_request())

    assert backend.breaker.state is CircuitState.CLOSED
    assert inner.calls == 3


@pytest.mark.anyio
async def test_cancelled_probe_frees_the_probe_slot() -> None:
    clock = FakeClock()
    inner = ScriptedBackend(outcomes=[transient(), asyncio.CancelledError()])
    backend = wrap(inner, clock, failure_threshold=1)

    with pytest.raises(BackendError):
        await backend.complete(make_request())
    clock.now += 30.0

    with pytest.raises(asyncio.CancelledError):
        await backend.complete(make_request())

    # Without release_probe, the breaker would reject every request from now on.
    assert backend.breaker.state is CircuitState.HALF_OPEN
    assert backend.breaker.allow_request()


def test_uses_the_inner_backend_name() -> None:
    backend = wrap(ScriptedBackend(outcomes=[]), FakeClock())

    assert backend.name == "scripted"


@pytest.mark.anyio
async def test_closing_the_wrapper_closes_the_inner_backend() -> None:
    inner = ScriptedBackend(outcomes=[])

    await wrap(inner, FakeClock()).aclose()

    assert inner.closed is True