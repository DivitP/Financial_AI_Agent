"""Minimal structured logging for the HTTP boundary."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "correlation_id": getattr(record, "correlation_id", None),
            },
            default=str,
        )


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("financial_ai.api")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
