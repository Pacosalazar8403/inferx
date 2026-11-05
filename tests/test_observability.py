"""Tests for structured JSON logging."""

import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from inferx.observability import (
    JsonFormatter,
    configure_logging,
    reset_request_id,
    set_request_id,
)


def make_record(**extra: Any) -> logging.LogRecord:
    record = logging.makeLogRecord(
        {
            "name": "inferx.test",
            "levelname": "INFO",
            "levelno": logging.INFO,
            "msg": "hello %s",
            "args": ("world",),
        }
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def format_as_json(record: logging.LogRecord) -> dict[str, Any]:
    return json.loads(JsonFormatter().format(record))


@pytest.fixture
def configured_logging() -> Iterator[None]:
    """Configure InferX logging for one test, then restore the handlers."""
    logger = logging.getLogger("inferx")
    original_handlers = logger.handlers[:]
    configure_logging()
    try:
        yield
    finally:
        logger.handlers = original_handlers


def test_includes_standard_fields() -> None:
    entry = format_as_json(make_record())

    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "inferx.test"
    assert entry["timestamp"].endswith("+00:00")


def test_includes_extra_fields() -> None:
    entry = format_as_json(make_record(backend="ollama-small", latency_ms=12.5))

    assert entry["backend"] == "ollama-small"
    assert entry["latency_ms"] == 12.5


def test_includes_exception_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = make_record()
        record.exc_info = sys.exc_info()

    entry = format_as_json(record)

    assert "RuntimeError: boom" in entry["exception"]


def test_values_that_are_not_json_become_strings() -> None:
    entry = format_as_json(make_record(config_path=Path("config/ollama.toml")))

    assert entry["config_path"] == "config/ollama.toml"


def test_configure_logging_does_not_add_duplicate_handlers(configured_logging: None) -> None:
    configure_logging()

    logger = logging.getLogger("inferx")
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0].formatter, JsonFormatter)


def test_log_records_carry_the_current_request_id(
    configured_logging: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    token = set_request_id("ctx-123")
    try:
        logging.getLogger("inferx.deep.inside").info("hello from a backend")
    finally:
        reset_request_id(token)

    (record,) = [r for r in caplog.records if r.getMessage() == "hello from a backend"]
    assert record.request_id == "ctx-123"


def test_request_id_is_none_outside_a_request(
    configured_logging: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="inferx")

    logging.getLogger("inferx.startup").info("starting up")

    (record,) = [r for r in caplog.records if r.getMessage() == "starting up"]
    assert record.request_id is None