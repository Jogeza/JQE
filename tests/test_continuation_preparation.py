from dataclasses import replace
from datetime import datetime,timedelta,timezone

import pytest

from execution.continuation_preparation import (
    FACTORS,ContinuationCandidate,ContinuationEvidence,prepare_continuation_batch,continuation_exit_advice)
from execution.pending_limits import LimitDraft

NOW = datetime(2026,10,5,9,30,tzinfo=timezone.utc)


def candidate(symbol='FX Vol 20', key='one', risk=2.0):
    return ContinuationCandidate(LimitDraft(symbol,'BUY',99,97,103,risk,key),
        ContinuationEvidence('BUY','TRENDING',FACTORS,NOW,NOW-timedelta(minutes=1),
                             'weltrade',True,True,risk,100,101))


def prepare(candidates=None,**overrides):
    state = dict(now=NOW,open_symbols=(),pending_symbols=(),snapshots_complete=True,
                 used_keys=frozenset(),verified_demo=True,equity=1000,currency='USD',
                 total_cap=5,total_risk_budget=5,existing_reserved_risk=0)
    state.update(overrides)
    return prepare_continuation_batch(candidates or [candidate()],**state)


def test_different_symbols_share_budget_and_never_authorize_submission():
    results = prepare([candidate(),candidate('FX Vol 40','two')])
    assert all(r.ready and not r.submission_authorized for r in results)


def test_preview_reserves_pending_capacity_and_duplicates_before_second_draft():
    assert not prepare([candidate(),candidate(key='two')])[1].ready
    results = prepare([candidate(),candidate('FX Vol 40','two'),candidate('FX Vol 60','three',risk=0.5)])
    assert results[2].reason == 'PENDING_LIMIT_REACHED'


def test_preview_cannot_multiply_risk_by_splitting_small_orders():
    result = prepare([candidate(risk=3),candidate('FX Vol 40','two',risk=3)])
    assert result[0].ready
    assert result[1].reason == 'COMBINED_RISK_BUDGET_EXCEEDED'


@pytest.mark.parametrize('state', [dict(verified_demo=False),dict(equity=49,total_cap=5),
    dict(currency='EUR'),dict(total_risk_budget=6),dict(existing_reserved_risk=None),
    dict(snapshots_complete=False)])
def test_incomplete_or_over_budget_state_rejects_every_draft(state):
    assert not prepare(**state)[0].ready


def test_fifth_combined_slot_blocks_second_draft():
    result = prepare([candidate(),candidate('FX Vol 40','two')],open_symbols=('a','b','c','d'))
    assert result[0].ready
    assert result[1].reason == 'TOTAL_CAP_REACHED'


def test_missing_factor_and_stale_observation_reject():
    c = candidate()
    for evidence in (replace(c.evidence,confirmed_factors=FACTORS-{'liquidity'}),
                     replace(c.evidence,observed_at=NOW-timedelta(seconds=91)),
                     replace(c.evidence,closed_bar_at=NOW-timedelta(minutes=10)),
                     replace(c.evidence,closed_bar_at=NOW+timedelta(seconds=1))):
        assert not prepare([replace(c,evidence=evidence)])[0].ready


def test_original_stop_target_are_preserved_and_exit_requires_confirmed_reversal():
    c = candidate()
    result = prepare([c])[0]
    assert result.draft.stop_loss == 97 and result.draft.take_profit == 103
    advice = lambda a,b: continuation_exit_advice(side='BUY',evidence=c.evidence,now=NOW,
        closed_bar_trend=a,prior_closed_bar_trend=b)
    assert advice('BEARISH','BULLISH') == 'KEEP_CURRENT_STOP_AND_TARGET'
    assert advice('BEARISH','BEARISH') == 'CONTINUATION_FAILED_EXIT_REVIEW_REQUIRED'


def test_sell_limit_is_prepared_and_low_reward_risk_rejects():
    c = candidate()
    sell = replace(c,draft=replace(c.draft,side='SELL',entry=102,stop_loss=104,take_profit=98),
                   evidence=replace(c.evidence,signal='SELL'))
    assert prepare([sell])[0].ready
    weak = replace(c,draft=replace(c.draft,take_profit=100))
    assert prepare([weak])[0].reason == 'CANONICAL_MINIMUM_REWARD_RISK_REQUIRED'
