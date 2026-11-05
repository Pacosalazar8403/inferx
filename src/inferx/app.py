"""InferX HTTP application.

This module creates the FastAPI app and defines its routes.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from starlette.routing import Match

from inferx.backends.base import Backend, BackendError
from inferx.backends.circuit_breaking import CircuitOpenError
from inferx.config import Settings, load_gateway_config
from inferx.gateway_config import build_backends, build_router
from inferx.metrics import CONTENT_TYPE, UNMATCHED_ROUTE, Metrics
from inferx.observability import configure_logging, reset_request_id, set_request_id
from inferx.router import LengthRouter, UnknownModelError
from inferx.schemas import ChatCompletionRequest, ChatCompletionResponse

# Read the version from the installed package metadata (which comes from
# pyproject.toml), so the version number lives in exactly one place.
APP_VERSION = version("inferx")

REQUEST_ID_HEADER = "X-Request-ID"

# Accept a caller's request ID only if it's short and uses safe characters,
# so it can't be used to inject fake entries into the logs.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

# Called constantly by Docker and Prometheus. Logged at DEBUG so they don't
# drown out real traffic in the logs. They're still counted in the metrics.
_PROBE_PATHS = frozenset({"/health", "/metrics"})

logger = logging.getLogger(__name__)


def elapsed_ms(start: float) -> float:
    """Milliseconds since `start`, a value from time.perf_counter()."""
    return round((time.perf_counter() - start) * 1000, 2)


def get_or_create_request_id(incoming: str | None) -> str:
    """Reuse a safe incoming request ID, or create a new one."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def route_template(request: Request) -> str:
    """The route's path template, like "/v1/chat/completions".

    Metrics are labeled with this instead of the raw URL, so requests to
    random paths all count as one "unmatched" series.
    """
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match is Match.FULL:
            return route.path
    return UNMATCHED_ROUTE


def failure_outcome(error: BackendError) -> str:
    """A bounded label value describing why a backend attempt failed."""
    if isinstance(error, CircuitOpenError):
        return "circuit_open"
    return "retryable_failure" if error.retryable else "permanent_failure"


def routing_headers(backend: str, reason: str, fallback_from: str | None) -> dict[str, str]:
    """Headers telling the caller which backend answered, why, and if it was a fallback."""
    headers = {
        "X-InferX-Backend": backend,
        "X-InferX-Route-Reason": reason,
    }
    if fallback_from is not None:
        headers["X-InferX-Fallback-From"] = fallback_from
    return headers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the router and backends at startup, close backends at shutdown."""
    settings = Settings()
    configure_logging(settings.log_level)
    gateway_config = load_gateway_config(settings)

    # Build the router first: it validates the routing rules before any
    # backend opens a connection.
    app.state.router = build_router(gateway_config)
    app.state.metrics = Metrics()
    app.state.backends = build_backends(gateway_config, metrics=app.state.metrics)
    app.state.metrics.watch_circuit_breakers(app.state.backends)
    app.state.request_timeout_seconds = gateway_config.limits.request_timeout_seconds
    logger.info(
        "inferx started",
        extra={
            "backends": sorted(app.state.backends),
            "request_timeout_seconds": app.state.request_timeout_seconds,
        },
    )
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
    """Give every request an ID, record its metrics, and log it when it finishes."""
    request_id = get_or_create_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id

    # Every log line written while handling this request gets this ID.
    token = set_request_id(request_id)
    try:
        start = time.perf_counter()
        response = await call_next(request)
        duration_seconds = time.perf_counter() - start

        response.headers[REQUEST_ID_HEADER] = request_id

        route = route_template(request)
        metrics: Metrics = request.app.state.metrics
        metrics.http_requests.labels(
            method=request.method,
            route=route,
            status=str(response.status_code),
        ).inc()
        metrics.http_request_duration.labels(method=request.method, route=route).observe(
            duration_seconds
        )

        level = logging.DEBUG if request.url.path in _PROBE_PATHS else logging.INFO
        logger.log(
            level,
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round(duration_seconds * 1000, 2),
                # Set by the chat endpoint. Other routes leave these empty.
                "backend": getattr(request.state, "backend", None),
                "route_reason": getattr(request.state, "route_reason", None),
                "fallback_from": getattr(request.state, "fallback_from", None),
                "backend_latency_ms": getattr(request.state, "backend_latency_ms", None),
            },
        )
        return response
    finally:
        reset_request_id(token)


def get_router(request: Request) -> LengthRouter:
    """Provide the router created at startup."""
    return request.app.state.router


def get_backends(request: Request) -> dict[str, Backend]:
    """Provide the backends created at startup, keyed by name.

    Endpoints receive backends through this function instead of creating
    them, so tests can swap in different ones.
    """
    return request.app.state.backends


def get_request_timeout(request: Request) -> float:
    """Provide the total time budget, in seconds, for one request."""
    return request.app.state.request_timeout_seconds


def get_metrics(request: Request) -> Metrics:
    """Provide the metrics created at startup."""
    return request.app.state.metrics


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the service is running.

    Load balancers, Docker, and monitoring tools call this endpoint
    to check whether the service is alive.
    """
    return {"status": "ok", "version": APP_VERSION}


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint(request: Request) -> Response:
    """Current metrics in Prometheus's text format, for Prometheus to scrape."""
    metrics: Metrics = request.app.state.metrics
    return Response(content=metrics.render(), media_type=CONTENT_TYPE)


@app.post("/v1/chat/completions")
async def chat_completions(
    chat_request: ChatCompletionRequest,
    http_request: Request,
    response: Response,
    router: Annotated[LengthRouter, Depends(get_router)],
    backends: Annotated[dict[str, Backend], Depends(get_backends)],
    request_timeout_seconds: Annotated[float, Depends(get_request_timeout)],
    metrics: Annotated[Metrics, Depends(get_metrics)],
) -> ChatCompletionResponse:
    """Route a chat request to a backend, falling back if it keeps failing.

    Everything (retries, backoff waits, and fallbacks) must finish within
    the request's time budget, or the request ends with a 504.
    """
    try:
        decision = router.route(chat_request)
    except UnknownModelError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown model '{chat_request.model}'. Use 'auto' or a configured backend name.",
        ) from error

    http_request.state.route_reason = decision.reason
    http_request.state.backend = decision.backend
    http_request.state.fallback_from = None

    # The routed backend first, then any fallbacks, in order.
    candidates = [decision.backend, *decision.fallbacks]

    start = time.perf_counter()
    try:
        async with asyncio.timeout(request_timeout_seconds):
            for index, backend_name in enumerate(candidates):
                fallback_from = decision.backend if index > 0 else None

                # Shared with the logging middleware, which writes them in its log line.
                http_request.state.backend = backend_name
                http_request.state.fallback_from = fallback_from
                headers = routing_headers(backend_name, decision.reason, fallback_from)

                try:
                    result = await backends[backend_name].complete(chat_request)
                except BackendError as error:
                    metrics.backend_attempts.labels(
                        backend=backend_name, outcome=failure_outcome(error)
                    ).inc()
                    has_next_candidate = index + 1 < len(candidates)

                    # Only fall back when the backend's health is the problem.
                    # A permanent failure would likely repeat, and silently moving
                    # traffic elsewhere could hide a misconfiguration.
                    if error.retryable and has_next_candidate:
                        next_backend = candidates[index + 1]
                        metrics.fallbacks.labels(
                            from_backend=backend_name, to_backend=next_backend
                        ).inc()
                        logger.warning(
                            "falling back to another backend",
                            exc_info=True,
                            extra={
                                "backend": backend_name,
                                "fallback_to": next_backend,
                                "backend_status_code": error.status_code,
                            },
                        )
                        continue

                    # The full error goes to the server's logs. The client only gets
                    # a generic message, so internal details never leak.
                    logger.warning(
                        "backend request failed",
                        exc_info=True,
                        extra={
                            "backend": backend_name,
                            "retryable": error.retryable,
                            "backend_status_code": error.status_code,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="The model backend failed to respond.",
                        headers=headers,
                    ) from error

                metrics.backend_attempts.labels(backend=backend_name, outcome="success").inc()
                response.headers.update(headers)
                return result

            # The loop always returns or raises, because there is always at least
            # one candidate. This line only exists to make that explicit.
            raise AssertionError("no backend candidates")
    except TimeoutError as error:
        # The budget ran out. asyncio.timeout already cancelled whatever was
        # in progress (an HTTP call, a backoff wait), all the way down.
        metrics.deadlines_exceeded.labels(backend=http_request.state.backend).inc()
        logger.warning(
            "request deadline exceeded",
            extra={
                "backend": http_request.state.backend,
                "request_timeout_seconds": request_timeout_seconds,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The request took too long to complete.",
            headers=routing_headers(
                http_request.state.backend,
                decision.reason,
                http_request.state.fallback_from,
            ),
        ) from error
    finally:
        http_request.state.backend_latency_ms = elapsed_ms(start)