"""A backend wrapper that skips a backend while its circuit is open.

CircuitBreakerBackend asks its CircuitBreaker before every request. While the
circuit is open, it fails immediately with a retryable error, so the gateway
falls back to another backend instead of waiting on one that's down.
"""

from inferx.backends.base import Backend, BackendError
from inferx.circuit_breaker import CircuitBreaker
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse


class CircuitOpenError(BackendError):
    """Raised instead of calling a backend whose circuit is open."""


class CircuitBreakerBackend(Backend):
    """A backend that stops calling another backend while it keeps failing."""

    def __init__(self, inner: Backend, breaker: CircuitBreaker) -> None:
        self.name = inner.name
        self.breaker = breaker
        self._inner = inner

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        if not self.breaker.allow_request():
            raise CircuitOpenError(
                f"circuit open for backend '{self.name}'",
                retryable=True,
            )

        try:
            response = await self._inner.complete(request)
        except BackendError as error:
            if error.retryable:
                self.breaker.record_failure()
            else:
                # The backend answered, so it's alive. The request was the
                # problem, not the backend's health.
                self.breaker.record_success()
            raise
        except BaseException:
            # Cancelled or crashed: this says nothing about the backend's
            # health, but a probe slot must never stay taken forever.
            self.breaker.release_probe()
            raise

        self.breaker.record_success()
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()