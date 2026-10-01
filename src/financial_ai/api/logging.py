"""Minimal structured logging for the HTTP boundary."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from financial_ai.observability import safe_event


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "message": "telemetry_unavailable"
                if record.msg == "telemetry_unavailable"
                else "application_event",
                **safe_event(getattr(record, "safe_event", {})),
            },
            default=str,
        )


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("financial_ai")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
