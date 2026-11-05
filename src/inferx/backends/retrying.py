"""Retries for backends, with exponential backoff and full jitter.

RetryingBackend wraps any other backend. When the inner backend fails with
a retryable error, it waits a random amount of time and tries again, up to
a fixed number of attempts. Permanent failures are raised immediately.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from inferx.backends.base import Backend, BackendError
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse

logger = logging.getLogger(__name__)

SleepFunction = Callable[[float], Awaitable[None]]
RandomFunction = Callable[[], float]


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to try, and how long to wait between tries.

    max_attempts counts every attempt, including the first one, so
    max_attempts=3 means one try plus up to two retries.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds cannot be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be less than base_delay_seconds")

    def backoff_cap(self, attempt: int) -> float:
        """The longest wait after a failed attempt (attempts start at 1).

        Doubles with every attempt, up to max_delay_seconds.
        """
        return min(self.max_delay_seconds, self.base_delay_seconds * 2 ** (attempt - 1))

    def delay_for(self, attempt: int, random_fraction: float) -> float:
        """Full jitter: a random wait between zero and the backoff cap.

        random_fraction is a number in [0, 1), usually from random.random().
        """
        return self.backoff_cap(attempt) * random_fraction


class RetryingBackend(Backend):
    """A backend that retries another backend's retryable failures."""

    def __init__(
        self,
        inner: Backend,
        policy: RetryPolicy,
        sleep: SleepFunction = asyncio.sleep,
        random_fraction: RandomFunction = random.random,
    ) -> None:
        self.name = inner.name
        self._inner = inner
        self._policy = policy
        self._sleep = sleep
        self._random_fraction = random_fraction

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        attempt = 1
        while True:
            try:
                return await self._inner.complete(request)
            except BackendError as error:
                out_of_attempts = attempt >= self._policy.max_attempts
                if not error.retryable or out_of_attempts:
                    raise

                delay = self._policy.delay_for(attempt, self._random_fraction())
                logger.warning(
                    "retrying backend request",
                    extra={
                        "backend": self.name,
                        "attempt": attempt,
                        "max_attempts": self._policy.max_attempts,
                        "delay_seconds": round(delay, 3),
                        "backend_status_code": error.status_code,
                    },
                )
                await self._sleep(delay)
                attempt += 1

    async def aclose(self) -> None:
        await self._inner.aclose()