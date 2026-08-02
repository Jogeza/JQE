"""Loguru-based structured logging configuration for the JQE platform.

This module is the single source of truth for *how* JQE logs: which
sinks are active, their format, and their rotation/retention policy. It
is deliberately separate from :mod:`core.logger` (a thin, backward
compatible re-export used by existing call sites) so that configuration
concerns live in exactly one place, per the single-responsibility
principle.

Configuration is driven by :data:`config.settings`, so log level, output
directory, and rotation policy are all controllable via environment
variables or ``.env`` without touching code.
"""

from __future__ import annotations

import sys
from typing import Final

from loguru import logger

from config import settings

_CONSOLE_FORMAT: Final[str] = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

_FILE_FORMAT: Final[str] = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)

_configured: bool = False


def configure_logging() -> None:
    """Configures loguru's sinks for the running process.

    Removes loguru's default sink and installs:

    * A colorized console sink (stderr), if ``settings.log_to_console``
      is enabled.
    * A rotating file sink under ``settings.log_dir``, governed by
      ``settings.log_rotation`` / ``settings.log_retention``.

    This function is idempotent: calling it more than once (e.g. because
    several modules import :mod:`core.logger`) is a no-op after the
    first call, so sinks are never duplicated and log lines are never
    emitted twice.
    """
    global _configured
    if _configured:
        return

    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    if settings.log_to_console:
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format=_CONSOLE_FORMAT,
            colorize=True,
            backtrace=False,
            diagnose=False,
        )

    logger.add(
        settings.log_dir / settings.log_file,
        level=settings.log_level,
        format=_FILE_FORMAT,
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
    )

    _configured = True


configure_logging()

__all__ = ["configure_logging", "logger"]
