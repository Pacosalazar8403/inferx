"""Tests for loading the gateway config and building backends and the router."""

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from inferx.backends.mock import MockBackend
from inferx.backends.openai_compatible import OpenAICompatibleBackend
from inferx.gateway_config import (
    DEFAULT_CONFIG,
    OpenAIBackendConfig,
    build_backend,
    build_backends,
    build_router,
    load_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_CONFIG = """
[routing]
small_backend = "small"
large_backend = "large"
max_small_prompt_chars = 100

[[backends]]
type = "mock"
name = "small"

[[backends]]
type = "openai"
name = "large"
base_url = "http://model-server.test/v1"
model = "big-model"
"""


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gateway.toml"
    path.write_text(textwrap.dedent(text))
    return path


def test_default_config_builds_mock_backends_and_router() -> None:
    backends = build_backends(DEFAULT_CONFIG)
    router = build_router(DEFAULT_CONFIG)

    assert set(backends) == {"mock-small", "mock-large"}
    assert all(isinstance(backend, MockBackend) for backend in backends.values())
    assert router.small_backend == "mock-small"


def test_loads_valid_config_file(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_CONFIG))

    assert [backend.name for backend in config.backends] == ["small", "large"]
    assert isinstance(config.backends[1], OpenAIBackendConfig)
    assert config.backends[1].model == "big-model"


def test_example_config_in_repo_is_valid() -> None:
    config = load_config(REPO_ROOT / "config" / "ollama.toml")

    build_router(config)


def test_rejects_misspelled_field(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace('model = "big-model"', 'modle = "big-model"')

    with pytest.raises(ValidationError):
        load_config(write_config(tmp_path, text))


def test_rejects_unknown_backend_type(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace('type = "mock"', 'type = "vllm"')

    with pytest.raises(ValidationError):
        load_config(write_config(tmp_path, text))


def test_rejects_duplicate_backend_names(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace('name = "large"', 'name = "small"')

    with pytest.raises(ValidationError, match="duplicate backend names"):
        load_config(write_config(tmp_path, text))


def test_router_pointing_at_missing_backend_is_rejected(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace('large_backend = "large"', 'large_backend = "typo"')
    config = load_config(write_config(tmp_path, text))

    with pytest.raises(ValueError, match="unknown backends"):
        build_router(config)


@pytest.mark.anyio
async def test_api_key_is_read_from_named_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_MODEL_API_KEY", "secret-value")
    config = OpenAIBackendConfig(
        type="openai",
        name="hosted",
        base_url="http://model-server.test/v1",
        model="big-model",
        api_key_env="TEST_MODEL_API_KEY",
    )

    backend = build_backend(config)
    try:
        assert isinstance(backend, OpenAICompatibleBackend)
    finally:
        await backend.aclose()


def test_missing_api_key_environment_variable_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_MODEL_API_KEY", raising=False)
    config = OpenAIBackendConfig(
        type="openai",
        name="hosted",
        base_url="http://model-server.test/v1",
        model="big-model",
        api_key_env="TEST_MODEL_API_KEY",
    )

    with pytest.raises(ValueError, match="TEST_MODEL_API_KEY"):
        build_backend(config)