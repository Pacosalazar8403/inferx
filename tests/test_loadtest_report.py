"""Tests for turning load test reports into a Markdown table."""

from typing import Any

from inferx.loadtest_report import markdown_table


def report(rate: float, latency_ms: dict[str, float], success_rate: float = 1.0) -> dict[str, Any]:
    return {
        "summary": {
            "target_rate": rate,
            "sent_rate": rate,
            "success_rate": success_rate,
            "latency_ms": latency_ms,
            "max_start_lag_ms": 1.5,
        }
    }


LATENCY = {"p50": 5.0, "p95": 8.0, "p99": 9.0, "max": 12.0}


def test_rows_are_ordered_by_rate_not_by_input_order() -> None:
    table = markdown_table([report(100, LATENCY), report(25, LATENCY)])

    rows = table.splitlines()[2:]
    assert rows[0].startswith("| 25 |")
    assert rows[1].startswith("| 100 |")


def test_run_without_successes_shows_n_a() -> None:
    table = markdown_table([report(800, {}, success_rate=0.0)])

    assert "| 0.0% | n/a | n/a | n/a | n/a |" in table