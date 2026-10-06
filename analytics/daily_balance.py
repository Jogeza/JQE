"""Pure UTC-day balance accounting; independent of execution authorization."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class BalanceMovement:
    ticket: str
    occurred_at: datetime
    category: str  # TRADE, FUNDING, or OTHER_ADJUSTMENT
    net_amount: float


def daily_balance(*, balance, observed_at, movements, history_complete):
    if history_complete is not True:
        raise ValueError('Complete daily broker history required')
    if observed_at.tzinfo is None or not math.isfinite(balance) or balance <= 0:
        raise ValueError('Verified positive balance and aware observation required')
    day = observed_at.astimezone(timezone.utc).date()
    totals = {'TRADE':0.0,'FUNDING':0.0,'OTHER_ADJUSTMENT':0.0}
    seen = set()
    for movement in movements:
        if (movement.category not in totals or not math.isfinite(movement.net_amount)
                or movement.occurred_at.tzinfo is None or not movement.ticket
                or movement.ticket in seen):
            raise ValueError('Invalid or duplicate broker balance movement')
        instant = movement.occurred_at.astimezone(timezone.utc)
        if instant.date() != day or instant > observed_at:
            raise ValueError('Movement outside verified UTC-day window')
        seen.add(movement.ticket)
        totals[movement.category] += movement.net_amount
    starting = balance-sum(totals.values())
    if not math.isfinite(starting) or starting <= 0:
        raise ValueError('Positive daily starting balance unavailable')
    return {'utc_date':day.isoformat(),'starting_balance':starting,
            'starting_balance_method':'RECONSTRUCTED_FROM_COMPLETE_BROKER_HISTORY',
            'current_balance':balance,'realized_net_pnl':totals['TRADE'],
            'net_funding':totals['FUNDING'],'other_adjustments':totals['OTHER_ADJUSTMENT'],
            'advisory_target_percent':20,'advisory_target_amount':starting*.2,
            'realized_return_percent':totals['TRADE']/starting*100,
            'observed_at':observed_at.isoformat(),'movement_count':len(seen)}
