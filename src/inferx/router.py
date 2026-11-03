"""Decide which backend handles each request.

The router only makes decisions. It never calls a backend itself, which
keeps it easy to test and easy to replace with a smarter router later.
"""

from dataclasses import dataclass
from typing import Literal

from inferx.schemas import ChatCompletionRequest

AUTO_MODEL = "auto"

RouteReason = Literal["requested", "short_prompt", "long_prompt"]


class UnknownModelError(Exception):
    """Raised when a request asks for a backend that doesn't exist."""


@dataclass(frozen=True)
class RouteDecision:
    """Which backend should handle a request, and why."""

    backend: str
    reason: RouteReason


def prompt_length_chars(request: ChatCompletionRequest) -> int:
    """Total characters across all messages, a cheap stand-in for size."""
    return sum(len(message.content) for message in request.messages)


class LengthRouter:
    """Send short prompts to a small backend and long prompts to a large one.

    Clients can skip routing by naming a backend in the request's model
    field. Sending "auto" lets the router decide.
    """

    def __init__(
        self,
        small_backend: str,
        large_backend: str,
        max_small_prompt_chars: int,
        available_backends: set[str],
    ) -> None:
        if max_small_prompt_chars <= 0:
            raise ValueError("max_small_prompt_chars must be positive")

        missing = {small_backend, large_backend} - available_backends
        if missing:
            raise ValueError(f"router refers to unknown backends: {sorted(missing)}")

        self.small_backend = small_backend
        self.large_backend = large_backend
        self.max_small_prompt_chars = max_small_prompt_chars
        self.available_backends = available_backends

    def route(self, request: ChatCompletionRequest) -> RouteDecision:
        if request.model != AUTO_MODEL:
            if request.model in self.available_backends:
                return RouteDecision(backend=request.model, reason="requested")
            raise UnknownModelError(request.model)

        if prompt_length_chars(request) <= self.max_small_prompt_chars:
            return RouteDecision(backend=self.small_backend, reason="short_prompt")
        return RouteDecision(backend=self.large_backend, reason="long_prompt")