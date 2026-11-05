# InferX

[![CI](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml/badge.svg)](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml)

An LLM inference gateway with cost-aware routing, fault tolerance, and reproducible benchmarks.

> **Status:** early development. Features listed under *Planned* are not built yet.

## What it does

InferX sits between client applications and multiple language model backends. Each request is routed to the cheapest backend that can handle it, while the gateway handles failures, enforces rate limits, and records cost and latency for every request.

### Current features

- OpenAI-compatible `POST /v1/chat/completions` endpoint (subset of the format)
- Multiple backends at once, described in a TOML config file
- Length-based router: with `"model": "auto"`, short prompts go to a small backend and long prompts go to a large one; clients can also name a backend directly
- Retries with exponential backoff and full jitter for transient failures (timeouts, connection errors, `408`, `429`, `5xx`); permanent failures (other `4xx`, malformed responses) are never retried
- Fallback to other backends, in a configured order, when the routed backend keeps failing with transient errors (only for `"auto"` requests)
- Circuit breakers per backend: after repeated failures, a backend is skipped instantly for a cooldown period, then tested with a single probe request before traffic returns
- A total time budget per request across retries, backoff waits, and fallbacks; when it runs out, in-progress work is cancelled and the client gets a `504`
- Prometheus metrics at `/metrics`: request rate and latency histograms, backend outcomes, retries, fallbacks, deadlines, and current circuit breaker states
- Docker Compose setup that runs InferX and Prometheus together, with a traffic script to try it out
- `X-InferX-Backend`, `X-InferX-Route-Reason`, and `X-InferX-Fallback-From` response headers show which backend answered, why, and whether it was a fallback, including on failures
- Structured JSON logs with one line per request: request ID, status, route decision, fallback, total latency, and backend latency
- Request IDs on every log line, including retries, fallbacks, circuit breaker changes, and deadlines, generated per request or reused from a safe incoming `X-Request-ID` header, and returned to the caller
- OpenAI-compatible HTTP backend that works with Ollama, vLLM, and hosted model APIs
- Mock backend with simulated latency and forced failures (retryable or permanent), used for tests and CI
- Strict config validation at startup: typos, unknown backend types, duplicate names, invalid retry, fallback, circuit breaker, or time limit settings, backend timeouts longer than the request budget, and missing API key variables are rejected before the server accepts traffic
- Clear errors: `422` for invalid requests, `404` for unknown models, `502` when backends fail, `504` when the time budget runs out (full details go to the server logs, not to the client)
- Docker image: multi-stage build with locked dependencies, runs as a non-root user, and has a built-in health check
- `/health` endpoint and auto-generated OpenAPI docs
- Automated tests with pytest, plus Docker, Compose, and Prometheus config checks, run in CI on every pull request

### Planned

- Ollama in its own container in the Compose setup
- Grafana dashboards for the metrics
- Streaming responses for the chat endpoint
- Routing by cost budget and latency target
- Smarter routing, evaluated against the length-based router as a baseline
- Per-key rate limiting and response caching (Redis)
- Usage and cost tracking (PostgreSQL)
- Reproducible load tests and published benchmark results

## Quickstart

Requirements: [uv](https://docs.astral.sh/uv/), which installs the correct Python version automatically.

```bash
git clone https://github.com/Pacosalazar8403/inferx.git
cd inferx
uv sync
uv run uvicorn inferx.app:app --reload --no-access-log
```

Without a config file, InferX starts with two mock backends (`mock-small` and `mock-large`). In another terminal:

```bash
curl -s -i http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hello InferX"}]}'
```

The `x-inferx-backend`, `x-inferx-route-reason`, and `x-request-id` headers show which backend handled the request, why, and the ID to search for in the logs. Interactive API docs are available at http://127.0.0.1:8000/docs, and metrics at http://127.0.0.1:8000/metrics.

### Using real models with Ollama

Install [Ollama](https://ollama.com), download two sizes of the same model family, and start InferX with the example config:

```bash
ollama pull llama3.2:1b
ollama pull llama3.2:3b
INFERX_CONFIG_PATH=config/ollama.toml uv run uvicorn inferx.app:app --reload --no-access-log
```

Short prompts now go to `llama3.2:1b` and longer prompts to `llama3.2:3b`. If one model keeps failing, requests fall back to the other.

## Monitoring with Prometheus

[`compose.yaml`](compose.yaml) runs InferX and Prometheus together. InferX uses [`config/compose-demo.toml`](config/compose-demo.toml): a fast `small` mock backend, a slower `large` one, and a `broken` one that always fails and is only used when a request names it.

```bash
docker compose up --build -d
docker compose ps
```

- InferX: http://127.0.0.1:8000
- Prometheus: http://127.0.0.1:9090 (scrape status at http://127.0.0.1:9090/targets)

Both are published only to your own machine. The services share a private Compose network, so Prometheus reaches InferX by its service name, `inferx:8000`. Prometheus starts only after InferX passes its health check, and its data is kept in the `prometheus-data` volume, so history survives restarts.

Send a mix of traffic (6 short prompts, 3 long prompts, and 1 request to `broken` out of every 10):

```bash
scripts/demo_traffic.sh
REQUESTS=500 scripts/demo_traffic.sh
```

Then try the example queries from the [Metrics](#metrics) section at http://127.0.0.1:9090/query.

Stop everything with `docker compose down`. Add `-v` to also delete the Prometheus data volume.

### Observed in the Compose demo

One run of `scripts/demo_traffic.sh` (200 requests) returned 180 `200` responses and 20 `502` responses. Querying `sum by (backend, outcome) (inferx_backend_attempts_total)` afterward showed:

| Backend | Outcome | Count |
|---|---|---|
| `small` | `success` | 120 |
| `large` | `success` | 60 |
| `broken` | `retryable_failure` | 5 |
| `broken` | `circuit_open` | 15 |

Every short prompt went to `small` and every long prompt to `large`. The first 5 requests to `broken` failed after their retries, which reached the circuit breaker's `failure_threshold` of 5, so the remaining 15 were rejected without calling the backend. Requests that named `broken` directly did not fall back, so they returned `502`. These are mock backends, so the numbers show behavior, not real model performance.

## Running with Docker

Build the image:

```bash
docker build -t inferx:dev .
```

Run it with the built-in mock backends:

```bash
docker run --rm -p 127.0.0.1:8000:8000 inferx:dev
```

`-p 127.0.0.1:8000:8000` publishes the port only to your own machine. Plain `-p 8000:8000` would expose InferX to every network the machine is connected to.

The image:

- uses a multi-stage build, so uv and build caches never reach the final image
- installs exactly the versions in `uv.lock`
- runs as an unprivileged `inferx` user, not root
- has a `HEALTHCHECK` that calls `/health`, so `docker ps` shows whether the container is healthy

### Reaching Ollama from the container

Every container has its own network, so inside the container `127.0.0.1` means the container itself, not your machine. With the example config, InferX can't reach an Ollama server running on your machine, and requests fail with `502` after retries and fallback.

For local development on Linux, share your machine's network with `--network host`:

```bash
docker run --rm --network host -e INFERX_CONFIG_PATH=config/ollama.toml inferx:dev \
  uvicorn inferx.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

With host networking, the container has no network boundary of its own, so the command is overridden to listen only on `127.0.0.1`. Running Ollama in its own container on the Compose network is the planned long-term setup.

## How failures are handled

Each backend is wrapped in layers, from the outside in:

```
CircuitBreakerBackend  ->  RetryingBackend  ->  backend (Ollama, vLLM, mock, ...)
```

1. **Circuit breaker:** if the backend's circuit is open, fail immediately without calling it
2. **Retries:** on a transient failure, wait (exponential backoff with full jitter) and try again, up to `max_attempts`
3. **Fallback:** if the backend still fails with a transient error, the endpoint tries the next fallback backend
4. **Deadline:** all of the above must finish within `request_timeout_seconds`. If time runs out, whatever is in progress (an HTTP call or a backoff wait) is cancelled, and the client gets a `504`

Each layer only counts a failure as "unhealthy" if it's transient. Permanent failures (like a `400` caused by the request) are not retried, don't trigger fallback, and count as a healthy response for the circuit breaker, since the backend did respond. A cancelled request (for example, from the deadline) doesn't count for or against a backend's health.

There are two kinds of timeout:

- **`timeout_seconds`** (per backend): how long one attempt may take
- **`request_timeout_seconds`** (per request): the total budget for every attempt, wait, and fallback

The circuit breaker has three states:

- **closed:** requests go through, and consecutive failures are counted
- **open:** after `failure_threshold` requests in a row fail (each after its retries), requests skip the backend for `cooldown_seconds`
- **half-open:** after the cooldown, exactly one probe request is sent. If it succeeds the circuit closes; if it fails the circuit opens again

## Observed behavior with real models

A manual run with `ollama-small` pointed at an unused port (so it always fails), retries with a `0.5` second base delay, and a circuit breaker that opens after 2 failures. Four identical short prompts were sent in a row:

| Request | Time | What happened |
|---|---|---|
| 1 | 24.99 s | Retries on the failing backend, then fallback to `llama3.2:3b`, which was not loaded yet (cold start) |
| 2 | 1.13 s | Retries on the failing backend, then fallback to the warm `llama3.2:3b`. The circuit opened after this request |
| 3 | 0.15 s | Circuit open: the failing backend was skipped, straight to `llama3.2:3b` |
| 4 | 0.18 s | Same as request 3 |

Requests 2 to 4 are the fair comparison, since the model was warm for all of them. Request 1 is dominated by loading the model onto the GPU. This is a single run on one laptop (RTX 3060 Laptop GPU, 6 GB), not a benchmark; reproducible load tests are planned.

## Metrics

`GET /metrics` serves metrics in Prometheus's text format:

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `inferx_http_requests_total` | counter | `method`, `route`, `status` | HTTP requests handled |
| `inferx_http_request_duration_seconds` | histogram | `method`, `route` | Time to handle each request |
| `inferx_backend_attempts_total` | counter | `backend`, `outcome` | Requests sent to each backend (after its retries), by `success`, `retryable_failure`, `permanent_failure`, or `circuit_open` |
| `inferx_backend_retries_total` | counter | `backend` | Retries of transient failures |
| `inferx_fallbacks_total` | counter | `from_backend`, `to_backend` | Requests moved to another backend |
| `inferx_deadline_exceeded_total` | counter | `backend` | Requests that ran out of their time budget |
| `inferx_circuit_breaker_state` | gauge | `backend`, `state` | `1` for each backend's current circuit state (`closed`, `open`, `half_open`), `0` for the others |

Labels only ever hold a small, fixed set of values. Requests to unknown paths are counted under `route="unmatched"` rather than their raw path, so random URLs can't create unlimited time series. The latency buckets span 10 milliseconds to 60 seconds, since model requests range from milliseconds to a cold start of about 25 seconds.

Example Prometheus queries:

```promql
# Requests per second over the last 5 minutes, by status
sum by (status) (rate(inferx_http_requests_total[5m]))

# p95 latency of chat requests
histogram_quantile(0.95, sum by (le) (rate(inferx_http_request_duration_seconds_bucket{route="/v1/chat/completions"}[5m])))

# What happened at each backend
sum by (backend, outcome) (inferx_backend_attempts_total)

# Backends whose circuit is open right now
inferx_circuit_breaker_state{state="open"} == 1
```

`/health` and `/metrics` requests are counted in the metrics but logged at `DEBUG`, so frequent health checks and scrapes don't flood the logs.

## Logs

InferX writes JSON logs to the terminal, one object per line. Every log line written while handling a request includes that request's ID. Every request produces one `request completed` line, for example:

```json
{"timestamp": "2026-11-04T23:24:02.285421+00:00", "level": "INFO", "logger": "inferx.app", "message": "request completed", "request_id": "juan-test-002", "method": "POST", "path": "/v1/chat/completions", "status": 200, "latency_ms": 269.69, "backend": "ollama-small", "route_reason": "short_prompt", "fallback_from": null, "backend_latency_ms": 267.84}
```

`latency_ms` is the total time inside InferX, and `backend_latency_ms` is the time spent waiting on backends (including retries and fallbacks), so the difference is the gateway's own overhead. `backend` is the backend that answered (or was being tried when the request ended), and `fallback_from` is the routed backend it replaced, if any.

Other log lines:

- `retrying backend request`: a transient failure is being retried, with the attempt number, the wait before the next attempt, and the backend's status code
- `falling back to another backend`: a backend kept failing with transient errors (or its circuit was open), with the failing backend, the next one to try, and the full error
- `backend request failed`: the request failed for good, with the full error, whether it was `retryable`, and the backend's status code
- `request deadline exceeded`: the time budget ran out, with the backend being tried and the budget
- `circuit breaker state changed`: a backend's circuit moved between `closed`, `open`, and `half_open`

`--no-access-log` turns off Uvicorn's plain-text request lines, since the JSON request logs replace them.

## Configuration

InferX reads these environment variables:

| Variable | Default | Description |
|---|---|---|
| `INFERX_CONFIG_PATH` | none | Path to a TOML config file. Without one, InferX uses two built-in mock backends. |
| `INFERX_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

In Docker, pass them with `-e`, for example `-e INFERX_CONFIG_PATH=config/ollama.toml`. The image includes the `config` folder at `/app/config`.

The config file lists the backends, the routing rules, the retry policy, the circuit breaker settings, and the time limits. See [`config/ollama.toml`](config/ollama.toml) for a complete example.

```toml
[routing]
small_backend = "ollama-small"
large_backend = "ollama-large"
max_small_prompt_chars = 200
fallback_backends = ["ollama-large", "ollama-small"]

[retry]
max_attempts = 3
base_delay_seconds = 0.1
max_delay_seconds = 2.0

[circuit_breaker]
failure_threshold = 5
cooldown_seconds = 30.0

[limits]
request_timeout_seconds = 60.0

[[backends]]
type = "openai"
name = "ollama-small"
base_url = "http://127.0.0.1:11434/v1"
model = "llama3.2:1b"
```

Backend types:

- `mock`: fields `name`, optional `latency_seconds`, optional `fail`, optional `retryable_failures` (default true)
- `openai`: fields `name`, `base_url`, `model`, optional `timeout_seconds` (default 30, at most `request_timeout_seconds`), optional `api_key_env`

Routing settings:

- `small_backend`, `large_backend`, `max_small_prompt_chars`: where `"auto"` requests go, by prompt length
- `fallback_backends` (optional): backends to try, in order, when the routed backend keeps failing with transient errors. The routed backend is skipped. Leave it out to disable fallback.

Retry settings (all optional, applied to every backend):

- `max_attempts`: total attempts including the first, from 1 to 10 (default 3)
- `base_delay_seconds`: the first backoff cap (default 0.1); each later cap doubles
- `max_delay_seconds`: the largest backoff cap (default 2.0)

Each wait is a random amount between zero and the current cap ("full jitter"), so retries from many requests spread out instead of arriving at the same moment.

Circuit breaker settings (all optional, applied to every backend):

- `failure_threshold`: consecutive failed requests (each after its retries) before the circuit opens (default 5)
- `cooldown_seconds`: how long the circuit stays open before a probe request is allowed (default 30)

Limits (optional):

- `request_timeout_seconds`: total time budget per request, up to 600 (default 60). The default leaves room for a model's cold start, which took about 25 seconds in local testing.

API keys never go in the config file. Set `api_key_env` to the name of an environment variable, and InferX reads the key from that variable at startup.

The `max_small_prompt_chars` threshold in the example is a starting guess, not a tuned value. Choosing it from measured cost and quality data is part of the planned benchmarks.

## Known limitations

- **Retries don't know the remaining time budget.** A retry can start even when it can't finish before the deadline, and is then cancelled. Passing the remaining budget down so retries can skip themselves (deadline propagation) would avoid that wasted work.
- **Circuit breaker state is per process and in memory.** Several InferX instances each track backends separately, and a restart resets every circuit to closed.
- **The circuit breaker counts consecutive failures.** A backend that fails intermittently (for example, every other request) never trips it. A failure rate over a time window would catch that case.
- **The circuit breaker metric shows the last known state.** A circuit only moves from `open` to `half_open` when a request arrives after its cooldown, so with no traffic, the metric keeps reporting `open`.
- **`/metrics` and the Prometheus UI have no authentication.** Metrics reveal backend names and traffic patterns. Both are published only to `127.0.0.1` in the Compose setup; anything exposed beyond a private network would need access control.
- **The Compose setup uses mock backends.** Prometheus scrapes every 5 seconds to make the demo feel live; 15 to 60 seconds is more typical in production.
- **Permanent failures don't fall back.** This is deliberate, so a misconfigured backend (like a bad API key) shows up as errors instead of silently shifting traffic, but it means some requests fail that another backend could have answered.
- **One retry and circuit breaker policy for all backends.** A hosted API might deserve different settings than a local model.
- **Retries can stack with other layers.** If clients and model servers also retry,