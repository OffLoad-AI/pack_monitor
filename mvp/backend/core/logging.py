"""Structured logging.

Runs are batch jobs whose interesting events are per-image and machine-readable —
"this image refused, here is what each stage measured" — not prose. structlog is
configured to render key-value pairs to the console for a human at a terminal, and
JSON when `PCM_LOG_JSON` is set, so the same call sites feed both.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

_configured = False


def configure(level: str | None = None, json_output: bool | None = None) -> None:
    """Set up structlog once per process. Safe to call repeatedly."""
    global _configured
    if _configured:
        return

    level = (level or os.environ.get("PCM_LOG_LEVEL", "INFO")).upper()
    if json_output is None:
        json_output = bool(os.environ.get("PCM_LOG_JSON"))

    logging.basicConfig(format="%(message)s", stream=sys.stderr,
                        level=getattr(logging, level, logging.INFO))

    # Opening the root logger at INFO also opens these, and they narrate their own
    # start-up — Alembic announces every autogenerate plugin it registers, on every
    # command. Their warnings still get through.
    for noisy in ("alembic", "sqlalchemy", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer = (structlog.processors.JSONRenderer() if json_output
                else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level, logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str):
    configure()
    return structlog.get_logger(name)
