# Demo trading readiness and recovery preview — 2026-10-11

Owner requests running JQE to make trades. Existing terminal identity verified Weltrade-Demo account ending 8111; balance 141.61 USD. API remains read-only. No supervisor running at inspection. No orders or armed process launched.

Supported preflight published fresh blocked diagnostic evidence, authoritative daily state, reason codes PERSISTED_INTEGRITY_HALT / CLOSE_UNCONFIRMED / READ_ONLY_PREFLIGHT_NO_ORDER_INTENT. Evidence: reports/demo-trading-preflight-20261011.txt. This refresh is not risk or order authorization. No halt cleared, environment/gates changed or source edits.

Affected operator ledger position 569491053, SFX Vol 99, 0.03 lots, opened October 9 14:05:13 UTC. Read-only attached-terminal evidence confirms zero current positions for ticket and matching entry/exit deal volumes, zero observed fees, close price 1656.54, net -0.95 USD. Evidence reports/demo-trading-close-evidence-20261011.json.

Copied both configured SQLite stores with SQLite backup to reports/demo-recovery-preview-20261011. Ran existing canonical close monitor on copies, notifications disabled. It confirmed CLOSE_CONFIRMED, close October 9 16:26:43 UTC, STOP_LOSS, price 1656.54, net -0.95 USD. Existing halt remained active on copy as designed; RuntimeError recorded. Operator ledger/halt not repaired or cleared. Result reports/demo-recovery-preview-20261011/result.json.

Specific owner authorization requested for backed-up operator reconciliation, clearing only the verified CLOSE_UNCONFIRMED marker with audit, and starting separate process-local gated demo supervisor. Required because original boundary explicitly forbids persisted safety-state changes. Shared dotenv, canonical live source, all risk limits, API read-only boundary, demo identity and research worker remain unchanged. Before applying any authorized recovery, recheck broker evidence and ledger/halt to reject changed state. Then rerun supported preflight; start only if sole reason READ_ONLY_PREFLIGHT_NO_ORDER_INTENT and daily state authoritative. No forced trades or guaranteed fills/performance.

Next: await scoped recovery authorization. Strategy expectancy/ML readiness remain unproven and campaign coverage incomplete.

## Authorized recovery applied and supervisor started

Owner explicitly authorized demo-only reconciliation, specific halt clearance and supervisor start. Rechecked exact broker deal evidence before mutation. SQLite backups of both operator stores, broker evidence and recovery record saved under `reports/demo-authorized-recovery-20261011`. Existing canonical close monitor reconciled operator ticket to CLOSE_CONFIRMED; notifications disabled during recovery. Transaction checked exact CLOSE_UNCONFIRMED halt, no unresolved PENDING/UNKNOWN intents and no CLOSE_UNCONFIRMED ledger rows, then inserted operator_halt_resolution_audit and deleted only the verified singleton marker. No other marker or risk limit changed.

Fresh preflight: AUTHORITATIVE daily state; sole READ_ONLY_PREFLIGHT_NO_ORDER_INTENT reason. Launched existing tools.run_weltrade_execution_supervisor with process-local execution flag; restored caller environment immediately. No dotenv/source edits. Launcher 8224, worker/heartbeat owner 6976; stdout/stderr/launch record in recovery directory. API remains execution-disabled, terminal stays existing Weltrade-Demo account ending 8111. Research worker 21872 remains alive/source unchanged.

First M5 cycle finished: RUNNING, cycle 1, 14 pairs evaluated. Logs record ten no-trade decisions and four sizing failures: authorized risk below broker minimum lot (FX Vol 20 M5, FX Vol 60 M5, FX Vol 99 M1, FX Vol 20 H1). No first-cycle submission/fill confirmed. Limits were not raised and minimum lots not rounded up. Heartbeat presence means loop operation, not every pair succeeded or a strategy edge.

Read-only observation-health API confirms RUNNING/process_alive=true/stale=false/execution_enabled=true for supervisor; terminal-observation API separately remains execution_enabled=false. Supervisor can submit future demo orders only through canonical strategy/risk/execution gates. Future integrity halts must stay fail-closed; this authorization applies only to the verified recovery above.

Validation: frontend 243/build passed; full offline backend result recorded after completion. No live test order forced. Next review subsequent demo cycles, sizing rejection frequency and broker-fill reconciliation without relaxing safeguards. Full research labels and positive expectancy remain unproven.
Final checks: backend 2,810 passed/four explicit opt-in skips/zero external network attempts, exit 0; frontend 243/build passed (existing bundle-size warning). Supervisor remains RUNNING/non-stale after first cycle; research worker retained. Logs reports/demo-start-backend-20261011.txt, reports/demo-start-frontend-20261011.txt and reports/demo-start-build-20261011.txt.

## Second cycle: broker-confirmed demo fill

At October 11 19:35:11 Kampala (16:35:11 UTC), canonical execution log records FILLED / ALREADY_EXECUTED, order 572131426, deal 540592635: SFX Vol 20 SELL 0.02 lots at 32827.82, SL 32853.28, TP 32772.14. Subsequent read-only terminal observation independently confirms matching open position. Evidence: reports/demo-authorized-recovery-20261011/confirmed-fill-observation.json and supervisor-stderr.log. ALREADY_EXECUTED is the executor reconciliation state, not evidence of a second submission.

Cycle 2 evaluated 14 pairs: one filled entry, nine no-trade outcomes and four broker minimum-lot risk failures. Risk-approved failure example: 0.5% of USD141.61 = USD0.70805; broker sizing rejects rather than rounding up minimum lots. Supervisor subsequently reports BLOCKED / OPEN_POSITION_LIMIT_REACHED, preserving the position cap. API remains execution-disabled. Research worker 21872 remains running. No source, limits, safety state or process changes in this follow-up.

A demo fill proves operational execution only; positive expectancy remains unproven. Next: verify this position's canonical monitoring and eventual broker-close reconciliation, preserving all caps/stops and campaign source. Recent full test results above remain applicable; no implementation changes requiring another suite run.

## Owner-authorized cap of five and other-symbol cycle

Owner selected five positions in response to bounded-cap/restart question. Restarted only verified old supervisor worker6976/launcher8224. New launcher6756/worker21488 uses process-local JQE_WELTRADE_DEMO_MAX_OPEN_POSITIONS=5 and execution=true; caller environment restored. No dotenv/source edits, MT5/API/research restarts or safety assertion changes. Existing equity-floor safeguard remains; pure effective-cap check returns5 at observed USD equity.

First new cycle at19:40 Kampala completed14 pairs, RUNNING: seven NO_TRADE_SIGNAL decisions, six minimum-lot risk failures (FX Vol20 M5/H1, FX Vol40 M1, FX Vol60 M1/M5, FX Vol99 M1), one DUPLICATE_SYMBOL_POSITION rejection for existing SFX Vol20. Zero new fills. Broker observation at19:41 confirms existing ticket572131426, unchanged SL/TP. API stays read-only/demo8111; research worker21872 retained. Launch/log/observation evidence: reports/demo-cap-five-20261011. Cap5 applies only this supervisor process and resets on a launch without explicit override.

156 focused offline position-cap/execution-policy/supervisor tests passed, zero external-network attempts. No implementation changed; prior complete backend/frontend checks remain recorded above. Other-symbol sizing constraints remain; no forced orders, risk increase or minimum-lot rounding. Next: quantify minimum-lot cash-risk feasibility from canonical evidence and monitor existing position's close. No positive-expectancy claim.

## Read-only sizing diagnosis — 19:42 Kampala

Current API terminal specifications for FX Vol20/40/60/99 and SFX Vol20: minimum0.01lots, tick size0.01, tick value0.01. Balance141.61USD and logged per-trade risk0.5% give budget0.70805USD. Indicative minimum-lot loss per price unit=0.01USD, maximum affordable stop distance70.805. These current tick-value estimates are explanatory, not authoritative order_calc_profit quotes, historical specifications, total fee-inclusive loss, or advice to change capital/risk. Saved evidence reports/demo-cap-five-20261011/sizing-feasibility.json.

Canonical first cap5 cycle logs and unchanged live builder (2ATR) explain rejected stop distances:

| Pair | Logged ATR | Planned 2ATR distance | Indicative min-lot loss USD |
|---|---:|---:|---:|
| FX Vol20 M5 |96.51643|193.03286|1.93033|
| FX Vol40 M1 |131.14286|262.28571|2.62286|
| FX Vol60 M1 |50.81500|101.63000|1.01630|
| FX Vol60 M5 |114.09929|228.19857|2.28199|
| FX Vol99 M1 |100.03429|200.06857|2.00069|
| FX Vol20 H1 |394.14071|788.28143|7.88281|

All exceed0.70805USD before additional costs. Actual canonical sizing rejects using broker P/L; table does not recreate signals or authorize orders. Quote-side/rounding adjustments may alter exact distances. SFX Vol20 candidate ATR13.48857 implies26.97714units/0.26977USD at minimum lot; duplicate-symbol policy rejected adding to existing position. Current observed ticket572131426 stillopen, SL32853.28/TP32772.14 intact; mark-to-market is not realized performance.

Supervisor remains RUNNING after14pairs, research worker21872 alive. No configuration/source/process/safety changes this diagnosis. Next preserve ongoing supervision and confirm broker-close reconciliation; evaluate any strategy/stop changes only through preregistered canonical research. Positive expectancy and full label coverage remain NOT proven.

## Progress check — 19:43 Kampala

Read-only terminal observation confirms ticket572131426 remains open; no broker close is yet available to reconcile. Read-only operator ledger lookup matches SELL0.02/entry32827.82/SL32853.28, remaining0.02, opened16:35:09UTC, timeframeM1, null close fields. Initial query used nonexistent broker_order_id column; inspected schema then corrected to position_id/order_id. No database mutations.

Research ledger snapshot:532 NEW COMPLETED,533 STARTED, zero FAILED records, no summary. Inherited11614 + NEW532 =12146 of241938 planned attempts (about5.02%); one in-flight attempt. Worker21872 alive. These are overlapping event-cost attempts, not independent trades. Coverage incomplete, no feature extraction or ML fit. Supervisor21488 RUNNING with fresh heartbeat. No process/source/settings changes.

Next: continue existing owners; reconcile actual close when available and finish complete label coverage before feature extraction. Do not launch duplicate campaigns or infer close/ML readiness from process health.

## Runtime close confirmed and dashboard discrepancy — 19:56 Kampala

Ticket572131426 canonical ledger CLOSE_CONFIRMED: closed16:54:44UTC (19:54:44Kampala), price32853.91, net-0.52USD, remaining0, reasonSTOP_LOSS, close notification claimed16:54:48UTC. Read-only terminal observation independently shows zero positions/balance141.09, matching141.61-0.52. Saved read-only ledger evidence reports/demo-cap-five-20261011/confirmed-close-ledger.json. Exit was0.63price units above requested SL32853.28; broker stops do not guarantee requested exit prices. Runtime close lifecycle succeeded for this ticket, not universal recovery qualification or positive expectancy.

API recent_trades count20 still omits this close despite fresh balance/positions. API service invokes gateway.get_trade_history(count=20); gateway uses a historical lookback. Trace ongoing; do not label this close unavailable or substitute fabricated history. Source frozen during campaign, no broker/API source patch or reload. SupervisorRUNNING/cycle4 and research retained.

Next investigate historical timestamp range/ordering with exact broker history evidence, preserving existing datasets and terminal identity. Fix dashboard read path only after source-transition qualification or authorized research-only stop; no automatic rearm.
