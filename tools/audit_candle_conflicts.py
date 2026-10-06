"""Read-only comparison of watchlist cache with existing verified demo history."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sqlite3

import MetaTrader5 as mt5
from broker.mt5_gateway import _history_server_offset
from config.settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', action='store_true', help='Back up cache and reconcile only audited conflicts')
    args = parser.parse_args()
    settings = Settings()
    if not mt5.initialize(str(settings.weltrade_terminal_path)):
        raise RuntimeError('Existing terminal unavailable')
    try:
        account, terminal = mt5.account_info(), mt5.terminal_info()
        if (account is None or terminal is None or account.trade_mode != 0
                or account.login != settings.effective_weltrade_login
                or account.server != settings.effective_weltrade_server
                or Path(terminal.path).resolve() != Path(settings.weltrade_terminal_path).resolve().parent):
            raise RuntimeError('Existing demo identity mismatch')
        now = datetime.now(timezone.utc)
        offset = _history_server_offset(mt5, now)
        if offset is None:
            raise RuntimeError('Server clock unresolved')
        with sqlite3.connect(Path(settings.watchlist_store_path).resolve().as_uri()+'?mode=ro', uri=True) as watch:
            pairs = watch.execute('SELECT symbol,timeframe FROM watchlist').fetchall()
        reports = []
        with sqlite3.connect(Path(settings.historical_data_path).resolve().as_uri()+'?mode=ro', uri=True) as db:
            catalogue = {s.name for s in mt5.symbols_get() or ()}
            for symbol, tf in pairs:
                native = next((s for s in catalogue if s.upper() == symbol.upper()), None)
                if native is None or tf not in ('M1','M5'):
                    raise RuntimeError('Unsupported or unavailable watchlist pair')
                seconds = 60 if tf == 'M1' else 300
                rates = mt5.copy_rates_from_pos(native, mt5.TIMEFRAME_M1 if tf == 'M1' else mt5.TIMEFRAME_M5, 0, 2001)
                if rates is None:
                    raise RuntimeError('Terminal history unavailable')
                conflicts = []
                compared = 0
                cached = {}
                for old in db.execute('SELECT time,symbol,open,high,low,close,volume FROM candles WHERE provider=? AND upper(symbol)=upper(?) AND timeframe=? AND time>=?',
                                      ('weltrade',symbol,tf,int(rates[0]['time'])-offset)):
                    cached.setdefault(old[0], []).append(old[1:])
                for rate in rates:
                    at = int(rate['time'])-offset
                    if at+seconds > now.timestamp():
                        continue
                    current = [float(rate[k]) for k in ('open','high','low','close','tick_volume')]
                    stored = cached.get(at, [])
                    for old in stored:
                        compared += 1
                        if list(old[1:]) != current:
                            conflicts.append({'symbol':old[0],'utc':datetime.fromtimestamp(at,timezone.utc).isoformat(),
                                              'stored':list(old[1:]),'broker':current,
                                              'ohlc_changed':list(old[1:5]) != current[:4]})
                reports.append({'symbol':native,'timeframe':tf,'compared':compared,'conflicts':conflicts})
        output = Path('reports')/f'candle-conflict-audit-{now:%Y%m%dT%H%M%SZ}.json'
        output.write_text(json.dumps({'offset_seconds':offset,'observed_at':now.isoformat(),'pairs':reports},indent=2))
        if args.repair:
            source_path = Path(settings.historical_data_path).resolve()
            backup_path = source_path.with_name(f'{source_path.stem}.pre-conflict-repair-{now:%Y%m%dT%H%M%SZ}.sqlite3')
            with sqlite3.connect(source_path.as_uri()+'?mode=ro', uri=True) as source:
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
                    if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Backup integrity check failed')
            with sqlite3.connect(source_path) as target:
                target.execute('BEGIN IMMEDIATE')
                for report in reports:
                    for conflict in report['conflicts']:
                        key = ('weltrade',conflict['symbol'],report['timeframe'],int(datetime.fromisoformat(conflict['utc']).timestamp()))
                        old = target.execute('SELECT open,high,low,close,volume FROM candles WHERE provider=? AND symbol=? AND timeframe=? AND time=?',key).fetchone()
                        if old is None or list(old) != conflict['stored']:
                            raise RuntimeError('Cache changed after audit; repair rolled back')
                        target.execute('UPDATE candles SET open=?,high=?,low=?,close=?,volume=? WHERE provider=? AND symbol=? AND timeframe=? AND time=?',
                                       tuple(conflict['broker'])+key)
            print(json.dumps({'backup':str(backup_path),'repair':'AUDITED_CONFLICTS_ONLY'}))
        print(json.dumps({'report':str(output),'pairs':len(reports),'conflicts':sum(len(r['conflicts']) for r in reports),
                          'ohlc_conflicts':sum(c['ohlc_changed'] for r in reports for c in r['conflicts'])}))
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    main()
