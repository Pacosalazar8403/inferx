"""Tests for the load generator's statistics and request scheduling."""

import httpx2
import pytest

from inferx.loadtest import RequestResult, percentile, run_load, summarize

URL = "http://inferx.test/v1/chat/completions"
BODY = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}


@pytest.mark.parametrize(
    ("p", "expected"),
    [(50, 50), (90, 90), (99, 99), (100, 100)],
)
def test_percentile_uses_nearest_rank(p: float, expected: float) -> None:
    values = [float(n) for n in range(1, 101)]

    assert percentile(values, p) == expected


def test_percentile_of_one_value_is_that_value() -> None:
    assert percentile([0.25], 99) == 0.25


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1.0], 0)


def test_summary_counts_failures_separately_from_latency() -> None:
    results = [
        RequestResult(status=200, latency_seconds=0.1, error=None, start_lag_seconds=0.0),
        RequestResult(status=200, latency_seconds=0.3, error=None, start_lag_seconds=0.002),
        RequestResult(status=502, latency_seconds=0.01, error=None, start_lag_seconds=0.0),
        RequestResult(status=None, latency_seconds=5.0, error="ConnectError", start_lag_seconds=0.0),
    ]

    summary = summarize(results, target_rate=4, send_seconds=1.0)

    assert summary.requests == 4
    assert summary.sent_rate == 4
    assert summary.success_rate == 0.5
    assert summary.statuses == {"200": 2, "502": 1}
    assert summary.errors == {"ConnectError": 1}
    # Only the two successes count toward latency.
    assert summary.latency_ms["p50"] == 100.0
    assert summary.latency_ms["max"] == 300.0
    assert summary.max_start_lag_ms == 2.0


@pytest.mark.anyio
async def test_sends_the_scheduled_number_of_requests() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={})

    results, _ = await run_load(
        URL, BODY, rate=200, duration_seconds=0.1, transport=httpx2.MockTransport(handler)
    )

    assert len(results) == 20
    assert all(result.status == 200 for result in results)


@pytest.mark.anyio
async def test_records_connection_errors_instead_of_crashing() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    results, _ = await run_load(
        URL, BODY, rate=100, duration_seconds=0.05, transport=httpx2.MockTransport(handler)
    )

    assert len(results) == 5
    assert all(result.status is None for result in results)
    assert all(result.error == "ConnectError" for result in results)


def test_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(run_load(URL, BODY, rate=0, duration_seconds=1))