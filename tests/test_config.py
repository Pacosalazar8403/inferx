"""Tests for settings and choosing the gateway config."""

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inferx.app import app
from inferx.config import Settings, load_gateway_config
from inferx.gateway_config import DEFAULT_CONFIG

CUSTOM_CONFIG = """
[routing]
small_backend = "custom-a"
large_backend = "custom-b"
max_small_prompt_chars = 50

[[backends]]
type = "mock"
name = "custom-a"

[[backends]]
type = "mock"
name = "custom-b"
"""


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "gateway.toml"
    path.write_text(textwrap.dedent(CUSTOM_CONFIG))
    return path


def test_defaults_to_built_in_mock_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFERX_CONFIG_PATH", raising=False)

    assert load_gateway_config(Settings()) is DEFAULT_CONFIG


def test_reads_config_path_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INFERX_CONFIG_PATH", str(write_config(tmp_path)))

    config = load_gateway_config(Settings())

    assert [backend.name for backend in config.backends] == ["custom-a", "custom-b"]


def test_app_uses_backends_from_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INFERX_CONFIG_PATH", str(write_config(tmp_path)))

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    assert response.headers["X-InferX-Backend"] == "custom-a"