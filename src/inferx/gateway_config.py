"""Gateway configuration: which backends exist and how requests are routed.

Loaded from a TOML file so several backends can be described in one place.
Secrets never go in this file: a backend names the environment variable
that holds its API key, and the key is read from the environment.
"""

import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inferx.backends.base import Backend
from inferx.backends.mock import MockBackend
from inferx.backends.openai_compatible import OpenAICompatibleBackend
from inferx.router import LengthRouter


class MockBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["mock"]
    name: str = Field(min_length=1)
    latency_seconds: float = Field(default=0.0, ge=0)


class OpenAIBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["openai"]
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)


# The "type" field decides which of the two models above validates a backend.
BackendConfig = Annotated[
    MockBackendConfig | OpenAIBackendConfig,
    Field(discriminator="type"),
]


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    small_backend: str
    large_backend: str
    max_small_prompt_chars: int = Field(gt=0)


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backends: list[BackendConfig] = Field(min_length=1)
    routing: RoutingConfig

    @model_validator(mode="after")
    def check_backend_names_are_unique(self) -> "GatewayConfig":
        names = [backend.name for backend in self.backends]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate backend names: {duplicates}")
        return self


# Used when no config file is given, so tests and CI need no setup.
DEFAULT_CONFIG = GatewayConfig(
    backends=[
        MockBackendConfig(type="mock", name="mock-small"),
        MockBackendConfig(type="mock", name="mock-large"),
    ],
    routing=RoutingConfig(
        small_backend="mock-small",
        large_backend="mock-large",
        max_small_prompt_chars=200,
    ),
)


def load_config(path: Path) -> GatewayConfig:
    """Read and validate a TOML config file."""
    with path.open("rb") as file:
        data = tomllib.load(file)
    return GatewayConfig.model_validate(data)


def build_backend(config: MockBackendConfig | OpenAIBackendConfig) -> Backend:
    """Create one backend from its config."""
    if isinstance(config, MockBackendConfig):
        return MockBackend(name=config.name, latency_seconds=config.latency_seconds)

    api_key = None
    if config.api_key_env:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise ValueError(
                f"backend '{config.name}' needs the environment variable "
                f"{config.api_key_env}, but it is not set"
            )

    return OpenAICompatibleBackend(
        name=config.name,
        base_url=config.base_url,
        model=config.model,
        api_key=api_key,
        timeout_seconds=config.timeout_seconds,
    )


def build_backends(config: GatewayConfig) -> dict[str, Backend]:
    """Create every configured backend, keyed by name."""
    return {backend.name: build_backend(backend) for backend in config.backends}


def build_router(config: GatewayConfig) -> LengthRouter:
    """Create the router, checking that it only refers to real backends."""
    return LengthRouter(
        small_backend=config.routing.small_backend,
        large_backend=config.routing.large_backend,
        max_small_prompt_chars=config.routing.max_small_prompt_chars,
        available_backends={backend.name for backend in config.backends},
    )