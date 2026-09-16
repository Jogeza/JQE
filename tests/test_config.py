"""Tests for config.settings — the platform's Pydantic Settings layer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import EmergencyStopState, Settings, get_settings


class TestSettingsDefaults:
    """Default values should match JQE's documented institutional defaults."""

    def test_default_symbol_is_volatility_75(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.default_symbol == "R_75"

    def test_default_risk_percent(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.risk_percent == 1.0

    def test_default_max_daily_loss(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.max_daily_loss == 3.0

    def test_default_max_trades_daily(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.max_trades_daily == 5

    def test_default_account_balance(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.account_balance == 50.0

    def test_default_environment_is_development(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.environment == "development"

    def test_default_log_level_is_info(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.log_level == "INFO"

    def test_missing_emergency_stop_defaults_to_unknown(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.emergency_stop is EmergencyStopState.UNKNOWN

    def test_default_research_experiment_catalog_is_repository_relative(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.research_experiment_path.as_posix() == "data/experiments"

    def test_observation_mt5_profile_is_unconfigured_by_default(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.observation_mt5_terminal_path is None
        assert settings.observation_mt5_portable_data_path is None


class TestSettingsEnvOverrides:
    """Environment variables (JQE_-prefixed) should override defaults."""

    def test_env_var_overrides_symbol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JQE_DEFAULT_SYMBOL", "EURUSD")
        settings = Settings(_env_file=None)
        assert settings.default_symbol == "EURUSD"

    def test_env_var_overrides_risk_percent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JQE_RISK_PERCENT", "2.5")
        settings = Settings(_env_file=None)
        assert settings.risk_percent == 2.5

    def test_env_var_is_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("jqe_default_symbol", "GBPUSD")
        settings = Settings(_env_file=None)
        assert settings.default_symbol == "GBPUSD"

    def test_obsolete_durable_executor_switch_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JQE_USE_DURABLE_EXECUTOR", "false")
        settings = Settings(_env_file=None)
        assert not hasattr(settings, "use_durable_executor")

    def test_log_level_is_normalized_to_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JQE_LOG_LEVEL", "debug")
        settings = Settings(_env_file=None)
        assert settings.log_level == "DEBUG"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("CLEAR", EmergencyStopState.CLEAR), ("active", EmergencyStopState.ACTIVE)],
    )
    def test_emergency_stop_env_is_explicit_and_normalized(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: EmergencyStopState
    ) -> None:
        monkeypatch.setenv("JQE_EMERGENCY_STOP", raw)
        assert Settings(_env_file=None).emergency_stop is expected


class TestSettingsValidation:
    """Invalid values should raise a Pydantic ValidationError, not fail silently."""

    def test_negative_risk_percent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, risk_percent=-1)

    def test_zero_risk_percent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, risk_percent=0)

    def test_risk_percent_over_100_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, risk_percent=150)

    def test_invalid_environment_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, environment="not-a-real-env")

    def test_zero_candle_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, default_candle_count=0)

    def test_invalid_log_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, log_level="NOT_A_LEVEL")

    def test_invalid_emergency_stop_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, emergency_stop="DISABLED")

    def test_risk_observation_freshness_must_be_positive(self) -> None:
        assert Settings(_env_file=None).risk_observation_freshness_seconds == 15
        with pytest.raises(ValidationError):
            Settings(_env_file=None, risk_observation_freshness_seconds=0)


class TestGetSettingsCaching:
    """get_settings() should return one cached, process-wide instance."""

    def test_returns_same_instance(self) -> None:
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_cache_clear_produces_a_new_instance(self) -> None:
        get_settings.cache_clear()
        first = get_settings()
        get_settings.cache_clear()
        second = get_settings()
        assert first is not second


class TestObsoleteDerivSelectors:
    """Obsolete Deriv execution selector env vars must be inert.

    ``deriv_demo_execution_enabled`` and ``deriv_approved_symbols`` were
    removed because they had zero production consumers. The pydantic-settings
    ``extra='ignore'`` policy means any env var that no longer maps to a
    field is silently discarded — no validation error, no effect on runtime.
    The application execution boundary (``main.py``: broker != 'simulation'
    raises) remains independent of these settings.
    """

    def test_obsolete_demo_execution_env_var_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JQE_DERIV_DEMO_EXECUTION_ENABLED no longer maps to any field."""
        monkeypatch.setenv("JQE_DERIV_DEMO_EXECUTION_ENABLED", "true")
        settings = Settings(_env_file=None)
        assert not hasattr(settings, "deriv_demo_execution_enabled")

    def test_obsolete_approved_symbols_env_var_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JQE_DERIV_APPROVED_SYMBOLS no longer maps to any field."""
        monkeypatch.setenv("JQE_DERIV_APPROVED_SYMBOLS", "XAUUSD,EURUSD")
        settings = Settings(_env_file=None)
        assert not hasattr(settings, "deriv_approved_symbols")

    def test_execution_boundary_is_simulation_only_regardless_of_deriv_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The broker guard in main.py is independent of Deriv configuration.

        Even with a Deriv API token and options account configured, the
        settings framework alone cannot enable live execution — that is
        enforced unconditionally by the ``settings.broker != 'simulation'``
        check at the top of ``main.run()``.
        """
        monkeypatch.setenv("JQE_BROKER", "simulation")
        monkeypatch.setenv("JQE_DERIV_API_TOKEN", "fake-token")
        monkeypatch.setenv("JQE_DERIV_OPTIONS_ACCOUNT_ID", "DOT12345")
        monkeypatch.setenv("JQE_DERIV_EXPECTED_ENVIRONMENT", "demo")
        # Obsolete vars are present but must be inert.
        monkeypatch.setenv("JQE_DERIV_DEMO_EXECUTION_ENABLED", "true")
        monkeypatch.setenv("JQE_DERIV_APPROVED_SYMBOLS", "XAUUSD")
        settings = Settings(_env_file=None)
        # Broker is still simulation — execution boundary holds.
        assert settings.broker == "simulation"
