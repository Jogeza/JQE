"""Pure preparation policy for demo limit drafts; no order submission.

Live activation additionally requires broker pending-order observations,
durable risk reservations, expiry/cancellation and fill reconciliation.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class LimitDraft:
    symbol: str
    side: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class LimitPreparation:
    ready: bool
    reason: str


def prepare_limit(draft, *, bid, ask, open_symbols, pending_symbols,
                  snapshots_complete, risk_approved, authorized_risk_amount,
                  total_cap, used_keys):
    """Validate one draft against explicit immutable broker/risk evidence."""
    reject = lambda reason: LimitPreparation(False, reason)
    if snapshots_complete is not True or open_symbols is None or pending_symbols is None or used_keys is None:
        return reject('BROKER_STATE_UNAVAILABLE')
    if (not isinstance(open_symbols, tuple) or not isinstance(pending_symbols, tuple)
            or not isinstance(used_keys, frozenset)
            or any(not isinstance(s, str) or not s.strip() for s in (*open_symbols, *pending_symbols, *used_keys))):
        return reject('BROKER_STATE_UNAVAILABLE')
    if type(total_cap) is not int or not 1 <= total_cap <= 5:
        return reject('CAP_UNAVAILABLE')
    if len(pending_symbols) >= 2:
        return reject('PENDING_LIMIT_REACHED')
    if len(open_symbols) + len(pending_symbols) >= total_cap:
        return reject('TOTAL_CAP_REACHED')
    if (not isinstance(draft, LimitDraft) or not isinstance(draft.symbol, str)
            or not isinstance(draft.idempotency_key, str)
            or not draft.symbol.strip() or not draft.idempotency_key.strip()):
        return reject('INVALID_DRAFT')
    if draft.idempotency_key in used_keys:
        return reject('DUPLICATE_DRAFT')
    normalized = draft.symbol.strip().upper()
    if normalized in {s.strip().upper() for s in (*open_symbols, *pending_symbols)}:
        return reject('SAME_SYMBOL_BLOCKED')
    values = (bid, ask, draft.entry, draft.stop_loss, draft.take_profit,
              draft.risk_amount, authorized_risk_amount)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values) or bid > ask:
        return reject('PRICE_OR_RISK_UNAVAILABLE')
    if risk_approved is not True or draft.risk_amount > authorized_risk_amount:
        return reject('RISK_NOT_APPROVED')
    if draft.side == 'BUY':
        valid = draft.stop_loss < draft.entry < draft.take_profit and draft.entry < ask
    elif draft.side == 'SELL':
        valid = draft.take_profit < draft.entry < draft.stop_loss and draft.entry > bid
    else:
        valid = False
    return LimitPreparation(valid, 'DRAFT_READY_NOT_AUTHORIZED_FOR_SUBMISSION' if valid else 'INVALID_LIMIT_LEVELS')
