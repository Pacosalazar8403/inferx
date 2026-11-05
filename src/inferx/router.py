"""Decide which backend handles each request.

The router only makes decisions. It never calls a backend itself, which
keeps it easy to test and easy to replace with a smarter router later.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from inferx.schemas import ChatCompletionRequest

AUTO_MODEL = "auto"

RouteReason = Literal["requested", "short_prompt", "long_prompt"]


class UnknownModelError(Exception):
    """Raised when a request asks for a backend that doesn't exist."""


@dataclass(frozen=True)
class RouteDecision:
    """Which backend should handle a request, why, and what to try if it fails.

    `fallbacks` lists other backends to try, in order, if the chosen one
    keeps failing. It's empty for requests that named a backend directly.
    """

    backend: str
    reason: RouteReason
    fallbacks: tuple[str, ...] = ()


def prompt_length_chars(request: ChatCompletionRequest) -> int:
    """Total characters across all messages, a cheap stand-in for size."""
    return sum(len(message.content) for message in request.messages)


class LengthRouter:
    """Send short prompts to a small backend and long prompts to a large one.

    Clients can skip routing by naming a backend in the request's model
    field. Sending "auto" lets the router decide, and only "auto" requests
    get fallback backends.
    """

    def __init__(
        self,
        small_backend: str,
        large_backend: str,
        max_small_prompt_chars: int,
        available_backends: set[str],
        fallback_backends: Sequence[str] = (),
    ) -> None:
        if max_small_prompt_chars <= 0:
            raise ValueError("max_small_prompt_chars must be positive")

        missing = ({small_backend, large_backend} | set(fallback_backends)) - available_backends
        if missing:
            raise ValueError(f"router refers to unknown backends: {sorted(missing)}")

        if len(set(fallback_backends)) != len(fallback_backends):
            raise ValueError("fallback_backends cannot list the same backend twice")

        self.small_backend = small_backend
        self.large_backend = large_backend
        self.max_small_prompt_chars = max_small_prompt_chars
        self.available_backends = available_backends
        self.fallback_backends = tuple(fallback_backends)

    def route(self, request: ChatCompletionRequest) -> RouteDecision:
        if request.model != AUTO_MODEL:
            if request.model in self.available_backends:
                # The client chose this backend on purpose, so no fallbacks.
                return RouteDecision(backend=request.model, reason="requested")
            raise UnknownModelError(request.model)

        if prompt_length_chars(request) <= self.max_small_prompt_chars:
            backend, reason = self.small_backend, "short_prompt"
        else:
            backend, reason = self.large_backend, "long_prompt"

        return RouteDecision(
            backend=backend,
            reason=reason,
            fallbacks=self._fallbacks_for(backend),
        )

    def _fallbacks_for(self, chosen: str) -> tuple[str, ...]:
        """The fallback list, in order, without the backend already chosen."""
        return tuple(name for name in self.fallback_backends if name != chosen)