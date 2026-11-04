"""InferX HTTP application.

This module creates the FastAPI app and defines its routes.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status

from inferx.backends.base import Backend, BackendError
from inferx.config import Settings, load_gateway_config
from inferx.gateway_config import build_backends, build_router
from inferx.router import LengthRouter, UnknownModelError
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse

# Read the version from the installed package metadata (which comes from
# pyproject.toml), so the version number lives in exactly one place.
APP_VERSION = version("inferx")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the router and backends at startup, close backends at shutdown."""
    gateway_config = load_gateway_config(Settings())

    # Build the router first: it validates the routing rules before any
    # backend opens a connection.
    app.state.router = build_router(gateway_config)
    app.state.backends = build_backends(gateway_config)
    try:
        yield
    finally:
        for backend in app.state.backends.values():
            await backend.aclose()


app = FastAPI(
    title="InferX",
    description=(
        "LLM inference gateway with cost-aware routing, "
        "fault tolerance, and reproducible benchmarks"
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)


def get_router(request: Request) -> LengthRouter:
    """Provide the router created at startup."""
    return request.app.state.router


def get_backends(request: Request) -> dict[str, Backend]:
    """Provide the backends created at startup, keyed by name.

    Endpoints receive backends through this function instead of creating
    them, so tests can swap in different ones.
    """
    return request.app.state.backends


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
    response: Response,
    router: Annotated[LengthRouter, Depends(get_router)],
    backends: Annotated[dict[str, Backend], Depends(get_backends)],
) -> ChatCompletionResponse:
    """Route a chat request to a backend and return its reply."""
    try:
        decision = router.route(request)
    except UnknownModelError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown model '{request.model}'. Use 'auto' or a configured backend name.",
        ) from error

    # Tell the caller which backend handled the request and why.
    routing_headers = {
        "X-InferX-Backend": decision.backend,
        "X-InferX-Route-Reason": decision.reason,
    }
    response.headers.update(routing_headers)

    try:
        return await backends[decision.backend].complete(request)
    except BackendError as error:
        # Don't expose internal backend details to clients. Once we add
        # logging, the full error will be recorded on the server side.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model backend failed to respond.",
            headers=routing_headers,
        ) from error