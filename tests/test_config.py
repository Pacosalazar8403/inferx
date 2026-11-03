"""Tests for settings and backend construction."""

import pytest
from pydantic import ValidationError

from inferx.backends.mock import MockBackend
from inferx.backends.openai_compatible import OpenAICompatibleBackend
from inferx.config import Settings, build_backend


def test_defaults_use_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFERX_BACKEND", raising=False)

    backend = build_backend(Settings())

    assert isinstance(backend, MockBackend)


@pytest.mark.anyio
async def test_environment_selects_openai_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFERX_BACKEND", "openai")
    monkeypatch.setenv("INFERX_BACKEND_MODEL", "llama3.2:3b")

    backend = build_backend(Settings())
    try:
        assert isinstance(backend, OpenAICompatibleBackend)
        assert backend.model == "llama3.2:3b"
    finally:
        await backend.aclose()


def test_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFERX_BACKEND", "opnai")

    with pytest.raises(ValidationError):
        Settings()


def test_api_key_is_hidden_when_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFERX_BACKEND_API_KEY", "super-secret-value")

    settings = Settings()

    assert "super-secret-value" not in repr(settings)
    assert settings.backend_api_key is not None
    assert settings.backend_api_key.get_secret_value() == "super-secret-value"