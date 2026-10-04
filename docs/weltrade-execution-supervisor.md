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

On 2026-10-04 the owner explicitly authorized demo execution and enabled terminal
Algo Trading and external Python trading. The read-only preflight then reported
authoritative daily state with only `READ_ONLY_PREFLIGHT_NO_ORDER_INTENT`.
The separate supervisor was started with a process-local execution flag, while
the shared dotenv files and the API remained execution-disabled. It evaluates
the four existing watchlist pairs at M5 boundaries; no symbols or risk limits
were expanded. The first journaled cycle recorded eight analysis/decision events,
all `NO_TRADE`. This verifies operation, not a successful new broker fill.

The append-only decision journal is `state/decision_journal.sqlite3`. Analysis is
written before an order path; an unreadable journal prevents new unaudited
submissions. Each analysis includes UTC candle time, regime, canonical confidence,
quality, contributing reasons and six-factor evidence. The decision event records
the status, decision code and broker order reference. Confirmed fills and closes
remain in the existing reconciled position ledger and MT5 history. Journaling does
not train or modify the strategy automatically.

The local browser entry is `http://127.0.0.1:5173/workstation` in Vite development
mode only, on an exact loopback hostname. Production builds always retain the
hosted auth shell. Open **Journal** to review reasons and the independent
supervisor state. The API's disabled execution flag describes the observation
process, not the separately armed supervisor.

Forward monitoring uses `data/live_monitoring_20261004.sqlite3` through a
process-local `JQE_HISTORICAL_DATA_PATH` override. It preserves the pre-existing
historical database whose duplicate conflicts caused cached fallback. The API
now caches only closed candles. Native Weltrade synthetic symbols use a continuous
weekend clock; forex weekend rules remain unchanged. Direct ticks and closed
candles were verified against the local terminal. Telegram accepted a real FX Vol
20 M5 chart diagnostic at the existing configured destination.

These processes run while this Windows session and workstation remain available.
No startup task or automatic restart after reboot was registered. The supervisor
halts on failed prerequisites; it never clears an emergency stop or integrity halt.
The Vercel deployment still cannot reach MT5: a protected authenticated HTTPS
read-only relay must be configured and verified before remote market monitoring.
No public workstation port or hosted order route was enabled.

Final validation: 2,460 backend tests passed, four skipped, all 18 group exit codes
zero (`reports/backend-demo-ready-20261004`); 168 frontend tests passed and the
production build passed. Journal transport errors stay in Notifications; failing
requests never report the supervisor armed. Desktop and 390px mobile journal/live
workspace screenshots are under `reports/demo-ready-20261004`; mobile document
width matched the 390px viewport. Source review found no credential-like literals.

Outstanding verification: wait for a genuine strategy-authorized demo signal,
then verify the new fill and close against broker history and the durable ledger.
No order was forced for demonstration. Hosted remote monitoring is blocked by the
absence of a configured authenticated HTTPS relay. A funding campaign also needs
an owner-selected budget/target, destination and audience; the draft is
`docs/jqe-funding-brief.md`. Pricing and payment collection remain inactive.
