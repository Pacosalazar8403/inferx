# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: install dependencies and InferX into a virtual environment.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Copy the uv binary from its official image, pinned to the same version
# used locally.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

# Compile Python files ahead of time for faster startup, copy files instead
# of linking them (cache mounts can't be linked across), use the image's own
# Python, and skip dev dependencies like pytest.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_DEV=1

WORKDIR /app

# Dependencies first. This layer is only rebuilt when uv.lock or
# pyproject.toml change, not on every code change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Then InferX itself.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# ---------------------------------------------------------------------------
# Runtime stage: only Python and the finished virtual environment.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# A dedicated unprivileged user, so InferX never runs as root.
RUN groupadd --system --gid 1001 inferx \
 && useradd --system --uid 1001 --gid inferx --no-create-home inferx

WORKDIR /app
COPY --from=builder --chown=inferx:inferx /app/.venv /app/.venv
COPY --chown=inferx:inferx config ./config

# Use the virtual environment's programs, and print logs immediately
# instead of buffering them.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER inferx
EXPOSE 8000

# Docker checks this every 30 seconds and marks the container unhealthy if
# /health stops answering.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Listen on all interfaces inside the container. Who can reach it is decided
# when the container is run, by which ports are published.
CMD ["uvicorn", "inferx.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
