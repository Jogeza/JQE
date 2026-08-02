"""Tests for config.settings — the platform's Pydantic Settings layer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import Settings, get_settings


class TestSettingsDefaults:
    """Default values should match JQE's documented institutional defaults."""

    def test_default_symbol_is_xauusd(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.default_symbol == "XAUUSD"

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

    def test_log_level_is_normalized_to_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JQE_LOG_LEVEL", "debug")
        settings = Settings(_env_file=None)
        assert settings.log_level == "DEBUG"


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
