"""Mocked coverage for the DEMO-only controlled trade preview workflow."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

import tools.demo_trade_preview as preview
from broker.types import (
    AccountInfo,
    ExecutionQuantity,
    ExecutionQuantityUnit,
    OrderResult,
    OrderStatus,
)
from core.exceptions import UnsafeBrokerAccountError
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
)
from tools.demo_trade_preview import (
    PreviewOnlyGateway,
    _SingleSubmissionExecutor,
    run,
)

WELTRADE_SYMBOLS = [{"symbol": "FX Vol 20"}, {"symbol": "FX Vol 75"}]
DERIV_SYMBOLS = [{"symbol": "1HZ100V"}, {"symbol": "R_75"}]

SPEC: dict[str, Any] = {
    "source": "MetaTrader5 symbol_info + order_calc_margin",
    "symbol": "FX Vol 20",
    "account_currency": "USD",
    "contract_size": 1.0,
    "tick_size": 0.01,
    "tick_value": 0.01,
    "point": 0.01,
    "digits": 2,
    "volume_min": 0.01,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "stops_level_points": 10,
    "minimum_stop_distance": 0.1,
    "minimum_volume_margin": 1.0,
}

QUANTITY_FACTS: dict[str, Any] = {
    "quantity_basis": "broker minimum volume",
    "volume_min": 0.01,
    "volume_step": 0.01,
    "authorized_risk_amount": 10.0,
    "expected_loss_at_stop": 0.72,
    "margin_requirement": 1.0,
    "free_margin": 9000.0,
}


@dataclass
class StubSettings:
    broker_execution_enabled: bool = False
    broker: str = "weltrade"
    selected_broker: str | None = "weltrade"
    environment: str = "development"
    emergency_stop: EmergencyStopState = EmergencyStopState.CLEAR
    risk_percent: float = 1.0
    execution_safety_freshness_seconds: int = 15
    broker_selection_store_path: Any = None
    execution_safety_store_path: Any = None
    intent_store_path: Any = None
    execution_position_ledger_path: Any = None
    execution_reservation_lease_seconds: int = 120
    deriv_app_id: int = 1089
    deriv_public_endpoint: str = "wss://example.invalid"

    def __post_init__(self) -> None:
        if self.broker_selection_store_path is None:
            self.broker_selection_store_path = "state/broker_selection.sqlite3"

    @property
    def effective_broker(self) -> str:
        return self.selected_broker or self.broker


class _Iloc:
    def __init__(self, latest: dict[str, Any]) -> None:
        self._latest = latest

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self._latest


class FakeFrame:
    """Minimal stand-in for the indicator dataframe consumed by the pipeline."""

    def __init__(self, latest: dict[str, Any]) -> None:
        self.index = ["2026-09-18T00:00:00+00:00"]
        self.iloc = _Iloc(latest)


class FakePlan:
    def __init__(
        self,
        *,
        signal: str = "BUY",
        entry: float = 100.0,
        stop_loss: float | None = 98.0,
        take_profit: float | None = 104.0,
        valid: bool = True,
    ) -> None:
        self.symbol = "FX VOL 20"
        self.signal = signal
        self.entry = entry
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.risk_reward = 2.0
        self.invalidation = None if valid else "stop-loss missing"
        self.warnings: list[str] = []
        self._valid = valid

    def is_valid(self) -> bool:
        return self._valid


class FakeGateway:
    def __init__(
        self,
        *,
        trade_mode: str = "demo",
        server: str = "Weltrade-Demo",
        demo_verified: bool = True,
        covers_today: bool = True,
        account_id: str = "43268111",
        balance: float = 1000.0,
    ) -> None:
        self.account = AccountInfo(
            account_id=account_id,
            balance=balance,
            currency="USD",
            equity=balance,
            server=server,
            trade_mode=trade_mode,
        )
        self.history = SimpleNamespace(
            trades=[], covers=lambda start, end: covers_today
        )
        self._demo_verified = demo_verified
        self.session_id = "weltrade-demo-test"
        self.is_connected = False
        self.connect_count = 0
        self.disconnect_count = 0
        self.candle_requests: list[tuple[str, int]] = []
        self.submit_calls: list[Any] = []

    async def __aenter__(self) -> "FakeGateway":
        self.connect_count += 1
        self.is_connected = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        self.disconnect_count += 1
        self.is_connected = False
        return False

    async def get_account_info(self) -> AccountInfo:
        return self.account

    async def get_candles(self, symbol: str, timeframe: Any, count: int, end: Any = None) -> list:
        self.candle_requests.append((symbol, count))
        return [SimpleNamespace(time=dt.datetime.now(dt.timezone.utc))]

    async def get_trade_history_snapshot(self, *, start: Any, end: Any, count: int = 100) -> Any:
        return self.history

    async def get_positions(self) -> list:
        return []

    async def submit_order(self, order: Any) -> OrderResult:
        self.submit_calls.append(order)
        return OrderResult(
            order_id="demo-order-1",
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value,
            filled_price=100.0,
        )


class FakeSafetyStore:
    def __init__(self, snapshot: ExecutionSafetySnapshot | None, error: Exception | None = None) -> None:
        self._snapshot = snapshot
        self._error = error

    def __call__(self, path: Any, initialize: bool = False) -> "FakeSafetyStore":
        return self

    def read(self) -> ExecutionSafetySnapshot | None:
        if self._error is not None:
            raise self._error
        return self._snapshot


def _snapshot(*, age_seconds: float = 1.0, emergency: str = "CLEAR") -> ExecutionSafetySnapshot:
    return ExecutionSafetySnapshot(
        observed_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=age_seconds),
        emergency_stop_state=EmergencyStopState(emergency),
        execution_mode=ExecutionMode.DURABLE,
        broker="weltrade",
        environment="development",
        durable_executor_enabled=True,
        daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
        unresolved_intent_count=0,
        unresolved_intent_blocked=False,
        execution_authorization=ExecutionAuthorization.NOT_EVALUATED,
        reason_codes=("NOT_EVALUATED",),
    )


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "preview": True,
        "submit_one_demo_order": False,
        "broker": None,
        "symbol": None,
        "timeframe": "H1",
        "count": 300,
        "json_out": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@dataclass
class Harness:
    settings: StubSettings
    gateway: FakeGateway
    constructed: list[Any] = field(default_factory=list)
    risk: dict[str, Any] = field(default_factory=dict)
    plan: FakePlan = field(default_factory=FakePlan)
    quantity: ExecutionQuantity | None = None
    quantity_facts: dict[str, Any] = field(default_factory=dict)
    quantity_blocker: str | None = None
    spec: dict[str, Any] | None = None
    reverifications: list[str] = field(default_factory=list)


@pytest.fixture
def harness(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    settings = StubSettings(
        broker_selection_store_path=tmp_path / "selection.sqlite3",
        execution_safety_store_path=tmp_path / "safety.sqlite3",
        intent_store_path=tmp_path / "missing-intents.sqlite3",
        execution_position_ledger_path=tmp_path / "ledger.sqlite3",
    )
    gateway = FakeGateway()
    built = Harness(settings=settings, gateway=gateway)
    built.risk = {
        "approved": True,
        "reason": "Approved",
        "reason_code": "APPROVED",
        "risk_percent": 1.0,
        "authorized_risk_amount": 10.0,
    }
    built.quantity = ExecutionQuantity(value=0.01, unit=ExecutionQuantityUnit.MT5_LOTS)
    built.quantity_facts = dict(QUANTITY_FACTS)
    built.spec = dict(SPEC)

    monkeypatch.setenv(preview._AUTHORIZATION_ENV, "1")
    monkeypatch.setattr(preview, "Settings", lambda: settings)
    monkeypatch.setattr(preview, "SQLiteExecutionSafetyStore", FakeSafetyStore(_snapshot()))

    def fake_get_gateway(active: Any) -> FakeGateway:
        built.constructed.append(active)
        return gateway

    monkeypatch.setattr(preview, "get_gateway", fake_get_gateway)
    monkeypatch.setattr(preview, "_discover_weltrade_symbols", lambda: list(WELTRADE_SYMBOLS))

    async def fake_discover_deriv(_settings: Any) -> list[dict[str, Any]]:
        return list(DERIV_SYMBOLS)

    monkeypatch.setattr(preview, "_discover_deriv_symbols", fake_discover_deriv)
    monkeypatch.setattr(
        preview,
        "_closed_frame",
        lambda candles, timeframe: (
            FakeFrame({"close": 100.0, "ATR": 1.0, "time": "2026-09-18T00:00:00+00:00"}),
            {"status": "OK", "candles_returned": len(candles), "candles_closed": len(candles)},
        ),
    )
    monkeypatch.setattr(preview, "detect_regime", lambda df: "TRENDING")
    monkeypatch.setattr(
        preview,
        "generate_trading_signal",
        lambda df, symbol, regime=None: {
            "signal": "BUY",
            "confidence": 82,
            "intelligence": {"atr": 1.0},
        },
    )
    monkeypatch.setattr(preview, "approve_trade", lambda *a, **k: dict(built.risk))
    monkeypatch.setattr(preview, "get_reconciled_daily_state", lambda: (0.0, 0, 3.0, 5))
    monkeypatch.setattr(preview, "reconcile_daily_history", lambda trades, balance: None)
    monkeypatch.setattr(
        preview,
        "TradePlanBuilder",
        lambda **kwargs: SimpleNamespace(build=lambda **build_kwargs: built.plan),
    )

    async def fake_spec(_gateway: Any, symbol: str) -> dict[str, Any]:
        if built.spec is None:
            raise ValueError("spec unavailable")
        return dict(built.spec)

    async def fake_quantity(_gateway: Any, spec: dict[str, Any], **kwargs: Any) -> tuple:
        return built.quantity, dict(built.quantity_facts), built.quantity_blocker

    monkeypatch.setattr(preview, "_weltrade_instrument_spec", fake_spec)
    monkeypatch.setattr(preview, "_weltrade_quantity", fake_quantity)

    async def fake_reverify(_gateway: Any, broker: str, _account: Any) -> dict[str, Any]:
        built.reverifications.append(broker)
        return {"guard_broker": broker, "verified": True}

    monkeypatch.setattr(preview, "_reverify_demo", fake_reverify)
    return built


def _steps(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["step"]: step for step in report["steps"]}


async def test_missing_environment_gate_blocks_without_broker_contact(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv(preview._AUTHORIZATION_ENV, raising=False)
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "BLOCKED" in capsys.readouterr().out


async def test_broker_execution_enabled_blocks(harness: Harness, capsys) -> None:
    harness.settings.broker_execution_enabled = True
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "JQE_BROKER_EXECUTION_ENABLED must remain false" in capsys.readouterr().out


async def test_simulation_is_never_used_as_a_fallback(harness: Harness, capsys) -> None:
    harness.settings.selected_broker = "simulation"
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "never used as a fallback" in capsys.readouterr().out


async def test_mt5_selection_is_rejected(harness: Harness, capsys) -> None:
    harness.settings.selected_broker = "mt5"
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "not a supported demo broker" in capsys.readouterr().out


async def test_requested_broker_must_match_the_selection(harness: Harness, capsys) -> None:
    assert await run(_args(broker="deriv")) == 2
    assert harness.constructed == []
    assert "does not match the selected broker" in capsys.readouterr().out


async def test_active_emergency_stop_blocks_before_broker_contact(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        preview, "SQLiteExecutionSafetyStore", FakeSafetyStore(_snapshot(emergency="ACTIVE"))
    )
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "Emergency stop is ACTIVE" in capsys.readouterr().out


async def test_configured_emergency_stop_blocks(harness: Harness, capsys) -> None:
    harness.settings.emergency_stop = EmergencyStopState.ACTIVE
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "Configured emergency stop is ACTIVE" in capsys.readouterr().out


async def test_missing_safety_snapshot_blocks(harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(preview, "SQLiteExecutionSafetyStore", FakeSafetyStore(None))
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "Execution safety snapshot is NOT_OBSERVED" in payload
    assert harness.gateway.submit_calls == []


async def test_stale_safety_snapshot_blocks(harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        preview, "SQLiteExecutionSafetyStore", FakeSafetyStore(_snapshot(age_seconds=600.0))
    )
    assert await run(_args()) == 1
    assert "Execution safety snapshot is STALE" in capsys.readouterr().out
    assert harness.gateway.submit_calls == []


async def test_unreadable_safety_snapshot_blocks(harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        preview, "SQLiteExecutionSafetyStore", FakeSafetyStore(None, error=RuntimeError("locked"))
    )
    assert await run(_args()) == 1
    assert "Execution safety snapshot is UNAVAILABLE" in capsys.readouterr().out


async def test_unresolved_durable_intent_blocks_before_broker_contact(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(preview, "_unresolved_intents", lambda settings: (2, "2 unresolved durable execution intent(s) must be resolved first"))
    assert await run(_args()) == 2
    assert harness.constructed == []
    assert "unresolved durable execution intent(s)" in capsys.readouterr().out


async def test_preview_mode_never_submits(harness: Harness, capsys) -> None:
    import json

    assert await run(_args()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "PREVIEW_READY"
    assert payload["mode"] == "PREVIEW"
    assert payload["blockers"] == []
    assert harness.gateway.submit_calls == []
    assert harness.gateway.connect_count == 1
    assert harness.gateway.disconnect_count == 1

    steps = _steps(payload)
    assert steps["4-gateway"]["detail"]["wrapper"] == "PreviewOnlyGateway"
    assert steps["4-gateway"]["detail"]["submission_possible"] is False
    assert steps["13-policy-preview"]["detail"]["allowed"] is False
    assert steps["13-policy-preview"]["detail"]["code"] == "DEPLOYMENT_NOT_AUTHORIZED"
    assert steps["14-policy-if-submitted"]["detail"]["allowed"] is True
    assert steps["7-symbol-discovery"]["detail"]["selected_symbol"] == "FX Vol 20"
    assert "15-demo-reverification" not in steps
    assert "16-submission" not in steps

    previewed = payload["preview"]
    assert previewed["broker"] == "weltrade"
    assert previewed["server"] == "Weltrade-Demo"
    assert previewed["account_id_masked"] == "******8111"
    assert previewed["symbol"] == "FX Vol 20"
    assert previewed["side"] == "BUY"
    assert previewed["quantity"] == {"value": 0.01, "unit": "MT5_LOTS"}
    assert previewed["entry_price"] == 100.0
    assert previewed["stop_loss"] == 98.0
    assert previewed["take_profit"] == 104.0
    assert previewed["order_type"] == "MARKET"
    assert previewed["risk"]["reason_code"] == "APPROVED"
    assert previewed["idempotency_key"].startswith("jqe-v2-")
    assert previewed["instrument_spec"]["minimum_stop_distance"] == 0.1


async def test_preview_gateway_makes_submission_impossible() -> None:
    inner = FakeGateway()
    gateway = PreviewOnlyGateway(inner)
    with pytest.raises(AssertionError):
        await gateway.submit_order(object())
    assert gateway.submission_attempts == 1
    assert inner.submit_calls == []


async def test_submission_executor_permits_exactly_one_submission() -> None:
    class StubExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, Any]] = []

        async def submit(self, intent: Any, context: Any) -> Any:
            self.calls.append((intent, context))
            return SimpleNamespace(order_id="demo-order-1")

    inner = StubExecutor()
    capped = _SingleSubmissionExecutor(inner)
    result = await capped.submit("intent", "context")
    assert result.order_id == "demo-order-1"
    assert capped.submissions == 1
    with pytest.raises(AssertionError):
        await capped.submit("intent", "context")
    assert capped.submissions == 1
    assert len(inner.calls) == 1


async def test_live_account_is_rejected(harness: Harness, capsys) -> None:
    harness.gateway.account = AccountInfo(
        account_id="43268111",
        balance=1000.0,
        currency="USD",
        server="Weltrade-Live",
        trade_mode="real",
    )
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "not 'demo'" in payload
    assert harness.gateway.candle_requests == []
    assert harness.gateway.submit_calls == []


async def test_unverified_demo_guard_is_rejected(harness: Harness, capsys) -> None:
    harness.gateway._demo_verified = False
    assert await run(_args()) == 1
    assert "did not verify the account as DEMO" in capsys.readouterr().out
    assert harness.gateway.submit_calls == []


async def test_non_weltrade_terminal_is_rejected(harness: Harness, capsys) -> None:
    harness.gateway.account = AccountInfo(
        account_id="43268111",
        balance=1000.0,
        currency="USD",
        server="OtherBroker-Demo",
        trade_mode="demo",
    )
    assert await run(_args()) == 1
    assert "not a Weltrade server" in capsys.readouterr().out


async def test_symbol_must_be_confirmed_by_the_broker(harness: Harness, capsys) -> None:
    assert await run(_args(symbol="R_999")) == 1
    payload = capsys.readouterr().out
    assert "was not confirmed by the broker" in payload
    assert harness.gateway.candle_requests == []


async def test_risk_rejection_blocks_the_preview(harness: Harness, capsys) -> None:
    harness.risk.update({"approved": False, "reason": "No trade signal", "reason_code": "NO_TRADE_SIGNAL"})
    harness.plan = FakePlan(signal="HOLD", stop_loss=None, take_profit=None, valid=False)
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "Risk engine did not approve the trade: NO_TRADE_SIGNAL" in payload
    assert harness.gateway.submit_calls == []


async def test_missing_stop_loss_blocks(harness: Harness, capsys) -> None:
    harness.plan = FakePlan(stop_loss=None, take_profit=104.0, valid=False)
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "Mandatory stop-loss and take-profit are not present" in payload
    assert "Trade plan invariants failed" in payload


async def test_invalid_quantity_blocks(harness: Harness, capsys) -> None:
    harness.quantity = None
    harness.quantity_blocker = "Minimum broker volume risks 40.00, above the authorized risk of 10.00"
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "above the authorized risk" in payload
    assert harness.gateway.submit_calls == []


async def test_missing_instrument_spec_blocks(harness: Harness, capsys) -> None:
    harness.spec = None
    assert await run(_args()) == 1
    assert "Broker instrument specification is unavailable" in capsys.readouterr().out


async def test_non_authoritative_daily_history_blocks_submission(harness: Harness, capsys) -> None:
    harness.gateway.history = SimpleNamespace(trades=[], covers=lambda start, end: False)
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "does not prove complete coverage" in payload
    assert "DAILY_STATE_NOT_AUTHORITATIVE" in payload


async def test_submit_mode_refuses_while_blockers_remain(harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        preview, "SQLiteExecutionSafetyStore", FakeSafetyStore(_snapshot(age_seconds=600.0))
    )
    assert await run(_args(preview=False, submit_one_demo_order=True)) == 1
    assert harness.gateway.submit_calls == []
    assert harness.reverifications == []
    assert "REFUSED" in capsys.readouterr().out


async def test_submit_mode_places_at_most_one_demo_order(
    harness: Harness, tmp_path, capsys
) -> None:
    import json

    harness.settings.intent_store_path = tmp_path / "intents.sqlite3"
    assert await run(_args(preview=False, submit_one_demo_order=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "SUBMITTED_ONE_DEMO_ORDER"
    assert payload["mode"] == "SUBMIT_ONE"
    assert harness.reverifications == ["weltrade"]
    assert len(harness.gateway.submit_calls) == 1
    order = harness.gateway.submit_calls[0]
    assert order.symbol == "FX VOL 20"
    assert order.stop_loss == 98.0
    assert order.take_profit == 104.0
    assert order.quantity.unit is ExecutionQuantityUnit.MT5_LOTS

    submission = payload["submission"]
    assert submission["submitted"] == 1
    assert submission["broker"] == "weltrade"
    assert submission["account_id_masked"] == "******8111"
    assert submission["order_type"] == "MARKET"
    assert submission["side"] == "BUY"
    assert submission["quantity"] == {"value": 0.01, "unit": "MT5_LOTS"}
    assert submission["order_id"] == "demo-order-1"
    assert harness.gateway.disconnect_count == 1


async def test_reverification_rejects_a_live_mt5_account(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_mt5 = SimpleNamespace(
        account_info=lambda: SimpleNamespace(login=42, server="Weltrade-Live", trade_mode=2)
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    monkeypatch.setattr(
        "broker.demo_guard.DEFAULT_BROKER_EVIDENCE_PATH",
        Path(tmp_path / "evidence.sqlite3"),
    )
    gateway = PreviewOnlyGateway(FakeGateway())
    account = AccountInfo(account_id="42", balance=100.0, currency="USD", trade_mode="real")
    with pytest.raises(UnsafeBrokerAccountError):
        await preview._reverify_demo(gateway, "weltrade", account)


async def test_deriv_preview_reports_fail_closed_quantity_and_stop_semantics(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    harness.settings.selected_broker = "deriv"
    harness.gateway.account = AccountInfo(
        account_id="VRTC10086175",
        balance=1000.0,
        currency="USD",
        server="deriv",
        trade_mode="demo",
    )
    harness.gateway._demo_verified = True

    async def fake_spec(_gateway: Any, symbol: str, side: Any, currency: str) -> dict[str, Any]:
        return {
            "source": "Deriv active_symbols + contracts_for + read-only proposal",
            "provider_symbol": symbol,
            "contract_type": "MULTUP",
            "quantity_basis": "stake",
            "multiplier_values": ["500"],
            "minimum_quantity": 0.35,
            "stop_loss_advertised": True,
            "take_profit_advertised": True,
        }

    monkeypatch.setattr(preview, "_deriv_instrument_spec", fake_spec)
    assert await run(_args()) == 1
    payload = capsys.readouterr().out
    assert "account-currency amounts" in payload
    assert "loss-model" in payload
    assert harness.gateway.submit_calls == []


async def test_report_records_every_gate(harness: Harness, capsys) -> None:
    import json

    await run(_args())
    payload = json.loads(capsys.readouterr().out)
    recorded = [step["step"] for step in payload["steps"]]
    for expected in (
        "1-authorization-gate",
        "2-broker-selection",
        "3-safety-state",
        "4-gateway",
        "5-connect",
        "6-demo-identity",
        "7-symbol-discovery",
        "8-market-data",
        "9-risk-approval",
        "10-trade-plan",
        "11-instrument-spec",
        "12-quantity",
        "13-policy-preview",
        "14-policy-if-submitted",
    ):
        assert expected in recorded
