"""Gateway configuration: which backends exist, how requests are routed,
and how failures are retried and contained.

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
from inferx.backends.circuit_breaking import CircuitBreakerBackend
from inferx.backends.mock import MockBackend
from inferx.backends.openai_compatible import OpenAICompatibleBackend
from inferx.backends.retrying import RetryingBackend, RetryPolicy
from inferx.circuit_breaker import CircuitBreaker
from inferx.router import LengthRouter


class MockBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["mock"]
    name: str = Field(min_length=1)
    latency_seconds: float = Field(default=0.0, ge=0)
    fail: bool = False
    retryable_failures: bool = True


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
    # Backends to try, in order, when the routed backend keeps failing.
    fallback_backends: list[str] = Field(default_factory=list)


class RetryConfig(BaseModel):
    """Retry settings applied to every backend.

    max_attempts is capped at 10, so a typo can't turn one failing request
    into a flood of retries against a struggling server.
    """

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: float = Field(default=0.1, ge=0)
    max_delay_seconds: float = Field(default=2.0, ge=0)

    @model_validator(mode="after")
    def check_delays(self) -> "RetryConfig":
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be less than base_delay_seconds")
        return self

    def to_policy(self) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=self.max_attempts,
            base_delay_seconds=self.base_delay_seconds,
            max_delay_seconds=self.max_delay_seconds,
        )


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker settings applied to every backend.

    A backend's circuit opens after failure_threshold requests in a row fail
    (each after its retries), and stays open for cooldown_seconds.
    """

    model_config = ConfigDict(extra="forbid")

    failure_threshold: int = Field(default=5, ge=1)
    cooldown_seconds: float = Field(default=30.0, gt=0)


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backends: list[BackendConfig] = Field(min_length=1)
    routing: RoutingConfig
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)

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
    """Create one backend from its config, without retries or a breaker."""
    if isinstance(config, MockBackendConfig):
        return MockBackend(
            name=config.name,
            latency_seconds=config.latency_seconds,
            fail=config.fail,
            retryable_failures=config.retryable_failures,
        )

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
    """Create every configured backend with retries and a circuit breaker.

    The breaker wraps the retries, so one breaker failure means one request
    that still failed after all of its retries.
    """
    policy = config.retry.to_policy()
    backends: dict[str, Backend] = {}
    for backend_config in config.backends:
        retrying = RetryingBackend(build_backend(backend_config), policy)
        breaker = CircuitBreaker(
            name=backend_config.name,
            failure_threshold=config.circuit_breaker.failure_threshold,
            cooldown_seconds=config.circuit_breaker.cooldown_seconds,
        )
        backends[backend_config.name] = CircuitBreakerBackend(retrying, breaker)
    return backends


def build_router(config: GatewayConfig) -> LengthRouter:
    """Create the router, checking that it only refers to real backends."""
    return LengthRouter(
        small_backend=config.routing.small_backend,
        large_backend=config.routing.large_backend,
        max_small_prompt_chars=config.routing.max_small_prompt_chars,
        available_backends={backend.name for backend in config.backends},
        fallback_backends=config.routing.fallback_backends,
    )