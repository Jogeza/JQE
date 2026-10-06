from datetime import datetime, timezone
import pytest
from analytics.daily_balance import BalanceMovement, daily_balance


NOW = datetime(2026,10,5,10,tzinfo=timezone.utc)


def test_funding_is_not_profit_and_fees_are_net():
    movements = [BalanceMovement('1',NOW,'TRADE',4.5),BalanceMovement('2',NOW,'FUNDING',50),
                 BalanceMovement('3',NOW,'OTHER_ADJUSTMENT',-1)]
    result = daily_balance(balance=153.5,observed_at=NOW,movements=movements,history_complete=True)
    assert result['starting_balance'] == 100
    assert result['realized_net_pnl'] == 4.5
    assert result['advisory_target_amount'] == 20


def test_incomplete_history_cannot_create_baseline():
    with pytest.raises(ValueError):
        daily_balance(balance=100,observed_at=NOW,movements=[],history_complete=False)


def test_duplicate_deals_reject_double_counting():
    deal = BalanceMovement('1',NOW,'TRADE',2)
    with pytest.raises(ValueError):
        daily_balance(balance=100,observed_at=NOW,movements=[deal,deal],history_complete=True)


def test_prior_day_and_future_movements_reject():
    for instant in (NOW.replace(day=4),NOW.replace(hour=11)):
        with pytest.raises(ValueError):
            daily_balance(balance=100,observed_at=NOW,movements=[BalanceMovement('1',instant,'TRADE',1)],history_complete=True)
