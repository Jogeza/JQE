from types import SimpleNamespace
import pytest
from broker.daily_accounting import read_daily_accounting


def terminal(*, deals=(), changed=False):
    account = SimpleNamespace(login=42,server='Weltrade-Demo',trade_mode=0,currency='USD',balance=100.0)
    calls = []
    def account_info():
        calls.append(1)
        return SimpleNamespace(**{**vars(account),'balance':101.0}) if changed and len(calls)>1 else account
    return SimpleNamespace(account_info=account_info,history_deals_get=lambda *args:deals,
                           DEAL_TYPE_BUY=0,DEAL_TYPE_SELL=1,DEAL_TYPE_BALANCE=2)


def test_empty_complete_day_reconstructs_start():
    result = read_daily_accounting(terminal(),offset_reader=lambda *args:10800)
    assert result['starting_balance'] == 100
    assert result['realized_net_pnl'] == 0


@pytest.mark.parametrize('mode', ['unavailable','changed','unsupported'])
def test_daily_reader_rejects_unverified_or_ambiguous_evidence(mode):
    source = terminal(deals=None if mode=='unavailable' else
                      [SimpleNamespace(type=99)] if mode=='unsupported' else (),changed=mode=='changed')
    with pytest.raises(ValueError):
        read_daily_accounting(source,offset_reader=lambda *args:10800)
