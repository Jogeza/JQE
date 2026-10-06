"""Compare history windows; opt-in backed-up ledger repair retains the halt.

No terminal login, order mutation, alert delivery, or halt clearing occurs.
"""
from datetime import datetime, timedelta, timezone
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3

from config.settings import Settings
from core.processes import is_process_alive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reconcile', action='store_true', help='Back up and reconcile ledger; retain halt and pending alerts')
    args = parser.parse_args()
    settings = Settings()
    heartbeat = json.loads(Path('state/weltrade_execution_supervisor_heartbeat.json').read_text())
    print('supervisor', heartbeat['status'], 'alive', is_process_alive(heartbeat['pid']))
    if args.reconcile and is_process_alive(heartbeat['pid']):
        raise RuntimeError('Supervisor must be stopped')
    for path, query in (
        (settings.intent_store_path, 'SELECT reason FROM post_fill_integrity_halt'),
        (settings.execution_position_ledger_path,
         'SELECT position_id,symbol,opened_at,reconciliation_state,realized_pnl,close_reason,closed_at FROM live_paper_positions'),
    ):
        with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
            print(query, db.execute(query).fetchall())
    import MetaTrader5 as terminal
    from broker.mt5_gateway import _history_server_offset
    if terminal.initialize(str(settings.weltrade_terminal_path)) is not True:
        raise RuntimeError('Existing terminal unavailable')
    try:
        account = terminal.account_info()
        info = terminal.terminal_info()
        if (account is None or info is None or account.trade_mode != 0
                or account.login != settings.effective_weltrade_login
                or account.server != settings.effective_weltrade_server
                or Path(info.path).resolve() != Path(settings.weltrade_terminal_path).resolve().parent):
            raise RuntimeError('Existing Weltrade demo identity mismatch')
        now = datetime.now(timezone.utc)
        offset = _history_server_offset(terminal, now)
        if offset is None:
            raise RuntimeError('Server clock unresolved')
        positions = terminal.positions_get()
        if positions is None:
            raise RuntimeError('Broker positions unavailable')
        print('offset_seconds', offset, 'open_positions', len(positions))
        for label, shift in (('UTC', 0), ('SERVER', offset)):
            deals = terminal.history_deals_get(now - timedelta(days=2) + timedelta(seconds=shift),
                                               now + timedelta(seconds=shift))
            print(label, 'unavailable' if deals is None else [
                dict(ticket=d.ticket, position=d.position_id, symbol=d.symbol,
                     entry=d.entry, volume=d.volume, profit=d.profit,
                     commission=d.commission, swap=d.swap,
                     utc=datetime.fromtimestamp(d.time-offset, timezone.utc).isoformat())
                for d in deals if d.position_id])
        if args.reconcile:
            source = Path(settings.execution_position_ledger_path).resolve()
            backup = source.parent / 'backups' / f'{source.stem}-pre-close-reconcile-{now:%Y%m%dT%H%M%SZ}.sqlite3'
            backup.parent.mkdir(exist_ok=True)
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as db:
                with sqlite3.connect(backup) as target:
                    db.backup(target)
            # Reuse the already verified session without switching login or terminal.
            class ExistingSession:
                def __getattr__(self, name):
                    return getattr(terminal, name)
                def initialize(self, path):
                    return path == str(Path(settings.weltrade_terminal_path).resolve())
                def login(self, login, *, password, server):
                    current = terminal.account_info()
                    return current is not None and current.login == login and current.server == server
                def shutdown(self):
                    pass
            from monitoring.weltrade_close_monitor import monitor_weltrade_closes
            try:
                asyncio.run(monitor_weltrade_closes(settings, terminal=ExistingSession(), notify=False))
            except RuntimeError as exc:
                if str(exc) != 'Weltrade persisted integrity halt remains active':
                    raise
                print('Ledger reconciliation completed; persisted halt remains active')
            print('backup', backup)
    finally:
        terminal.shutdown()


if __name__ == '__main__':
    main()
