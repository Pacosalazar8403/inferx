#!/usr/bin/env bash
# Runs the load generator against a running InferX at several request rates,
# saves one JSON report per rate, and prints a Markdown table of the results.
#
#   scripts/rate_sweep.sh benchmarks/results/my-run
#   RATES="25 50 100" DURATION=20 scripts/rate_sweep.sh benchmarks/results/my-run

set -euo pipefail

OUTPUT_DIR="${1:?usage: scripts/rate_sweep.sh OUTPUT_DIR}"
RATES="${RATES:-25 50 100 200 400 800}"
DURATION="${DURATION:-20}"
WARMUP="${WARMUP:-5}"

mkdir -p "$OUTPUT_DIR"

for rate in $RATES; do
  echo "Running $rate requests per second..." >&2
  uv run python -m inferx.loadtest \
    --rate "$rate" --duration "$DURATION" --warmup "$WARMUP" \
    --output "$OUTPUT_DIR/rate-$rate.json" > /dev/null
done

uv run python -m inferx.loadtest_report "$OUTPUT_DIR"/rate-*.json