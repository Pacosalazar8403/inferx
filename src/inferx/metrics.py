"""Prometheus metrics for InferX.

Metrics answer questions about the whole system over time, like request
rate and latency percentiles, while logs answer questions about single
requests. Prometheus collects these by calling GET /metrics regularly.

Each Metrics object has its own registry, so every app (and every test)
starts from zero instead of sharing global counters.
"""

from collections.abc import Iterator, Mapping
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    disable_created_metrics,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily

from inferx.circuit_breaker import CircuitState

# Don't emit an extra "_created" timestamp series for every counter and
# histogram. Prometheus doesn't need them, and they double the output.
disable_created_metrics()

# Seconds. Requests range from milliseconds (mock backends) to about a minute
# (a model's cold start was observed at about 25 seconds), so the buckets span
# that whole range. The library's default buckets stop at 10 seconds.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

# Label value for requests that matched no route. Using the raw path instead
# would let anyone create unlimited time series by requesting random URLs.
UNMATCHED_ROUTE = "unmatched"

CONTENT_TYPE = CONTENT_TYPE_LATEST


class CircuitBreakerCollector:
    """Reports each backend's circuit state whenever Prometheus scrapes.

    For every backend there's one series per state, set to 1 for the current
    state and 0 for the others. A breaker only moves from open to half_open
    when a request arrives after its cooldown, so this is the last known state.
    """

    def __init__(self, backends: Mapping[str, Any]) -> None:
        self._backends = backends

    def collect(self) -> Iterator[GaugeMetricFamily]:
        family = GaugeMetricFamily(
            "inferx_circuit_breaker_state",
            "1 for each backend's current circuit breaker state, 0 for the others.",
            labels=["backend", "state"],
        )
        for name in sorted(self._backends):
            breaker = getattr(self._backends[name], "breaker", None)
            if breaker is None:
                continue
            for state in CircuitState:
                family.add_metric([name, state.value], 1.0 if breaker.state is state else 0.0)
        yield family


class Metrics:
    """All of InferX's metrics, registered in one registry."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()

        self.http_requests = Counter(
            "inferx_http_requests",
            "HTTP requests handled by InferX.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.http_request_duration = Histogram(
            "inferx_http_request_duration_seconds",
            "Time spent handling HTTP requests, in seconds.",
            ["method", "route"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.backend_attempts = Counter(
            "inferx_backend_attempts",
            "Requests sent to each backend (after its retries), by outcome.",
            ["backend", "outcome"],
            registry=self.registry,
        )
        self.backend_retries = Counter(
            "inferx_backend_retries",
            "Retries of transient backend failures.",
            ["backend"],
            registry=self.registry,
        )
        self.fallbacks = Counter(
            "inferx_fallbacks",
            "Requests moved from one backend to another after transient failures.",
            ["from_backend", "to_backend"],
            registry=self.registry,
        )
        self.deadlines_exceeded = Counter(
            "inferx_deadline_exceeded",
            "Requests that ran out of their total time budget.",
            ["backend"],
            registry=self.registry,
        )

    def watch_circuit_breakers(self, backends: Mapping[str, Any]) -> None:
        """Report these backends' circuit states on every scrape."""
        self.registry.register(CircuitBreakerCollector(backends))

    def render(self) -> bytes:
        """The current values in Prometheus's text format."""
        return generate_latest(self.registry)