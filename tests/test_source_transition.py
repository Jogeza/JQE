from pathlib import Path
import pytest
from backtesting.source_transition import check_reviewed_diff


def sources():
    root=Path(__file__).resolve().parents[1]
    archive=root/'reports/long-history-label-campaign-20261009-01/source-archive'
    if not archive.exists():pytest.skip('Explicit local owned source archive unavailable')
    old={p.relative_to(archive).as_posix():p.read_text() for p in archive.rglob('*.py')}
    approved=root/'reports/source-transition-evidence-20261010-01/source-archive'
    if not approved.exists():pytest.skip('Explicit approved transition source archive unavailable')
    new={p.relative_to(approved).as_posix():p.read_text() for p in approved.rglob('*.py')}
    return old,new


@pytest.mark.parametrize('mode',['valid','strategy','serializer','dispatcher','runner','removed','added'])
def test_exact_transition_rejects_unreviewed_source_edits(mode):
    old,new=sources()
    if mode=='strategy':new['strategy/pipeline.py']+='\n#changed\n'
    if mode=='serializer':new['backtesting/models.py']+='\n#changed\n'
    if mode=='dispatcher':new['backtesting/long_history_labels.py']+='\n#changed\n'
    if mode=='runner':new['backtesting/backtest.py']=new['backtesting/backtest.py'].replace(
        'return engine\n','return None\n',1)
    if mode=='removed':new.pop('backtesting/models.py')
    if mode=='added':new['backtesting/unreviewed.py']=''
    if mode=='valid':check_reviewed_diff(old,new)
    else:
        with pytest.raises(ValueError):check_reviewed_diff(old,new)
