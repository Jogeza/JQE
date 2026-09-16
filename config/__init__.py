"""JQE configuration package.

Exposes a single, validated, environment-aware :class:`~config.settings.Settings`
object used throughout the platform.

Typical usage:

    >>> from config import settings
    >>> settings.default_symbol
    'R_75'

In tests, or anywhere a fresh instance is required (e.g. after mutating
environment variables), use :func:`get_settings` directly together with
``get_settings.cache_clear()``.
"""

from config.settings import Settings, get_settings, settings
from execution.safety import EmergencyStopState

__all__ = ["EmergencyStopState", "Settings", "get_settings", "settings"]
