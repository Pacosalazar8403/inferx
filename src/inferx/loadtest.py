"""A small open-loop load generator for InferX.

Sends requests at a fixed rate (an "open" workload), measures each request's
latency from when it was scheduled, and reports throughput and latency
percentiles.

    uv run python -m inferx.loadtest --rate 50 --duration 30

Why open-loop: a "closed" load generator, where each worker waits for a
response before sending its next request, slows down whenever the server
slows down. It quietly sends fewer requests exactly when things get bad,
and under-reports latency. This is called coordinated omission. Here,
requests go out on schedule no matter how the server is doing, and latency
is measured from the scheduled send time, so any queueing (in the server,
the network, or this generator itself) shows up in the results.
"""

import argparse
import asyncio
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx2

PERCENTILES = (("p50", 50.0), ("p90", 90.0), ("p95", 95.0), ("p99", 99.0), ("max", 100.0))


@dataclass(frozen=True)
class RequestResult:
    """What happened to one request."""

    status: int | None
    latency_seconds: float
    error: str | None
    start_lag_seconds: float


@dataclass(frozen=True)
class Summary:
    """The results of one load test run."""

    target_rate: float
    requests: int
    sent_rate: float
    success_rate: float
    statuses: dict[str, int]
    errors: dict[str, int]
    latency_ms: dict[str, float]
    max_start_lag_ms: float


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile of already sorted values, for p in (0, 100].

    Always returns a value that actually occurred, never an interpolation.
    """
    if not sorted_values:
        raise ValueError("cannot take a percentile of no values")
    if not 0 < p <= 100:
        raise ValueError("p must be greater than 0 and at most 100")
    rank = math.ceil(p / 100 * len(sorted_values))
    return sorted_values[rank - 1]


def summarize(
    results: list[RequestResult],
    target_rate: float,
    send_seconds: float,
) -> Summary:
    """Turn raw results into throughput, error counts, and latency percentiles.

    Latency percentiles only include successful requests, because a fast
    error is not a fast response. Failures are counted separately.
    """
    statuses = Counter(str(r.status) for r in results if r.status is not None)
    errors = Counter(r.error for r in results if r.error is not None)
    successes = sorted(
        r.latency_seconds for r in results if r.status is not None and r.status < 400
    )

    latency_ms = (
        {name: round(percentile(successes, p) * 1000, 2) for name, p in PERCENTILES}
        if successes
        else {}
    )
    max_lag = max((r.start_lag_seconds for r in results), default=0.0)

    return Summary(
        target_rate=target_rate,
        requests=len(results),
        sent_rate=round(len(results) / send_seconds, 2) if send_seconds > 0 else 0.0,
        success_rate=round(len(successes) / len(results), 4) if results else 0.0,
        statuses=dict(sorted(statuses.items())),
        errors=dict(sorted(errors.items())),
        latency_ms=latency_ms,
        max_start_lag_ms=round(max_lag * 1000, 2),
    )


async def send_one(
    client: httpx2.AsyncClient,
    url: str,
    body: dict[str, Any],
    scheduled_at: float,
) -> RequestResult:
    """Send one request and measure its latency from its scheduled time."""
    # How late this request started compared to its schedule. Large values
    # mean the load generator itself is falling behind.
    start_lag = max(0.0, time.perf_counter() - scheduled_at)
    try:
        response = await client.post(url, json=body)
        status, error = response.status_code, None
    except httpx2.HTTPError as exc:
        status, error = None, type(exc).__name__
    return RequestResult(
        status=status,
        latency_seconds=time.perf_counter() - scheduled_at,
        error=error,
        start_lag_seconds=start_lag,
    )


async def run_load(
    url: str,
    body: dict[str, Any],
    rate: float,
    duration_seconds: float,
    timeout_seconds: float = 60.0,
    max_connections: int = 200,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> tuple[list[RequestResult], float]:
    """Send requests at `rate` per second for `duration_seconds`.

    Returns every request's result and how long the sending phase took.
    """
    if rate <= 0 or duration_seconds <= 0:
        raise ValueError("rate and duration_seconds must be positive")

    total = round(rate * duration_seconds)
    limits = httpx2.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)

    async with httpx2.AsyncClient(timeout=timeout_seconds, limits=limits, transport=transport) as client:
        start = time.perf_counter()
        tasks = []
        for index in range(total):
            scheduled_at = start + index / rate
            delay = scheduled_at - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            # Start the request without waiting for it: this is what makes
            # the workload open instead of closed.
            tasks.append(asyncio.create_task(send_one(client, url, body, scheduled_at)))
        send_seconds = time.perf_counter() - start
        results = await asyncio.gather(*tasks)

    return list(results), send_seconds


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open-loop load generator for InferX.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="InferX base URL")
    parser.add_argument("--rate", type=float, default=20.0, help="requests per second")
    parser.add_argument("--duration", type=float, default=30.0, help="measured seconds")
    parser.add_argument("--warmup", type=float, default=5.0, help="discarded seconds first")
    parser.add_argument("--model", default="auto", help="model field of each request")
    parser.add_argument("--content", default="hi", help="user message of each request")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout")
    parser.add_argument("--max-connections", type=int, default=200)
    parser.add_argument("--output", type=Path, help="also save the results as JSON here")
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    url = f"{args.url.rstrip('/')}/v1/chat/completions"
    body = {"model": args.model, "messages": [{"role": "user", "content": args.content}]}

    if args.warmup > 0:
        await run_load(url, body, args.rate, args.warmup, args.timeout, args.max_connections)

    results, send_seconds = await run_load(
        url, body, args.rate, args.duration, args.timeout, args.max_connections
    )
    summary = summarize(results, args.rate, send_seconds)

    # Save the settings next to the results, so every number can be reproduced.
    settings = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    return {"settings": settings, "summary": asdict(summary)}


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = asyncio.run(main_async(args))
    text = json.dumps(report, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()