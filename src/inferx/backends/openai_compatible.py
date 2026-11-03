"""A backend for any server that speaks the OpenAI Chat Completions API.

Ollama, vLLM, and most hosted model APIs expose this format, so one class
covers all of them. Only the URL, model name, and API key change.
"""

import httpx2

from inferx.backends.base import Backend, BackendError
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse


class OpenAICompatibleBackend(Backend):
    """Sends chat requests to an OpenAI-compatible server over HTTP."""

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self.name = name
        self.model = model

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        # One client for the backend's whole lifetime, so connections to the
        # model server are reused instead of reopened for every request.
        self._client = httpx2.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        # Send the client's request, but with this backend's real model name.
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self.model

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx2.HTTPError as error:
            raise BackendError(f"backend '{self.name}' request failed: {error}") from error

        try:
            return ChatCompletionResponse.model_validate(response.json())
        except ValueError as error:
            raise BackendError(
                f"backend '{self.name}' returned an invalid response"
            ) from error

    async def aclose(self) -> None:
        """Close the connection pool. Call this when shutting down."""
        await self._client.aclose()