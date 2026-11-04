"""Application settings, read from environment variables.

The gateway layout (backends and routing) lives in a TOML file pointed to
by INFERX_CONFIG_PATH. Without one, InferX uses two built-in mock backends,
so tests and CI never need a real model server.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from inferx.gateway_config import DEFAULT_CONFIG, GatewayConfig, load_config


class Settings(BaseSettings):
    """InferX settings that vary between environments."""

    model_config = SettingsConfigDict(env_prefix="INFERX_")

    config_path: Path | None = None


def load_gateway_config(settings: Settings) -> GatewayConfig:
    """Load the configured gateway layout, or the built-in default."""
    if settings.config_path is None:
        return DEFAULT_CONFIG
    return load_config(settings.config_path)