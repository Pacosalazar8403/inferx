# InferX

[![CI](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml/badge.svg)](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml)

An LLM inference gateway with cost-aware routing, fault tolerance, and reproducible benchmarks.

> **Status:** early development. Features listed under *Planned* are not built yet.

## What it does

InferX sits between client applications and multiple language model backends. Each request is routed to the cheapest backend that can handle it, while the gateway handles failures, enforces rate limits, and records cost and latency for every request.

### Current features

- OpenAI-compatible `POST /v1/chat/completions` endpoint (subset of the format)
- Request validation with clear `422` errors for invalid input
- Backend interface, with a mock backend that supports simulated latency and forced failures
- `502 Bad Gateway` responses when a backend fails, without exposing internal details
- `/health` endpoint and auto-generated OpenAPI docs
- Automated tests with pytest, run in CI on every pull request

### Planned

- Streaming responses for the chat endpoint
- Real model backends (local model and hosted model)
- Configurable routing by prompt length, cost budget, and latency target
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

In another terminal, check that the service is up:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0"}
```

Send a chat request (currently answered by the mock backend):

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "mock", "messages": [{"role": "user", "content": "Hello InferX"}]}'
```

Interactive API docs are available at http://127.0.0.1:8000/docs.

## Running tests

```bash
uv run pytest -v
```

## Project structure

```
inferx/
├── src/inferx/
│   ├── app.py           FastAPI app and routes
│   ├── schemas.py       request and response models
│   └── backends/
│       ├── base.py      backend interface
│       └── mock.py      mock backend for development and testing
├── tests/               automated tests
├── .github/workflows/   CI pipeline
├── pyproject.toml       project metadata and dependencies
└── uv.lock              exact locked dependency versions
```

## Tech stack

Python 3.12, FastAPI, Uvicorn, Pydantic, pytest, uv, GitHub Actions