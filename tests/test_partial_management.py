import math
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from broker.types import OrderSide
from execution.partial_policy import split_lots,levels,ready
import execution.partial_manager as manager
from execution.safety import EmergencyStopState


def test_floor_even_steps_never_doubles():
    assert split_lots(.03,.01,.01)==(.02,.01)
    assert split_lots(.06,.01,.01)==(.06,.03)
    with pytest.raises(ValueError):split_lots(.01,.01,.01)


@pytest.mark.parametrize('side,stop,trigger,profit_stop',[('BUY',90,115,105),('SELL',110,85,95)])
def test_actual_entry_original_r_and_broker_distance(side,stop,trigger,profit_stop):
    assert levels(side,100,stop)==(trigger,profit_stop)
    assert ready(side,trigger,100,stop,9)
    assert not ready(side,trigger,100,stop,10)
    assert not ready(side,100,100,stop,0)


@pytest.mark.parametrize('value',[math.nan,math.inf,0,-.01])
def test_invalid_lot_rules_fail_closed(value):
    with pytest.raises(ValueError):split_lots(.03,.01,value)


def settings(tmp_path):
    return SimpleNamespace(weltrade_partial_management_enabled=True,weltrade_partial_store_path=tmp_path/'partial.db',broker_execution_enabled=True,emergency_stop=EmergencyStopState.CLEAR,intent_store_path=tmp_path/'intents.db')


class Gateway:
    def __init__(self):
        self.snap={'side':'BUY','entry':100,'volume':.02,'quote':115,'distance':1,'trade_tick_size':.01,'volume_min':.01,'volume_step':.01}
        self.get_account_info=AsyncMock(return_value=SimpleNamespace(account_id='demo'))
        self.partial_management_snapshot=AsyncMock(side_effect=lambda _:dict(self.snap))
        self.partial_close_confirmed=AsyncMock(side_effect=self.close)
        self.partial_volume_confirmed=AsyncMock(return_value=True)
        self.protect_partial_stop=AsyncMock(return_value=True)
    async def close(self,*args,**kwargs):self.snap['volume']=.01
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass


async def setup(tmp_path,monkeypatch):
    s=settings(tmp_path);g=Gateway();monkeypatch.setattr(manager,'get_gateway',lambda _:g);monkeypatch.setattr(manager,'authorized',lambda _:None)
    p=SimpleNamespace(position_id='1',volume=.02,side=OrderSide.BUY,open_price=100,stop_loss=90)
    await manager.register_fill(s,g,p)
    return s,g


@pytest.mark.asyncio
async def test_close_once_then_protect_and_no_repeat(tmp_path,monkeypatch):
    s,g=await setup(tmp_path,monkeypatch)
    await manager.manage_partials(s);await manager.manage_partials(s)
    g.partial_close_confirmed.assert_awaited_once()
    g.protect_partial_stop.assert_awaited_once_with('1',remaining_volume=.01,stop=105)
    with manager.database(s) as c:assert c.execute('SELECT state FROM partial_positions').fetchone()[0]=='PROTECTED'


@pytest.mark.asyncio
async def test_uncertain_close_never_resubmitted(tmp_path,monkeypatch):
    s,g=await setup(tmp_path,monkeypatch);g.partial_close_confirmed.side_effect=RuntimeError('uncertain');g.partial_volume_confirmed.return_value=False
    with pytest.raises(RuntimeError):await manager.manage_partials(s)
    with pytest.raises(RuntimeError,match='operator reconciliation'):await manager.manage_partials(s)
    g.partial_close_confirmed.assert_awaited_once();g.protect_partial_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_recovers_confirmed_partial_without_second_close(tmp_path,monkeypatch):
    s,g=await setup(tmp_path,monkeypatch)
    with manager.database(s) as c:c.execute("UPDATE partial_positions SET state='CLOSE_REQUESTED'")
    g.snap['volume']=.01
    await manager.manage_partials(s)
    g.partial_close_confirmed.assert_not_awaited();g.protect_partial_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_stop_persists_and_retry_does_not_close_again(tmp_path,monkeypatch):
    s,g=await setup(tmp_path,monkeypatch);g.protect_partial_stop.return_value=False
    with pytest.raises(RuntimeError,match='profit stop pending'):await manager.manage_partials(s)
    with manager.database(s) as c:assert c.execute('SELECT state FROM partial_positions').fetchone()[0]=='PARTIAL_CONFIRMED'
    g.protect_partial_stop.return_value=True;await manager.manage_partials(s)
    g.partial_close_confirmed.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_trigger_no_mutation(tmp_path,monkeypatch):
    s,g=await setup(tmp_path,monkeypatch);g.snap['quote']=114
    await manager.manage_partials(s)
    g.partial_close_confirmed.assert_not_awaited();g.protect_partial_stop.assert_not_awaited()

@pytest.mark.asyncio
async def test_entry_sizing_reprobes_reduced_even_lots(monkeypatch):
    import broker.mt5_demo as module
    g=module.MT5DemoGateway.__new__(module.MT5DemoGateway)
    monkeypatch.setattr(g,'verify_instrument_risk_spec',AsyncMock(return_value={'symbol':'SFX Vol 99'}))
    monkeypatch.setattr(module.mt5,'symbol_info',lambda _:SimpleNamespace(volume_step=.01,volume_min=.01,volume_max=5))
    profit=[]
    def pnl(kind,symbol,lots,entry,stop):profit.append(lots);return -10*lots
    monkeypatch.setattr(module.mt5,'order_calc_profit',pnl)
    monkeypatch.setattr(module.mt5,'order_calc_margin',lambda *args:1.)
    monkeypatch.setattr(module.mt5,'account_info',lambda:SimpleNamespace(margin_free=50))
    q,facts=await g.authorize_account_currency_risk(symbol='SFX Vol 99',side=OrderSide.BUY,balance=35,risk_percent=1,entry=100,stop_loss=90,split_for_partials=True)
    assert q.value==.02 and facts['expected_loss_at_stop']==.2
    assert profit==[1.,.02]


@pytest.mark.asyncio
@pytest.mark.parametrize('side,old_sl,stop,quote',[('BUY',90,105.001,115),('SELL',110,94.999,85)])
async def test_profit_stop_rounding_and_target_preserved(monkeypatch,side,old_sl,stop,quote):
    import broker.weltrade_gateway as module
    g=module.WeltradeGateway.__new__(module.WeltradeGateway)
    target=120 if side=='BUY' else 80
    snapshot={'side':side,'volume':.01,'entry':100,'sl':old_sl,'tp':target,'quote':quote,'distance':1,'trade_tick_size':.01,'symbol':'SFX Vol 99'}
    updated=dict(snapshot);updated['sl']=105.01 if side=='BUY' else 94.99
    monkeypatch.setattr(g,'partial_management_snapshot',AsyncMock(side_effect=[snapshot,updated]))
    monkeypatch.setattr(g,'_verify_connection_identity',lambda **kwargs:True)
    monkeypatch.setattr(module.mt5,'order_check',lambda request:SimpleNamespace(retcode=0))
    requests=[]
    monkeypatch.setattr(module.mt5,'order_send',lambda request:(requests.append(request) or SimpleNamespace(retcode=module.mt5.TRADE_RETCODE_DONE)))
    assert await g.protect_partial_stop('1',remaining_volume=.01,stop=stop)
    assert requests[0]['tp']==target and requests[0]['sl']==updated['sl']


@pytest.mark.asyncio
async def test_profit_stop_invalid_distance_never_sends(monkeypatch):
    import broker.weltrade_gateway as module
    g=module.WeltradeGateway.__new__(module.WeltradeGateway)
    monkeypatch.setattr(g,'partial_management_snapshot',AsyncMock(return_value={'side':'BUY','volume':.01,'entry':100,'sl':90,'tp':120,'quote':105.5,'distance':1,'trade_tick_size':.01,'symbol':'SFX Vol 99'}))
    send=[];monkeypatch.setattr(module.mt5,'order_send',lambda request:send.append(request))
    assert not await g.protect_partial_stop('1',remaining_volume=.01,stop=105)
    assert not send


@pytest.mark.asyncio
async def test_existing_tighter_stop_never_loosened(monkeypatch):
    import broker.weltrade_gateway as module
    g=module.WeltradeGateway.__new__(module.WeltradeGateway)
    monkeypatch.setattr(g,'partial_management_snapshot',AsyncMock(return_value={'side':'BUY','volume':.01,'entry':100,'sl':108,'tp':120,'quote':115,'distance':1,'trade_tick_size':.01,'symbol':'SFX Vol 99'}))
    send=[];monkeypatch.setattr(module.mt5,'order_send',lambda request:send.append(request))
    assert await g.protect_partial_stop('1',remaining_volume=.01,stop=105)
    assert not send


@pytest.mark.asyncio
async def test_account_mismatch_never_mutates(tmp_path,monkeypatch):
    s,g=await setup(tmp_path,monkeypatch)
    g.get_account_info.return_value=SimpleNamespace(account_id='other')
    with pytest.raises(RuntimeError,match='account mismatch'):await manager.manage_partials(s)
    g.partial_close_confirmed.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_close_must_match_exact_volume(monkeypatch):
    import broker.weltrade_gateway as module
    g=module.WeltradeGateway.__new__(module.WeltradeGateway)
    monkeypatch.setattr(g,'partial_management_snapshot',AsyncMock(return_value={'volume':.01,'volume_min':.01,'volume_step':.01}))
    close=AsyncMock();monkeypatch.setattr(g,'close_position',close)
    with pytest.raises(Exception,match='volume changed'):
        await g.partial_close_confirmed('1',original_volume=.02,portion=.01)
    close.assert_not_awaited()

@pytest.mark.parametrize('state',['missing','emergency','unresolved'])
def test_durable_safety_failure_blocks_management(tmp_path,monkeypatch,state):
    s=settings(tmp_path);s.execution_safety_store_path=tmp_path/'safety.db'
    snapshot=None if state=='missing' else SimpleNamespace(broker='weltrade',emergency_stop_state=EmergencyStopState.ACTIVE if state=='emergency' else EmergencyStopState.CLEAR,unresolved_intent_blocked=state=='unresolved')
    monkeypatch.setattr(manager,'SQLiteExecutionSafetyStore',lambda *args,**kwargs:SimpleNamespace(read=lambda:snapshot))
    with pytest.raises(RuntimeError,match='durable safety state'):manager.authorized(s)


@pytest.mark.asyncio
async def test_supervisor_retries_pending_stop_without_signal_cycle(monkeypatch):
    import monitoring.weltrade_execution_supervisor as supervisor
    monkeypatch.setattr(supervisor,'settings',SimpleNamespace(observation_close_grace_seconds=0))
    monkeypatch.setattr(supervisor,'_require_process_authorization',lambda:None)
    monkeypatch.setattr(supervisor,'monitor_weltrade_closes',AsyncMock())
    monkeypatch.setattr(supervisor.asyncio,'sleep',AsyncMock())
    pending=AsyncMock(side_effect=manager.PartialProtectionPending('pending'))
    monkeypatch.setattr(supervisor,'manage_partials',pending)
    records=[];monkeypatch.setattr(supervisor,'_publish',lambda **kwargs:records.append(kwargs))
    monkeypatch.setattr(supervisor,'evaluate',lambda _:(_ for _ in ()).throw(AssertionError('No entry prerequisite after pending protection')))
    await supervisor._wait_for_cycle(1,'RUNNING',None)
    assert pending.await_count>0 and all(r['reason']=='PARTIAL_PROFIT_STOP_PENDING' for r in records)
