"""Structured JSON logging (SPEC §20 Operations). Secrets are redacted before rendering."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET_KEY_RE = re.compile(r"(key|token|secret|password|authorization)", re.IGNORECASE)


def _redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for k in list(event_dict):
        if _SECRET_KEY_RE.search(k):
            event_dict[k] = "***"
    return event_dict


def configure_logging(service: str, level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
