from dataclasses import replace
import pytest
from execution.pending_limits import LimitDraft, prepare_limit

DRAFT = LimitDraft('SFX Vol 20', 'BUY', 99, 98, 102, 0.5, 'draft-1')


def check(**kwargs):
    evidence = dict(bid=100, ask=101, open_symbols=(), pending_symbols=(), snapshots_complete=True,
                    risk_approved=True, authorized_risk_amount=0.5, total_cap=5, used_keys=frozenset())
    draft = kwargs.pop('draft', DRAFT)
    evidence.update(kwargs)
    return prepare_limit(draft, **evidence)


def test_ready_is_a_draft_and_never_order_authorization():
    assert check().ready
    assert check().reason == 'DRAFT_READY_NOT_AUTHORIZED_FOR_SUBMISSION'


@pytest.mark.parametrize('evidence,reason', [
    ({'pending_symbols': ('FX Vol 20', 'SFX Vol 99')}, 'PENDING_LIMIT_REACHED'),
    ({'open_symbols': ('a','b','c','d'), 'pending_symbols': ('e',)}, 'TOTAL_CAP_REACHED'),
    ({'open_symbols': None}, 'BROKER_STATE_UNAVAILABLE'),
    ({'snapshots_complete': False}, 'BROKER_STATE_UNAVAILABLE'),
    ({'open_symbols': ('SFX VOL 20',)}, 'SAME_SYMBOL_BLOCKED'),
    ({'risk_approved': False}, 'RISK_NOT_APPROVED'),
    ({'authorized_risk_amount': 0.4}, 'RISK_NOT_APPROVED'),
    ({'used_keys': frozenset({'draft-1'})}, 'DUPLICATE_DRAFT'),
    ({'ask': float('nan')}, 'PRICE_OR_RISK_UNAVAILABLE'),
    ({'open_symbols': (None,)}, 'BROKER_STATE_UNAVAILABLE'),
    ({'draft': replace(DRAFT, symbol=None)}, 'INVALID_DRAFT'),
])
def test_unsafe_or_unreadable_evidence_fails_closed(evidence, reason):
    assert check(**evidence).reason == reason
    assert not check(**evidence).ready


def test_sell_limit_and_reversed_stop_are_checked():
    assert check(draft=replace(DRAFT, side='SELL', entry=102, stop_loss=103, take_profit=99)).ready
    assert not check(draft=replace(DRAFT, entry=101.5)).ready
    assert not check(draft=replace(DRAFT, stop_loss=100)).ready
