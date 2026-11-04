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
- `X-InferX-Backend` and `X-InferX-Route-Reason` response headers on every request, including failures
- OpenAI-compatible HTTP backend that works with Ollama, vLLM, and hosted model APIs
- Mock backend with simulated latency and forced failures, used for tests and CI
- Strict config validation at startup: typos, unknown backend types, duplicate names, and missing API key variables are rejected before the server accepts traffic
- Clear errors: `422` for invalid requests, `404` for unknown models, `502` when a backend fails (without exposing internal details)
- `/health` endpoint and auto-generated OpenAPI docs
- Automated tests with pytest, run in CI on every pull request

### Planned

- Streaming responses for the chat endpoint
- Routing by cost budget and latency target
- Smarter routing, evaluated against the length-based router as a baseline
- Timeouts, retries with backoff, and circuit breakers
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
uv run uvicorn inferx.app:app --reload
```

Without a config file, InferX starts with two mock backends (`mock-small` and `mock-large`). In another terminal:

```bash
curl -s -i http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hello InferX"}]}'
```

The `x-inferx-backend` and `x-inferx-route-reason` headers show which backend handled the request and why. Interactive API docs are available at http://127.0.0.1:8000/docs.

### Using real models with Ollama

Install [Ollama](https://ollama.com), download two sizes of the same model family, and start InferX with the example config:

```bash
ollama pull llama3.2:1b
ollama pull llama3.2:3b
INFERX_CONFIG_PATH=config/ollama.toml uv run uvicorn inferx.app:app --reload
```

Short prompts now go to `llama3.2:1b` and longer prompts to `llama3.2:3b`.

## Configuration

InferX reads one environment variable:

| Variable | Default | Description |
|---|---|---|
| `INFERX_CONFIG_PATH` | none | Path to a TOML config file. Without one, InferX uses two built-in mock backends. |

The config file lists the backends and the routing rules. See [`config/ollama.toml`](config/ollama.toml) for a complete example.

```toml
[routing]
small_backend = "ollama-small"
large_backend = "ollama-large"
max_small_prompt_chars = 200

[[backends]]
type = "openai"
name = "ollama-small"
base_url = "http://127.0.0.1:11434/v1"
model = "llama3.2:1b"
```

Backend types:

- `mock`: fields `name`, optional `latency_seconds`
- `openai`: fields `name`, `base_url`, `model`, optional `timeout_seconds` (default 30), optional `api_key_env`

API keys never go in the config file. Set `api_key_env` to the name of an environment variable, and InferX reads the key from that variable at startup.

The `max_small_prompt_chars` threshold in the example is a starting guess, not a tuned value. Choosing it from measured cost and quality data is part of the planned benchmarks.

## Running tests

```bash
uv run pytest -v
```

Tests use mock backends and a mock HTTP transport, so they never need a model server.

## Project structure

```
inferx/
├── config/
│   └── ollama.toml               example config for two local Ollama models
├── src/inferx/
│   ├── app.py                    FastAPI app, lifespan, and routes
│   ├── config.py                 environment settings
│   ├── gateway_config.py         config file models and builders
│   ├── router.py                 length-based router
│   ├── schemas.py                request and response models
│   └── backends/
│       ├── base.py               backend interface
│       ├── mock.py               mock backend for development and testing
│       └── openai_compatible.py  HTTP backend for OpenAI-compatible servers
├── tests/                        automated tests (shared fixtures in conftest.py)
├── .github/workflows/            CI pipeline
├── pyproject.toml                project metadata and dependencies
└── uv.lock                       exact locked dependency versions
```

## Tech stack

Python 3.12, FastAPI, Uvicorn, Pydantic, pydantic-settings, httpx2, pytest, uv, Ollama, GitHub Actions