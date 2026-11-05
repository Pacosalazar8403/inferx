"""Tests for retries with exponential backoff and jitter."""

import logging

import pytest

from inferx.backends.base import Backend, BackendError
from inferx.backends.mock import MockBackend
from inferx.backends.retrying import RetryingBackend, RetryPolicy
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse, ChatMessage


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Hello")],
    )


def transient() -> BackendError:
    return BackendError("temporary failure", retryable=True, status_code=503)


def permanent() -> BackendError:
    return BackendError("permanent failure", retryable=False, status_code=401)


class FlakyBackend(Backend):
    """Fails with the given errors, in order, then succeeds."""

    def __init__(self, failures: list[BackendError]) -> None:
        self.name = "flaky"
        self.calls = 0
        self.closed = False
        self._failures = list(failures)

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return await MockBackend(name=self.name).complete(request)

    async def aclose(self) -> None:
        self.closed = True


class FakeSleep:
    """Records requested delays instead of actually waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_retrying(
    inner: Backend,
    sleep: FakeSleep,
    max_attempts: int = 3,
    random_fraction: float = 1.0,
) -> RetryingBackend:
    return RetryingBackend(
        inner,
        RetryPolicy(max_attempts=max_attempts, base_delay_seconds=0.1, max_delay_seconds=2.0),
        sleep=sleep,
        random_fraction=lambda: random_fraction,
    )


@pytest.mark.anyio
async def test_succeeds_without_waiting_when_first_attempt_works() -> None:
    inner = FlakyBackend(failures=[])
    sleep = FakeSleep()

    await make_retrying(inner, sleep).complete(make_request())

    assert inner.calls == 1
    assert sleep.delays == []


@pytest.mark.anyio
async def test_retries_transient_failures_until_success() -> None:
    inner = FlakyBackend(failures=[transient(), transient()])
    sleep = FakeSleep()

    response = await make_retrying(inner, sleep, max_attempts=3).complete(make_request())

    assert response.choices[0].message.content == "Mock reply to: Hello"
    assert inner.calls == 3
    assert len(sleep.delays) == 2


@pytest.mark.anyio
async def test_gives_up_after_max_attempts() -> None:
    inner = FlakyBackend(failures=[transient()] * 5)
    sleep = FakeSleep()

    with pytest.raises(BackendError, match="temporary failure"):
        await make_retrying(inner, sleep, max_attempts=3).complete(make_request())

    assert inner.calls == 3
    assert len(sleep.delays) == 2


@pytest.mark.anyio
async def test_permanent_failure_is_not_retried() -> None:
    inner = FlakyBackend(failures=[permanent()])
    sleep = FakeSleep()

    with pytest.raises(BackendError, match="permanent failure"):
        await make_retrying(inner, sleep).complete(make_request())

    assert inner.calls == 1
    assert sleep.delays == []


@pytest.mark.anyio
async def test_waits_grow_exponentially() -> None:
    inner = FlakyBackend(failures=[transient()] * 3)
    sleep = FakeSleep()

    # A random fraction of 1.0 means "wait the full cap", so we can check it.
    await make_retrying(inner, sleep, max_attempts=4, random_fraction=1.0).complete(make_request())

    assert sleep.delays == pytest.approx([0.1, 0.2, 0.4])


@pytest.mark.anyio
async def test_jitter_scales_the_wait() -> None:
    inner = FlakyBackend(failures=[transient(), transient()])
    sleep = FakeSleep()

    await make_retrying(inner, sleep, random_fraction=0.5).complete(make_request())

    assert sleep.delays == pytest.approx([0.05, 0.1])


@pytest.mark.parametrize(
    ("attempt", "expected_cap"),
    [(1, 0.1), (2, 0.2), (3, 0.3), (4, 0.3)],
)
def test_backoff_cap_doubles_and_stops_at_maximum(attempt: int, expected_cap: float) -> None:
    policy = RetryPolicy(base_delay_seconds=0.1, max_delay_seconds=0.3)

    assert policy.backoff_cap(attempt) == pytest.approx(expected_cap)


@pytest.mark.parametrize(
    "settings",
    [
        {"max_attempts": 0},
        {"base_delay_seconds": -1.0},
        {"base_delay_seconds": 1.0, "max_delay_seconds": 0.5},
    ],
    ids=["zero-attempts", "negative-delay", "max-below-base"],
)
def test_rejects_invalid_policy(settings: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**settings)


@pytest.mark.anyio
async def test_logs_a_warning_for_each_retry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="inferx")
    inner = FlakyBackend(failures=[transient(), transient()])

    await make_retrying(inner, FakeSleep()).complete(make_request())

    retries = [r for r in caplog.records if r.getMessage() == "retrying backend request"]
    assert [r.attempt for r in retries] == [1, 2]
    assert all(r.backend == "flaky" for r in retries)
    assert all(r.backend_status_code == 503 for r in retries)


def test_uses_the_inner_backend_name() -> None:
    wrapper = make_retrying(FlakyBackend(failures=[]), FakeSleep())

    assert wrapper.name == "flaky"


@pytest.mark.anyio
async def test_closing_the_wrapper_closes_the_inner_backend() -> None:
    inner = FlakyBackend(failures=[])

    await make_retrying(inner, FakeSleep()).aclose()

    assert inner.closed is True