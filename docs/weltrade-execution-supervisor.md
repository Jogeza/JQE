# Weltrade demo execution supervisor

The API is read-only. The shared `.env` keeps
`JQE_BROKER_EXECUTION_ENABLED=false`. The observation supervisor remains
read-only and refuses an enabled execution flag.

`tools.run_weltrade_execution_supervisor` is the separate execution process.
It requires `JQE_BROKER_EXECUTION_ENABLED=true` in **that process's own
environment**. It evaluates the read-only Weltrade preflight before each M5
cycle and then delegates watchlist pairs to `main.run_watchlist`, which uses the
canonical strategy, risk, durable intent, and broker checks. A blocked or
unreadable preflight prevents the cycle. The process has a separate mutex and
heartbeat under `state/`.

Before the first cycle and before every later signal cycle, the supervisor
reconciles open ledger positions against the demo terminal. This monitor only
reads positions and the authoritative MT5 deal history. A confirmed full close
records the broker exit price, time, net profit including attributed swap and
commission, and the reported reason, then claims the closed-trade alert once.
Confirmation requires the opening deal volume as well as every closing deal;
missing opening fee evidence leaves the result unconfirmed.
Partial closes update the remaining volume and realized profit; the row stays
open until the broker reports no position. An overdue position is logged and
left untouched.

## Close reconciliation halt and operator recovery

If the broker position disappears but its closing deals cannot be established
from complete, authoritative history, the ledger row becomes
`CLOSE_UNCONFIRMED`, one blocked-trade alert is claimed, and a durable integrity
halt prevents all further submissions. An unreadable position snapshot or a
ledger write failure also halts submissions. The monitor never guesses an exit
price or result and never closes or changes a broker position.

To resolve a halt, keep the supervisor stopped. Compare the affected ticket in
the Weltrade demo terminal with the ledger and the complete broker deal history.
Resolve missing or ambiguous history with the broker before changing the
ledger. After the history reader is authoritative again, run the read-only
monitor to reconcile the position and confirm that its ledger row is closed
with the correct volume, exit, result, and reason. For an integrity halt caused
by a ledger write failure, repair the database problem and reconcile the
affected row from broker evidence. For a prior confirmed-fill halt, reconcile
its intent, broker position, ledger row, and opened alert separately. Only then
may an operator remove the single row from the `post_fill_integrity_halt`
table in the configured intent SQLite store, in a SQLite transaction:

```sql
BEGIN IMMEDIATE;
SELECT reason FROM post_fill_integrity_halt WHERE singleton_id = 1;
DELETE FROM post_fill_integrity_halt WHERE singleton_id = 1;
COMMIT;
```

The operator must check the selected reason and broker/ledger evidence before
executing the delete. The application deliberately has
no automatic halt clearing: clearing the marker while a row remains
`CLOSE_UNCONFIRMED`, or while broker and ledger evidence disagree, would make
the next execution cycle unsafe. Preserve a backup and an audit record of the
broker evidence and the manual database change.

The preflight can be run without arming execution:

```powershell
& D:\JQE\venv\Scripts\python.exe -m tools.evaluate_execution_safety
```

Its safety snapshot is always `BLOCKED` with
`READ_ONLY_PREFLIGHT_NO_ORDER_INTENT`: it does not evaluate a signal, stop-loss,
quantity, or order. Additional reason codes report failed prerequisites. A
clear preflight is therefore evidence for the supervisor's next guarded cycle,
not a trade authorization. The ordinary safety snapshot freshness window is
15 seconds; a single manual evaluation will become stale.

No execution supervisor or scheduled task is started by this change. Launching
the process is a separate operator decision after the terminal reports
`trade_allowed=True` and all other checks pass.
