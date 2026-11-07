# InferX benchmarks

These benchmarks measure InferX's own overhead and capacity: how its latency changes as load increases, and where it breaks down. The backends are mock backends that answer instantly, so the results describe the gateway (routing, validation, middleware, metrics, logging), not model performance.

All raw results are in [`results/`](results/), one JSON report per run, each including the settings it ran with.

## Method

The load generator is [`src/inferx/loadtest.py`](../src/inferx/loadtest.py).

- **Open-loop workload.** Requests are sent on a fixed schedule (for example, one every 4 ms at 250 requests per second), whether or not earlier requests have finished. A closed-loop generator, where each worker waits for a response before sending the next request, sends fewer requests exactly when the server slows down and under-reports latency (coordinated omission).
- **Latency is measured from each request's scheduled send time**, so any queueing in InferX, the network, the connection pool, or the generator itself counts.
- **Generator lag** is reported for every run: how far behind schedule the generator started requests. When it grows large, the generator itself is a bottleneck, and those results say less about InferX.
- **Percentiles are nearest-rank** (always a latency that actually occurred) and include only successful responses. Failures are reported separately.
- **Each run** is 5 seconds of warmup (discarded) followed by 20 measured seconds.
- **InferX** runs as a single Uvicorn worker with the built-in mock backends and `--no-access-log`.

## Setup

- Laptop with a 12th Gen Intel Core i7-12650H (16 logical CPUs visible to Linux)
- Ubuntu 22.04 on WSL2, Python 3.12
- InferX at commit `cec505a`
- The generator and InferX on the same machine, talking over `127.0.0.1`

## Reproducing

Start InferX, then run the sweep from another terminal:

```bash
INFERX_LOG_LEVEL=WARNING uv run uvicorn inferx.app:app --no-access-log
scripts/rate_sweep.sh benchmarks/results/my-run
```

To pin InferX and the generator to separate CPUs, as in runs 2 and 3:

```bash
INFERX_LOG_LEVEL=WARNING taskset -c 2,3 uv run uvicorn inferx.app:app --no-access-log
RATES="100 200 220 240 260 280 300 320" taskset -c 8,9 scripts/rate_sweep.sh benchmarks/results/my-run
```

## Results

### Run 1: rate sweep, unpinned

`results/2026-11-06-rate-sweep`. Logging at `WARNING`. InferX and the generator could run on any CPU.

| target rps | sent rps | success | p50 ms | p95 ms | p99 ms | max ms | max lag ms |
|---|---|---|---|---|---|---|---|
| 25 | 25.05 | 100.0% | 4.95 | 6.55 | 7.07 | 7.71 | 3.27 |
| 50 | 50.05 | 100.0% | 4.45 | 5.85 | 6.33 | 7.05 | 2.63 |
| 100 | 100.05 | 100.0% | 4.52 | 6.18 | 7.18 | 48 | 3.1 |
| 200 | 200.04 | 100.0% | 7.75 | 24.17 | 45.21 | 99.01 | 33.26 |
| 400 | 393.47 | 100.0% | 5155.26 | 9610.72 | 9744.6 | 9931.12 | 516.93 |
| 800 | 788.36 | 99.4% | 39177.1 | 55305.9 | 56414.1 | 56749.6 | 8368.49 |

The 800 row is not a valid measurement of InferX: the generator fell more than 8 seconds behind its own schedule, so it was a bottleneck itself.

### Run 2: rate sweep, pinned CPUs

`results/2026-11-06-pinned-sweep`. Logging at `WARNING`. InferX on CPUs 2 and 3, the generator on CPUs 8 and 9 (each pair shares one core, according to the CPU layout WSL reports).

| target rps | sent rps | success | p50 ms | p95 ms | p99 ms | max ms | max lag ms |
|---|---|---|---|---|---|---|---|
| 100 | 100.05 | 100.0% | 4.49 | 5.98 | 6.68 | 7.85 | 2.77 |
| 200 | 200.04 | 100.0% | 4.41 | 8.09 | 15.32 | 76.25 | 9.44 |
| 220 | 220.03 | 100.0% | 4.84 | 7.57 | 27.22 | 76.06 | 23.2 |
| 240 | 240.04 | 100.0% | 5.2 | 7.72 | 28.47 | 66.39 | 12.79 |
| 260 | 259.94 | 100.0% | 7 | 31.47 | 92.1 | 146.32 | 22.84 |
| 280 | 279.96 | 100.0% | 119.28 | 807.06 | 863.17 | 1308.2 | 296.88 |
| 300 | 295.76 | 100.0% | 259.01 | 636.69 | 794.41 | 1037.34 | 327.32 |
| 320 | 319.96 | 100.0% | 2683.65 | 4195.16 | 4305.68 | 4426.34 | 279.41 |

### Run 3: rate sweep, pinned CPUs, `INFO` logging

`results/2026-11-06-pinned-sweep-info-logging`. Same as run 2, but every request writes a JSON log line (written to a file, not a terminal).

| target rps | sent rps | success | p50 ms | p95 ms | p99 ms | max ms | max lag ms |
|---|---|---|---|---|---|---|---|
| 100 | 100.04 | 100.0% | 4.02 | 5.31 | 6.05 | 7.32 | 2.31 |
| 200 | 200.04 | 100.0% | 4.87 | 7.88 | 15.29 | 53.43 | 3.48 |
| 220 | 220.05 | 100.0% | 3.52 | 5 | 6.44 | 28.13 | 2.05 |
| 240 | 240.05 | 100.0% | 3.82 | 6.18 | 8.79 | 31.76 | 16.59 |
| 260 | 260.05 | 100.0% | 4.2 | 23.94 | 59.41 | 79.23 | 19.71 |
| 280 | 280.03 | 100.0% | 1387.76 | 2248.13 | 2305.3 | 2349.2 | 137.44 |

The log file had 32,510 lines (12 MB) for 32,500 requests, including warmup: exactly one line per request, plus startup and shutdown lines.

## Findings

1. **InferX's capacity is about 270 requests per second on one process.** In run 2, the median stays near 5 ms up to 260 requests per second, then a queue builds from 280 on. A capacity estimate from run 1's saturated rows (about 260) predicted this before run 2 was measured. Queueing estimates from different rows of the same configuration range from about 250 to 290.
2. **The tail warns first.** Between 200 and 240 requests per second in run 2, p50 barely moves (4.4 to 5.2 ms) while p99 roughly quadruples (6.7 to 28 ms). p99 rises well before the median does.
3. **Separating the generator from InferX cleaned up the tail.** At 200 requests per second, p99 dropped from 45.2 ms (run 1) to 15.3 ms (run 2), and generator lag from 33 to 9 ms. Capacity changed little, since it's bounded by one Python process either way.
4. **The CPU cost of logging is too small to measure reliably with one run per configuration.** At 280 requests per second, `INFO` logging made the median 11 times worse, which suggests it costs roughly 10% of capacity. But between 220 and 260, the `INFO` run had *better* tail latency, which means run-to-run variation is larger than the effect below capacity. Several repeated runs per configuration would be needed to put a confident number on it.
5. **The larger cost of logging is volume.** At about 370 bytes per request, logging every request at full capacity would produce roughly 8.6 GB of logs per day from one instance. That storage and ingestion cost is a stronger argument for sampling or for logging successes at `DEBUG` than the CPU cost.
6. **The gateway is unlikely to be the bottleneck with real models.** A local GPU serves a handful of model requests per second, roughly 100 times fewer than InferX's measured capacity.

## Limitations

- **One run per configuration.** Differences smaller than the run-to-run variation (such as the logging cost below capacity) can't be separated from noise.
- **The generator and InferX share one machine.** Pinning reduces interference but doesn't remove it: they still share memory, caches, and the WSL virtual machine.
- **WSL reports a virtual CPU layout.** Linux sees 8 cores with 2 threads each, while the physical chip has 6 performance cores and 4 efficiency cores, so "one core each" is what Linux reports, not necessarily the hardware.
- **Mock backends answer instantly**, so these results describe gateway overhead, not end-to-end latency with real models.
- **One Uvicorn worker.** Several workers would raise capacity, but each would have its own metrics registry and circuit breakers, which InferX doesn't yet coordinate across processes.
- **Localhost only.** Real network latency between clients, InferX, and backends isn't included.