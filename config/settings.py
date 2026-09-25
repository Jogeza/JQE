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

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from execution.safety import EmergencyStopState

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
        broker: Configured :class:`~broker.base.BrokerGateway` selection
            used by :func:`broker.factory.get_gateway` when no persisted
            operator selection exists. Defaults to ``"mt5"``; the
            persisted store at ``broker_selection_store_path`` is
            authoritative at runtime (see ``effective_broker``).
            ``"simulation"`` is only honored as an explicit
            development/testing configuration — the platform never
            silently falls back to it.
        market_data_source: Read-only candle source for dashboard and live
            execution cycles. ``broker`` uses the verified broker gateway for
            broker-native instruments.
            Defaults to offline simulation; ``"deriv_public"`` selects the
            unauthenticated public Deriv candle adapter without changing the
            execution broker.
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
        deriv_expected_environment: Expected Deriv account environment
            (``"demo"`` or ``"real"``). Used by the demo authentication
            harness (``tools/deriv_demo_auth.py``) as a pre-flight check.
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
        intent_store_path: Deterministic SQLite path for durable execution
            intent records. Relative paths resolve from the process working
            directory; production should set an explicit absolute path.
        risk_observation_freshness_seconds: Maximum age of a durable-cycle
            risk observation before API consumers must treat it as stale.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.ai"),
        env_file_encoding="utf-8",
        env_prefix="JQE_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = "development"

    broker: Literal["simulation", "mt5", "deriv", "weltrade", "mt5_demo", "deriv_demo", "weltrade_demo"] = "mt5"
    broker_execution_enabled: bool = False
    market_data_source: Literal["simulation", "deriv_public", "broker"] = "simulation"

    @property
    def effective_broker(self) -> str:
        """Resolve the authoritative active broker from persistent store or settings."""
        from data.broker_selection import get_effective_broker
        return get_effective_broker(self)

    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_terminal_path: Path | None = None
    mt5_expected_environment: Literal["demo", "live"] | None = None
    observation_mt5_terminal_path: Path | None = None
    observation_mt5_portable_data_path: Path | None = None

    weltrade_login: int | None = None
    weltrade_password: str | None = Field(default=None, repr=False)
    weltrade_server: str | None = None
    weltrade_terminal_path: Path | None = None
    weltrade_demo_login: int | None = None
    weltrade_demo_password: str | None = Field(default=None, repr=False)
    weltrade_demo_server: str | None = None

    @property
    def effective_weltrade_login(self) -> int | None:
        return self.weltrade_demo_login if self.weltrade_demo_login is not None else self.weltrade_login

    @property
    def effective_weltrade_password(self) -> str | None:
        return self.weltrade_demo_password if self.weltrade_demo_password is not None else self.weltrade_password

    @property
    def effective_weltrade_server(self) -> str | None:
        return self.weltrade_demo_server if self.weltrade_demo_server is not None else self.weltrade_server

    deriv_api_token: str | None = Field(default=None, repr=False)
    deriv_app_id: str = "1089"
    deriv_endpoint: str = "wss://ws.derivws.com/websockets/v3"
    deriv_public_endpoint: str = "wss://api.derivws.com/trading/v1/options/ws/public"
    deriv_options_account_id: str | None = None
    deriv_expected_environment: Literal["demo", "real"] | None = None

    telegram_enabled: bool = False
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_allowed_chat_id: int | None = None
    telegram_request_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    slack_webhook_url: str | None = Field(default=None, repr=False)
    slack_request_timeout_seconds: float = Field(default=10.0, gt=0, le=30)

    anthropic_api_key: str | None = Field(default=None, repr=False, exclude=True)
    ai_assistant_enabled: bool = False
    ai_assistant_kill_switch: bool = True
    ai_assistant_model: str = "claude-haiku-4-5-20251001"
    ai_assistant_max_output_tokens: int = Field(default=512, ge=1, le=4096)
    ai_assistant_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    ai_assistant_max_message_chars: int = Field(default=1000, ge=1, le=10000)
    ai_assistant_max_context_bytes: int = Field(default=32768, ge=1024, le=262144)
    ai_assistant_requests_per_minute: int = Field(default=6, ge=1, le=60)
    ai_assistant_daily_request_limit: int = Field(default=100, ge=1, le=10000)

    default_symbol: str = "R_75"
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
    historical_data_path: Path = Path("data/historical.sqlite3")
    research_experiment_path: Path = Path("data/experiments")
    intent_store_path: Path = Path("state/intent_records.sqlite3")
    execution_position_ledger_path: Path = Path("state/execution_positions.sqlite3")
    execution_lifetime_store_path: Path = Path("state/execution_lifetime.sqlite3")
    daily_instrument_trade_store_path: Path = Path("state/daily_instrument_trades.sqlite3")
    max_daily_trades_per_instrument: int = Field(default=20, gt=0)
    emergency_stop: EmergencyStopState = EmergencyStopState.UNKNOWN
    execution_safety_store_path: Path = Path("state/execution_safety.sqlite3")
    execution_safety_freshness_seconds: int = Field(default=15, gt=0)
    risk_observation_freshness_seconds: int = Field(default=15, gt=0)
    execution_reservation_lease_seconds: int = Field(default=120, gt=0)
    runtime_mode: Literal["disabled", "paper_continuous"] = "disabled"
    paper_runtime_enabled: bool = False
    paper_runtime_poll_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)
    paper_runtime_max_backoff_seconds: float = Field(default=300.0, ge=1.0, le=3600.0)
    paper_runtime_state_path: Path = Path("state/paper_runtime.sqlite3")
    paper_runtime_intent_store_path: Path = Path("state/paper_runtime_intents.sqlite3")
    paper_diagnostics_path: Path = Path("state/paper_diagnostics.sqlite3")
    dashboard_paper_store_path: Path = Path("state/dashboard_paper.sqlite3")
    dashboard_paper_intent_store_path: Path = Path("state/dashboard_paper_intents.sqlite3")
    simulation_daily_submission_store_path: Path = Path("state/simulation_daily_submissions.sqlite3")
    simulation_daily_submission_limit: int = Field(default=5, gt=0)
    offline_analysis_seed: int = 62061
    offline_analysis_candle_count: int = Field(default=500, ge=200, le=5000)
    paper_diagnostics_minimum_sample: int = Field(default=100, gt=0)

    # Fallback static list used when no WatchlistStore is injected.
    # Must be kept in sync with DEFAULT_SYNTHETIC_SEEDS in data/watchlist.py.
    observation_symbols: str = (
        "R_75:H1,"
        "FX Vol 20:H1,"
        "SFX Vol 20:H1,"
        "PainX 400:H1,"
        "GainX 400:H1,"
        "TrendX 600:H1,"
        "FiboX:H1,"
        "QuadX:H1,"
        "MAX PainX 1000:H1,"
        "MAX GainX 1000:H1"
    )
    watchlist_store_path: Path = Path("state/watchlist.sqlite3")
    broker_selection_store_path: Path = Path("state/broker_selection.sqlite3")
    observation_evidence_path: Path = Path(
        "state/live_paper_operational/observation_daemon.evidence.sqlite3"
    )
    observation_close_grace_seconds: float = Field(default=5.0, ge=0, le=300)
    observation_max_backoff_seconds: float = Field(default=300.0, ge=1, le=3600)
    observation_heartbeat_stale_cycles: int = Field(default=2, ge=1, le=24)

    campaign_mode: Literal["historical", "historical_replay", "live_paper"] = "historical"
    live_paper_max_candles: int | None = Field(default=None, gt=0)
    live_paper_max_duration_seconds: float | None = Field(default=None, gt=0)
    # Legacy configuration compatibility only. Live broker campaigns must use
    # SQLiteOneShotExecutionGuard as their sole submission-count authority.
    live_paper_max_orders_per_session: int = Field(default=50, gt=0)
    live_paper_min_order_spacing_seconds: float = Field(default=60.0, ge=0)
    live_paper_order_poll_timeout_seconds: float = Field(default=30.0, gt=0)

    @model_validator(mode="after")
    def _validate_live_paper_mode(self) -> Settings:
        if self.campaign_mode == "live_paper":
            if not self.broker_execution_enabled:
                raise ValueError(
                    "live_paper campaign mode requires broker_execution_enabled=True"
                )
            if self.broker not in {"mt5_demo", "deriv_demo", "weltrade_demo"}:
                raise ValueError(
                    f"live_paper campaign mode requires a demo broker ('mt5_demo' or 'deriv_demo'), got '{self.broker}'"
                )
            if self.live_paper_max_candles is None and self.live_paper_max_duration_seconds is None:
                raise ValueError(
                    "live_paper requires at least one stop condition"
                )
        return self

    @field_validator(
        "mt5_terminal_path",
        "weltrade_terminal_path",
        "observation_mt5_terminal_path",
        "observation_mt5_portable_data_path",
        mode="before",
    )
    @classmethod
    def _normalize_windows_paths(cls, value: object) -> object:
        if isinstance(value, str) and "\t" in value:
            cand = value.replace("\t", "\\t")
            if Path(cand).exists():
                return Path(cand)
        return value

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

    @field_validator("emergency_stop", mode="before")
    @classmethod
    def _normalize_emergency_stop(cls, value: object) -> object:
        """Normalize recognized enum text while leaving invalid values to fail validation."""
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
