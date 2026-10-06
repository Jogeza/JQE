# Weltrade close-history repair — 5 October 2026

The execution supervisor heartbeat reports STOPPED and its PID is no longer
alive. The demo terminal had no open positions. The persisted
`post_fill_integrity_halt` remains `CLOSE_UNCONFIRMED`; execution was not restarted
or armed, and no execution gates or dotenv files were changed.

## Broker evidence and repair

An existing-terminal read, without switching login, verified the configured
Weltrade demo account and terminal path. A fresh FX Vol 20 tick established a
10,800-second server offset. A two-day UTC history query returned zero deals;
the same bounds shifted to server time returned both openings and closes.

The shared history snapshot reader now shifts query bounds into server time
while retaining UTC coverage metadata and converting returned timestamps to
UTC. UNKNOWN-intent recovery shifts both historical-order and historical-deal
queries too, preventing a false absence finding from the same defect.

The ledger was backed up using SQLite backup to
`state/backups/execution_positions-pre-close-reconcile-20261004T214324Z.sqlite3`
before reconciliation. Both positions now have `CLOSE_CONFIRMED`:

| Position | Native symbol | Lots | UTC close | Reason | Net realized USD |
| --- | --- | --- | --- | --- | --- |
| 562375715 | SFX Vol 99 | 0.03 | 2026-10-04 20:11:13 | STOP_LOSS | -1.02 |
| 562440699 | SFX Vol 20 | 0.02 | 2026-10-04 20:12:58 | TAKE_PROFIT | +1.58 |

Broker-reported commission and swap for these deals were zero. Their combined
result is +0.56 USD. This is evidence for two closes, not expectancy evidence or
daily target tracking.

`python -m tools.inspect_close_history` is read-only by default. Its explicit
`--reconcile` mode backs up the ledger, reuses the verified existing terminal
session and invokes the canonical close monitor with notification delivery off.
It retains the persisted halt and leaves close notifications unclaimed. It never
submits orders, clears the halt, changes terminal login or restarts a service.
Offline regression coverage verifies server-filtered recent deals, recovery
matching, and silent close reconciliation with a retained halt.

Running API processes were left intact, so they have not loaded this source
repair. Operator review and a controlled service reload remain necessary before
any subsequent execution decision. The halt must not be cleared merely because
the ledger rows are closed; follow the reconciliation procedure in
`docs/weltrade-execution-supervisor.md` for all durable intent and fill evidence.

## Hosted AI verification

The signed-in production Workspace displayed LIVE closed-candle evidence for
FX Vol 20 M5, a verified demo balance/equity of 143.91 USD, and zero terminal
positions. Local active-analysis also returned BROKER, non-stale, non-degraded
evidence with a fresh observation time.

One text-only hosted AI request asked for context state, observation time and
latest close. JQE rejected it at the daily quota. No retry, quota bypass, paid
model or screenshot upload was used. A successful hosted AI context answer
remains unverified; the existing context projection was not relaxed.

## Remaining work

Markets layout and drawing persistence/usability improvements remain pending.
Daily starting-balance and realized-P&L tracking also remain pending. The current
20% target is advisory and based on current balance. TP1/add-on semantics are
still undesigned, and no VPS purchase or real-account execution is authorized.

An existing shared-log rotation produced Windows file-lock warnings during the
read-only broker guard check. Reconciliation still completed and durable rows
were verified afterward; the shared logging issue remains separate follow-up.

## Validation

Full backend validation: 2,522 passed, four skipped, all 18 group exit codes
zero (`reports/backend-20261005-004045/totals.json`). The final focused rerun
includes the two subsequently added recovery/silent-reconciliation regressions:
29 passed (`reports/close-history-final-20261005`). Frontend: 172 passed;
production build passed with the existing bundle-size warning. No deployment
was made. Existing temporary scripts and historical backups remain intact.
