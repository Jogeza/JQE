"""Tests for core.logging_config (and the core.logger backward-compat shim)."""

from __future__ import annotations

from core import logging_config


class TestConfigureLogging:
    """configure_logging() must be safe to call repeatedly and set up sinks."""

    def test_is_idempotent(self) -> None:
        # configure_logging() already ran at import time; calling it again
        # must not raise, duplicate sinks, or change the configured state.
        logging_config.configure_logging()
        assert logging_config._configured is True

    def test_log_directory_is_created(self) -> None:
        from config import settings

        logging_config.configure_logging()
        assert settings.log_dir.exists()

    def test_logger_is_usable(self) -> None:
        # Should not raise.
        logging_config.logger.debug("test log line from test_logging_config")
        logging_config.logger.info("test log line from test_logging_config")


class TestLoggerShim:
    """core.logger must remain a thin, backward-compatible re-export."""

    def test_core_logger_is_the_same_object_as_logging_config_logger(self) -> None:
        from core.logger import logger as shim_logger

        assert shim_logger is logging_config.logger
