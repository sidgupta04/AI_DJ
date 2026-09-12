"""Structured logging.

Decisions in this project are reconstructed from logs, so every event is a structured record
with bound key/value context rather than a formatted string.
"""

from __future__ import annotations

import logging
from typing import Literal

import structlog

LogFormat = Literal["console", "json"]


def configure_logging(level: str = "INFO", log_format: LogFormat = "console") -> None:
    """Install the structlog pipeline. Safe to call more than once."""
    numeric_level = logging.getLevelNamesMapping()[level.upper()]

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # Keep third-party (uvicorn, sqlalchemy) records at the same threshold.
    logging.basicConfig(level=numeric_level, format="%(message)s")


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
