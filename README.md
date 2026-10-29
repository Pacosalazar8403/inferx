# InferX

[![CI](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml/badge.svg)](https://github.com/Pacosalazar8403/inferx/actions/workflows/ci.yml)

An LLM inference gateway with cost-aware routing, fault tolerance, and reproducible benchmarks.

> **Status:** early development. Features listed under *Planned* are not built yet.

## What it does

InferX sits between client applications and multiple language model backends. Each request is routed to the cheapest backend that can handle it, while the gateway handles failures, enforces rate limits, and records cost and latency for every request.

### Current features

- FastAPI service with a `/health` endpoint and auto-generated OpenAPI docs
- Automated tests with pytest
- Continuous integration with GitHub Actions

### Planned

- Chat endpoint with streaming responses
- Multiple model backends (local model, hosted model, and a mock backend for testing)
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

In another terminal:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0"}
```

Interactive API docs are available at http://127.0.0.1:8000/docs.

## Running tests

```bash
uv run pytest -v
```

## Project structure

```
inferx/
├── src/inferx/          application code
│   └── app.py           FastAPI app and routes
├── tests/               automated tests
├── .github/workflows/   CI pipeline
├── pyproject.toml       project metadata and dependencies
└── uv.lock              exact locked dependency versions
```

## Tech stack

Python 3.12, FastAPI, Uvicorn, pytest, uv, GitHub Actions