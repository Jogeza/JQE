"""Capture advisory daily accounting from an existing verified demo session."""
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import MetaTrader5 as mt5
from analytics.daily_balance import BalanceMovement, daily_balance
from broker.mt5_gateway import _history_server_offset
from config.settings import Settings


def main():
    configured = Settings()
    if not mt5.initialize(str(configured.weltrade_terminal_path)):
        raise RuntimeError('Existing terminal unavailable')
    try:
        account, terminal = mt5.account_info(), mt5.terminal_info()
        if (account is None or terminal is None or account.trade_mode != 0
                or account.login != configured.effective_weltrade_login
                or account.server != configured.effective_weltrade_server
                or Path(terminal.path).resolve() != Path(configured.weltrade_terminal_path).resolve().parent):
            raise RuntimeError('Existing demo identity mismatch')
        now = datetime.now(timezone.utc)
        offset = _history_server_offset(mt5,now)
        if offset is None:
            raise RuntimeError('Server clock unresolved')
        start = datetime.combine(now.date(),time.min,tzinfo=timezone.utc)
        deals = mt5.history_deals_get(start+timedelta(seconds=offset),now+timedelta(seconds=offset))
        if deals is None:
            raise RuntimeError('Daily broker history unavailable')
        categories = {mt5.DEAL_TYPE_BUY:'TRADE',mt5.DEAL_TYPE_SELL:'TRADE',mt5.DEAL_TYPE_BALANCE:'FUNDING'}
        for label in ('DEAL_TYPE_COMMISSION','DEAL_TYPE_COMMISSION_DAILY','DEAL_TYPE_COMMISSION_MONTHLY','DEAL_TYPE_INTEREST'):
            value = getattr(mt5,label,None)
            if value is not None:
                categories[value] = 'TRADE'
        movements = []
        for deal in deals:
            if deal.type not in categories:
                raise RuntimeError('Unsupported balance movement; no baseline published')
            movements.append(BalanceMovement(str(deal.ticket),datetime.fromtimestamp(deal.time-offset,timezone.utc),
                categories[deal.type],float(deal.profit)+float(deal.commission)+float(deal.swap)+float(getattr(deal,'fee',0))))
        # Reject an account change or a balance mutation during history retrieval.
        after = mt5.account_info()
        if after is None or after.login != account.login or after.server != account.server or after.balance != account.balance:
            raise RuntimeError('Account snapshot changed; retry required')
        result = daily_balance(balance=float(account.balance),observed_at=now,movements=movements,history_complete=True)
        result.update(broker='weltrade',environment='DEMO',currency=account.currency,day_boundary='00:00 UTC',
                      advisory_only=True,execution_authorized=False)
        store_path = Path('state/daily_balance_observations.sqlite3')
        with sqlite3.connect(store_path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS observations (account_id TEXT, observed_at TEXT, utc_date TEXT, payload TEXT)')
            db.execute('INSERT INTO observations VALUES (?,?,?,?)',(str(account.login),now.isoformat(),now.date().isoformat(),json.dumps(result)))
        Path('reports/daily-balance-latest.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    main()
