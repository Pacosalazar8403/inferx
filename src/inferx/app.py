"""InferX HTTP application.

This module creates the FastAPI app and defines its routes.
"""

from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from inferx.backends.base import Backend, BackendError
from inferx.backends.mock import MockBackend
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse

# Read the version from the installed package metadata (which comes from
# pyproject.toml), so the version number lives in exactly one place.
APP_VERSION = version("inferx")

app = FastAPI(
    title="InferX",
    description=(
        "LLM inference gateway with cost-aware routing, "
        "fault tolerance, and reproducible benchmarks"
    ),
    version=APP_VERSION,
)

# One shared backend for the whole app. Later, the router will choose
# between several backends; for now there is only the mock.
_default_backend = MockBackend()


def get_backend() -> Backend:
    """Provide the backend that handles chat requests.

    Endpoints receive the backend through this function instead of
    creating it themselves, so tests can swap in a different one.
    """
    return _default_backend


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the service is running.

    Load balancers, Docker, and monitoring tools call this endpoint
    to check whether the service is alive.
    """
    return {"status": "ok", "version": APP_VERSION}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    backend: Annotated[Backend, Depends(get_backend)],
) -> ChatCompletionResponse:
    """Send a chat request to a backend and return its reply."""
    try:
        return await backend.complete(request)
    except BackendError as error:
        # Don't expose internal backend details to clients. Once we add
        # logging, the full error will be recorded on the server side.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model backend failed to respond.",
        ) from error