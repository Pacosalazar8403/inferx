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
- `X-InferX-Backend` and `X-InferX-Route-Reason` response headers on every request, including failures
- Structured JSON logs with one line per request: request ID, status, route decision, total latency, and backend latency
- Request IDs on every log line, including retries, generated per request or reused from a safe incoming `X-Request-ID` header, and returned to the caller
- OpenAI-compatible HTTP backend that works with Ollama, vLLM, and hosted model APIs
- Mock backend with simulated latency and forced failures, used for tests and CI
- Strict config validation at startup: typos, unknown backend types, duplicate names, invalid retry settings, and missing API key variables are rejected before the server accepts traffic
- Clear errors: `422` for invalid requests, `404` for unknown models, `502` when a backend fails (full details go to the server logs, not to the client)
- `/health` endpoint and auto-generated OpenAPI docs
- Automated tests with pytest, run in CI on every pull request

### Planned

- Fallback to another backend when one fails
- Circuit breakers that stop sending traffic to a failing backend
- Streaming responses for the chat endpoint
- Routing by cost budget and latency target
- Smarter routing, evaluated against the length-based router as a baseline
- Per-key rate limiting and response caching (Redis)
- Usage and cost tracking (PostgreSQL)
- Metrics and dashboards (Prometheus and Grafana)
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

The `x-inferx-backend`, `x-inferx-route-reason`, and `x-request-id` headers show which backend handled the request, why, and the ID to search for in the logs. Interactive API docs are available at http://127.0.0.1:8000/docs.

### Using real models with Ollama

Install [Ollama](https://ollama.com), download two sizes of the same model family, and start InferX with the example config:

```bash
ollama pull llama3.2:1b
ollama pull llama3.2:3b
INFERX_CONFIG_PATH=config/ollama.toml uv run uvicorn inferx.app:app --reload --no-access-log
```

Short prompts now go to `llama3.2:1b` and longer prompts to `llama3.2:3b`.

## Logs

InferX writes JSON logs to the terminal, one object per line. Every log line written while handling a request includes that request's ID. Every request produces one `request completed` line, for example:

```json
{"timestamp": "2026-11-04T23:24:02.285421+00:00", "level": "INFO", "logger": "inferx.app", "message": "request completed", "request_id": "juan-test-002", "method": "POST", "path": "/v1/chat/completions", "status": 200, "latency_ms": 269.69, "backend": "ollama-small", "route_reason": "short_prompt", "backend_latency_ms": 267.84}
```

`latency_ms` is the total time inside InferX, and `backend_latency_ms` is the time spent waiting on the backend (including retries), so the difference is the gateway's own overhead.

Other log lines under the same request ID:

- `retrying backend request`: a transient failure is being retried, with the attempt number, the wait before the next attempt, and the backend's status code
- `backend request failed`: the request failed after any retries, with the full error, whether it was `retryable`, and the backend's status code

`--no-access-log` turns off Uvicorn's plain-text request lines, since the JSON request logs replace them.

## Configuration

InferX reads these environment variables:

| Variable | Default | Description |
|---|---|---|
| `INFERX_CONFIG_PATH` | none | Path to a TOML config file. Without one, InferX uses two built-in mock backends. |
| `INFERX_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

The config file lists the backends, the routing rules, and the retry policy. See [`config/ollama.toml`](config/ollama.toml) for a complete example.

```toml
[routing]
small_backend = "ollama-small"
large_backend = "ollama-large"
max_small_prompt_chars = 200

[retry]
max_attempts = 3
base_delay_seconds = 0.1
max_delay_seconds = 2.0

[[backends]]
type = "openai"
name = "ollama-small"
base_url = "http://127.0.0.1:11434/v1"
model = "llama3.2:1b"
```

Backend types:

- `mock`: fields `name`, optional `latency_seconds`, optional `fail`
- `openai`: fields `name`, `base_url`, `model`, optional `timeout_seconds` (default 30), optional `api_key_env`

Retry settings (all optional, applied to every backend):

- `max_attempts`: total attempts including the first, from 1 to 10 (default 3)
- `base_delay_seconds`: the first backoff cap (default 0.1); each later cap doubles
- `max_delay_seconds`: the largest backoff cap (default 2.0)

Each wait is a random amount between zero and the current cap ("full jitter"), so retries from many requests spread out instead of arriving at the same moment.

API keys never go in the config file. Set `api_key_env` to the name of an environment variable, and InferX reads the key from that variable at startup.

The `max_small_prompt_chars` threshold in the example is a starting guess, not a tuned value. Choosing it from measured cost and quality data is part of the planned benchmarks.

## Known limitations

- **No overall request deadline yet.** Retries run inside a single request, so the worst case is roughly `max_attempts` times the backend timeout, plus backoff waits. With the defaults, that can exceed 90 seconds against a backend that keeps timing out.
- **One retry policy for all backends.** A hosted API might deserve different settings than a local model.
- **Retries can stack with other layers.** If clients and model servers also retry, attempts multiply. Keep `max_attempts` small.

## Running tests

```bash
uv run pytest -v
```

Tests use mock backends, a mock HTTP transport, and a fake sleep function, so they never need a model server and never actually wait between retries.

## Project structure

```
inferx/
├── config/
│   └── ollama.toml               example config for two local Ollama models
├── src/inferx/
│   ├── app.py                    FastAPI app, lifespan, middleware, and routes
│   ├── config.py                 environment settings
│   ├── gateway_config.py         config file models and builders
│   ├── observability.py          JSON logging and request ID context
│   ├── router.py                 length-based router
│   ├── schemas.py                request and response models
│   └── backends/
│       ├── base.py               backend interface and error type
│       ├── mock.py               mock backend for development and testing
│       ├── openai_compatible.py  HTTP backend for OpenAI-compatible servers
│       └── retrying.py           retry wrapper with backoff and jitter
├── tests/                        automated tests (shared fixtures in conftest.py)
├── .github/workflows/            CI pipeline
├── pyproject.toml                project metadata and dependencies
└── uv.lock                       exact locked dependency versions
```

## Tech stack

Python 3.12, FastAPI, Uvicorn, Pydantic, pydantic-settings, httpx2, pytest, uv, Ollama, GitHub Actions