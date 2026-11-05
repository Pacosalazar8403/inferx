"""Structured JSON logging, with the current request ID on every log line.

Each log record becomes one JSON object per line, so log tools can search
and filter by field (for example, every request that went to one backend)
instead of matching text.

The request ID is stored in a context variable while a request is being
handled, and attached to every log record created during that time. Code
deep inside the app, like a backend wrapper, gets it in its logs for free.
"""

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

# Attributes that every log record has. Anything else on a record was added
# through `extra=...` (or by our record factory) and becomes its own field.
_STANDARD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

# Each async task (each request) sees its own value, so concurrent
# requests never mix up their IDs.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_original_record_factory = logging.getLogRecordFactory()


def set_request_id(request_id: str) -> Token[str | None]:
    """Make `request_id` current for the code handling this request."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request ID, usually none."""
    _request_id.reset(token)


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Create log records the normal way, then attach the current request ID."""
    record = _original_record_factory(*args, **kwargs)
    record.request_id = _request_id.get()
    return record


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRIBUTES:
                entry[key] = value

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Send InferX's logs to the terminal as JSON, with request IDs.

    Only the "inferx" logger gets the JSON handler, so this doesn't change
    how other libraries' logs look. Calling it more than once is safe: it
    replaces the handler and record factory instead of stacking them.
    """
    if logging.getLogRecordFactory() is not _record_factory:
        logging.setLogRecordFactory(_record_factory)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("inferx")
    logger.handlers = [handler]
    logger.setLevel(level)