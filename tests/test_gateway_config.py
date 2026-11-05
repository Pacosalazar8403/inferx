"""Tests for loading the gateway config and building backends and the router."""

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from inferx.backends.circuit_breaking import CircuitBreakerBackend
from inferx.backends.mock import MockBackend
from inferx.backends.openai_compatible import OpenAICompatibleBackend
from inferx.gateway_config import (
    DEFAULT_CONFIG,
    MockBackendConfig,
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

RETRY_SECTION = """
[retry]
max_attempts = 5
base_delay_seconds = 0.2
max_delay_seconds = 4.0
"""

CIRCUIT_BREAKER_SECTION = """
[circuit_breaker]
failure_threshold = 2
cooldown_seconds = 10.0
"""

LIMITS_SECTION = """
[limits]
request_timeout_seconds = 45.0
"""


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gateway.toml"
    path.write_text(textwrap.dedent(text))
    return path


def with_fallbacks(fallbacks: str) -> str:
    """VALID_CONFIG with a fallback_backends line added to [routing]."""
    return VALID_CONFIG.replace(
        "max_small_prompt_chars = 100",
        f"max_small_prompt_chars = 100\nfallback_backends = {fallbacks}",
    )


def test_default_config_builds_protected_backends_and_router() -> None:
    backends = build_backends(DEFAULT_CONFIG)
    router = build_router(DEFAULT_CONFIG)

    assert set(backends) == {"mock-small", "mock-large"}
    assert all(isinstance(backend, CircuitBreakerBackend) for backend in backends.values())
    assert router.small_backend == "mock-small"
    assert router.fallback_backends == ()


def test_loads_valid_config_file_with_defaults(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_CONFIG))

    assert [backend.name for backend in config.backends] == ["small", "large"]
    assert isinstance(config.backends[1], OpenAIBackendConfig)
    assert config.backends[1].model == "big-model"
    assert config.retry.max_attempts == 3
    assert config.circuit_breaker.failure_threshold == 5
    assert config.limits.request_timeout_seconds == 60.0


def test_loads_retry_settings(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_CONFIG + RETRY_SECTION))

    policy = config.retry.to_policy()
    assert policy.max_attempts == 5
    assert policy.base_delay_seconds == 0.2
    assert policy.max_delay_seconds == 4.0


def test_loads_circuit_breaker_settings(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_CONFIG + CIRCUIT_BREAKER_SECTION))

    backends = build_backends(config)

    breaker = backends["small"].breaker
    assert breaker.failure_threshold == 2
    assert breaker.cooldown_seconds == 10.0


def test_loads_request_timeout(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_CONFIG + LIMITS_SECTION))

    assert config.limits.request_timeout_seconds == 45.0


def test_example_config_in_repo_is_valid() -> None:
    config = load_config(REPO_ROOT / "config" / "ollama.toml")

    router = build_router(config)
    assert router.fallback_backends == ("ollama-large", "ollama-small")


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


def test_rejects_retry_max_delay_below_base(tmp_path: Path) -> None:
    text = VALID_CONFIG + RETRY_SECTION.replace("max_delay_seconds = 4.0", "max_delay_seconds = 0.1")

    with pytest.raises(ValidationError, match="max_delay_seconds"):
        load_config(write_config(tmp_path, text))


def test_rejects_zero_retry_attempts(tmp_path: Path) -> None:
    text = VALID_CONFIG + RETRY_SECTION.replace("max_attempts = 5", "max_attempts = 0")

    with pytest.raises(ValidationError):
        load_config(write_config(tmp_path, text))


def test_rejects_too_many_retry_attempts(tmp_path: Path) -> None:
    text = VALID_CONFIG + RETRY_SECTION.replace("max_attempts = 5", "max_attempts = 100")

    with pytest.raises(ValidationError):
        load_config(write_config(tmp_path, text))


def test_rejects_zero_circuit_breaker_threshold(tmp_path: Path) -> None:
    text = VALID_CONFIG + CIRCUIT_BREAKER_SECTION.replace(
        "failure_threshold = 2", "failure_threshold = 0"
    )

    with pytest.raises(ValidationError):
        load_config(write_config(tmp_path, text))


def test_rejects_zero_request_timeout(tmp_path: Path) -> None:
    text = VALID_CONFIG + LIMITS_SECTION.replace(
        "request_timeout_seconds = 45.0", "request_timeout_seconds = 0"
    )

    with pytest.raises(ValidationError):
        load_config(write_config(tmp_path, text))


def test_rejects_backend_timeout_longer_than_request_timeout(tmp_path: Path) -> None:
    text = (
        VALID_CONFIG.replace('model = "big-model"', 'model = "big-model"\ntimeout_seconds = 50.0')
        + LIMITS_SECTION
    )

    with pytest.raises(ValidationError, match="could never finish"):
        load_config(write_config(tmp_path, text))


def test_router_pointing_at_missing_backend_is_rejected(tmp_path: Path) -> None:
    text = VALID_CONFIG.replace('large_backend = "large"', 'large_backend = "typo"')
    config = load_config(write_config(tmp_path, text))

    with pytest.raises(ValueError, match="unknown backends"):
        build_router(config)


def test_loads_fallback_backends(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, with_fallbacks('["large", "small"]')))

    router = build_router(config)

    assert router.fallback_backends == ("large", "small")


def test_rejects_unknown_fallback_backend(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, with_fallbacks('["large", "typo"]')))

    with pytest.raises(ValueError, match="unknown backends"):
        build_router(config)


def test_mock_backend_can_be_configured_to_fail() -> None:
    backend = build_backend(
        MockBackendConfig(type="mock", name="broken", fail=True, retryable_failures=False)
    )

    assert isinstance(backend, MockBackend)
    assert backend.fail is True
    assert backend.retryable_failures is False


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