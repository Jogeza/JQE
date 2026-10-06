"""Pure continuation limit preparation and exit advice; no broker mutations.

Every draft needs canonical signal, six confirmed factors, fresh broker
evidence and explicit upstream risk approval. Drafts share the supplied risk
budget and existing position/pending caps; they are never order authorization.
"""
from dataclasses import dataclass
from datetime import datetime
import math

from execution.pending_limits import LimitDraft, prepare_limit


FACTORS = frozenset({'trend','structure','liquidity','momentum','volatility','risk'})


@dataclass(frozen=True)
class ContinuationEvidence:
    signal: str
    regime: str
    confirmed_factors: frozenset[str]
    observed_at: datetime
    closed_bar_at: datetime
    provider: str
    continuation_confirmed: bool
    risk_approved: bool
    authorized_risk_amount: float
    bid: float
    ask: float
    bar_seconds: int = 300


@dataclass(frozen=True)
class ContinuationCandidate:
    draft: LimitDraft
    evidence: ContinuationEvidence


@dataclass(frozen=True)
class PreparedContinuation:
    draft: LimitDraft
    ready: bool
    reason: str
    submission_authorized: bool = False


def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value > 0


def _fresh(evidence, now):
    if not isinstance(evidence,ContinuationEvidence) or not isinstance(now,datetime) or now.tzinfo is None:
        return False
    if any(not isinstance(t,datetime) or t.tzinfo is None for t in (evidence.observed_at,evidence.closed_bar_at)):
        return False
    return (evidence.provider == 'weltrade' and evidence.bar_seconds in (60,300)
            and 0 <= (now-evidence.closed_bar_at).total_seconds() <= evidence.bar_seconds+90
            and 0 <= (now-evidence.observed_at).total_seconds() <= 90
            and evidence.closed_bar_at <= evidence.observed_at)


def prepare_continuation_batch(candidates, *, now, open_symbols, pending_symbols,
                               snapshots_complete, used_keys, verified_demo,
                               equity, currency, total_cap, total_risk_budget,
                               existing_reserved_risk):
    """Reserve capacity inside this preview only; never persist or submit it.

The caller must supply complete open/pending risk exposure. A declared budget
cannot exceed 0.5% equity. Broker sizing/risk approval is still upstream.
"""
    outcomes = []
    state_valid = (snapshots_complete is True and verified_demo is True
        and currency == 'USD' and _positive(equity) and _positive(total_risk_budget)
        and type(existing_reserved_risk) in (int,float) and math.isfinite(existing_reserved_risk)
        and existing_reserved_risk >= 0 and total_risk_budget <= equity*0.005
        and type(total_cap) is int and 1 <= total_cap <= (5 if equity >= 50 else 1)
        and isinstance(open_symbols,tuple) and isinstance(pending_symbols,tuple)
        and isinstance(used_keys,frozenset))
    preview_pending = pending_symbols
    preview_keys = used_keys
    reserved = existing_reserved_risk
    for candidate in candidates:
        draft, evidence = candidate.draft,candidate.evidence
        reason = None
        if not state_valid:
            reason = 'COMPLETE_DEMO_ACCOUNT_RISK_STATE_REQUIRED'
        elif not _fresh(evidence,now):
            reason = 'FRESH_CLOSED_BROKER_EVIDENCE_REQUIRED'
        elif (evidence.continuation_confirmed is not True or evidence.regime != 'TRENDING'
              or evidence.signal != draft.side or evidence.confirmed_factors != FACTORS):
            reason = 'CONTINUATION_AND_ALL_FACTORS_REQUIRED'
        elif not _positive(draft.risk_amount) or reserved+draft.risk_amount > total_risk_budget:
            reason = 'COMBINED_RISK_BUDGET_EXCEEDED'
        elif (all(_positive(v) for v in (draft.entry,draft.stop_loss,draft.take_profit))
              and (abs(draft.entry-draft.stop_loss) == 0
                   or abs(draft.take_profit-draft.entry)/abs(draft.entry-draft.stop_loss) < 1.5)):
            reason = 'CANONICAL_MINIMUM_REWARD_RISK_REQUIRED'
        if reason is None:
            result = prepare_limit(draft,bid=evidence.bid,ask=evidence.ask,
                open_symbols=open_symbols,pending_symbols=preview_pending,
                snapshots_complete=True,risk_approved=evidence.risk_approved,
                authorized_risk_amount=evidence.authorized_risk_amount,
                total_cap=total_cap,used_keys=preview_keys)
            ready,reason = result.ready,result.reason
        else:
            ready = False
        outcomes.append(PreparedContinuation(draft,ready,reason))
        if ready:
            reserved += draft.risk_amount
            preview_pending += (draft.symbol,)
            preview_keys = preview_keys | {draft.idempotency_key}
    return tuple(outcomes)


def continuation_exit_advice(*, side, evidence, now, closed_bar_trend, prior_closed_bar_trend):
    """Advise an early exit only after two closed bars oppose the position.

Missing observations give no mutation authority. Original broker stop/target
remain necessary; a NO_TRADE entry score alone does not cancel a valid trend.
"""
    if side not in ('BUY','SELL') or not _fresh(evidence,now):
        return 'OBSERVATION_UNAVAILABLE_KEEP_BROKER_PROTECTION'
    opposite = 'BEARISH' if side == 'BUY' else 'BULLISH'
    if closed_bar_trend == prior_closed_bar_trend == opposite:
        return 'CONTINUATION_FAILED_EXIT_REVIEW_REQUIRED'
    return 'KEEP_CURRENT_STOP_AND_TARGET'
