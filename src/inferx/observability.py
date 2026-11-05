"""Structured JSON logging.

Each log record becomes one JSON object per line, so log tools can search
and filter by field (for example, every request that went to one backend)
instead of matching text.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

# Attributes that every log record has. Anything else on a record was added
# through `extra=...` and becomes its own field in the JSON output.
_STANDARD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


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
    """Send InferX's logs to the terminal as JSON.

    Only the "inferx" logger is configured, so this doesn't change how other
    libraries log. Calling it more than once replaces the handler instead of
    adding duplicates.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("inferx")
    logger.handlers = [handler]
    logger.setLevel(level)