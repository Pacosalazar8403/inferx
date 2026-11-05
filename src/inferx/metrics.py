"""Prometheus metrics for InferX.

Metrics answer questions about the whole system over time, like request
rate and latency percentiles, while logs answer questions about single
requests. Prometheus collects these by calling GET /metrics regularly.

Each Metrics object has its own registry, so every app (and every test)
starts from zero instead of sharing global counters.
"""

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

# Seconds. Requests range from milliseconds (mock backends) to about a minute
# (a model's cold start was observed at about 25 seconds), so the buckets span
# that whole range. The library's default buckets stop at 10 seconds.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

# Label value for requests that matched no route. Using the raw path instead
# would let anyone create unlimited time series by requesting random URLs.
UNMATCHED_ROUTE = "unmatched"


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

    def render(self) -> bytes:
        """The current values in Prometheus's text format."""
        return generate_latest(self.registry)


CONTENT_TYPE = CONTENT_TYPE_LATEST