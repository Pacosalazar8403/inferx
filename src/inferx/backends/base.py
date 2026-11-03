"""The interface every model backend must implement."""

from abc import ABC, abstractmethod

from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse


class BackendError(Exception):
    """Raised when a backend fails to produce a response."""


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