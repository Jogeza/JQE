"""Backward-compatible logger accessor.

Existing modules across the codebase import the shared logger as
``from core.logger import logger``. The actual sink configuration lives
in :mod:`core.logging_config` (single source of truth for logging
setup) — this module simply re-exports the already-configured logger so
none of those call sites need to change.

New code should generally import from :mod:`core.logger` too, for
consistency with the rest of the codebase; :mod:`core.logging_config` is
the place to change *how* logging behaves.
"""

from core.logging_config import configure_logging, logger

configure_logging()

__all__ = ["logger"]
