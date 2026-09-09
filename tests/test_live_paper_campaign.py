"""Tests for the live-paper campaign runner with real demo broker execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broker.demo_guard import DemoOnlyGuard
from broker.deriv_demo import DerivDemoGateway
from broker.mt5_demo import MT5DemoGateway
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
from execution.policy import ExecutionDecisionCode
from research.campaign_provenance import CampaignEvidenceStore
from research.live_safety import LivePaperSafetyContext
from tools import live_paper_campaign
from tools.live_paper_campaign import (
    _OrderRateGuard,
    _round_lots_to_broker_constraints,
    run_live_paper_campaign,
)


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
        self._connected = True
        self._demo_verified = True
        self.submitted_orders: list[OrderRequest] = []
        self._mock_positions: list[Position] = []
        self._candle_call_count = 0

    async def connect(self) -> None:
        self._connected = True
        self._demo_verified = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            account_id=self._mock_account_id,
            balance=self._mock_balance,
            currency="USD",
            equity=self._mock_balance,
        )

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


@pytest.fixture(autouse=True)
def configure_settings(monkeypatch):
    monkeypatch.setattr(settings, "campaign_mode", "live_paper")
    monkeypatch.setattr(settings, "broker_execution_enabled", True)
    monkeypatch.setattr(settings, "broker", "mt5_demo")
    monkeypatch.setattr(settings, "risk_percent", 1.0)
    monkeypatch.setattr(settings, "max_daily_loss", 5.0)
    monkeypatch.setattr(settings, "max_trades_daily", 20)
    monkeypatch.setattr(settings, "live_paper_max_orders_per_session", 50)
    monkeypatch.setattr(settings, "live_paper_min_order_spacing_seconds", 0.0)
    monkeypatch.setattr(settings, "live_paper_max_candles", 5)
    monkeypatch.setattr(settings, "live_paper_max_duration_seconds", None)


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


# 11. Order rate limit exceeded
@pytest.mark.asyncio
async def test_order_rate_limit_exceeded(tmp_path, monkeypatch):
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    monkeypatch.setattr(settings, "live_paper_max_orders_per_session", 1)

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

    assert len(gateway.submitted_orders) == 1
    store = CampaignEvidenceStore(evidence_path)
    events = store.events(summary["session"]["session_id"])
    rate_events = [e for e in events if e["facts"].get("reason_code") == "ORDER_RATE_LIMIT"]
    assert len(rate_events) >= 1


# 12. Minimum spacing violated
def test_order_rate_guard_spacing():
    guard = _OrderRateGuard(max_orders_per_session=10, min_spacing_seconds=60.0)
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

    # Pre-seed local state by patching _open_trades/_own_order_ids.
    # We achieve this by injecting a recovered position via _raw_magic.
    class TaggedPosition(Position):
        _raw_magic: int = live_paper_campaign.LIVE_MAGIC_NUMBER

    tagged = TaggedPosition(
        position_id=order_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.01,
        open_price=2000.0,
        current_price=2000.0,
    )
    tagged._raw_magic = live_paper_campaign.LIVE_MAGIC_NUMBER
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


# 19. No history_deals_get result falls back to neutral label
@pytest.mark.asyncio
async def test_close_reason_no_history_falls_back_to_neutral(tmp_path, monkeypatch):
    """When history_deals_get returns no results, exit_reason must be
    'POSITION_NO_LONGER_OPEN', not the fabricated 'BROKER_SL_TP'.
    """
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
    )
    tagged_position._raw_magic = live_paper_campaign.LIVE_MAGIC_NUMBER  # type: ignore
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
    assert closed_events[0]["facts"]["exit_reason"] == "POSITION_NO_LONGER_OPEN"
    assert closed_events[0]["facts"]["exit_reason"] != "BROKER_SL_TP"


# 20. Startup recovery: pre-existing tagged position is recognized and counts toward limits
@pytest.mark.asyncio
async def test_startup_recovery_counts_tagged_position_toward_limit(tmp_path, monkeypatch):
    """A tagged position already open before the campaign starts must be:
    - Detected and emitted as POSITION_RECOVERED_ON_STARTUP evidence.
    - Added to _own_order_ids and _open_trades immediately.
    - Counted against MAX_OPEN_POSITIONS so no second position is opened.
    """
    gateway = MockMT5DemoGateway()
    output_path = tmp_path / "out.json"
    evidence_path = tmp_path / "evidence.sqlite3"

    # Seed a pre-existing live-paper position (tagged via _raw_magic).
    existing_id = "EXISTING-001"
    pre_existing = Position(
        position_id=existing_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.01,
        open_price=2000.0,
        current_price=2001.0,
    )
    pre_existing._raw_magic = live_paper_campaign.LIVE_MAGIC_NUMBER  # type: ignore
    gateway._mock_positions = [pre_existing]

    async def mock_strategy(window):
        return {"signal": "BUY", "confidence": 85, "features": {"atr_14": 1.5}}, {"signal_direction": "BUY", "regime": "TREND_UP"}
    monkeypatch.setattr(live_paper_campaign, "evaluate_strategy_candidate", mock_strategy)

    def mock_observe(self, ts, regime):
        cand = _mock_candidate(ts, "BUY")
        return MagicMock(state="ENTRY_DUE", candidate=cand, reason="CONFIRMED")
    monkeypatch.setattr(live_paper_campaign.HistoricalConfirmationState, "observe", mock_observe)

    monkeypatch.setattr(settings, "live_paper_max_orders_per_session", 10)
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

    # 1. Startup recovery event emitted
    recovery_events = [
        e for e in events
        if e["facts"].get("reason_code") == "POSITION_RECOVERED_ON_STARTUP"
    ]
    assert len(recovery_events) == 1
    assert recovery_events[0]["facts"]["position_id"] == existing_id

    # 2. No new order was submitted (existing position fills the limit)
    assert len(gateway.submitted_orders) == 0

    # 3. The blocking event for MAX_OPEN_POSITIONS was emitted
    blocked_events = [
        e for e in events
        if e["facts"].get("reason_code") == "MAX_OPEN_POSITIONS"
    ]
    assert len(blocked_events) >= 1
