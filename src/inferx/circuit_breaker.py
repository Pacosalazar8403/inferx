"""A circuit breaker: stop sending requests to a backend that keeps failing.

States:
- closed: requests go through, and consecutive failures are counted
- open: requests are rejected immediately until a cooldown passes
- half-open: one probe request is allowed through to test the backend.
  If it succeeds the circuit closes; if it fails the circuit opens again.

This class only tracks state. It never calls a backend itself, which keeps
it easy to test. The clock is a parameter so tests can move time forward.
"""

import logging
import time
from collections.abc import Callable
from enum import StrEnum

logger = logging.getLogger(__name__)

Clock = Callable[[], float]


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Tracks one backend's health and decides whether to allow requests."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        clock: Clock = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")

        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        return self._state

    def allow_request(self) -> bool:
        """Decide whether a request may go to the backend right now.

        In half-open, this returns True only for the single probe request.
        """
        if self._state is CircuitState.OPEN:
            if self._clock() - self._opened_at < self.cooldown_seconds:
                return False
            self._move_to(CircuitState.HALF_OPEN)

        if self._state is CircuitState.HALF_OPEN:
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

        return True

    def record_success(self) -> None:
        """The backend responded. Close the circuit if it wasn't closed."""
        self._consecutive_failures = 0
        self._probe_in_flight = False
        if self._state is not CircuitState.CLOSED:
            self._move_to(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """The backend failed in a way that suggests it's unhealthy."""
        self._probe_in_flight = False

        if self._state is CircuitState.HALF_OPEN:
            self._open()
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._open()

    def release_probe(self) -> None:
        """Give up the probe slot without a result, so another request can probe.

        Used when a probe ends for a reason that says nothing about the
        backend's health, like the client disconnecting.
        """
        self._probe_in_flight = False

    def _open(self) -> None:
        self._opened_at = self._clock()
        self._consecutive_failures = 0
        self._move_to(CircuitState.OPEN)

    def _move_to(self, new_state: CircuitState) -> None:
        old_state = self._state
        self._state = new_state
        logger.warning(
            "circuit breaker state changed",
            extra={
                "backend": self.name,
                "from_state": old_state,
                "to_state": new_state,
            },
        )