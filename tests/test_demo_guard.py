"""Tests for broker.demo_guard.DemoOnlyGuard.

Verifies the central fail-closed gate ensuring all operations are strictly
restricted to verified demo/virtual accounts.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from broker.demo_guard import (
    DEFAULT_BROKER_EVIDENCE_PATH,
    DemoAccountVerification,
    DemoOnlyGuard,
    MT5_ACCOUNT_TRADE_MODE_CONTEST,
    MT5_ACCOUNT_TRADE_MODE_DEMO,
    MT5_ACCOUNT_TRADE_MODE_REAL,
)
from core.exceptions import UnsafeBrokerAccountError


class TestDerivDemoVerification:
    def test_demo_account_passes(self, tmp_path) -> None:
        payload = {"authorize": {"loginid": "VRTC12345", "is_virtual": 1, "currency": "USD"}}
        evidence_db = tmp_path / "evidence.sqlite3"
        result = DemoOnlyGuard.assert_demo_account(
            "deriv", payload, session_id="test-session-1", evidence_store_path=evidence_db
        )
        assert isinstance(result, DemoAccountVerification)
        assert result.broker == "deriv"
        assert result.account_id == "VRTC12345"
        assert result.checked_field == "is_virtual"
        assert result.observed_value == 1
        assert result.status == "PASSED"

    def test_direct_authorize_dict_passes(self) -> None:
        payload = {"loginid": "VRTC999", "is_virtual": 1}
        result = DemoOnlyGuard.assert_demo_account("deriv_demo", payload)
        assert result.account_id == "VRTC999"
        assert result.observed_value == 1

    def test_object_with_attributes_passes(self) -> None:
        obj = SimpleNamespace(loginid="VRTC888", is_virtual=1)
        result = DemoOnlyGuard.assert_demo_account("deriv", obj)
        assert result.account_id == "VRTC888"
        assert result.observed_value == 1

    @pytest.mark.parametrize("real_val", [0, False])
    def test_real_account_raises_unsafe_error(self, real_val) -> None:
        payload = {"loginid": "CR12345", "is_virtual": real_val}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("deriv", payload)

    @pytest.mark.parametrize("malformed", [None, "1", "true", 1.0, 2, -1, [], {}])
    def test_malformed_is_virtual_fails_closed(self, malformed) -> None:
        payload = {"loginid": "CR12345", "is_virtual": malformed}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("deriv", payload)

    def test_missing_is_virtual_fails_closed(self) -> None:
        payload = {"loginid": "CR12345"}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("deriv", payload)

    def test_empty_account_data_fails_closed(self) -> None:
        with pytest.raises(UnsafeBrokerAccountError):
            DemoOnlyGuard.assert_demo_account("deriv", None)


class TestMT5DemoVerification:
    def test_demo_account_dict_passes(self, tmp_path) -> None:
        payload = {"login": 10001, "trade_mode": MT5_ACCOUNT_TRADE_MODE_DEMO}
        evidence_db = tmp_path / "mt5_evidence.sqlite3"
        result = DemoOnlyGuard.assert_demo_account(
            "mt5", payload, session_id="mt5-session", evidence_store_path=evidence_db
        )
        assert isinstance(result, DemoAccountVerification)
        assert result.broker == "mt5"
        assert result.account_id == "10001"
        assert result.checked_field == "trade_mode"
        assert result.observed_value == 0
        assert result.status == "PASSED"

    def test_demo_account_sdk_object_passes(self) -> None:
        account_obj = SimpleNamespace(login=55555, trade_mode=MT5_ACCOUNT_TRADE_MODE_DEMO)
        result = DemoOnlyGuard.assert_demo_account("mt5_demo", account_obj)
        assert result.account_id == "55555"
        assert result.observed_value == 0

    def test_real_account_trade_mode_raises(self) -> None:
        payload = {"login": 20002, "trade_mode": MT5_ACCOUNT_TRADE_MODE_REAL}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("mt5", payload)

    def test_contest_account_trade_mode_raises(self) -> None:
        payload = {"login": 30003, "trade_mode": MT5_ACCOUNT_TRADE_MODE_CONTEST}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("mt5", payload)

    @pytest.mark.parametrize("malformed", [None, "0", False, 0.0, 3, -1, "demo"])
    def test_malformed_trade_mode_fails_closed(self, malformed) -> None:
        payload = {"login": 10001, "trade_mode": malformed}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("mt5", payload)

    def test_missing_trade_mode_fails_closed(self) -> None:
        payload = {"login": 10001}
        with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
            DemoOnlyGuard.assert_demo_account("mt5", payload)

    def test_none_account_data_fails_closed(self) -> None:
        with pytest.raises(UnsafeBrokerAccountError):
            DemoOnlyGuard.assert_demo_account("mt5", None)


class TestDemoOnlyGuardGeneral:
    def test_unknown_broker_fails_closed(self) -> None:
        with pytest.raises(UnsafeBrokerAccountError, match="Unsupported broker"):
            DemoOnlyGuard.assert_demo_account("binance", {"trade_mode": 0})

    def test_guard_order_submission_with_valid_demo(self) -> None:
        provider = MagicMock(return_value={"login": 123, "trade_mode": 0})
        verification = DemoOnlyGuard.guard_order_submission("mt5", provider)
        assert verification.status == "PASSED"
        provider.assert_called_once()

    def test_guard_order_submission_with_real_raises(self) -> None:
        provider = MagicMock(return_value={"login": 123, "trade_mode": 2})
        with pytest.raises(UnsafeBrokerAccountError):
            DemoOnlyGuard.guard_order_submission("mt5", provider)

    def test_guard_order_submission_with_provider_error_fails_closed(self) -> None:
        provider = MagicMock(side_effect=RuntimeError("SDK disconnected"))
        with pytest.raises(UnsafeBrokerAccountError, match="Failed to fetch account data"):
            DemoOnlyGuard.guard_order_submission("mt5", provider)


class TestEvidencePersistence:
    def test_verification_persists_to_sqlite(self, tmp_path) -> None:
        db_path = tmp_path / "test_broker_evidence.sqlite3"
        payload = {"loginid": "VRTC100", "is_virtual": 1}
        DemoOnlyGuard.assert_demo_account(
            "deriv", payload, session_id="session-ev-1", evidence_store_path=db_path
        )

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT session_id, broker, account_id, checked_field, observed_value, status FROM broker_account_verifications"
            ).fetchone()
            assert row is not None
            assert row[0] == "session-ev-1"
            assert row[1] == "deriv"
            assert row[2] == "VRTC100"
            assert row[3] == "is_virtual"
            assert row[4] == 1
            assert row[5] == "PASSED"

    def test_verification_appends_to_campaign_evidence_store(self, tmp_path) -> None:
        mock_campaign_store = MagicMock()
        payload = {"login": 9999, "trade_mode": 0}
        DemoOnlyGuard.assert_demo_account(
            "mt5",
            payload,
            session_id="camp-session-42",
            campaign_evidence_store=mock_campaign_store,
        )
        mock_campaign_store.append.assert_called_once()
        args = mock_campaign_store.append.call_args[0]
        assert args[0] == "camp-session-42"
        event = args[1]
        assert event.event_type == "BROKER_ACCOUNT_VERIFIED"
        assert event.facts["broker"] == "mt5"
        assert event.facts["account_id"] == "9999"
        assert event.facts["observed_value"] == 0
        assert event.facts["check"] == "PASSED"
