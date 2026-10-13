"""Durable one-shot demo partial management; mutation stays behind BrokerGateway."""
import math
import sqlite3
from pathlib import Path

from broker.factory import get_gateway
from execution.partial_policy import split_lots,levels,ready
from execution.safety import EmergencyStopState, SQLiteExecutionSafetyStore


class PartialProtectionPending(RuntimeError):
    """Confirmed partial is protected by its original stop; tighter stop pending."""


def database(settings):
    path=Path(settings.weltrade_partial_store_path);path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=5)
    c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS partial_positions (account TEXT NOT NULL,ticket TEXT NOT NULL,side TEXT NOT NULL,entry REAL NOT NULL,initial_stop REAL NOT NULL,volume REAL NOT NULL,portion REAL NOT NULL,state TEXT NOT NULL,reason TEXT,PRIMARY KEY(account,ticket))')
    c.commit();return c


async def register_fill(settings,gateway,position):
    snapshot=await gateway.partial_management_snapshot(position.position_id)
    if snapshot is None:raise RuntimeError('New managed fill absent')
    total,portion=split_lots(position.volume,snapshot['volume_min'],snapshot['volume_step'])
    if not math.isclose(total,position.volume,abs_tol=1e-8):raise RuntimeError('Actual fill is not two equal valid portions')
    levels(position.side.value,position.open_price,position.stop_loss)
    account=await gateway.get_account_info()
    with database(settings) as c:
        c.execute('INSERT OR IGNORE INTO partial_positions VALUES (?,?,?,?,?,?,?,?,NULL)',(account.account_id,position.position_id,position.side.value,position.open_price,position.stop_loss,position.volume,portion,'READY'))
        row=c.execute('SELECT * FROM partial_positions WHERE account=? AND ticket=?',(account.account_id,position.position_id)).fetchone()
        if row['volume']!=position.volume or row['entry']!=position.open_price or row['initial_stop']!=position.stop_loss:
            raise RuntimeError('Managed fill registry identity disagreement')


def update(settings,row,state,reason=None, *, expected=None):
    with database(settings) as c:
        if expected is not None:
            changed=c.execute('UPDATE partial_positions SET state=?,reason=? WHERE account=? AND ticket=? AND state=?',(state,reason,row['account'],row['ticket'],expected)).rowcount
            if changed!=1:raise RuntimeError('Partial operation already claimed')
        else:c.execute('UPDATE partial_positions SET state=?,reason=? WHERE account=? AND ticket=?',(state,reason,row['account'],row['ticket']))


def authorized(settings):
    if not settings.broker_execution_enabled or settings.emergency_stop is not EmergencyStopState.CLEAR:
        raise RuntimeError('Demo partial-management authorization blocked')
    snapshot=SQLiteExecutionSafetyStore(settings.execution_safety_store_path,initialize=False).read()
    if snapshot is None or snapshot.broker!='weltrade' or snapshot.emergency_stop_state is not EmergencyStopState.CLEAR or snapshot.unresolved_intent_blocked:
        raise RuntimeError('Missing, unreadable or blocked durable safety state')
    intent_path=Path(settings.intent_store_path).resolve()
    if not intent_path.is_file():raise RuntimeError('Durable intent state unavailable')
    with sqlite3.connect(intent_path.as_uri()+'?mode=ro',uri=True,timeout=3) as c:
        if c.execute('SELECT count(*) FROM post_fill_integrity_halt').fetchone()[0] or c.execute("SELECT count(*) FROM intent_records WHERE state IN ('PENDING','UNKNOWN')").fetchone()[0]:
            raise RuntimeError('Persisted integrity halt or unresolved intent blocks management')


async def manage_partials(settings):
    if getattr(settings,'weltrade_partial_management_enabled',False) is not True:return
    authorized(settings)
    with database(settings) as c:rows=[dict(r) for r in c.execute("SELECT * FROM partial_positions WHERE state NOT IN ('PROTECTED','CLOSED')")]
    if not rows:return
    async with get_gateway(settings) as gateway:
        account=await gateway.get_account_info()
        for row in rows:
            authorized(settings)
            if row['account']!=account.account_id:raise RuntimeError('Partial registry account mismatch')
            snap=await gateway.partial_management_snapshot(row['ticket'])
            if snap is None:
                update(settings,row,'CLOSED');continue # canonical close monitor separately confirms outcome
            if snap['side']!=row['side'] or not math.isclose(snap['entry'],row['entry'],abs_tol=1e-8):
                raise RuntimeError('Managed position identity changed')
            _,stop=levels(row['side'],row['entry'],row['initial_stop'])
            if row['state']=='READY':
                if not math.isclose(snap['volume'],row['volume'],abs_tol=1e-8):
                    raise RuntimeError('Unexpected unmanaged volume change')
                if not ready(row['side'],snap['quote'],row['entry'],row['initial_stop'],snap['distance']+snap['trade_tick_size']):continue
                update(settings,row,'CLOSE_REQUESTED',expected='READY')
                # A durable claim precedes the mutation. An uncertain result is never resent.
                await gateway.partial_close_confirmed(row['ticket'],original_volume=row['volume'],portion=row['portion'])
                update(settings,row,'PARTIAL_CONFIRMED');row['state']='PARTIAL_CONFIRMED'
            elif row['state']=='CLOSE_REQUESTED':
                if not await gateway.partial_volume_confirmed(row['ticket'],original_volume=row['volume'],portion=row['portion']):
                    raise RuntimeError('Uncertain partial outcome; operator reconciliation required')
                update(settings,row,'PARTIAL_CONFIRMED');row['state']='PARTIAL_CONFIRMED'
            if row['state']=='PARTIAL_CONFIRMED':
                authorized(settings)
                if await gateway.protect_partial_stop(row['ticket'],remaining_volume=row['portion'],stop=stop):
                    update(settings,row,'PROTECTED')
                else:
                    update(settings,row,'PARTIAL_CONFIRMED','BROKER_STOP_DISTANCE_OR_UPDATE_PENDING')
                    raise PartialProtectionPending('Partial confirmed; profit stop pending broker-valid update')
