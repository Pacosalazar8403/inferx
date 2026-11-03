"""InferX HTTP application.

This module creates the FastAPI app and defines its routes.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status

from inferx.backends.base import Backend, BackendError
from inferx.config import Settings, build_backend
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse

# Read the version from the installed package metadata (which comes from
# pyproject.toml), so the version number lives in exactly one place.
APP_VERSION = version("inferx")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the backend at startup and close it at shutdown."""
    settings = Settings()
    app.state.backend = build_backend(settings)
    try:
        yield
    finally:
        await app.state.backend.aclose()


app = FastAPI(
    title="InferX",
    description=(
        "LLM inference gateway with cost-aware routing, "
        "fault tolerance, and reproducible benchmarks"
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)


def get_backend(request: Request) -> Backend:
    """Provide the backend created at startup.

    Endpoints receive the backend through this function instead of
    creating it themselves, so tests can swap in a different one.
    """
    return request.app.state.backend


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