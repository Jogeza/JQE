import pytest
from backtesting.long_history_training import verify_inputs
from backtesting.label_protocol import file_hash


def test_changed_input_rejected(tmp_path):
    p=tmp_path/'evidence';p.write_text('original')
    protocol={'input_hashes':{str(p):file_hash(p)},'helper_source_hashes':{}}
    verify_inputs(protocol)
    p.write_text('changed')
    with pytest.raises(ValueError,match='Frozen input changed'):verify_inputs(protocol)


@pytest.mark.asyncio
async def test_failure_preserved_without_runner(tmp_path):
    from backtesting.long_history_training import dispatch
    called=[]
    async def runner(**kwargs):called.append(kwargs)
    with pytest.raises(FileNotFoundError):await dispatch(tmp_path/'absent',tmp_path/'output',runner)
    assert not called
    assert 'FAILED' in (tmp_path/'output/trials.jsonl').read_text()


@pytest.mark.asyncio
async def test_existing_output_rejected(tmp_path):
    from backtesting.long_history_training import dispatch
    with pytest.raises(FileExistsError):await dispatch(tmp_path,tmp_path,None)

@pytest.mark.asyncio
async def test_preflight_only_never_replays(tmp_path,monkeypatch):
    import backtesting.long_history_training as module
    monkeypatch.setattr(module,'preflight',lambda _:({'limitations':['conditional']},[]))
    async def forbidden(**kwargs):raise AssertionError('Outcomes forbidden')
    await module.dispatch(tmp_path,tmp_path/'output',forbidden,preflight_only=True)
    import json
    assert json.loads((tmp_path/'output/preflight.json').read_text())['outcomes']==0
    assert not (tmp_path/'output/summary.json').exists()
