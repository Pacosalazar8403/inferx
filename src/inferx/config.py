"""Application settings, read from environment variables.

Every setting can be overridden with an environment variable that starts
with INFERX_, for example INFERX_BACKEND=openai. The defaults use the mock
backend, so tests and CI never need a real model server.
"""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from inferx.backends.base import Backend
from inferx.backends.mock import MockBackend
from inferx.backends.openai_compatible import OpenAICompatibleBackend


class Settings(BaseSettings):
    """InferX configuration."""

    model_config = SettingsConfigDict(env_prefix="INFERX_")

    backend: Literal["mock", "openai"] = "mock"
    backend_name: str = "default"
    backend_base_url: str = "http://127.0.0.1:11434/v1"
    backend_model: str = "llama3.2:1b"
    backend_api_key: SecretStr | None = None
    backend_timeout_seconds: float = Field(default=30.0, gt=0)


def build_backend(settings: Settings) -> Backend:
    """Create the backend described by the settings."""
    if settings.backend == "mock":
        return MockBackend(name="mock")

    api_key = settings.backend_api_key.get_secret_value() if settings.backend_api_key else None
    return OpenAICompatibleBackend(
        name=settings.backend_name,
        base_url=settings.backend_base_url,
        model=settings.backend_model,
        api_key=api_key,
        timeout_seconds=settings.backend_timeout_seconds,
    )