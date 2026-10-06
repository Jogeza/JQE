"""Back up and refresh blocked safety evidence against the existing demo session.

Never logs in, changes accounts, submits orders or clears the integrity halt.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import MetaTrader5 as mt5

from config.settings import Settings
from tools.evaluate_execution_safety import evaluate


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
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        original = Path(configured.execution_safety_store_path).resolve()
        if original.exists():
            backup = original.parent/'backups'/f'{original.stem}-pre-readonly-refresh-{stamp}.sqlite3'
            backup.parent.mkdir(exist_ok=True)
            with sqlite3.connect(original.as_uri()+'?mode=ro', uri=True) as source:
                with sqlite3.connect(backup) as target:
                    source.backup(target)
        class ExistingSession:
            def __getattr__(self, name):
                return getattr(mt5, name)
            def initialize(self, path):
                return path == str(Path(configured.weltrade_terminal_path).resolve())
            def login(self, login, *, password, server):
                current = mt5.account_info()
                return current is not None and current.login == login and current.server == server
            def shutdown(self):
                pass
        result = evaluate(configured, terminal=ExistingSession())
        print(json.dumps({'observed_at': result.observed_at.isoformat(),
                          'authorization': result.execution_authorization.value,
                          'daily_state_authority': result.daily_state_authority.value,
                          'reasons': result.reason_codes}))
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    main()
