"""End-to-end test: an open circuit makes fallback instant."""

import logging
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inferx.app import app
from inferx.backends.circuit_breaking import CircuitOpenError

# The small backend always fails, and its circuit opens after 2 failures.
CONFIG = """
[routing]
small_backend = "small"
large_backend = "large"
max_small_prompt_chars = 200
fallback_backends = ["large", "small"]

[retry]
max_attempts = 1

[circuit_breaker]
failure_threshold = 2
cooldown_seconds = 60.0

[[backends]]
type = "mock"
name = "small"
fail = true

[[backends]]
type = "mock"
name = "large"
"""


def test_open_circuit_skips_straight_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "gateway.toml"
    config_path.write_text(textwrap.dedent(CONFIG))
    monkeypatch.setenv("INFERX_CONFIG_PATH", str(config_path))
    caplog.set_level(logging.INFO, logger="inferx")

    with TestClient(app) as client:
        responses = [
            client.post(
                "/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            )
            for _ in range(3)
        ]

    # Every request still gets an answer from the fallback backend.
    assert [r.status_code for r in responses] == [200, 200, 200]
    assert all(r.headers["X-InferX-Backend"] == "large" for r in responses)

    # The first two requests tried "small" and failed. The third didn't even
    # try it, because its circuit was already open.
    fallbacks = [r for r in caplog.records if r.getMessage() == "falling back to another backend"]
    errors = [record.exc_info[1] for record in fallbacks]
    assert len(errors) == 3
    assert not isinstance(errors[0], CircuitOpenError)
    assert not isinstance(errors[1], CircuitOpenError)
    assert isinstance(errors[2], CircuitOpenError)