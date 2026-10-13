# Training and demo continuation check (2026-10-09)

The existing training campaign remains running; no duplicate, retry or source
edit was made. Latest: seven completed, eighth active, zero recorded failures;
final summary absent. Replay and detached one-shot audit watcher alive.

Independent saved-artifact partial audit of the first six pairs passed with
zero errors: `reports/long-history-training-partial-audit-20261009-02/audit.json`.
It checks complete-result/fingerprint hash preimages, exact windows/configuration,
provider/manifest/spread/cost/source bindings, counts and no-trade nulls. All six
had zero trades. Trade-invariant audit branches are not qualified by zero-trade
cases. Final 30-case audit and expectancy/performance conclusions remain pending.

Demo supervisor worker 8004 remains RUNNING; cycle two completed across the same
14 watchlist pairs. Since launch: 19 NO_TRADE and nine BLOCKED journal decisions;
no filled-order status reported. Existing limits remain enforced; no forced
order, gate/risk expansion or terminal/service restart occurred.

Snapshot: `reports/long-history-and-demo-progress-20261009-01.json`.
Full validation remains backend 2,702/four skips and frontend 240/build passed;
no application code changed, so tests were not needlessly repeated.

Next: inspect these same running processes and ledger; finish fixed 30 cases,
then inspect full audit/report. Never fit ML/promote a candidate based on this
partial training snapshot. Costs/calendar/historical economics remain conditional.

## Subsequent continuation: half campaign audited

Latest snapshot `reports/long-history-and-demo-progress-20261009-02.json`:
15/30 complete, SFX Vol 20 zero-commission active, zero failures/no summary.
All five FX symbols across three costs completed with no trades. Partial saved-
artifact audit `reports/long-history-training-partial-audit-20261009-03/audit.json`
PASS for 15 pairs, zero errors. Null expectancy/profit factor retained. No
qualification of the remaining SFX cases, executed-trade audit branches or ML.

Demo supervisor RUNNING, six cycles: 63 NO_TRADE, 20 BLOCKED, one
PRE_SUBMIT_VALIDATION_REJECTED. That SFX99 candidate passed the pure execution
policy but its stop was 892 points versus the broker minimum 1,716; gateway
rejected before broker submission. No fill reported; read-only terminal check
verified configured demo identity and zero open positions. Do not interpret
journal decision_code ALLOWED as a fill or bypass the stop/quantity constraints.

Replay and final-audit watcher are alive. No source/risk/gate changes, duplicate
campaign, automatic retry or supervisor restart. Next finish same 30-case
campaign and inspect its full audit. Validation unchanged; no code edits.

## Subsequent continuation: 25-case audit and verified demo opening fill

Existing campaign latest 25/30 complete, SFX80 assumed-cost active, zero failures,
no summary. Partial saved-artifact audit 04 PASS/25 pairs/zero errors:
`reports/long-history-training-partial-audit-20261009-04/audit.json`.
Final five cases/full audit remain pending; replay/watcher alive and unchanged.

Demo supervisor now BLOCKED OPEN_POSITION_LIMIT_REACHED, which preserves the
configured one-position limit. SFX99 M5 BUY position/order 569491053, broker opening
deal 538066669: 0.03 lots, fill 1688.05, SL 1669.88, TP 1725.44. Broker opening
deal, live position, accepted durable intent and position ledger agree on identity,
side/volume/fill/stops. Planned intent entry 1688.4 differs from actual fill; ledger
records actual 1688.05. Expected stop loss USD 0.56 versus authorized USD 0.71485.
No integrity halt. Position is OPEN; floating P/L is not a closed outcome.
Opening commission/swap/fee zero is one observed deal, not a universal tariff.
Evidence: `reports/demo-opening-fill-audit-20261009-01.json`.

Direct UTC-bound history query initially returned no deals because Weltrade SDK
filters use server-clock epochs. Position-scoped history returned the opening
deal, consistent with existing canonical history reader's offset conversion.
No history reader, terminal, position, risk/gate or replay source was changed.
Do not close/modify the position merely to generate outcome evidence. Next finish
same training campaign/full audit and let canonical monitor reconcile a natural
broker close. No source edits; existing full tests/build validation still applies.
