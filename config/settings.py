"""Centralized runtime configuration for the JQE Trading Platform.

This module defines :class:`Settings`, a validated, environment-aware
configuration object built on Pydantic Settings. It replaces the previous
flat ``config.py`` (a bare dataclass with no validation, secrets handling,
or environment support) with a single source of truth that:

* Loads values from process environment variables (prefixed ``JQE_``) and
  an optional ``.env`` file at the project root.
* Validates every value at startup (e.g. ``risk_percent`` must be a
  positive percentage) rather than failing deep inside trading logic.
* Is safe to import from anywhere in the codebase without triggering I/O
  side effects, via the cached :func:`get_settings` accessor.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Validated runtime configuration for the JQE Trading Platform.

    Every field can be overridden by an environment variable named
    ``JQE_<FIELD_NAME>`` (case-insensitive) or by an entry in a ``.env``
    file at the project root. See ``.env.example`` for the full list of
    supported variables.

    Attributes:
        environment: Deployment environment. Affects logging verbosity
            and future environment-gated behavior (e.g. disabling live
            order routing outside of "production").
        broker: Which :class:`~broker.base.BrokerGateway` implementation
            :func:`broker.factory.get_gateway` constructs. Defaults to
            ``"simulation"`` so the platform runs out of the box with
            no credentials or live broker connection required.
        mt5_login: MetaTrader 5 account number used to authenticate with
            the terminal. ``None`` when using an already-logged-in
            terminal instance.
        mt5_password: MetaTrader 5 account password. Never logged.
        mt5_server: MetaTrader 5 broker server name (e.g.
            ``"ICMarketsSC-Demo"``).
        deriv_api_token: Deriv API token, required when ``broker`` is
            ``"deriv"``. Never logged; obtain from
            https://app.deriv.com/account/api-token.
        deriv_app_id: Deriv application ID. Defaults to Deriv's public
            demo app ID (``"1089"``, used throughout their own docs) —
            register your own for anything beyond development.
        deriv_endpoint: Deriv WebSocket endpoint URL.
        default_symbol: Instrument symbol used when none is explicitly
            supplied to the trading pipeline.
        default_timeframe: MT5 timeframe name (e.g. ``"M5"``, ``"H1"``)
            used when none is explicitly supplied.
        default_candle_count: Number of historical candles requested by
            default when fetching market data.
        account_balance: Fallback account balance, in account currency,
            used for position sizing when a live balance is unavailable
            (e.g. simulation/backtesting mode).
        risk_percent: Percentage of account balance risked per trade.
        max_daily_loss: Maximum permitted daily loss, expressed as a
            percentage of account balance, before trading halts.
        max_trades_daily: Maximum number of trades permitted in a single
            trading day.
        log_level: Minimum severity emitted to all configured log sinks.
        log_dir: Directory where rotating log files are written.
        log_file: File name of the primary application log within
            ``log_dir``.
        log_rotation: Loguru rotation policy (size- or time-based, e.g.
            ``"10 MB"`` or ``"00:00"``).
        log_retention: Loguru retention policy for rotated log files
            (e.g. ``"14 days"``).
        log_to_console: Whether logs are also emitted to stderr, in
            addition to the rotating file sink.
        cache_dir: Directory for the local historical-candle cache
            (SQLite; see ``data/storage.py``). Runtime state, not
            source — git-ignored.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JQE_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = "development"

    broker: Literal["simulation", "mt5", "deriv"] = "simulation"

    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None

    deriv_api_token: str | None = None
    deriv_app_id: str = "1089"
    deriv_endpoint: str = "wss://ws.derivws.com/websockets/v3"

    default_symbol: str = "XAUUSD"
    default_timeframe: str = "M5"
    default_candle_count: int = Field(default=500, gt=0)

    account_balance: float = Field(default=50.0, gt=0)
    risk_percent: float = Field(default=1.0, gt=0, le=100)
    max_daily_loss: float = Field(default=3.0, gt=0, le=100)
    max_trades_daily: int = Field(default=5, gt=0)

    log_level: LogLevel = "INFO"
    log_dir: Path = Path("logs")
    log_file: str = "jqe.log"
    log_rotation: str = "10 MB"
    log_retention: str = "14 days"
    log_to_console: bool = True

    cache_dir: Path = Path("cache")

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Upper-cases string log levels so ``"debug"`` and ``"DEBUG"`` both work.

        Args:
            value: The raw value supplied for ``log_level``.

        Returns:
            The upper-cased string if a string was given, otherwise the
            original value (letting Pydantic raise its own validation
            error for genuinely invalid types).
        """
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    """Returns the process-wide, cached :class:`Settings` instance.

    A cached factory function is used instead of a bare module-level
    singleton so that importing this module never performs I/O (reading
    the environment or ``.env`` file) as a side effect, while every
    caller within a process still shares one validated instance. Tests
    that need a fresh instance (e.g. after changing environment
    variables) should call ``get_settings.cache_clear()`` first.

    Returns:
        The shared :class:`Settings` instance for the current process.
    """
    return Settings()


settings = get_settings()
"""The shared, process-wide Settings instance, for convenient importing."""
