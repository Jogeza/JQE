"""Pytest tests for execution.trade_lifecycle.TradeLifecycle.

Replaces the previous module-level demo script (which called
lifecycle.process() and printed the result at import time — no
assertions, no directional safety guarantees).

Core invariants tested
----------------------
BUY:   stop_loss < entry < take_profit
SELL:  take_profit < entry < stop_loss

These invariants MUST hold for every submitted trade.  Any violation is
a safety bug.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from execution.trade_lifecycle import TradeLifecycle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order_manager(reject: bool = False) -> MagicMock:
    """Returns an OrderManager mock that creates or rejects orders."""
    om = MagicMock()
    if reject:
        om.create_order.return_value = {"status": "REJECTED", "reason": "Test rejection"}
    else:
        om.create_order.side_effect = lambda signal, symbol, lot, entry, stop_loss, take_profit: {
            "status": "CREATED",
            "symbol": symbol,
            "type": signal,
            "lot": lot,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
    return om


def _make_position_manager() -> MagicMock:
    pm = MagicMock()
    pm.open_position.side_effect = lambda order: {**order, "status": "OPEN"}
    return pm


def _lifecycle() -> TradeLifecycle:
    return TradeLifecycle()


# ---------------------------------------------------------------------------
# Risk rejection
# ---------------------------------------------------------------------------


class TestRiskRejection:
    def test_zero_risk_percent_rejects(self) -> None:
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 0},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="BTCUSD",
            price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
        )
        assert result["status"] == "REJECTED"

    def test_negative_risk_percent_rejects(self) -> None:
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": -1.0},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="BTCUSD",
            price=100.0,
            stop_loss=90.0,
            take_profit=120.0,
        )
        assert result["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Missing SL / TP
# ---------------------------------------------------------------------------


class TestMissingLevels:
    def test_missing_stop_loss_rejects(self) -> None:
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="BTCUSD",
            price=100.0,
            stop_loss=None,
            take_profit=120.0,
        )
        assert result["status"] == "REJECTED"
        assert "stop_loss" in result["reason"].lower()

    def test_missing_take_profit_rejects(self) -> None:
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="BTCUSD",
            price=100.0,
            stop_loss=90.0,
            take_profit=None,
        )
        assert result["status"] == "REJECTED"
        assert "take_profit" in result["reason"].lower()


# ---------------------------------------------------------------------------
# BUY directional invariant: SL < entry < TP
# ---------------------------------------------------------------------------


class TestBuyDirectionalInvariant:
    def test_valid_buy_executes(self) -> None:
        """BUY with SL < entry < TP should succeed."""
        entry = 4000.0
        sl = 3900.0   # below entry ✓
        tp = 4200.0   # above entry ✓

        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=entry,
            stop_loss=sl,
            take_profit=tp,
        )
        assert result["status"] == "EXECUTED"
        pos = result["position"]
        assert pos["stop_loss"] < pos["entry"] < pos["take_profit"], (
            f"BUY invariant violated: SL={pos['stop_loss']} entry={pos['entry']} TP={pos['take_profit']}"
        )

    def test_buy_sl_above_entry_rejects(self) -> None:
        """BUY with SL >= entry must be rejected — this is the bug that was fixed."""
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=4000.0,
            stop_loss=4100.0,   # ABOVE entry — wrong for BUY
            take_profit=4200.0,
        )
        assert result["status"] == "REJECTED"
        assert "BUY invariant" in result["reason"]

    def test_buy_tp_below_entry_rejects(self) -> None:
        """BUY with TP <= entry must be rejected."""
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=4000.0,
            stop_loss=3900.0,
            take_profit=3950.0,   # BELOW entry — wrong for BUY
        )
        assert result["status"] == "REJECTED"
        assert "BUY invariant" in result["reason"]

    def test_old_hardcoded_values_would_fail_sell(self) -> None:
        """Regression: the old code used price±10/±20 for ALL signals.
        For a BUY at 4000 this gave SL=3990 (< entry) and TP=4020 (> entry) —
        which happened to be correct by accident.
        For a SELL at 4000 it gave SL=3990 (BELOW entry) — which is wrong.
        This test documents that the old behaviour is rejected for SELL.
        """
        entry = 4000.0
        # Old BUG values — SL below entry and TP above entry, applied to a SELL
        result = _lifecycle().process(
            signal="SELL",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=entry,
            stop_loss=entry - 10,   # 3990 — below entry, WRONG for SELL
            take_profit=entry + 20,  # 4020 — above entry, WRONG for SELL
        )
        assert result["status"] == "REJECTED", (
            "The old hardcoded BUY-style SL/TP should be rejected for a SELL trade"
        )


# ---------------------------------------------------------------------------
# SELL directional invariant: TP < entry < SL
# ---------------------------------------------------------------------------


class TestSellDirectionalInvariant:
    def test_valid_sell_executes(self) -> None:
        """SELL with TP < entry < SL should succeed."""
        entry = 4000.0
        sl = 4100.0   # above entry ✓
        tp = 3800.0   # below entry ✓

        result = _lifecycle().process(
            signal="SELL",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=entry,
            stop_loss=sl,
            take_profit=tp,
        )
        assert result["status"] == "EXECUTED"
        pos = result["position"]
        assert pos["take_profit"] < pos["entry"] < pos["stop_loss"], (
            f"SELL invariant violated: TP={pos['take_profit']} entry={pos['entry']} SL={pos['stop_loss']}"
        )

    def test_sell_sl_below_entry_rejects(self) -> None:
        """SELL with SL <= entry must be rejected."""
        result = _lifecycle().process(
            signal="SELL",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=4000.0,
            stop_loss=3900.0,   # BELOW entry — wrong for SELL
            take_profit=3800.0,
        )
        assert result["status"] == "REJECTED"
        assert "SELL invariant" in result["reason"]

    def test_sell_tp_above_entry_rejects(self) -> None:
        """SELL with TP >= entry must be rejected."""
        result = _lifecycle().process(
            signal="SELL",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="XAUUSD",
            price=4000.0,
            stop_loss=4100.0,
            take_profit=4050.0,   # ABOVE entry — wrong for SELL
        )
        assert result["status"] == "REJECTED"
        assert "SELL invariant" in result["reason"]


# ---------------------------------------------------------------------------
# Unknown signal
# ---------------------------------------------------------------------------


class TestUnknownSignal:
    def test_unknown_signal_rejects(self) -> None:
        result = _lifecycle().process(
            signal="HOLD",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(),
            position_manager=_make_position_manager(),
            symbol="EURUSD",
            price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        assert result["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Order manager rejection propagates
# ---------------------------------------------------------------------------


class TestOrderManagerRejection:
    def test_order_manager_rejection_propagates(self) -> None:
        result = _lifecycle().process(
            signal="BUY",
            risk={"risk_percent": 1.5},
            order_manager=_make_order_manager(reject=True),
            position_manager=_make_position_manager(),
            symbol="BTCUSD",
            price=50000.0,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        assert result["status"] == "REJECTED"