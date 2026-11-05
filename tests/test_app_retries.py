"""End-to-end test: retries happen inside a request and are traceable."""

import logging
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inferx.app import app

# Zero delays, so the test doesn't actually wait between retries.
FAILING_CONFIG = """
[routing]
small_backend = "flaky"
large_backend = "flaky"
max_small_prompt_chars = 200

[retry]
max_attempts = 3
base_delay_seconds = 0
max_delay_seconds = 0

[[backends]]
type = "mock"
name = "flaky"
fail = true
"""


def test_retries_are_logged_with_the_request_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "failing.toml"
    config_path.write_text(textwrap.dedent(FAILING_CONFIG))
    monkeypatch.setenv("INFERX_CONFIG_PATH", str(config_path))
    caplog.set_level(logging.INFO, logger="inferx")

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"X-Request-ID": "retry-test-1"},
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 502

    retries = [r for r in caplog.records if r.getMessage() == "retrying backend request"]
    assert [r.attempt for r in retries] == [1, 2]
    assert all(r.request_id == "retry-test-1" for r in retries)