from datetime import datetime, timezone

from broker.types import Timeframe
from research.shadow_outcomes import SignalSpec
from research.tick_quote_replay import TickQuote, replay_buy_plan


def _spec() -> SignalSpec:
    return SignalSpec(
        signal_id="tick-plan", symbol="PAINX 1200", timeframe=Timeframe.M1,
        side="BUY", signal_close=datetime(2026, 1, 1, tzinfo=timezone.utc),
        stop_loss=99.0, take_profit=102.0, horizon_bars=20,
    )


def test_tick_replay_uses_ask_entry_and_first_bid_trigger():
    quotes = [
        TickQuote(1767225600100, 100.0, 100.5),
        TickQuote(1767225600200, 98.8, 99.3),
        TickQuote(1767225600300, 102.1, 102.6),
    ]
    outcome = replay_buy_plan(_spec(), quotes)
    assert outcome.status == "SL"
    assert outcome.entry_price == 100.5
    assert outcome.outcome_price == 98.8
    assert outcome.net_r == (98.8 - 100.5) / (100.5 - 99.0)


def test_tick_replay_does_not_substitute_missing_timeout_quote():
    outcome = replay_buy_plan(_spec(), [TickQuote(1767225600100, 100.0, 100.5)])
    assert outcome.status == "UNRESOLVED"
    assert outcome.unresolved_reason == "timeout quote unavailable"


def test_tick_replay_flags_quote_gaps_but_keeps_observed_quote():
    outcome = replay_buy_plan(_spec(), [
        TickQuote(1767225605000, 100.0, 100.5),
        TickQuote(1767225608000, 102.1, 102.6),
    ])
    assert outcome.status == "TP"
    assert outcome.has_quote_gap is True
