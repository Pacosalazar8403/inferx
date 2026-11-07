"""Turn saved load test reports into a Markdown table.

    uv run python -m inferx.loadtest_report benchmarks/results/my-run/*.json
"""

import json
import sys
from pathlib import Path
from typing import Any

COLUMNS = (
    "target rps",
    "sent rps",
    "success",
    "p50 ms",
    "p95 ms",
    "p99 ms",
    "max ms",
    "max lag ms",
)


def row(report: dict[str, Any]) -> list[str]:
    """One table row from one saved report."""
    summary = report["summary"]
    latency = summary["latency_ms"]
    latency_cells = [
        f"{latency[key]:g}" if key in latency else "n/a" for key in ("p50", "p95", "p99", "max")
    ]
    return [
        f"{summary['target_rate']:g}",
        f"{summary['sent_rate']:g}",
        f"{summary['success_rate'] * 100:.1f}%",
        *latency_cells,
        f"{summary['max_start_lag_ms']:g}",
    ]


def markdown_table(reports: list[dict[str, Any]]) -> str:
    """A Markdown table with one row per report, ordered by target rate."""
    ordered = sorted(reports, key=lambda report: report["summary"]["target_rate"])
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
        *("| " + " | ".join(row(report)) + " |" for report in ordered),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    paths = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        raise SystemExit("usage: python -m inferx.loadtest_report REPORT.json [REPORT.json ...]")
    reports = [json.loads(path.read_text()) for path in paths]
    print(markdown_table(reports))


if __name__ == "__main__":
    main()