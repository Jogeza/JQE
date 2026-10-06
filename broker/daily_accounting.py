"""Read-only daily cash accounting from an already verified MT5 session."""
from datetime import datetime, time, timedelta, timezone
from analytics.daily_balance import BalanceMovement, daily_balance


def read_daily_accounting(terminal, *, offset_reader):
    account = terminal.account_info()
    if account is None or account.trade_mode != 0 or 'WELTRADE' not in str(account.server).upper():
        raise ValueError('Verified Weltrade demo account required')
    now = datetime.now(timezone.utc)
    offset = offset_reader(terminal, now)
    if offset is None:
        raise ValueError('Server clock unavailable')
    start = datetime.combine(now.date(),time.min,tzinfo=timezone.utc)
    deals = terminal.history_deals_get(start+timedelta(seconds=offset),now+timedelta(seconds=offset))
    if deals is None:
        raise ValueError('Complete daily history unavailable')
    categories = {terminal.DEAL_TYPE_BUY:'TRADE',terminal.DEAL_TYPE_SELL:'TRADE',terminal.DEAL_TYPE_BALANCE:'FUNDING'}
    for label in ('DEAL_TYPE_COMMISSION','DEAL_TYPE_COMMISSION_DAILY','DEAL_TYPE_COMMISSION_MONTHLY','DEAL_TYPE_INTEREST'):
        value = getattr(terminal,label,None)
        if value is not None:
            categories[value] = 'TRADE'
    movements = []
    for deal in deals:
        if deal.type not in categories:
            raise ValueError('Unsupported balance movement')
        movements.append(BalanceMovement(str(deal.ticket),datetime.fromtimestamp(deal.time-offset,timezone.utc),
            categories[deal.type],float(deal.profit)+float(deal.commission)+float(deal.swap)+float(getattr(deal,'fee',0))))
    after = terminal.account_info()
    if (after is None or after.login != account.login or after.server != account.server
            or after.currency != account.currency or after.balance != account.balance):
        raise ValueError('Account snapshot changed during history query')
    result = daily_balance(balance=float(account.balance),observed_at=now,movements=movements,history_complete=True)
    result.update(currency=account.currency,day_boundary='00:00 UTC',advisory_only=True)
    return result
