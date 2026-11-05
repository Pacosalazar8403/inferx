"""The interface every model backend must implement."""

from abc import ABC, abstractmethod

from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse


class BackendError(Exception):
    """Raised when a backend fails to produce a response.

    `retryable` says whether trying again might succeed (like a timeout or
    a 503), as opposed to a failure that will repeat (like a 401 or a bad
    request). Retry and fallback logic rely on it, so the default is the
    safe choice: not retryable.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class Backend(ABC):
    """A service that can generate chat completions.

    InferX talks to every model through this interface, so the rest of
    the system never needs to know whether it's calling a local model,
    a hosted API, or a fake backend in a test.
    """

    name: str

    @abstractmethod
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Generate a reply for the given conversation."""

    async def aclose(self) -> None:
        """Release resources the backend holds, like open connections.

        Backends with nothing to clean up can rely on this default.
        """