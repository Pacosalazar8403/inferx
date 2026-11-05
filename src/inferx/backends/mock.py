"""A fake backend for development and testing.

It returns a predictable reply after a configurable delay, and can be told
to fail on purpose, either temporarily (retryable) or permanently. This lets
us test routing, retries, and timeouts without a GPU or a paid API.
"""

import asyncio
import time
import uuid

from inferx.backends.base import Backend, BackendError
from inferx.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)


def approximate_tokens(text: str) -> int:
    """Roughly count tokens as words.

    Real backends report exact token counts. This approximation is only
    good enough for a fake backend.
    """
    return len(text.split())


class MockBackend(Backend):
    """A backend that echoes the last message back to the caller."""

    def __init__(
        self,
        name: str = "mock",
        latency_seconds: float = 0.0,
        fail: bool = False,
        retryable_failures: bool = True,
    ) -> None:
        if latency_seconds < 0:
            raise ValueError("latency_seconds cannot be negative")

        self.name = name
        self.latency_seconds = latency_seconds
        self.fail = fail
        self.retryable_failures = retryable_failures

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        # Simulate the time a real model spends generating. This uses
        # asyncio.sleep, so other requests keep running while we wait.
        await asyncio.sleep(self.latency_seconds)

        if self.fail:
            raise BackendError(
                f"backend '{self.name}' failed on purpose",
                retryable=self.retryable_failures,
            )

        reply = f"Mock reply to: {request.messages[-1].content}"
        prompt_tokens = sum(approximate_tokens(m.content) for m in request.messages)
        completion_tokens = approximate_tokens(reply)

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=self.name,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content=reply),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )