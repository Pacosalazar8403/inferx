"""InferX HTTP application.

This module creates the FastAPI app and defines its routes.
"""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status

from inferx.backends.base import Backend, BackendError
from inferx.config import Settings, load_gateway_config
from inferx.gateway_config import build_backends, build_router
from inferx.observability import configure_logging
from inferx.router import LengthRouter, UnknownModelError
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse

# Read the version from the installed package metadata (which comes from
# pyproject.toml), so the version number lives in exactly one place.
APP_VERSION = version("inferx")

REQUEST_ID_HEADER = "X-Request-ID"

# Accept a caller's request ID only if it's short and uses safe characters,
# so it can't be used to inject fake entries into the logs.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

logger = logging.getLogger(__name__)


def elapsed_ms(start: float) -> float:
    """Milliseconds since `start`, a value from time.perf_counter()."""
    return round((time.perf_counter() - start) * 1000, 2)


def get_or_create_request_id(incoming: str | None) -> str:
    """Reuse a safe incoming request ID, or create a new one."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the router and backends at startup, close backends at shutdown."""
    settings = Settings()
    configure_logging(settings.log_level)
    gateway_config = load_gateway_config(settings)

    # Build the router first: it validates the routing rules before any
    # backend opens a connection.
    app.state.router = build_router(gateway_config)
    app.state.backends = build_backends(gateway_config)
    logger.info("inferx started", extra={"backends": sorted(app.state.backends)})
    try:
        yield
    finally:
        for backend in app.state.backends.values():
            await backend.aclose()
        logger.info("inferx stopped")


app = FastAPI(
    title="InferX",
    description=(
        "LLM inference gateway with cost-aware routing, "
        "fault tolerance, and reproducible benchmarks"
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Give every request an ID and write one log line when it finishes."""
    request_id = get_or_create_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)

    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info(
        "request completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": elapsed_ms(start),
            # Set by the chat endpoint. Other routes leave these empty.
            "backend": getattr(request.state, "backend", None),
            "route_reason": getattr(request.state, "route_reason", None),
            "backend_latency_ms": getattr(request.state, "backend_latency_ms", None),
        },
    )
    return response


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
    chat_request: ChatCompletionRequest,
    http_request: Request,
    response: Response,
    router: Annotated[LengthRouter, Depends(get_router)],
    backends: Annotated[dict[str, Backend], Depends(get_backends)],
) -> ChatCompletionResponse:
    """Route a chat request to a backend and return its reply."""
    try:
        decision = router.route(chat_request)
    except UnknownModelError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown model '{chat_request.model}'. Use 'auto' or a configured backend name.",
        ) from error

    # Shared with the logging middleware, which writes them in its log line.
    http_request.state.backend = decision.backend
    http_request.state.route_reason = decision.reason

    # Tell the caller which backend handled the request and why.
    routing_headers = {
        "X-InferX-Backend": decision.backend,
        "X-InferX-Route-Reason": decision.reason,
    }
    response.headers.update(routing_headers)

    start = time.perf_counter()
    try:
        return await backends[decision.backend].complete(chat_request)
    except BackendError as error:
        # The full error goes to the server's logs. The client only gets a
        # generic message, so internal details never leak.
        logger.warning(
            "backend request failed",
            exc_info=True,
            extra={"request_id": http_request.state.request_id, "backend": decision.backend},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model backend failed to respond.",
            headers=routing_headers,
        ) from error
    finally:
        http_request.state.backend_latency_ms = elapsed_ms(start)