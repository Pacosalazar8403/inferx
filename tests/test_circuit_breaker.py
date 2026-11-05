"""Tests for the circuit breaker state machine."""

import logging

import pytest

from inferx.circuit_breaker import CircuitBreaker, CircuitState


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_breaker(
    clock: FakeClock,
    failure_threshold: int = 3,
    cooldown_seconds: float = 30.0,
) -> CircuitBreaker:
    return CircuitBreaker(
        name="test-backend",
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
        clock=clock,
    )


def fail_times(breaker: CircuitBreaker, count: int) -> None:
    for _ in range(count):
        assert breaker.allow_request()
        breaker.record_failure()


def test_starts_closed_and_allows_requests() -> None:
    breaker = make_breaker(FakeClock())

    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request()


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker = make_breaker(FakeClock(), failure_threshold=3)

    fail_times(breaker, 2)
    assert breaker.state is CircuitState.CLOSED

    fail_times(breaker, 1)
    assert breaker.state is CircuitState.OPEN


def test_success_resets_the_failure_count() -> None:
    breaker = make_breaker(FakeClock(), failure_threshold=3)

    fail_times(breaker, 2)
    breaker.record_success()
    fail_times(breaker, 2)

    assert breaker.state is CircuitState.CLOSED


def test_open_circuit_rejects_requests_until_cooldown_passes() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock, cooldown_seconds=30.0)
    fail_times(breaker, 3)

    clock.advance(29.9)

    assert not breaker.allow_request()
    assert breaker.state is CircuitState.OPEN


def test_after_cooldown_allows_exactly_one_probe() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock, cooldown_seconds=30.0)
    fail_times(breaker, 3)

    clock.advance(30.0)

    assert breaker.allow_request()
    assert breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow_request()


def test_successful_probe_closes_the_circuit() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    fail_times(breaker, 3)
    clock.advance(30.0)

    assert breaker.allow_request()
    breaker.record_success()

    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request()


def test_failed_probe_reopens_and_restarts_the_cooldown() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock, cooldown_seconds=30.0)
    fail_times(breaker, 3)
    clock.advance(30.0)

    assert breaker.allow_request()
    breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    clock.advance(29.9)
    assert not breaker.allow_request()
    clock.advance(0.1)
    assert breaker.allow_request()


def test_released_probe_lets_another_request_probe() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    fail_times(breaker, 3)
    clock.advance(30.0)

    assert breaker.allow_request()
    breaker.release_probe()

    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.allow_request()


@pytest.mark.parametrize(
    "settings",
    [{"failure_threshold": 0}, {"cooldown_seconds": 0}],
    ids=["zero-threshold", "zero-cooldown"],
)
def test_rejects_invalid_settings(settings: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(name="bad", **settings)


def test_state_changes_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="inferx")
    clock = FakeClock()
    breaker = make_breaker(clock)

    fail_times(breaker, 3)
    clock.advance(30.0)
    breaker.allow_request()
    breaker.record_success()

    changes = [
        (r.from_state, r.to_state)
        for r in caplog.records
        if r.getMessage() == "circuit breaker state changed"
    ]
    assert changes == [
        ("closed", "open"),
        ("open", "half_open"),
        ("half_open", "closed"),
    ]