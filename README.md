# InferX

[![CI](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml/badge.svg)](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml)

An LLM inference gateway with cost-aware routing, fault tolerance, and reproducible benchmarks.

> **Status:** early development. Features listed under *Planned* are not built yet.

## What it does

InferX sits between client applications and multiple language model backends. Each request is routed to the cheapest backend that can handle it, while the gateway handles failures, enforces rate limits, and records cost and latency for every request.

### Current features

- OpenAI-compatible `POST /v1/chat/completions` endpoint (subset of the format)
- OpenAI-compatible HTTP backend that works with Ollama, vLLM, and hosted model APIs
- Mock backend with simulated latency and forced failures, used for tests and CI
- Configuration through `INFERX_` environment variables, with validation at startup
- Backend connections created at startup and closed cleanly at shutdown
- Request validation with clear `422` errors, and `502 Bad Gateway` on backend failure without exposing internal details
- `/health` endpoint and auto-generated OpenAPI docs
- Automated tests with pytest, run in CI on every pull request

### Planned

- Streaming responses for the chat endpoint
- Multiple backends at once, with configurable routing by prompt length, cost budget, and latency target
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

By default, InferX uses the mock backend. In another terminal:

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hello InferX"}]}'
```

Interactive API docs are available at http://127.0.0.1:8000/docs.

### Using a real model with Ollama

Install [Ollama](https://ollama.com), download a small model, and point InferX at it:

```bash
ollama pull llama3.2:1b
INFERX_BACKEND=openai INFERX_BACKEND_NAME=ollama-small uv run uvicorn inferx.app:app --reload
```

The same backend works with any OpenAI-compatible server, such as vLLM, by changing `INFERX_BACKEND_BASE_URL` and `INFERX_BACKEND_MODEL`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INFERX_BACKEND` | `mock` | `mock` or `openai` (any OpenAI-compatible server) |
| `INFERX_BACKEND_NAME` | `default` | Name used to identify the backend internally |
| `INFERX_BACKEND_BASE_URL` | `http://127.0.0.1:11434/v1` | Base URL of the model server |
| `INFERX_BACKEND_MODEL` | `llama3.2:1b` | Model name sent to the model server |
| `INFERX_BACKEND_API_KEY` | none | API key sent as a bearer token, if the server needs one |
| `INFERX_BACKEND_TIMEOUT_SECONDS` | `30` | Maximum time to wait for a backend response |

## Running tests

```bash
uv run pytest -v
```

Tests use the mock backend and a mock HTTP transport, so they never need a model server.

## Project structure

```
inferx/
├── src/inferx/
│   ├── app.py                    FastAPI app, lifespan, and routes
│   ├── config.py                 settings and backend factory
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