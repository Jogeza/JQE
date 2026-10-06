# Operator-authorized demo restart

The owner requested “enable broker execution” and then “do it” after the
audited halt-resolution prerequisite was explained. The existing manual
recovery procedure in `docs/weltrade-execution-supervisor.md` was followed.

The supervisor was verified stopped. The existing configured Weltrade demo
identity and terminal path matched, positions and pending orders were empty,
and all three ledger records were CLOSE_CONFIRMED. Complete broker deal history
matched opening/closing volumes, symbols, net P&L including fees and UTC close
times. No unresolved PENDING/UNKNOWN intents remained.

At 13:09 Kampala the intent database was backed up to
`state/backups/intent_records-pre-halt-resolution-20261005T100930Z.sqlite3`.
The operator authorization and broker evidence were recorded transactionally
in `operator_halt_resolution_audit`; only the reconciled CLOSE_UNCONFIRMED
marker was removed. Evidence is `reports/close-halt-resolution-20261005.json`.
The one-time operator script is `reports/resolve-close-halt-20261005.py`.

The canonical supervisor was launched with a process-local execution flag,
separate logs and all existing risk limits. Shared .env/.env.ai and the
read-only API remain execution-disabled. Actual supervisor PID is 11628.
Heartbeat reported RUNNING, cycle 1, “14 pairs evaluated” at 13:11 Kampala.
All 14 initial decisions were NO_TRADE; no new order was forced.

Logs: `logs/execution-20261005-1309.stdout.log` and
`logs/execution-20261005-1309.stderr.log`. The PC and terminal must remain on.
Five combined positions at verified USD equity >=50 remains the existing cap;
limit-order preparation, experimental Fibonacci variants and automatic
continuation exit advice were not enabled in production. No positive expectancy
or profit guarantee follows from this operational verification.
