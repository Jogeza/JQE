"""Tests for the live-paper campaign runner with real demo broker execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.mt5_stubs import activate_gateway, release_gateway

from broker.demo_guard import DemoOnlyGuard
from broker.deriv_demo import DerivDemoGateway
from broker.mt5_demo import MT5DemoGateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from broker.types import (
    AccountInfo,
    Candle,
    ExecutionQuantity,
    ExecutionQuantityUnit,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
    Timeframe,
)
from config import settings
from core.exceptions import ConfigurationError, UnsafeBrokerAccountError
from execution.executor import ReconciliationState
from execution.persistence import SQLitePositionLedger
from execution.policy import ExecutionDecisionCode
from research.campaign_provenance import CampaignEvidenceStore
from research.live_safety import LivePaperSafetyContext
from tools import live_paper_campaign
from tools.live_paper_campaign import (
    _OrderSpacingGuard,
    _round_lots_to_broker_constraints,
    run_live_paper_campaign,
)


@pytest.mark.asyncio
async def test_campaign_sends_factual_no_trade_signal_to_telegram(
    tmp_path, monkeypatch
):
    gateway = MockMT5DemoGateway()
    telegram = AsyncMock()
    monkeypatch.setattr(settings, "telegram_enabled", True)
    monkeypatch.setattr(
        live_paper_campaign, "telegram_gateway_from_settings", lambda _settings: telegram
    )

    async def no_trade(_window):
        return {"signal": "NO_TRADE", "confidence": 41}, {
            "signal_direction": "NO_TRADE",
            "signal_confidence": 41,
            "regime": "RANGE",
        }

    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", no_trade)
    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        gateway=gateway,
        output=tmp_path / "telegram-summary.json",
        max_candles=1,
    )

    telegram.send.assert_awaited_once()
    notification = telegram.send.await_args.args[0]
    assert "NO_TRADE / ANALYSIS ONLY" in notification.title
    assert notification.facts["Symbol / timeframe"] == "XAUUSD / M15"
    assert notification.facts["Conclusion"] == "NO_TRADE"
    assert notification.facts["Quality score"] == "41"
    assert notification.facts["Data freshness"] in {"fresh", "stale", "degraded"}
    assert "Observed at" in notification.facts
    assert "Candle closed at" in notification.facts
    assert "Expires at" in notification.facts
    assert gateway.submitted_orders == []
    signal_event = next(
        event
        for event in CampaignEvidenceStore(
            Path(summary["session"]["evidence_path"])
        ).events(summary["session"]["session_id"])
        if event["event_type"] == "SIGNAL"
    )
    assert signal_event["facts"]["conclusion"] == "NO_TRADE"
    assert signal_event["facts"]["quality_score"] == 41
    assert signal_event["facts"]["data_freshness"] in {
        "fresh", "stale", "degraded", "cached"
    }


def _generate_candles(count: int, start: datetime | None = None) -> list[Candle]:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(minutes=15)
    return [
        Candle(
            time=start + (i * interval),
            open=2000.0 + (i * 0.1),
            high=2002.0 + (i * 0.1),
            low=1999.0 + (i * 0.1),
            close=2001.0 + (i * 0.1),
            volume=100.0,
            source="mt5",
        )
        for i in range(count)
    ]


def _mock_candidate(ts: datetime, direction: str = "BUY") -> MagicMock:
    cand = MagicMock()
    cand.signal_candle = ts
    cand.direction = direction
    cand.expected_entry_candle = ts + timedelta(minutes=30)
    cand.strategy_context = {
        "signal": {"signal": direction, "confidence": 85, "features": {"atr_14": 1.5}},
        "regime": "TREND_UP",
    }
    cand.confirmation_reason = "TEST"
    return cand


class MockMT5DemoGateway(MT5DemoGateway):
    """Subclass of MT5DemoGateway for isolated live-paper testing."""

    def __init__(self, account_id: str = "12345", balance: float = 10000.0) -> None:
        super().__init__(login=int(account_id), server="DemoServer")
        self._mock_account_id = account_id
        self._mock_balance = balance
        activate_gateway(self)
        self._demo_verified = True
        self.submitted_orders: list[OrderRequest] = []
        self._mock_positions: list[Position] = []
        self._candle_call_count = 0

    async def connect(self) -> None:
        activate_gateway(self)
        self._demo_verified = True

    async def disconnect(self) -> None:
        release_gateway(self)

    async def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            account_id=self._mock_account_id,
            balance=self._mock_balance,
            currency="USD",
            equity=self._mock_balance,
        )

    async def verify_instrument_risk_spec(self, symbol: str):
        return {
            "symbol": symbol, "account_currency": "USD", "contract_size": 100.0,
            "tick_size": 0.01, "tick_value": 1.0, "tick_value_profit": 1.0,
            "tick_value_loss": 1.0, "point": 0.01, "point_value": 1.0,
            "volume_min": 0.01, "minimum_volume_margin": 20.0,
        }

    async def authorize_account_currency_risk(
        self, *, symbol, side, balance, risk_percent, entry, stop_loss,
    ):
        risk = balance * risk_percent / 100.0
        quantity = ExecutionQuantity(value=0.1, unit=ExecutionQuantityUnit.MT5_LOTS)
        return quantity, {
            "authorized_risk_amount": risk,
            "expected_loss_at_stop": min(risk, 10.0),
            "margin_requirement": 20.0,
        }

    async def get_candles(self, symbol: str, timeframe: Timeframe, count: int, end: datetime | None = None) -> list[Candle]:
        self._candle_call_count += 1
        start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * self._candle_call_count)
        return _generate_candles(count, start=start)

    async def get_positions(self) -> list[Position]:
        return list(self._mock_positions)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        DemoOnlyGuard.assert_demo_account("mt5", {"trade_mode": 0})
        self.submitted_orders.append(order)
        order_id = f"ORDER-{len(self.submitted_orders)}"
        pos = Position(
            position_id=order_id,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value,
            open_price=2000.0,
            current_price=2000.0,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
        )
        self._mock_positions.append(pos)
        return OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value,
            filled_price=2000.0,
        )


class MockDerivDemoGateway(DerivDemoGateway):
    """Deriv demo gateway with deterministic in-memory broker observations."""

    def __init__(self, positions: list[Position] | None = None) -> None:
        super().__init__(api_token="test-token", app_id="test-app")
        self._connected = True
        self._demo_verified = True
        self._account_id = "VRTC90001"
        self._currency = "USD"
        self._mock_positions = list(positions or [])
        self.submitted_orders: list[OrderRequest] = []
        self._candle_call_count = 0

    async def connect(self) -> None:
        self._connected = True
        self._demo_verified = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            account_id=self._account_id,
            balance=10000.0,
            currency="USD",
            equity=10000.0,
        )

    async def get_candles(self, symbol, timeframe, count, end=None) -> list[Candle]:
        self._candle_call_count += 1
        start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            minutes=15 * self._candle_call_count
        )
        return _generate_candles(count, start=start)

    async def get_positions(self) -> list[Position]:
        return list(self._mock_positions)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self.submitted_orders.append(order)
        position_id = f"CONTRACT-{len(self.submitted_orders)}"
        self._mock_positions.append(
            Position(
                position_id=position_id,
                symbol=order.symbol,
                side=order.side,
                volume=order.quantity.value,
                open_price=10.0,
                current_price=10.0,
            )
        )
        return OrderResult(
            order_id=position_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value,
            filled_price=10.0,
        )


@pytest.fixture(autouse=True)
def configure_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "campaign_mode", "live_paper")
    monkeypatch.setattr(settings, "broker_execution_enabled", True)
    monkeypatch.setattr(settings, "broker", "mt5_demo")
    monkeypatch.setattr(settings, "deriv_expected_environment", "demo")
    monkeypatch.setattr(settings, "risk_percent", 1.0)
    monkeypatch.setattr(settings, "max_daily_loss", 5.0)
    monkeypatch.setattr(settings, "max_trades_daily", 20)
    monkeypatch.setattr(settings, "live_paper_min_order_spacing_seconds", 0.0)
    monkeypatch.setattr(settings, "live_paper_order_poll_timeout_seconds", 0.01)
    monkeypatch.setattr(
        settings, "execution_lifetime_store_path", tmp_path / "lifetime.sqlite3"
    )
    monkeypatch.setattr(settings, "live_paper_max_candles", 5)
    monkeypatch.setattr(settings, "live_paper_max_duration_seconds", None)
    monkeypatch.setattr(settings, "telegram_enabled", False)


# 1. Happy path: N candles, mock gateway FILLED, POSITION_OPENED recorded
@pytest.mark.asyncio
async def test_happy_path_completes_and_records_position_opened(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "summary.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}

    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")

    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=2,
    )

    assert summary["session"]["status"] == "COMPLETED"
    assert output_path.is_file()

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    event_types = [e["event_type"] for e in events]
    assert "POSITION_OPENED" in event_types

    opened = next(e for e in events if e["event_type"] == "POSITION_OPENED")
    facts = opened["facts"]
    assert facts["broker_order_id"] == "ORDER-1"
    assert facts["broker_fill_price"] == 2000.0
    assert facts["partial_fill"] is False
    assert facts["campaign_mode"] == "live_paper"
    ledger_entries = SQLitePositionLedger(
        summary["session"]["position_ledger_path"]
    ).open_entries(broker="mt5_demo")
    assert len(ledger_entries) == 1
    assert ledger_entries[0].position_id == "ORDER-1"
    assert ledger_entries[0].order_id == "ORDER-1"


# 2. Non-demo gateway (SimulationGateway) raises ConfigurationError
@pytest.mark.asyncio
async def test_non_demo_gateway_raises_configuration_error(tmp_path):
    sim_gateway = SimulationGateway()
    with pytest.raises(ConfigurationError, match="requires DerivDemoGateway or MT5DemoGateway"):
        await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=sim_gateway,  # type: ignore
            output=tmp_path / "out.json",
        )


# 3. broker_execution_enabled=False in settings raises ConfigurationError
@pytest.mark.asyncio
async def test_broker_execution_disabled_raises_configuration_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "broker_execution_enabled", False)
    gateway = MockMT5DemoGateway()
    with pytest.raises(ConfigurationError, match="broker_execution_enabled must be True"):
        await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=gateway,
            output=tmp_path / "out.json",
        )


# 4. broker="simulation" + campaign_mode="live_paper" raises ConfigurationError
@pytest.mark.asyncio
async def test_simulation_broker_raises_configuration_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "broker", "simulation")
    gateway = MockMT5DemoGateway()
    with pytest.raises(ConfigurationError, match="requires demo broker"):
        await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=gateway,
            output=tmp_path / "out.json",
        )


@pytest.mark.asyncio
async def test_deriv_gateway_configuration_mismatch_fails_before_connect(tmp_path, monkeypatch):
    gateway = MockDerivDemoGateway()
    connect = AsyncMock()
    monkeypatch.setattr(gateway, "connect", connect)
    monkeypatch.setattr(settings, "broker", "mt5_demo")
    with pytest.raises(ConfigurationError, match="gateway/configuration mismatch"):
        await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=gateway,
            output=tmp_path / "out.json",
            max_candles=1,
        )
    connect.assert_not_awaited()


# 5. Stop by candle count
@pytest.mark.asyncio
async def test_stop_by_candle_count(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"

    counter = 0
    async def get_advancing_candles(symbol, timeframe, count, end=None):
        nonlocal counter
        counter += 1
        return _generate_candles(count, start=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * counter))

    monkeypatch.setattr(gateway, "get_candles", get_advancing_candles)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        max_candles=3,
    )
    assert summary["session"]["status"] == "COMPLETED"
    assert summary["session"]["processed_candles"] == 3


# 6. Stop by wall-clock duration
@pytest.mark.asyncio
async def test_stop_by_wall_clock_duration(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"

    monkeypatch.setattr(settings, "live_paper_max_candles", None)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        max_duration_seconds=0.1,
        poll_interval_seconds=0.02,
    )
    assert summary["session"]["status"] == "COMPLETED"


# 7. Broker REJECTED order -> ENTRY evidence with broker_rejection_reason
@pytest.mark.asyncio
async def test_broker_rejected_order_records_entry_rejection(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    async def mock_reject(order: OrderRequest) -> OrderResult:
        return OrderResult(
            order_id="",
            status=OrderStatus.REJECTED,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value,
            raw={"retcode": 10015, "comment": "Invalid volume"},
        )

    monkeypatch.setattr(gateway, "submit_order", mock_reject)

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=1,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    entries = [e for e in events if e["event_type"] == "ENTRY" and e["facts"].get("result") == "REJECTED"]
    assert len(entries) >= 1
    assert "broker_rejection_reason" in entries[0]["facts"]


# 8. Partial fill (MT5)
@pytest.mark.asyncio
async def test_partial_fill_handling(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    async def mock_partial(order: OrderRequest) -> OrderResult:
        order_id = "PARTIAL-1"
        pos = Position(
            position_id=order_id,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value / 2.0,
            open_price=2000.0,
            current_price=2000.0,
        )
        gateway._mock_positions.append(pos)
        return OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.quantity.value / 2.0,
            filled_price=2000.0,
        )

    monkeypatch.setattr(gateway, "submit_order", mock_partial)

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=1,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    opened = next(e for e in events if e["event_type"] == "POSITION_OPENED")
    assert opened["facts"]["partial_fill"] is True
    assert opened["facts"]["filled_volume"] < opened["facts"]["requested_volume"]


# 9. Idempotency: retry same key
@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_submission(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    fixed_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    def mock_observe(self, ts, regime):
        cand = _mock_candidate(fixed_time, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=1,
    )
    assert len(gateway.submitted_orders) == 1


# 10. Position count reconciliation mismatch
@pytest.mark.asyncio
async def test_broker_position_mismatch_reconciliation(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    cycle = 0
    async def get_pos():
        nonlocal cycle
        cycle += 1
        if cycle <= 2:
            return [Position(position_id="ORDER-1", symbol="XAUUSD", side=OrderSide.BUY, volume=0.01, open_price=2000.0, current_price=2000.0)]
        return []

    monkeypatch.setattr(gateway, "get_positions", get_pos)

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    counter = 0
    async def get_advancing_candles(symbol, timeframe, count, end=None):
        nonlocal counter
        counter += 1
        return _generate_candles(count, start=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * counter))
    monkeypatch.setattr(gateway, "get_candles", get_advancing_candles)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=3,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    mismatch_events = [e for e in events if e["facts"].get("reason_code") == "BROKER_POSITION_MISMATCH"]
    assert len(mismatch_events) >= 1


# 11. Durable account lifetime cap blocks a second submission
@pytest.mark.asyncio
async def test_durable_lifetime_cap_blocks_second_submission(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    counter = 0
    async def get_advancing_candles(symbol, timeframe, count, end=None):
        nonlocal counter
        counter += 1
        if counter > 1:
            gateway._mock_positions.clear()
        return _generate_candles(count, start=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * counter))
    monkeypatch.setattr(gateway, "get_candles", get_advancing_candles)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=3,
    )

    assert len(gateway.submitted_orders) == 1
    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    blocked = [
        e for e in events
        if e["facts"].get("reason_code") == "ACCOUNT_LIFETIME_CAP_CONSUMED"
    ]
    assert len(blocked) >= 1
    assert blocked[0]["facts"]["account_scope"] == "mt5:12345"
    from execution.persistence import SQLiteOneShotExecutionGuard
    guard = SQLiteOneShotExecutionGuard(settings.execution_lifetime_store_path)
    assert guard.count("mt5:12345") == 1


# 12. Minimum spacing violated
def test_order_rate_guard_spacing():
    guard = _OrderSpacingGuard(min_spacing_seconds=60.0)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    allowed, code = guard.check_and_record(now)
    assert allowed is True
    assert code == "ALLOWED"

    too_soon = now + timedelta(seconds=30)
    allowed, code = guard.check_and_record(too_soon)
    assert allowed is False
    assert code == "MIN_SPACING_VIOLATED"

    ok_time = now + timedelta(seconds=61)
    allowed, code = guard.check_and_record(ok_time)
    assert allowed is True
    assert code == "ALLOWED"


# 13. Lot rounds to 0 / below volume_min
def test_round_lots_to_broker_constraints():
    mock_sym = MagicMock(volume_step=0.01, volume_min=0.05)
    assert _round_lots_to_broker_constraints(mock_sym, 0.04) is None
    assert _round_lots_to_broker_constraints(mock_sym, 0.07) == 0.07
    assert _round_lots_to_broker_constraints(mock_sym, 0.078) == 0.07


# 14. DemoOnlyGuard on submit path is verified
@pytest.mark.asyncio
async def test_demo_guard_assert_demo_account_called_on_submit(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    with patch.object(DemoOnlyGuard, "assert_demo_account", wraps=DemoOnlyGuard.assert_demo_account) as mock_guard:
        await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=gateway,
            output=output_path,
            max_candles=1,
        )
        assert mock_guard.call_count >= 1


# 15. Real-account connect rejection
@pytest.mark.asyncio
async def test_real_account_connect_rejection(tmp_path):
    gateway = MockMT5DemoGateway()
    gateway._demo_verified = False

    async def mock_connect():
        raise UnsafeBrokerAccountError("Cannot connect to real account")

    gateway.connect = mock_connect  # type: ignore

    with pytest.raises(UnsafeBrokerAccountError):
        await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=gateway,
            output=tmp_path / "out.json",
            max_candles=1,
        )


# 16. Evidence field shape matches historical
@pytest.mark.asyncio
async def test_evidence_field_shape_matches_historical(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=1,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    opened = next(e for e in events if e["event_type"] == "POSITION_OPENED")
    facts = opened["facts"]

    expected_keys = {
        "candidate_id", "symbol", "side", "requested_price", "broker_order_id",
        "broker_fill_price", "broker_fill_time", "slippage", "requested_volume",
        "filled_volume", "partial_fill", "campaign_mode", "session_kind",
    }
    assert expected_keys.issubset(set(facts.keys()))


# 17. Pending order timeout
@pytest.mark.asyncio
async def test_pending_order_timeout(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    with patch("tools.live_paper_campaign.AsyncTradeExecutor.submit") as mock_submit:
        decision = MagicMock(allowed=True, code=ExecutionDecisionCode.ALLOWED, reason="OK")
        mock_submit.return_value = MagicMock(
            state=ReconciliationState.PENDING,
            decision=decision,
            order_id="",
            reason="Order pending",
        )

        async def mock_strategy(window):
            return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
        monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

        def mock_observe(self, ts, regime):
            cand = _mock_candidate(ts, "BUY")
            return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
        monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

        summary = await run_live_paper_campaign(
            symbol="XAUUSD",
            gateway=gateway,
            output=output_path,
            evidence_path=evidence_path,
            max_candles=1,
        )

        store = CampaignEvidenceStore(evidence_path)
        events = store.events(summary["session"]["session_id"])
        timeout_events = [e for e in events if e["event_type"] == "ENTRY_TIMEOUT"]
        assert len(timeout_events) >= 1


# 18. MT5 confirmed SL-hit records honest exit_reason "BROKER_SL"
@pytest.mark.asyncio
async def test_mt5_close_reason_sl_confirmed(tmp_path, monkeypatch):
    """When history_deals_get returns a DEAL_REASON_SL closing deal,
    the POSITION_CLOSED evidence must carry exit_reason='BROKER_SL',
    not the fabricated 'BROKER_SL_TP' label.
    """
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    # Seed one open position that will disappear after the first candle.
    order_id = "SL-HIT-001"
    gateway._mock_positions.append(Position(
        position_id=order_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.01,
        open_price=2000.0,
        current_price=1990.0,
    ))
    # Add order_id to the local trade tracking so the campaign knows it's ours.
    # We exercise _fetch_mt5_close_reason by having the position disappear.
    # The campaign will query history_deals_get after position disappears.

    # Mock history_deals_get to return a closing deal with reason=4 (DEAL_REASON_SL).
    sl_deal = MagicMock()
    sl_deal.position_id = order_id
    sl_deal.reason = 4  # _MT5_DEAL_REASON_SL -> "BROKER_SL"
    sl_deal.time = 1700000000
    sl_deal.price = 1990.0
    sl_deal.profit = -12.5
    sl_deal.commission = -0.25
    sl_deal.swap = 0.0
    sl_deal.fee = 0.0

    import MetaTrader5 as mt5_mod
    mt5_mod.DEAL_ENTRY_OUT = 1
    mt5_mod.DEAL_ENTRY_INOUT = 2
    sl_deal.entry = 1  # DEAL_ENTRY_OUT
    mt5_mod.history_deals_get = MagicMock(return_value=[sl_deal])

    # Patch _fetch_mt5_close_reason to use our mock
    # (We call it via asyncio.to_thread; ensure history_deals_get is patched.)
    async def mock_strategy(window):
        return {"signal": "NO_TRADE"}, {"signal_direction": "NO_TRADE", "regime": "FLAT"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    candle_counter = 0
    async def advancing_candles(symbol, timeframe, count, end=None):
        nonlocal candle_counter
        candle_counter += 1
        candles = _generate_candles(
            count,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * candle_counter),
        )
        # Simulate position disappearing after first candle.
        if candle_counter > 1 and gateway._mock_positions:
            gateway._mock_positions.clear()
        return candles
    monkeypatch.setattr(gateway, "get_candles", advancing_candles)

    tagged = Position(
        position_id=order_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.01,
        open_price=2000.0,
        current_price=2000.0,
        magic=live_paper_campaign.LIVE_MAGIC_NUMBER,
    )
    gateway._mock_positions = [tagged]

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=2,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    closed_events = [e for e in events if e["event_type"] == "POSITION_CLOSED"]
    assert len(closed_events) >= 1
    assert closed_events[0]["facts"]["exit_reason"] == "BROKER_SL"
    assert closed_events[0]["facts"]["exit_reason"] != "BROKER_SL_TP"
    assert closed_events[0]["facts"]["pnl"] == -12.75
    assert closed_events[0]["facts"]["currency"] == "USD"
    assert closed_events[0]["facts"]["reconciliation_state"] == "RECONCILED"
    ledger_entries = SQLitePositionLedger(
        summary["session"]["position_ledger_path"]
    ).entries()
    assert len(ledger_entries) == 1
    assert ledger_entries[0].closed_at is not None
    assert ledger_entries[0].close_price == 1990.0
    assert ledger_entries[0].realized_pnl == -12.75
    assert ledger_entries[0].currency == "USD"
    assert ledger_entries[0].reconciliation_state == "RECONCILED"


# 19. No history result remains visibly pending after the bounded poll
@pytest.mark.asyncio
async def test_close_history_unavailable_is_recorded_pending(tmp_path, monkeypatch):
    import MetaTrader5 as mt5_mod
    mt5_mod.DEAL_ENTRY_OUT = 1
    mt5_mod.DEAL_ENTRY_INOUT = 2
    mt5_mod.history_deals_get = MagicMock(return_value=None)  # no history

    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    order_id = "CLOSED-UNKNOWN"
    tagged_position = Position(
        position_id=order_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.01,
        open_price=2000.0,
        current_price=2000.0,
        magic=live_paper_campaign.LIVE_MAGIC_NUMBER,
    )
    gateway._mock_positions = [tagged_position]

    candle_counter = 0
    async def advancing_candles(symbol, timeframe, count, end=None):
        nonlocal candle_counter
        candle_counter += 1
        if candle_counter > 1:
            gateway._mock_positions.clear()
        return _generate_candles(
            count,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * candle_counter),
        )
    monkeypatch.setattr(gateway, "get_candles", advancing_candles)

    async def mock_strategy(window):
        return {"signal": "NO_TRADE"}, {"signal_direction": "NO_TRADE", "regime": "FLAT"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=2,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    closed_events = [e for e in events if e["event_type"] == "POSITION_CLOSED"]
    assert len(closed_events) >= 1
    assert closed_events[0]["facts"]["exit_reason"] == "MT5_CLOSE_HISTORY_PENDING"
    assert closed_events[0]["facts"]["reconciliation_state"] == "PENDING"
    assert closed_events[0]["facts"]["pnl"] is None
    ledger = SQLitePositionLedger(
        summary["session"]["position_ledger_path"]
    ).entries()[0]
    assert ledger.realized_pnl is None
    assert ledger.currency == "USD"
    assert ledger.reconciliation_state == "PENDING"


# 20. MT5 tag fallback: missing ledger row is recovered and counts toward limits
@pytest.mark.asyncio
async def test_mt5_tag_fallback_counts_position_toward_limit(tmp_path, monkeypatch):
    class ParsingMT5DemoGateway(MockMT5DemoGateway):
        async def get_positions(self) -> list[Position]:
            return await MT5Gateway.get_positions(self)

    gateway = ParsingMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    existing_id = "EXISTING-001"
    native_position = SimpleNamespace(
        ticket=existing_id,
        symbol="XAUUSD",
        type=0,
        volume=0.01,
        price_open=2000.0,
        price_current=2001.0,
        profit=1.0,
        sl=1990.0,
        tp=2020.0,
        time=1700000000,
        magic=live_paper_campaign.LIVE_MAGIC_NUMBER,
        comment="JQE LivePaper recovered",
    )
    monkeypatch.setattr("broker.mt5_gateway.mt5.ORDER_TYPE_BUY", 0)
    positions_get = MagicMock(return_value=[native_position])
    monkeypatch.setattr("broker.mt5_gateway.mt5.positions_get", positions_get)

    parsed_positions = await gateway.get_positions()
    assert parsed_positions[0].magic == live_paper_campaign.LIVE_MAGIC_NUMBER
    assert parsed_positions[0].comment == "JQE LivePaper recovered"

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    # MAX_OPEN_POSITIONS is 1 by default in LivePaperSafetyContext.

    summary = await run_live_paper_campaign(
        symbol="XAUUSD",
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        max_candles=2,
    )

    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])

    recovery_events = [
        e for e in events
        if e["facts"].get("reason_code") == "RECOVERED_VIA_MT5_TAG_FALLBACK"
    ]
    assert len(recovery_events) == 1
    assert recovery_events[0]["facts"]["position_id"] == existing_id
    assert positions_get.call_count >= 1
    ledger = SQLitePositionLedger(summary["session"]["position_ledger_path"])
    assert ledger.open_entries(broker="mt5_demo")[0].position_id == existing_id

    # 2. No new order was submitted (existing position fills the limit)
    assert len(gateway.submitted_orders) == 0

    # 3. The blocking event for MAX_OPEN_POSITIONS was emitted
    blocked_events = [
        e for e in events
        if e["facts"].get("reason_code") == "MAX_OPEN_POSITIONS"
    ]
    assert len(blocked_events) >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("broker_name", ["mt5_demo", "deriv_demo"])
async def test_ledger_survives_restart_and_recovers_by_id_for_both_brokers(
    tmp_path, monkeypatch, broker_name
):
    output_path = tmp_path / f"{broker_name}.json"
    ledger_path = tmp_path / f"{broker_name}.positions.sqlite3"
    position_id = f"{broker_name}-POSITION-1"
    position = Position(
        position_id=position_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.25,
        open_price=2000.0,
        current_price=2005.0,
        stop_loss=1990.0,
        take_profit=2020.0,
    )
    SQLitePositionLedger(ledger_path).record_open(
        broker=broker_name,
        symbol="XAUUSD",
        position_id=position_id,
        order_id=f"{broker_name}-ORDER-1",
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    if broker_name == "mt5_demo":
        gateway = MockMT5DemoGateway()
        gateway._mock_positions = [position]
    else:
        monkeypatch.setattr(settings, "broker", "deriv_demo")
        gateway = MockDerivDemoGateway([position])

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        return MagicMock(state="ENTRY_DUE", candidate=_mock_candidate(ts), reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    evidence_path = tmp_path / f"{broker_name}.restart.evidence.sqlite3"
    summary = await run_live_paper_campaign(
        gateway=gateway,
        output=output_path,
        evidence_path=evidence_path,
        ledger_path=ledger_path,
        max_candles=1,
    )
    events = CampaignEvidenceStore(evidence_path).events(summary["session"]["session_id"])
    recovered = [e for e in events if e["facts"].get("reason_code") == "POSITION_RECOVERED_ON_STARTUP"]
    assert len(recovered) == 1
    assert recovered[0]["facts"]["position_id"] == position_id
    assert recovered[0]["facts"]["recovery_source"] == "LOCAL_POSITION_LEDGER"
    assert any(e["facts"].get("reason_code") == "MAX_OPEN_POSITIONS" for e in events)
    assert gateway.submitted_orders == []


@pytest.mark.asyncio
async def test_deriv_ledger_position_closed_while_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "broker", "deriv_demo")
    ledger_path = tmp_path / "deriv.positions.sqlite3"
    SQLitePositionLedger(ledger_path).record_open(
        broker="deriv_demo",
        symbol="R_100",
        position_id="CONTRACT-CLOSED",
        order_id="CONTRACT-CLOSED",
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    gateway = MockDerivDemoGateway()
    evidence_path = tmp_path / "deriv.offline.evidence.sqlite3"
    summary = await run_live_paper_campaign(
        symbol="R_100",
        gateway=gateway,
        output=tmp_path / "deriv.json",
        evidence_path=evidence_path,
        ledger_path=ledger_path,
        max_candles=1,
    )
    events = CampaignEvidenceStore(evidence_path).events(summary["session"]["session_id"])
    closed = next(e for e in events if e["event_type"] == "POSITION_CLOSED")
    assert closed["facts"]["exit_reason"] == "CLOSED_WHILE_OFFLINE"
    assert closed["facts"]["closed_while_offline"] is True
    assert SQLitePositionLedger(ledger_path).entries()[0].closed_at is not None


@pytest.mark.asyncio
async def test_mt5_offline_close_uses_persisted_deal_reason(tmp_path, monkeypatch):
    ledger_path = tmp_path / "mt5.positions.sqlite3"
    SQLitePositionLedger(ledger_path).record_open(
        broker="mt5_demo",
        symbol="XAUUSD",
        position_id="MT5-CLOSED",
        order_id="MT5-ORDER",
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    import MetaTrader5 as mt5_mod
    mt5_mod.DEAL_ENTRY_OUT = 1
    mt5_mod.DEAL_ENTRY_INOUT = 2
    history_deals_get = MagicMock(return_value=[SimpleNamespace(
        position_id="MT5-CLOSED", entry=1, reason=5, time=1700000010,
        price=2020.0, profit=20.0, commission=-0.2, swap=0.0, fee=0.0,
    )])
    monkeypatch.setattr(mt5_mod, "history_deals_get", history_deals_get)
    gateway = MockMT5DemoGateway()
    evidence_path = tmp_path / "mt5.offline.evidence.sqlite3"
    summary = await run_live_paper_campaign(
        gateway=gateway,
        output=tmp_path / "mt5.json",
        evidence_path=evidence_path,
        ledger_path=ledger_path,
        max_candles=1,
    )
    events = CampaignEvidenceStore(evidence_path).events(summary["session"]["session_id"])
    closed = next(e for e in events if e["event_type"] == "POSITION_CLOSED")
    assert closed["facts"]["exit_reason"] == "BROKER_TP"
    assert closed["facts"]["pnl"] == 19.8
    assert closed["facts"]["currency"] == "USD"
    assert history_deals_get.call_count == 1
    assert SQLitePositionLedger(ledger_path).entries()[0].closed_at is not None


@pytest.mark.asyncio
async def test_deriv_unmatched_position_emits_attention_and_is_not_claimed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "broker", "deriv_demo")
    position = Position(
        position_id="UNMATCHED-CONTRACT",
        symbol="R_100",
        side=OrderSide.BUY,
        volume=10.0,
        open_price=10.0,
    )
    gateway = MockDerivDemoGateway([position])
    ledger_path = tmp_path / "deriv.positions.sqlite3"
    evidence_path = tmp_path / "deriv.unmatched.evidence.sqlite3"
    summary = await run_live_paper_campaign(
        symbol="R_100",
        gateway=gateway,
        output=tmp_path / "deriv.json",
        evidence_path=evidence_path,
        ledger_path=ledger_path,
        max_candles=1,
    )
    events = CampaignEvidenceStore(evidence_path).events(summary["session"]["session_id"])
    unmatched = [e for e in events if e["facts"].get("reason_code") == "UNMATCHED_DERIV_POSITION_ON_STARTUP"]
    assert len(unmatched) == 1
    assert unmatched[0]["facts"]["result"] == "ATTENTION_REQUIRED"
    assert unmatched[0]["facts"]["position_id"] == "UNMATCHED-CONTRACT"
    assert SQLitePositionLedger(ledger_path).entries() == ()
    assert not any(e["facts"].get("reason_code") == "POSITION_RECOVERED_ON_STARTUP" for e in events)


@pytest.mark.asyncio
async def test_live_paper_excludes_in_progress_candle_from_strategy(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    interval = timedelta(minutes=15)
    current_open = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    candles = _generate_candles(501, start=current_open - (500 * interval))
    observed_latest: list[datetime] = []

    async def fixed_candles(symbol, timeframe, count, end=None):
        return candles

    async def capture_strategy(window):
        observed_latest.append(window[-1].candle_opened_at)
        return {"signal": "NO_TRADE"}, {"signal_direction": "NO_TRADE", "regime": "FLAT"}

    monkeypatch.setattr(gateway, "get_candles", fixed_candles)
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", capture_strategy)
    await run_live_paper_campaign(
        gateway=gateway,
        output=tmp_path / "chronology.json",
        max_candles=1,
    )
    assert observed_latest == [current_open - interval]
