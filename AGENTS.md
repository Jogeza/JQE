# AGENTS.md — JQE AI Development & Architecture Guide

Latest continuation: supervisor RUNNING (worker 16492, cycle 3); order
575518694 closed TAKE_PROFIT +0.96, 575522313 open; balance 141.90 exact.
Local read-only frontend session live at http://localhost:5173/workstation
with populated account/chart/positions (evidence reports/frontend-session-
20261014-01/); nothing deployed. Campaign 17,291/241,938 pairs; full
coverage still gates ML.

Latest UI/runtime continuation: section 57 restores read-only API and populated
chart/account observation; supervisor stale, no execution readiness established.

Latest UI continuation: section 56 completes the Deriv-style workstation arrangement;
local only, populated account/chart verification remains blocked by API availability.

Latest UI continuation: section 55 adds the workstation account summary above
the chart. Local API failure still blocks populated visual verification.

Latest UI continuation: section 54 simplifies Research with collapsed controls;
local API HTTP 500 blocks populated-view verification. Research source unchanged.

Latest UI continuation: section53 simplifies Markets/Settings locally; no deployment.
Campaign source remains unchanged; inspect existing owner/ledger before research.

Latest UI continuation: section52 continues other-page design, not deployment.
Hosted release deferred by owner; campaign source remains untouched.

Latest UI continuation: section51 improves notification backgrounds locally.
Hosted release remains pending; keep unrelated workspace changes out of deployment.

Latest frontend continuation: section50 is presentation-only while campaign runs.
Read its handoff and inspect the existing campaign before research work.

Latest continuation: section49 supersedes running snapshots. Prior resume stopped
178 NEW/one unfinished, cause unknown. NEW second resume launched after231 inherited
completions verified. Inspect its owner/ledger; no duplicate/source edits.

Latest continuation: section48 audits36 NEW saved pairs, partial only. Resumed
campaign is running/source stable. Inspect its existing ledger/owner before work.

Latest continuation: section47 qualifies exact mixed-source lineage and launches
a NEW resumed segment. Check its owner/ledger before work; no source edits or
duplicate campaign. Complete coverage and feature extraction remain blocked.

Latest continuation: section 46 qualifies fixed executed/null replay evidence;
campaign stopped53/one unfinished. Exact contract integration still required.

Latest continuation: section 45 tests serialization acceleration only. Campaign
stopped53/one unfinished; source transition/resume not qualified. Read its handoff.

Latest continuation: section 44 supersedes running snapshots. Owner authorized
research-only stop;53 labels/one unfinished attempt retained. Profiling complete;
no acceleration or resume adopted. Read its handoff before source-transition work.

Latest continuation: section 43 audits23 saved full-label pairs; partial only.
Campaign still running/source stable. Inspect existing process/ledger before work.

Latest continuation: section 42 starts the full241938-attempt label campaign;
running/partial only. Check existing ledger/process before any work or source edit.

Latest continuation: section 41 implements lossless shared full-result storage;
read its proof/handoff before full dispatch. No new labels or campaign launched.

Latest continuation: section 40 implements immutable resumable full label dispatch;
full campaign not started. Read its handoff before launch or source edits.

Latest continuation: section 39 completes the separate all-symbol label pilot;
90 attempts audited, no full campaign or ML fit. Read its dated handoff before
implementing immutable resumable dispatch; preserve the pilot source/archive.

Latest continuation: section 28 freezes a separate longer-history training design;
zero new outcomes. Read its dated protocol before dispatch implementation.

Latest continuation: the training-label campaign and full coverage audit are
complete. Section 21 supersedes earlier running/pending progress snapshots.
Section 22 records the subsequent feature-semantics qualification.
Section 23 records completed canonical training-feature recording.
Section 24 records feature–label join and purge qualification.
Section 25 records the unqualified 90-day historical acquisition.
Section 26 records corrected range bounds and conditional Sunday-gap evidence.
Section 27 records conditional session coverage and new immutable 90-day bundles.

This document is the authoritative developer and AI agent guide for the **JQE Quantitative Trading Platform**. The supported deployment is Weltrade synthetic indices through the local Windows MT5 terminal. The previous phase is committed at `d6d00e1`; the Weltrade-only migration is the current work. Read README.md and docs/weltrade-roadmap.md first.

---

## 1. Core Architecture & Layering

JQE follows a strict Clean Architecture pattern. The Quant Core is completely broker-agnostic.

```text
Quant Core -> BrokerGateway -> WeltradeGateway -> MetaTrader5 Python API -> local Weltrade MT5
```

### Layer Rules:
- **`config/`**: Validated Pydantic Settings (`JQE_` prefix).
- **`core/`**: Shared kernel (logging, exceptions, indicators). Never import broker SDKs into `core/`.
- **`broker/`**: `BrokerGateway` ABC + implementations. Only `broker/factory.py` constructs gateways.
- **`data/`**: `CandleStore` (SQLite) + `HistoricalDataService` (gap-filling & incremental cache).
- **`intelligence/`**: Feature engines, market regime detection, 6-factor `ConfidenceModel`.
- **`strategy/`**: Signal generation. `strategy/pipeline.py` is the canonical bridge.
- **`risk/`**: `RiskEngine` authorizes account-currency risk and typed broker quantities. Legacy raw-lot helpers are backtesting-only.
- **`execution/`**: pure execution policy and lifecycle invariants; `execution/simulator.py` remains backtest-only. Broker mutation stays behind `BrokerGateway`.

---

## 2. Canonical Entry Points

### 2.1 Live Cycle — `main.py`
The single canonical live execution path is:
```text
main.py:run()
  1. gateway = get_gateway(settings) [async with gateway]
  2. gateway.get_candles(symbol, timeframe, count)
  3. validate_market_data(df)
  4. calculate_indicators(df)
  5. detect_regime(df)
  6. generate_trading_signal(df, symbol, regime)
  7. account = gateway.get_account_info()
  8. reconcile broker trade history; approve_trade(..., enforce_limits=True)
  9. TradePlanBuilder.build(...) and plan.is_valid()
 10. construct OrderRequest from the valid plan
 11. gateway.submit_order(order)
```

### 2.2 Backtest Cycle — `backtesting/backtest.py`
Replays historical data through the identical signal and risk pipeline via `BacktestEngine`.

---

## 3. Key Invariants & Pitfalls for AI Coding Agents

1. **Strategy Bridge is Mandatory:**
   - Always route signal generation through `strategy.pipeline.generate_trading_signal()`.
   - Direct calls to `SignalEngine` will drop signals because of indicator naming and regime vocabulary translation requirements.
2. **Trade Lifecycle Invariants:**
   - BUY: `stop_loss < entry < take_profit`
   - SELL: `take_profit < entry < stop_loss`
   - The live path currently rejects violations through `TradePlan.is_valid()`.
   - `TradeLifecycle` enforces the same relationship in its isolated legacy path but is not yet wired into `main.py`.
3. **Dead-Code Caution:**
   - `core.engine.JQEEngine`, `core.market_scanner.MarketScanner`, and `core.decision_pipeline.DecisionPipeline` are legacy dead-code paths. Do NOT build live logic on top of them.
4. **Environment Execution:**
   - Always run Python commands and tests via `D:\JQE\venv\Scripts\python.exe` and `D:\JQE\venv\Scripts\pytest.exe`.

5. **Phase 6 Execution Policy:**
   - `execution.policy.ExecutionPolicy` is a pure, fail-closed authorization policy. It must not construct/connect gateways, submit orders, or own authoritative position state.
   - Emergency stop blocks every new submission.
   - Upstream risk approval must be explicitly `True`.
   - Missing or unreadable safety state rejects execution.
   - Open-position limits reject at or above the configured limit.
   - Any existing position for the same symbol blocks another order; hedging and pyramiding remain undesigned.
   - Reused idempotency keys reject.
   - Broker-reported positions and history remain the source of truth.
   - The synchronous legacy `OrderManager` has been removed. Do not recreate an execution boundary outside `main.py` or `execution.executor.AsyncTradeExecutor`.

---

## 4. Development & Testing Workflow

```powershell
# Run the complete test suite
& D:\JQE\venv\Scripts\pytest.exe

# Execute one configured Weltrade cycle (inspect execution gate first; not an unconditional dry-run)
& D:\JQE\venv\Scripts\python.exe main.py

# Execute historical backtest
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest
```

## 5. Weltrade-only product contract

- Weltrade is the only configurable/selectable broker; MT5 is its transport. Reject unsupported configured or persisted identities without silently falling back.
- New dashboard and research history must come from the Weltrade terminal and be stored under the Weltrade provider. Do not substitute Deriv history or generated prices.
- Only native Weltrade synthetic indices are in deployment scope. Validate symbols through `broker/weltrade_symbols.py` and the terminal catalogue. Never equate Deriv aliases with Weltrade contracts.
- The current gateway is demo-only. Preserve server/account verification, terminal ownership, pre-submit checks and durable recovery. This migration does not authorize real-account execution or new orders.
- Backtest simulation and fake test gateways are internal research/testing tools, not selectable brokers. Keep tests offline with explicit injected doubles; do not loosen production validation to satisfy old tests.
- MT5 contract economics determine account-currency sizing. Do not label simulation units, assumed tick values or inferred volume as verified Weltrade lots or exchange volume.
- Keep old broker evidence and databases intact. Legacy adapters may remain during migration; their presence does not imply supported deployment. Update or retire obsolete product paths deliberately with coverage.
- Never read/log secrets wholesale. Do not change `.env`, `.env.ai`, running terminals, execution gates or persisted safety state as a side effect of tests.
- Use `D:\JQE\venv\Scripts\python.exe -m pytest` if the pytest launcher cannot start. Frontend checks are `npm test` and `npm run build` in `frontend/`.

## 6. Research and product standards

- Professional/institutional quality is a target, not a claim of verified profitability. Current scope research has not demonstrated positive expectancy.
- Use provider-pinned immutable datasets, closed bars, chronological holdouts, walk-forward tests, explicit costs and uncertainty intervals. Preserve negative results and disclose sample sizes and parameter trials.
- All live strategies use the canonical pipeline. Specialized research scripts are experimental unless equivalence with the live path is proven.
- Present live connection, stale evidence, simulated outcomes and broker fills accurately in the UI. Surface actionable blocks and data provenance; never imply readiness from a green connection badge alone.
- Future commercial access is verified Weltrade partner registration OR a paid JQE licence. It is not implemented. Obtain actual partner/payment/verification details before implementing entitlements; no invented API or client-side bypass.
- Before claiming completion, run relevant tests, then the full backend suite and frontend tests/build. Record remaining failures honestly in the handoff. Never delete safety assertions to make a migration green.

## 7. Windows validation and health checks

- Use `core.processes.is_process_alive()` for process health. Never use
  `os.kill(pid, 0)` on Windows: signal zero is a console control event and can
  interrupt the application, pytest, and its parent runner.
- `venv\Scripts\python.exe tools/check_backend_groups.py` validates all backend
  modules in bounded offline groups, with temporary configured stores and blocked
  real MT5 calls. It preserves verbose logs, JUnit XML and totals in a fresh
  `reports/backend-*` directory. Inspect every group exit code, not only totals.
- Archived forensic integration tests require `JQE_ARCHIVED_FORENSICS_ROOT` and
  the complete immutable campaign/database fixtures. Never substitute current
  operator databases to make these tests pass.

## 8. Entry-quality research controls (2026-10-08)

- `ff879e9` establishes canonical strategy v2 correctness, not positive expectancy.
  Keep v1 results immutable; do not transfer their validation to v2. The operative
  feature confidence and six-factor ConfidenceModel are distinct evidence: report
  which score actually gates entry. Unknown spread fallback 1.0 is not broker cost evidence.
- Run research backtests only through `D:\JQE\venv\Scripts\python.exe -m backtesting.backtest`.
  `--qualify-research-data NEWDIR` inventories frozen M5 bundles offline;
  `--entry-quality-audit NEWDIR` is diagnostic and cannot establish untouched OOS status.
  Neither command authorizes terminal acquisition or execution.
- Canonical backtest identity schema 2 binds effective evaluation window, provider,
  source, supplied manifest hash, source hashes and dependency versions. Start fresh
  processes. Reject detected edits during replay; do not compare results from
  concurrently edited code. Source snapshots are read-only and contain no environment files.
- Research comparisons require identical evaluation windows, dataset, provider,
  costs and capital/risk assumptions. Dataset equality or the legacy catalog's
  `controlled_comparison` flag alone is insufficient. Record all configurations,
  uncertainty, trade counts, symbols and windows, including negative findings.
- Existing inspected holdouts cannot become untouched by renaming or splitting
  them again. Require closed-bar provenance, documented gaps, verified MT5 contract
  economics/costs and a preregistered chronological campaign before promotion.
  Preserve missing economics as unavailable; never infer verified account-currency
  results from simulation quantities. Re-run at double spread/commission.
- Pytest discovery is rooted at `tests/`; downloaded external repositories under
  `reports/` are audit evidence, not JQE tests. Run the complete offline suite with
  `-p tests.offline_research_guard`; preserve every existing safety assertion.
- External repositories are design references only. Do not import their execution
  paths or claim their reported returns validate JQE. Rust work requires profiling
  and canonical equivalence first. See the dated repository audit and foundations handoff.

## 9. Frozen v2 campaign (2026-10-08)

- Read `docs/strategy-research/2026-10-08-v2-campaign.md` and its hashed protocol
  before candidate work. One reserved 2.0-ATR EMA50-distance filter; zero evaluated
  candidates. Do not broaden the grid, reset the registration or inspect final-test
  outcomes to improve a failed candidate. Validation: October 9–16 UTC; final test:
  October 16–30 UTC. All windows are half-open. Future evidence is unavailable now.
- The user has authorized read-only terminal inspection/history acquisition.
  That does not authorize orders, execution gate/state changes, account switching,
  service restarts or modification of existing datasets. Acquisition must use
  HistoricalDataService and NEW stores/bundles. Preserve every failed attempt.
- `tools.acquire_entry_campaign` preregisters before acquisition; `--protocol`
  reuses a verified frozen registration. `--attach-existing` only attaches to the
  already-running configured terminal and verifies its existing demo identity
  without logging in. Production gateway/demo checks remain active. Market Watch
  mutation and order submission are forbidden; verification evidence is isolated.
- Spread sidecars must bind to the same SDK response used by the historical
  service, timestamps/OHLC and manifest hash. A later read can differ while MT5
  synchronizes. Never fill gaps or repair immutable snapshots in place.
- Eighty current broker P/L probes are not historical sizing validation. Eighteen
  demo deal observations with zero commission fields do not establish a fee tariff;
  captured swap charges and published SyntX commission terms must be reconciled.
  Keep simulation units separate from verified account-currency P/L and MT5 lots.
- Next: frozen offline economics/cost integration in the canonical backtest, then
  training baseline and loser diagnosis. No terminal calls belong inside replay.
  Do not advance to the candidate or future test while those prerequisites fail.

## 10. Conditional offline economics and training

- Read `docs/strategy-research/2026-10-08-v2-training-baseline.md` before replay.
  `--campaign-training CAMPAIGN --cost-terms SNAPSHOT --output NEWDIR` dispatches
  through the canonical backtest module. It evaluates TRAIN only; do not silently
  expand it to validation/test or implement the reserved candidate in this step.
- FrozenMarketModel is optional research-only accounting. It requires exact native
  USD CFD terms, matched P/L and margin probes, timestamp-bound spread sidecars and
  immutable evidence hashes. No SDK session/history/order calls belong in replay.
- Unknown spread fallback remains a signal input; lagged recorded spread is a fill
  proxy. Generic replay stop/target defaults do not prove live-plan equivalence.
  Preserve these limitations in every report. Modeled USD is conditional evidence,
  not verified broker account returns or actual fills.
- Keep all three preregistered cost cases and all ten symbols, including no-trade
  outcomes. Never round up to minimum lot or raise capital/relax risk after seeing
  feasibility failures. No-trade expectancy and profit factor are undefined.
- Current swap rates, server offset and ending-day rollover calendar are assumptions
  about history. Published commission 'from USD 3' and zero observed fee fields do
  not verify a per-side tariff. Promotion remains blocked pending exact evidence.
- Preserve source during the full replay and retain the append-only trial ledger,
  full result hashes and source/dependency snapshots. Future holdouts remain sealed.
- Next work: finish the training campaign and loss/feasibility diagnosis, then
  reconcile costs. Current checks: 2,604 backend passed, four explicit opt-in skips;
  238 frontend passed and build passed. Safety assertions remain intact.
- Completion update: all 30 training replays finished with stable source. Only SFX
  Vol 99 traded; all three cost cases have negative mean net R. Nine symbols have
  no-trade outcomes from minimum-lot cash-risk/margin constraints. Preserve null
  expectancy for those symbols. No candidate or holdout was evaluated. Next work
  is exact fee/financing reconciliation and independent frozen-model/feasibility
  review, not a parameter search. See the completed dated training report.

## 11. Offline model review gate (2026-10-08)

- Read `docs/strategy-research/2026-10-08-model-review.md` before more research.
  Current frozen model v1 requires correction: quote-side minimum-stop checks,
  combined stop/slippage cash-risk rounding, and liquidation tick rounding.
- The prior 30 runs remain immutable flawed-model diagnostics. Do not delete
  affected trades to estimate corrected performance: balances and eligibility
  change. Correct accounting with regression tests, a new model identity and a
  complete canonical rerun on identical frozen assumptions into NEW files.
- Official Copy Trading fee schedules have a distinct product scope and cannot
  verify this demo account's fees. Aggregate deal summaries cannot reconstruct
  swap bookings. Exact tariff and position-level financing evidence remain open.
- No candidate or final holdout work until model/cost prerequisites are met.
  Next work is the offline correction and full validation, with live execution,
  terminal/session state and existing datasets untouched.

## 12. Corrected offline accounting model

- `frozen-weltrade-cfd-v2` corrects the three model-review defects without changing
  strategy, data, cost assumptions, capital or risk. See
  `docs/strategy-research/2026-10-08-accounting-correction.md`.
- Version 1 artifacts remain immutable flawed-model diagnostics. Version 2 uses
  a NEW output directory and a complete canonical 30-case training replay.
  Comparison must disclose eligibility and balance-path changes; never selectively
  replace trades or claim an accounting correction is strategy improvement.
- Five new regression cases preserve existing assertions. Validation: 2,609 backend
  passed, four explicit opt-in skips; 238 frontend passed and build passed.
- Next: finish the corrected comparison and exact fee/financing reconciliation.
  No candidate or holdout work while the existing qualification gates remain open.

## 13. Fee and financing evidence scope

- Read `docs/strategy-research/2026-10-08-fee-financing-reconciliation.md` and source
  hashes. All returned demo cashflows balance exactly, with zero observed fees on
  18 trade deals; three FX20 ordinary swaps reconcile. Do not upgrade that to a
  universal tariff, historical rate stability or an observed triple-day calendar.
- Public native-symbol data matches terminal annual-rate magnitudes for all ten
  contracts. Preserve public positive magnitudes versus terminal negative rates.
  Legal current terms specify midnight server time; historical offset/DST and
  synthetic Friday/weekend boundary remain unverified.
- Ordinary SyntX and Copy Trading are separate fee scopes under official terms.
  Zero commission is best supported for observed demo trades; positive commission
  cases remain declared stresses. Do not silently revise frozen cost identities.
- Owner has no written terms. Deeper public-source research is authorized, not
  sending messages to broker support or placing trades to generate fee evidence.
- Corrected campaign completion: 30/30, stable source; 499 overlapping observations,
  zero audited stop-distance/planned-risk violations. All cost-case mean R values
  remain negative, one traded symbol. No candidate/OOS evaluation occurred.
- Owner now requests deep ML research. This authorizes research/feasibility work,
  not claims of profitability, holdout reuse, execution changes or relaxing cost
  qualification. Any ML experiment requires its own preregistration, chronological
  leakage controls and canonical-pipeline equivalence before signal use.

## 14. ML research scope and leakage/security controls

- Read `docs/strategy-research/2026-10-08-ml-entry-quality.md`. The current work is
  research feasibility, not a profitable-model claim. Zero ML models/configurations
  have been fitted/evaluated. Existing EMA50 registration and holdouts stay sealed.
- `research.ml_validation` is a pure experimental governance helper, not an alternate
  signal/label/performance pipeline and not wired into execution. Every future ML
  signal filter must route through canonical generate_trading_signal and be evaluated
  only by `python -m backtesting.backtest` with baseline-identical assumptions.
- Actual label availability determines purging/embargo; opening timestamps are not
  closed-bar availability. Synchronize all symbols by time. Fit transformations
  inside training folds only; forbid future fills, entry gaps, MAE/MFE and outcomes
  as entry features. Accepted-trade-only labels have state-selection bias.
- Need complete canonical opportunity labels, fresh ML holdout, verified costs and
  sufficient independent history before fitting. The proposed 1,000-event/90-day
  readiness and 200-test-trade floors are project choices, not guarantees; do not
  relabel the original campaign's separate 100-trade acceptance requirement.
- Do not install/download arbitrary model dependencies or weights, upload broker
  evidence to hosted predictors, deserialize untrusted pickle/joblib, or use ML to
  override quantities, stops or safety policy. Initial linear artifact design is
  finite schema-validated JSON with source/data/version hashes, not executable code.
- Next: canonical opportunity-recorder design and new immutable history inventory;
  register exact ML dates/configuration before fit. Deep models need their own
  budgeted hypothesis and cannot be selected by repeated final-test evaluation.
- Latest complete backend after ML governance: 2,625 passed, four explicit opt-in
  skips, zero external network attempts. Frontend unchanged since 238-test/build
  pass. No ML fit, performance trial, candidate or holdout evaluation occurred.

## 15. Canonical opportunity inventory

- Read `docs/strategy-research/2026-10-08-opportunity-inventory.md`. Saved canonical
  decisions already preserve position-blocked signals. Extract them through
  `python -m backtesting.backtest --opportunity-inventory`; do not recreate signals.
- Never count next-bar EXECUTION_REJECTED events as extra opportunities. QUEUED
  does not establish a fill. Existing inventory: 27,459 opportunities, 266 labels,
  27,193 unlabelled; 1,322 SFX99 signals position-blocked. No ML fit occurred.
- Exported outcomes are executed-baseline-only, not complete counterfactual labels.
  Features are not exported. Bar-close availability and source hashes are explicit.
- Qualified campaign history spans 41.7 days. Old manifests span at most 1.74 days;
  17/34 fail last-bar closedness. Metadata inventory is not content qualification.
- Next: freeze canonical training-only counterfactual-label semantics for executable
  opportunities, then qualify new HistoricalDataService files and preregister an
  independent ML holdout. Stateful candidate performance remains canonical only.
- Validation: full backend 2,630 passed/four opt-in skips/zero external network
  attempts; final focused extractor six passed. Frontend 238 passed/build passed.

## 16. Frozen counterfactual label design

- Read `docs/strategy-research/2026-10-08-counterfactual-label-protocol.md` and its
  JSON/hash. One past-training design, zero label outcomes/ML fits. Original EMA50
  holdouts remain sealed; this is not an untouched OOS strategy preregistration.
- Scope SFX Vol 99/M5 only: 2,876 opportunities, 2,833 eligible, 24 gap-censored,
  19 partition-censored. Three fixed cost cases overlap; never count them as
  independent events. Label generation is not implemented or authorized live.
- Each event resets USD 50/1% risk, preserves native quantity/margin/stop/cost
  constraints, original full indicator prefix and exactly one target entry.
  Only canonical generate_trading_signal may produce the target signal.
- Gap/partition censoring uses the full predeclared i-3 through i+19 window,
  never observed early exits. Rejects/censoring have null returns, not zeros.
  Independent opportunity returns are not stateful strategy P&L.
- Next implement canonical one-target replay and prove signal/fill equivalence,
  then run the registered training-only label attempts with an honest ledger.
  ML fitting stays blocked pending labels, history, costs and fresh registration.
- Latest checks: backend 2,636 passed/four opt-in skips/zero external network
  attempts; frontend 238 passed/build passed. Owner authorized running the
  loopback frontend/backend and read-only existing-terminal checks. Both services
  are running; demo observation passed without orders/login/selection calls.
  This does not authorize execution, arming gates or terminal reconfiguration.

## 17. Single-opportunity replay pilot

- Read `docs/strategy-research/2026-10-08-single-opportunity-replay.md`. Canonical
  run_backtest now supports the fixed one-target research contract; no live hook.
  Only the target canonical signal is queued; preserve its original full prefix.
- Nine first-three-event/cost pilot attempts completed: three executed and six
  non-executable null labels. First saved trade exactly matches the stateful
  baseline. This limited pilot is not complete equivalence or strategy evidence.
- Original label design is immutable. Implementation plan binds its checksum to
  the changed source snapshot; do not pretend old/new source hashes are equal.
- Next implement resumable complete 8,499-attempt training dispatch and coverage
  audit. No ML fit until causal labels/features, history, costs and fresh holdout
  requirements are met. Independent opportunity labels are not portfolio returns.
- Validation: backend 2,642 passed/four opt-in skips/zero external network attempts;
  frontend 238 passed/build passed. Six new replay checks independently passed.
- Operational issue: frontend serves HTTP 200; backend health and proxy repeatedly
  timed out while processes remained present. Diagnose this before full dispatch.
  No restarts or execution/terminal reconfiguration occurred; tests passing does
  not establish live API responsiveness.

## 18. API responsiveness fix awaiting runtime verification

- Read `docs/strategy-research/2026-10-08-api-responsiveness.md`. Verified blocking
  contributor: full-history demo evidence reads (233,831 rows) executed twice on
  the event loop per live broker-status request. Sole timeout cause not proven.
- Prepared fix: latest normalized-broker rows only, read-only SQLite connection,
  off-event-loop durable status reads. Preserve post-session evidence freshness
  and all safety/identity semantics. Never prune operator evidence to improve speed.
- Existing backend has not reloaded this change. Original user boundary forbids
  changing running processes; get explicit authorization for backend-only restart
  before applying. Do not restart/reconfigure MT5, frontend or execution services.
- Next verify health under dashboard polling, then resume full training-label
  dispatch. No ML fit, live orders or holdout evaluation was performed here.
- Validation: 18 targeted checks passed; full backend 2,643 passed/four opt-in
  skips/one existing 20-second bootstrap subprocess timeout. Both bootstrap
  safety tests passed unchanged on isolated rerun. Preserve failure and rerun
  logs; do not claim a completely green full run. Frontend 238 passed/build passed.
- Owner explicitly authorized backend-only restart; completed after verifying
  current listener command line. Twenty concurrent read-only probes passed HTTP
  200, maximum 0.3001 seconds. Frontend/MT5 process identities retained. This is
  short-run recovery evidence, not sustained-latency proof or order authorization.
- Next resume full registered training-label dispatch; preserve ML readiness
  blocks and sealed holdouts. Restart authorization was scoped to this backend.

## 19. Reliability follow-up and full label dispatch

- Owner authorized frontend and read-only MT5 reliability while preserving demo
  identity/gates/safety, then running the registered training-only label campaign.
  Read `docs/strategy-research/2026-10-08-frontend-mt5-reliability.md`.
- Research acquisition polls are completion-paced/hidden-tab paused. Contract
  specification reads exact symbols off-loop without Market Watch selection.
  Other gateway paths are not newly certified mutation-free; MT5 was not restarted.
- Backend reloaded and health passed. Frontend 240 tests/build and eight focused
  backend checks passed; record full-suite result separately.
- Full campaign started at `reports/counterfactual-campaign-20261008-01`, 2,833
  events/8,499 costs, 43 predeclared censors. Source-bound canonical-only replay,
  SDK blocked, immutable compact results, honest ledger. Stops on failure;
  automatic resume is not implemented. Never claim startup as completion.
- Next finish/audit every attempt before feature/history qualification or ML fit.
  Holdouts remain sealed, no new candidates or orders authorized.
- Final reliability checks: backend 2,646 passed/four opt-in skips/zero external
  network attempts; frontend 240 passed/build passed. Campaign session 97044 is
  RUNNING, last snapshot 78 completed/one active/zero failures of 8,499. No final
  summary yet. Do not launch a duplicate campaign or change source during replay;
  inspect its existing ledger/session first on continuation.
- Subsequent partial audit: 211 completed artifacts, matching source snapshot,
  no identity/chronology/R/rejection-label errors. Read the label-progress-audit
  report. Campaign still running/no final summary; no duplicate launched or replay
  code changed. This is partial qualification, not ML readiness or expectancy.

## 20. Interrupted label campaign and validated resume

- Original process is absent, 4,900 completed/one unfinished STARTED/no summary;
  cause unknown. Preserve original artifacts/ledger; never infer completion.
- Read `docs/strategy-research/2026-10-08-label-campaign-resume.md`. New output:
  `reports/counterfactual-campaign-resume-20261008-01`; 3,599 remaining attempts.
  Original labels validated/hashed before reuse. Three changed orchestration
  modules and separate snapshots disclosed; canonical replay body unchanged.
- Resume command remains canonical `-m backtesting.backtest --counterfactual-campaign
  ... --resume-labels-from ORIGINAL --output NEW`. Do not overwrite or duplicate.
- Detached campaign and one-shot audit process survive tool-session loss. PID/log
  files are in reports/label-resume-* and reports/label-coverage-watcher-*.
  Check existing processes/ledger before any continuation or resume.
- Feature extraction stays blocked until final summary and PASS complete coverage
  audit of 8,499 pairs, 43 censors, source/data lineage, every availability interval
  and null rejects. Failed/interrupted attempts remain explicit audit evidence.
- Validation: backend 2,650 passed/four opt-in skips/zero external network attempts;
  frontend 240 passed/build passed. No ML/candidate/holdout evaluation occurred.

## 21. Complete training-label coverage

- Read `docs/strategy-research/2026-10-08-complete-label-coverage.md` and its JSON
  audit. Final summary exists; complete audit PASS, zero errors, stable source.
  All 8,499 unique event/cost pairs for 2,833 eligible SFX99/M5 events completed;
  all 43 predeclared censors preserved. No duplicate campaign is needed.
- Original 4,900 labels remain immutable; resumed directory contains 3,599 new
  labels and one disclosed interrupted-attempt retry. Cause of interruption
  unknown; zero recorded FAILED entries does not explain the process loss.
- Executed/null-rejected counts: zero commission 1,545/1,288; assumed USD 3 per
  lot per side 1,186/1,647; doubled spread/commission 607/2,226. Cost observations
  overlap and independent labels are not stateful strategy returns.
- Final saved-artifact audit binds source/input/lineage hashes and checks every
  identity, interval, lifecycle and return/null status. Compact artifacts are not
  full result-hash preimages. Do not claim full-result reconstruction or OOS edge.
- No feature extraction, ML fit, candidate or holdout evaluation occurred. Next
  freeze/verify causal features against the original canonical indicator prefix
  and bar-close availability before extraction; longer qualified history, costs
  and a fresh chronological ML registration/holdout still gate fitting.
- Validation: backend 2,650 passed/four opt-in skips/zero external network attempts;
  frontend 240 passed/build passed. Safety assertions retained.

## 22. Frozen causal feature semantics (2026-10-09)

- Read `docs/strategy-research/2026-10-09-causal-feature-contract.md`, JSON and
  checksum before extraction. Eight formulas frozen, one contract, zero feature
  rows exported/ML fits. Existing labels and original holdouts remain immutable.
- `research.causal_features` is experimental computation, not a signal/label or
  performance path. It cuts raw bars before canonical indicators, keeps the
  original prefix and rejects invalid/gapped lookbacks or mismatched spread time.
  Callers still must verify frozen provider/dataset/prefix and sidecar provenance.
- Lagged spread means signal-bar recorded spread lagged relative to next entry;
  require same-response sidecar/OHLC/manifest binding. Never use unknown-spread
  fallback as broker cost. Preserve missing feature rows, null rejects and censors.
- Nine focused checks passed. All 8,832 saved original training indicator rows
  matched immutable-prefix recomputation; this is not complete feature-recorder
  equivalence or live-plan equivalence. Separate feature/label source snapshots.
- Next implement training-only recorder through canonical backtest CLI and prove
  event/signal identity and availability before NEW-file extraction. No outcome
  rerun needed. Costs, longer qualified history and fresh ML registration/holdout
  still gate fitting; no candidate or OOS evaluation authorized by this milestone.
- Validation: backend 2,659 passed/four opt-in skips/zero network attempts;
  frontend 240 passed/build passed. Safety assertions unchanged.

## 23. Canonical training-feature recording complete

- Read `docs/strategy-research/2026-10-09-training-feature-recorder.md` and audit
  JSON. New output `reports/training-features-20261009-02`: 2,876 unique events,
  2,870 finite feature rows/six unavailable gap-censored rows. All 2,833 eligible
  labelled events have features; all 43 censors remain. Coverage audit PASS.
- Canonical CLI `--record-training-features CONTRACT --output NEWDIR` observes
  generate_trading_signal inside run_backtest. Feature-only mode forbids economic
  replay, queues no trades and returns no performance result. No alternate signal
  path, model fit, candidate or holdout evaluation was introduced.
- Preserve failed output 01: baseline stateful reasons were incorrectly compared
  as canonical reasons. Corrected comparison requires original direction,
  confidence and canonical reason prefix; portfolio/risk suffixes are separate.
  Existing signal/prefix/spread/availability assertions remain fail-closed.
- Separate feature and historical label source snapshots; unchanged data/strategy
  semantics are bound, not claimed as equal source identities. Frozen dataset
  content rechecked after export; no continuous file-monitor claim.
- Next qualify feature-label joins and actual-label-availability purge rules,
  then longer qualified HistoricalDataService history and fresh ML registration.
  Cost/financing gates still block fitting. No duplicate label replay needed.
- Validation: final backend 2,668 passed/four opt-in skips/zero network attempts;
  frontend 240 passed/build passed. Initial failed recorder evidence preserved.

## 24. Training feature–label joins and purge diagnostics

- Read `docs/strategy-research/2026-10-09-feature-label-joins.md` and its audit
  JSON. Canonical CLI `--qualify-feature-label-joins NEWDIR` reads saved evidence
  only. Output `reports/feature-label-joins-20261009-01`, saved audit PASS.
- All 2,876 events retained with three nested cost dispositions: 3,338 executed,
  5,161 non-executable and 129 censored. Null returns remain null. Only 1,545
  distinct events have any executed outcome; nearby events remain dependent.
- Fixed TRAIN-only splits September 22–29 and September 29–October 8, 95-minute
  embargo. Cost siblings grouped by latest actual executed-label availability.
  Strict cutoff/right-boundary equality excludes events. These are plumbing
  diagnostics on inspected training, not OOS validation or an ML registration.
- Late diagnostic window has 12 zero/assumed-cost executable events and one at
  doubled costs. Preserve thin chronological coverage; do not move windows,
  change capital/risk or remove rejected events to manufacture adequacy.
- No fitting, performance or holdout evaluation. Next longer native qualified
  history inventory and new HistoricalDataService acquisition registration;
  costs/financing and fresh ML registration/holdout remain separate gates.
- Validation: 26 focused checks; full backend 2,678 passed/four opt-in skips/zero
  network attempts; frontend 240 passed/build passed. Safety assertions retained.

## 25. Longer history registration and failed qualification

- Read `docs/strategy-research/2026-10-09-long-history-qualification.md`. Frozen
  registration `reports/history-registration-20261009-01`: ten native symbols,
  M5 July 10–October 8 UTC half-open; history-only, not ML/OOS registration.
- `tools.acquire_entry_campaign --history-only --attach-existing --protocol ...`
  uses HistoricalDataService ranges and forbids latest-position reads. Keep
  sealed partitions, demo identity, Market Watch and service completeness gates.
- Attempt 01 blocked before SDK initialization (terminal absent). Owner opened
  terminal; attempt 02 verified configured demo/USD/10,800-second offset and
  unchanged Market Watch but failed completeness on all ten symbols.
- Preserve both attempts and new partial store. Each symbol: 25,894 bars, July 9
  21:00–October 7 20:55 UTC, 13 gaps; SFX99 has 26 missing bars. Uniform three-hour
  early window matches range/normalization mismatch evidence. No 90-day qualified
  bundle or spread sidecar exported; no repair, fitting or holdout read occurred.
- Next offline range-time contract correction/regressions, then SAME registration
  in a NEW directory and explicit gap qualification. Never shift old snapshots or
  weaken completeness/safety assertions. Costs/fresh ML holdout remain open.
- Validation: six focused checks; backend 2,684 passed/four opt-in skips/zero
  network attempts; frontend 240 passed/build passed. Tests do not qualify data.

## 26. Read-only range-time correction and Sunday gaps

- Read `docs/strategy-research/2026-10-09-range-time-correction.md`. Weltrade
  get_candles_range inverts existing fixed server normalization for SDK query
  bounds and rejects naive/reversed bounds/out-of-range or unordered responses.
  No live execution, backend restart, terminal reconfiguration or safety change.
- SAME frozen registration/new attempt `reports/history-acquisition-20261009-03`:
  correct July 10 00:00–October 8 00:00 UTC boundaries, 25,894 bars/symbol. All ten
  service completeness checks still fail; preserve all attempts and partial stores.
- All symbols share 13 Sunday gaps at 03:50/03:55 UTC. Official current SyntX
  conditions publish Sunday 06:50–07:00 EET real/demo break. Alignment is
  conditional on observed UTC+3; historical offset/DST remains unverified.
- Coverage gate unchanged; no qualified bundles or bound spread sidecars exported.
  No synthetic fills, in-place shift, strategy/ML fit or holdout evaluation occurred.
- Next freeze evidence-bound Sunday-session coverage design with explicit timezone
  uncertainty and strict unexpected-gap tests, then SAME registration/NEW files.
  Do not substitute current calendar terms as verified historical financing.
- Validation: five focused checks; full backend 2,689 passed/four opt-in skips/zero
  network attempts; frontend 240 passed/build passed. Safety assertions preserved.

## 27. Conditional Sunday-session research coverage

- Read `docs/strategy-research/2026-10-09-sunday-session-coverage.md` and conditional
  audit JSON. Evidence-bound policy `reports/session-calendar-20261009-01` was
  frozen before attempt 04; historical UTC+3/Sunday terms remain assumptions.
- Default continuous Weltrade coverage unchanged. Explicit research policy only:
  exact ten native identities/M5, July 10–October 8; exclude Sunday 03:50/03:55
  buckets. Unexpected gaps, closure candles, duplicates and scope mismatches reject.
  No coverage/safety assertion deleted; no general holiday/calendar inference.
- NEW `reports/history-acquisition-20261009-04` acquired all ten bundles/sidecars
  through HistoricalDataService with matching SDK response/OHLC binding. 25,894
  closed bars/symbol, 90 source-calendar days, 26 conditional closures, zero
  unexpected missing/returned buckets. Audit PASS_CONDITIONAL_SESSION_COVERAGE_NOT_ML_READY.
- Keep attempts 01–03 immutable. No timezone/financing verification, universal fees,
  ML fit, candidate or holdout evaluation established. Raw gaps remain and crossing
  events must still be censored. Ninety source days is not sample sufficiency.
- Next freeze separate all-symbol training-baseline/opportunity protocol with
  warmup and explicit conditional costs. Expanded indicator prefix changes signal
  identities: never transfer old labels. Costs/calendar and fresh ML registration/
  holdout still gate fitting. Reserved EMA50 campaign remains untouched.
- Validation: nine focused checks; backend 2,698 passed/four opt-in skips/zero
  network attempts; frontend 240 passed/build passed. Safety assertions unchanged.

## 28. Frozen longer-history training design

- Read `docs/strategy-research/2026-10-09-long-history-training-protocol.md` and
  `reports/long-history-training-registration-20261009-01/protocol.json`/checksum.
  Design only: compatible dispatcher not implemented, zero outcomes/ML fits.
- All ten attempt-04 bundles, original full prefix, 200 observed warmup bars;
  evaluate July 10 16:40–October 8 00:00 UTC half-open (89.3056 days).
  One baseline configuration, 30 planned symbol/cost runs, USD 50/1% risk fixed.
- Exact hash-bound costs: commission 0/3/6 per lot per side; spread 1/1/2;
  slippage 0.05 ATR per fill. Rates/calendar/old margin terms remain conditional.
- Next implement separate canonical CLI preflight/dispatcher; compare old terms
  against new economics offline before outcomes and reject mismatch. Do not alter
  acquisition status to force old campaign reuse. Bind new implementation separately.
- Preserve no-trade nulls, gap/boundary semantics, old data/labels and all attempts.
  New prefix cannot inherit old labels. No candidate, ML fit or original holdout work.
- Validation: backend 2,698 passed/four opt-in skips/zero external network attempts;
  frontend 240 passed/build passed. Registration/documents only; no runtime change.

## 29. Longer-history offline preflight and dispatcher

- Read `docs/strategy-research/2026-10-09-long-history-dispatch.md`.
  Final offline preflight PASS for ten symbols; captured contract/P&L/margin
  compatibility, hashes, closedness, conditional coverage and spreads verified.
  Historical economics/calendar/fees remain conditional, not newly certified.
- Separate canonical `--long-history-training REGISTRATION --output NEWDIR`
  implemented; `--preflight-only` produces zero outcomes. Preserve frozen design
  and separately bound implementation. Old dispatcher gates are unchanged.
- Zero real-data training outcomes/ML fits here. Next fixed 30-case replay on
  stable source, then complete saved-artifact audit; no candidate/holdout work.
- Full backend 2,701 passed/four skips; final focused 28 passed, including one
  subsequently added test and finite-probe strengthening. See validation timing
  disclosure in handoff. Zero network attempts; frontend 240/build passed.
  Services, MT5, execution/safety state untouched.

## 30. Longer-history training campaign running

- Read `docs/strategy-research/2026-10-09-long-history-training-running.md`.
  Existing campaign `reports/long-history-training-20261009-01`: latest two
  completed/third active/zero recorded failures; no final summary. Do not duplicate
  or edit frozen replay source. Check existing processes/ledger on continuation.
- Both completed FX20 cases no-trade/null expectancy; partial saved-result
  identity audit PASS only. No all-symbol outcome/ML readiness claim.
- Detached one-shot audit watcher runs full saved-artifact audit/report after
  summary and preserves failures/interruptions. Audit pending, not qualified.
  PID/log/script/output paths and validation scope are in the dated handoff.
- Full backend 2,702 passed/four opt-in skips/zero external network attempts;
  frontend 240 passed/build passed. No source edits during replay, terminal,
  service, execution or safety changes. Costs/calendar/ML gates remain open.

## 31. Owner-authorized demo execution

- Owner explicitly said “allow mt5 and live execution”. Applied to existing
  configured Weltrade demo account, canonical watchlist and safety/risk limits.
  Read `docs/strategy-research/2026-10-09-demo-execution-authorized.md`.
- Exact existing demo identity and terminal trade permissions passed; preflight
  authoritative/only non-authorizing no-order reason. Separate supervisor RUNNING,
  launcher 16200/worker 8004; first cycle 14 pairs, eight NO_TRADE/six minimum-lot
  risk blocks, zero positions after cycle. No new fill demonstrated.
- Shared dotenv/API/source unchanged; process-local execution flag and existing
  forward cache. Telegram disabled process-locally; no external messages authorized.
- This supersedes the prior no-new-orders boundary for this demo supervisor only;
  never bypass halts, expand risk or promote a research candidate/ML model. MT5
  was not restarted/reconfigured. Offline campaign/audit remains separate/pending.

## 32. Existing training/demo continuation audit

- Read `docs/strategy-research/2026-10-09-training-demo-progress.md`.
  Existing training latest seven completed/eighth active/zero failures, no summary.
  Replay/audit watcher alive; no duplicate/retry/source change.
- First six pairs saved-artifact partial audit PASS/zero errors; all no-trade.
  This is not complete 30-case coverage or trade-invariant branch qualification.
- Demo supervisor RUNNING, two cycles; 19 NO_TRADE/nine BLOCKED journal decisions,
  no filled-order status reported. Existing risk/safety controls unchanged.
- Next finish same training campaign/full audit and retain conditional costs,
  calendar and ML/holdout gates. Validation unchanged since no code edits.

## 33. Half longer-history campaign audited

- Latest existing campaign 15/30 complete, SFX20 zero-commission active, zero
  failures/no summary. All five FX symbols/all costs no-trade. Partial saved
  audit 03 PASS/15 pairs/zero errors; no complete coverage or ML claim.
- Read subsequent continuation in `docs/strategy-research/2026-10-09-training-demo-progress.md`.
  Demo supervisor RUNNING/six cycles: 63 NO_TRADE/20 BLOCKED/one pre-submit
  rejection (SFX99 stop 892 versus required 1,716 points). Pure policy ALLOWED
  does not mean broker fill. Exact demo identity/zero open positions verified.
- Existing replay/watcher remain alive; no source or risk/control edits. Next
  finish same campaign/full audit, preserve all no-trade nulls and cost gates.

## 34. Twenty-five training cases audited and demo opening fill verified

- Existing training latest 25/30 complete, SFX80 assumed-cost active, zero
  failures/no summary. Partial audit 04 PASS/25 pairs/zero errors; full audit
  pending, replay/watcher alive. No duplicate/retry/source edit.
- Read continuation in `docs/strategy-research/2026-10-09-training-demo-progress.md`.
  Demo SFX99 M5 BUY order/position 569491053, deal 538066669 reconciled to
  ACCEPTED intent/ledger: 0.03 lots, actual entry 1688.05, SL1669.88/TP1725.44;
  planned stop risk USD0.56 <= authorized USD0.71485. No integrity halt.
- Position remains OPEN; supervisor blocks new submissions at position limit.
  No closed outcome/profitability or universal zero-fee claim. Never force a
  close to manufacture evidence. Next natural-close reconciliation and final
  same-campaign 30-case audit; historical cost/calendar/ML gates remain open.

## 35. Owner-requested five-position demo cap

- Owner requested removing one-position limit and selected “5 positions”. Existing
  supported cap setting applied process-locally; no policy/source edits during
  training. Supervisor alone restarted after identity/unresolved-intent/halt
  checks: old 8004/16200 stopped, new launcher20040/worker20540.
- New preflight has only READ_ONLY_PREFLIGHT_NO_ORDER_INTENT; position-limit block
  cleared. Effective cap five verified against observed demo USD equity. Original
  SFX99 open position retained; MT5 terminal not restarted/reconfigured.
- Per-trade risk0.5%, daily loss3%/five daily trades, duplicate-symbol guard and all
  durable safety controls retained. Equity-floor fail-closed cap remains one if
  capital/currency evidence is unsuitable. Shared dotenv/API remain unchanged.
- Evidence `reports/demo-five-position-cap-20261009-01.json` plus PID/stdout/stderr.
  Restart requires process-local JQE_WELTRADE_DEMO_MAX_OPEN_POSITIONS=5; shared
  default remains one. No automatic restart or research promotion introduced.

## 36. Longer-history training complete; separate demo partial management

- Frozen campaign completed30/30; full saved audit PASS/zero errors/source stable.
  Read `docs/strategy-research/2026-10-09-long-history-training-complete.md`.
  Only SFX99 traded319/171/63 across overlapping costs; mean netR negative in
  all three. Nine symbols retained no-trade nulls. No candidate/OOS/ML fit.
  Full replay source copied/hash-verified before subsequent live code changes.
- Owner froze future-entry management: floor authorized quantity to two equal
  valid lot-step portions, close50% at +1.5 original priceR, after confirmed
  partial move remaining SL +0.5R beyond actual fill. Existing risk unchanged.
  Read `docs/strategy-research/2026-10-09-partial-management.md`.
- Durable account/position registry claims close before mutation; uncertain close
  never resent. Broker deal/remainder confirmation precedes stop update; preserve
  TP/never loosen tighter SL. Pending profit-stop update blocks new entries while
  only protection retries. Missing/blocked durable safety/identity rejects.
- New fills only; existing0.03 position not adopted/resized. Gateway holds all
  mutations; canonical supervisor sole live loop. No claims that prior TRAIN
  negatives validate new management; historical costs/calendar/ML gates persist.
- Activated process-local execution/partial flags/five cap; launcher8988/worker21232,
  clear preflight/STARTING awaiting cycle. No real partial executed yet. Shared
  dotenv/API unchanged; Telegram false. Registry path/PID/logs in dated handoff.
- Final backend2725/four opt-in skips/zero external network attempts; focused102;
  frontend240/build passed. Prior failures/earlier validation retained.

## 37. Partial runtime follow-up and saved training diagnosis

- Supervisor21232 alive/RUNNING; no newly registered equal-half fills or partial
  mutations yet. Existing0.03 SFX99 position retains broker SL/TP. New candidates
  can be rejected when risk cannot fund two minimum-volume portions; no risk
  increase, forced trade or legacy-position adoption. Read-only runtime evidence
  `reports/partial-management-followup-20261009-01.json`.
- Hash-verified all30 saved training metrics; generated read-only loss/feasibility
  diagnosis `reports/long-history-saved-diagnosis-20261009-01/report.md`/JSON.
  Zero new replays/ML fits. Nine symbols no-trade; SFX99 mean netR negative at all
  costs. Preserve positive inspected subgroups as diagnostics, not filter/OOS proof.
- No application changes; validation remains2725/four skips, frontend240/build.
  Next freeze longer-prefix all-symbol opportunity/label semantics before new
  labels. Old labels cannot transfer; historical costs/calendar and independent
  fresh ML registration/holdout still gate fitting/promotion.

## 38. Frozen all-symbol longer-history label design

- Read `docs/strategy-research/2026-10-09-long-history-label-protocol.md` and
  reports/long-history-label-registration-20261009-01 protocol/events/hash/audit.
  Inspected past-TRAIN design:81,679 events,80,646 eligible,978 gap/55 boundary
  censors;241,938 planned cost attempts/3,099 censored cost dispositions.
- PASS_DESIGN_ONLY/zero errors; all30 saved results/archive source/input hashes,
  cost-sibling signal identities, complete observations and independent full-window
  censor audit passed. No new labels, features, ML fits or holdout reads.
- Reset USD50/1% per event, same three conditional costs/frozenv2/original full
  prefix; only target canonical signal queued. Full i-3..i+19 window censors every
  gap/boundary regardless of early exit. Preserve all ten/rejects/null returns.
- New prefix-bound IDs: old labels cannot transfer. Existing SFX99-only dispatcher
  incompatible; implement separate all-symbol contract and equivalence pilot.
  New live partial-management policy excluded; baseline archive bound separately
  from future implementation. No source-hash equality/live-equivalence claim.
- Relevant offline29 passed/zero network attempts. No application/runtime changes;
  latest unchanged full2725/four skips, frontend240/build passed. Costs/calendar,
  causal features, independent samples/fresh ML registration/holdout still block fit.


## 39. Separate canonical all-symbol label pilot complete

- Read docs/strategy-research/2026-10-09-long-history-label-pilot.md. Separate
  --long-history-label-pilot command and immutable LongHistoryOpportunity contract;
  frozen registration unchanged, old SFX99-only guard/restrictions preserved.
- Fixed first three eligible events per ten symbols/all three costs:90 attempts
  completed with stable source. Saved audit PASS/zero errors; two executed labels,
  88 null NON_EXECUTABLE dispositions. One saved baseline first fill matches
  exactly; all ten synthetic first-fill tests pass. Independent overlapping labels
  are not portfolio returns or independent samples; no performance promotion.
- reports/long-history-label-pilot-20261009-01 retains complete result preimages,
  ledger, implementation identity and 106 verified source files. Audit with actual
  label availability in reports/long-history-label-pilot-audit-20261009-01/audit.json.
  Canonical arithmetic/strategy/risk dependencies match training; new dispatcher
  and prior live broker/config differences disclosed. Live partial policy excluded.
- Full backend2742/four explicit skips/zero external network attempts; focused23;
  frontend240/build passed. No terminal/process/gate/safety/dotenv changes here.
- Full241938-attempt campaign not started; pilot has no resume mechanism. Next
  implement immutable resumable full canonical dispatch and complete coverage
  audit, preserving failed/interrupted attempts. Costs/calendar/causal features,
  sufficient independent events/fresh chronological ML registration/holdout still
  gate fitting. No features, ML fits, candidate or holdout evaluations occurred.

## 40. Immutable resumable full label dispatcher

- Read `docs/strategy-research/2026-10-09-long-history-label-dispatch.md`.
  Existing prepared implementation reviewed; final-summary coverage gate added.
  Frozen registration/pilot archive untouched; full241938 attempts not launched.
- Canonical --long-history-label-campaign only; full gzip result preimages,
  exclusive NEW artifacts, fsynced ledger, source archive and shared OS lock.
  Resume requires absent owner, identical source and verified all ancestor segments.
  Pilot reuse/source drift/recorded failures/duplicate completions reject.
- Interrupted STARTED attempts disclosed; retry only in NEW segment. Audit via
  --audit-long-history-labels requires all pairs, censors, hashes, causal prefix,
  actual availability/null labels and matching final summary. No partial readiness.
- Next check disk/runtime budget against preserved pilot, then stable-source full
  registered training-only dispatch and complete audit before features. No ML fit,
  candidate/holdout work or terminal/process/gate/safety/dotenv changes here.
- Capacity check blocks current-layout launch:90 pilot gzip results median1.18MB;
  extrapolated286GB versus80GB observed free. Estimate only, not full-scale proof.
  Read reports/long-history-label-capacity-20261009-01.json. Next hash-verifiable
  shared immutable storage with reconstructable full result preimages, or adequate
  additional capacity. Never drop full evidence or claim compact-label preimages.
- Validation: focused42; backend2761/four explicit opt-in skips/zero network
  attempts; frontend240/build passed. Safety assertions retained.

## 41. Lossless shared full-result storage

- Read `docs/strategy-research/2026-10-09-shared-label-storage.md`. Schema
  jqe-shared-full-result-v1 shares full indicator arithmetic/source snapshot;
  per-result regime overrides and all other original fields reconstruct exactly.
  Content/file hashes and original full-result preimages are mandatory.
- Writer uses exclusive/fsynced artifacts; corrupt/missing objects, invalid
  references/overrides and per-symbol dataset arithmetic drift fail closed.
  Resume/audit retain and recheck every used object. Existing same-source resume
  guard unchanged; old full gzip supported. Pilot/source/archive unchanged.
- --qualify-long-label-storage NEWDIR only reencodes90 saved audit-bound pilot
  results; no signals/replays/new labels. Proof directory is NOT a resume segment.
- Full241938 campaign unstarted. Next assess proof and conservative storage budget,
  then stable-source canonical full dispatch/complete audit before features.
  No ML/candidate/holdout work or terminal/process/gate/safety/dotenv changes here.
- Complete storage proof PASS90/90/zero errors/source stable at
  reports/shared-label-storage-20261009-01/audit.json. Shared11.30MB, envelopes
  median11133bytes, extrapolated2.70GB versus80.47GB free; reserve12GB engineering
  allowance, not measured upper bound. Monitor actual growth/runtime at launch.
- Validation: focused51; backend2770/four explicit skips/zero network attempts;
  frontend240/build passed. Next stable-source/capacity/no-existing-campaign checks,
  canonical full training-only launch and complete coverage audit before features.

## 42. Full registered training-label campaign running

- Read `docs/strategy-research/2026-10-09-long-history-full-label-running.md`.
  NEW reports/long-history-label-campaign-20261009-01,241938 fixed attempts.
  Launcher19044/worker16240 observed; audit watcher17012/3836. Check actual health
  and commands/ledger first; do not duplicate or edit replay source while running.
- Frozen inputs/storage evidence rehashed; source matched lossless proof. Capacity
  exceeded12GB allowance. Process-local isolated WARNING logs only; dotenv and
  live services/terminal/gates/safety unchanged. No code changes in this step.
- Five completed artifacts PASS partial audit/source/archive/shared/full-result
  hashes; reports/long-history-full-label-partial-audit-20261009-01.json. Partial
  snapshot is not complete/current coverage; final summary/audit not yet available.
- Detached watcher waits owner exit then canonical saved audit, or records stop
  without summary. Never auto-restarts/resumes; capacity alert does not terminate.
  Runtime evidence/logs at reports/long-history-full-label-runtime-20261009-01.
- Next finish/monitor existing ledger, check summary and complete coverage PASS
  before features. Diagnose interruption before immutable same-source resume.
  No ML/candidate/holdout work. Unchanged-source validation2770/four skips,
  focused51/frontend240/build; background endurance/completion not proven.

## 43. Full-label partial progress qualification

- Read `docs/strategy-research/2026-10-09-long-history-label-progress.md` and
  reports/long-history-full-label-partial-audit-20261009-02.json. PASS23 pairs,
  zero errors, one active at snapshot; all23 NON_EXECUTABLE/null. Not trades/zeros.
  Stdout later passed25; final241938 coverage/summary still unavailable.
- Owner16240 alive/source stable; full result/shared hashes, original arithmetic
  prefix/regime, labels/availability and ledger transitions verified.9.48MB saved,
  80.46GB free at snapshot. No source/process/terminal/gate/safety/dotenv changes.
- Read-only script reports/audit-long-history-label-progress-20261009.py preserves
  snapshot evidence; it creates no signals/labels/performance. Next monitor SAME
  campaign/capacity/watcher, then complete summary/audit PASS before features.
- Runtime not qualified; visible repeated full-dataset work is only a hypothesis.
  No acceleration/source edits during campaign. Future optimization requires
  profiling/new source binding/canonical full-result equivalence. ML/holdouts gated.
- Validation unchanged2770/four skips/focused51/frontend240/build. No new fits,
  candidates or holdout evaluation; no duplicate dispatch or safety-test changes.

## 44. Authorized offline stop and canonical profile

- Read `docs/strategy-research/2026-10-09-long-history-label-profiling.md`.
  Owner explicitly authorized stop only research campaign for profiling. Verified
  launcher19044/worker16240 stopped; watcher exited STOPPED_WITHOUT_SUMMARY.
  MT5/live services/gates/safety/dotenv unchanged. No campaign currently running.
- Original53 COMPLETED/one STARTED/zero FAILED/no summary retained. Stopped audit
  PASS53 full artifacts/source/shared/prefix/label checks. All53 null/non-executable.
- --profile-long-label-attempt canonical CLI: fixed first eligibleSFX99/zero cost,
  one diagnostic replay/zero changed parameters/zero trades. Full golden084 payload
  matches except disclosed source identity/fingerprint. Profile source archived.
- Profile11.50s with overhead:serialization6.38s,runner5.13s,iterrows2.22s within
  runner. Not additive costs/ETA. Saved verification2.73s separately. No speedup
  adopted. Verifier strengthened afterwards; stored profile rechecked successfully.
- Next one byte/hash-equivalent serialization hypothesis,90 golden payloads and
  canonical executed/null equivalence, then explicit audited source transition
  before NEW resumed segment. Same-source guard unchanged; never assert equality
  of changed sources or reuse old labels without qualification. Campaign stays
  stopped pending qualification; no full rerun/ML/candidate/holdout work here.
- Validation:focused34; backend2776/four explicit skips/zero network attempts;
  frontend240/build passed. Stopped53 audit predates new profile sources; preserve
  each archived snapshot/identity and never transfer hash validation across them.

## 45. One serialization acceleration hypothesis

- Read `docs/strategy-research/2026-10-09-serialization-acceleration.md`.
  to_json_bytes reuses one normalized snapshot; unchanged canonical hash/JSON.
  Dispatcher reuses verified serialized hash. No cache or arithmetic change.
- Focused39 passed:typed legacy byte/hash/rejection/mutation/timezone cases plus
  reproducibility/profile/resume. Canonical profile02 same fixed nullSFX99 target
  matches golden084 except disclosed source identity/fingerprint. One new replay,
  zero strategy parameters/ML fits. Observed serialization6.38->4.28s; not ETA.
- --qualify-long-label-serialization NEWDIR compares90 preserved golden payloads
  to owned verified archived serializer; no fresh labels/replays. New source bound
  separately. Microbenchmark normalized JSON objects, not90 typed broker replays.
- Protected models/source guards and strict same-source resume unchanged; they
  reject new implementation until exact audited transition is qualified. Do not
  weaken/bypass them or assert old/new hashes equal. Old53 and interruption remain.
- Next exact allowed source-transition contract, canonical executed/null checks,
  inherited artifact/lineage audit, then NEW resumed segment. Campaign stays stopped
  pending qualification; no live/terminal/service/gate/safety/dotenv edits here.
- Golden audit PASS90/exact original bytes/hashes/zero errors; archived83.3436s,
  candidate64.2594s (ratio1.2970 under concurrent validation). Microbenchmark only.
  Retain change; no campaign resume/source transition adopted. Backend2784/four
  explicit skips/zero network attempts; frontend240/build passed. Current source
  bound to qualification archive, distinct from original stopped-campaign archive.

## 46. Exact source-transition evidence; resume not enabled

- Read `docs/strategy-research/2026-10-10-source-transition-evidence.md`.
  Fixed two executed pilot examples/first null:stable rerun PASS3/zero errors,
  canonical full payloads match except verified source identity/fingerprint.
- First replay attempt rejected source drift caused by edits during replay;
  failed directory/log retained. Rerun only after source frozen in NEW directory.
  Missing-file test initially failed KeyError; corrected explicit rejection,
  test unchanged. Focused40 passed; record full-suite figures separately.
- Evidence verifier checks exact serializer/dispatcher edits, canonical function
  AST equality, no other source/dependency changes; archives both identities and
  revalidates original53 completions/one interruption. Verifier-only change after
  replay is disclosed/bound separately. Never claim changed source hashes equal.
- Contract evidence-only resume_enabled=false; same-source loader unchanged.
  Next integrate hashed exact contract into NEW-segment resume/final coverage
  lineage with tampering/ancestor/owner tests before launch. ML/holdouts gated;
  no feature/strategy/live/terminal/service/gate/safety/dotenv work here.
- Contract reports/source-transition-evidence-20261010-01/contract.json/checksum
  PASS53/one interruption; all input hashes/current source verified. Original
  same-source loader untouched; contract alone never authorizes mixed resume.
- First full run1 failed/2790 passed/four skips retained, started before missing-file
  correction; focused40 passed and corrected full rerun required. Frontend240/build.
  Diagnostic invocations5 across failed/stable runs (four completed/one drift reject),
  not six finished replays, not campaign labels or strategy trials.
- Final corrected backend2791/four explicit skips/zero external network attempts;
  focused40/frontend240/build passed. Campaign still stopped. Accept exact evidence
  for guarded integration only; no source transition activated in resume loader.

## 47. Qualified exact-contract label resume

- Read `docs/strategy-research/2026-10-10-label-lineage-resume.md`. Contract
  `reports/lineage-integration-qualification-20261010-02/contract.json` qualifies
  only the original stopped segment/current reviewed implementation. Default
  same-source resume stays strict; old/new identities remain distinct.
- Real preflight PASS53 inherited completions/one unfinished attempt. Protected
  strategy/indicators/economics/risk/dependencies unchanged; original files immutable.
- NEW segment `reports/long-history-label-campaign-resume-20261010-01` launched,
  241885 remaining attempts. Runtime `reports/qualified-label-resume-runtime-20261010-01`.
  Launcher19864/watcher20364 at launch; verify current owner/process health.
  Watcher performs complete canonical audit after exit, never auto-resumes.
- Initial hash-format qualification rejection and full-suite source-drift failure
  retained. Representation normalized without accepting changed bytes; no assertion
  weakened. Stable backend2810/four opt-in skips/zero network attempts; focused62,
  isolated FRVP5, frontend240/build passed.
- Next monitor existing ledger/source/capacity, finish/audit all241938 pairs and
  3099 censors before features/ML. Startup is not completion; labels are not
  strategy returns. Holdouts sealed; zero strategy configurations or ML fits.
  No live/terminal/service/gate/safety/dotenv changes in this work.
- Startup04:59:39UTC:worker19124 alive/source stable,four new completions/one
  active/zero failures/no summary. Snapshot reports/qualified-label-resume-startup-20261010-01.json;
  partial only, not complete coverage. Inspect current ledger before continuation.

## 48. Resumed campaign partial saved-result audit

- Read `docs/strategy-research/2026-10-10-resumed-label-progress.md`.
  Fixed snapshot PASS36 NEW completed pairs/zero errors; all NON_EXECUTABLE/null.
  Original53 inherited separately, not newly audited here. Full preimage/shared
  hashes, source/event/cost/risk, canonical prefixes/regime/economics and label
  timing verified. Evidence reports/qualified-label-partial-audit-20261010-01.json.
- At05:03:27UTC worker19124 alive/source stable/free80.39GB/no final summary.
  No duplicate, restart or source edit. Initial report import-path failure retained;
  rerun successful with audit-process-only PYTHONPATH. No tests/assertions changed.
- Prior unchanged-source backend2810/four opt-in skips/zero network attempts;
  frontend240/build passed. Partial audit is not complete coverage or ML readiness.
- Next inspect existing ledger/owner/source/capacity; complete canonical audit of
  all241938 pairs/3099 censors before features. Do not edit replay source while
  running. Zero ML/strategy trials/holdout work; all safety boundaries retained.
- Latest monitor05:05:15UTC:worker19124/watcher20364 alive,source/contract verified;
  57 NEW completed plus53 inherited=110/241938,one active/zero failures/no summary.
  reports/qualified-label-monitor-20261010-01.json is ledger/health evidence only;
  saved-artifact audit remains36. No duplicate launch/source edit/tests repeated.
- Monitor05:06:12UTC supersedes prior counts:64 NEW+53 inherited=117/241938;
  one active/zero FAILED states,worker/watcher alive,source/contract verified,
  no summary/free80.39GB. reports/qualified-label-monitor-20261010-02.json;
  ledger health only. Continue existing campaign; feature extraction stays blocked.

## 49. Interrupted segment and second qualified resume

- Read `docs/strategy-research/2026-10-10-second-label-resume.md`. Previous worker
  and watcher absent/no summary/empty stderr; cause unknown.178 NEW saved pairs
  audit PASS/zero errors, all null/non-executable. Prior53 inherited separately.
- User explicitly authorized continuing. Preflight validates231 completions/two
  unfinished attempts across both immutable ancestors; same source/contract.
  NEW reports/long-history-label-campaign-resume-20261010-02; runtime
  reports/qualified-label-resume-runtime-20261010-02. Launcher5564/watcher7260
  at launch,241707 remaining. Inspect actual owner/ledger before further work.
- Watcher final audit includes all three segments; never auto-resumes. No replay
  source/live/terminal/service/gate/safety/dotenv/data changes or ML/holdout work.
- Next monitor NEW segment and require full241938-pair/3099-censor audit before
  features. No summary/coverage/performance claim from launch. Prior backend2810/
  four opt-in skips/frontend240/build retained for unchanged source.
- Runtime05:34:15UTC:second resume initialized;worker14560/launcher5564/watcher7260
  alive,source/contract verified.17 NEW+231 inherited=248/241938,one active/zero
  FAILED states/no summary/free80.35GB. Snapshot reports/qualified-label-second-resume-monitor-20261010-01.json;
  ledger health only,not separate artifact audit. Continue existing segment.
- Latest06:12:30UTC:336 NEW+231 inherited=567/241938,241371 remaining;
  worker14560/watcher alive,source/contract stable,no FAILED states/no summary,
  free80.35GB. Snapshot reports/qualified-label-second-resume-monitor-20261010-02.json;
  ledger health only. No unfinished state at snapshot may mean between attempts.

## 50. Login/account and card clarity pass

- Read `docs/strategy-research/2026-10-10-frontend-clarity.md`. New clarity.css
  simplifies login/account surfaces and opaque cards; main.tsx imports it last.
  Signup heading clearer; auth/entitlements/requests/execution behavior unchanged.
- Frontend240 tests/build passed. Initial backend2808/four opt-in skips/two lock
  failures: active campaign owns global OS lock. Failure preserved, no assertion
  weakened. Full unchanged suite rerun with NEW process-local TEMP/TMP isolates
  test-owned locks/stores; record final result in handoff. No campaign stop.
- Loopback Vite preview started because existing endpoint refused connection;
  no existing services/MT5 restarted. Auth unavailable notice remains accurate;
  no environment file/credentials changed. Preview is not service readiness.
- Visual login/signup review completed; desktop screenshot clipped by in-app
  browser, exhaustive device verification not claimed. Campaign source unchanged.
- Next review styling and simplify account/workstation information grouping.
  Research still requires campaign completion/full audit before features or ML.
- Final isolated-temp full backend2810/four explicit opt-in skips/zero external
  network attempts; final frontend240/build passed. Initial lock failures retained.

## 51. Opaque notification surfaces

- Read `docs/strategy-research/2026-10-10-notification-clarity.md`. Clarity.css
  overrides glass for notifications with opaque theme backgrounds, visible header,
  separators/close control; amber markers/status messages unchanged.
- Local light/dark screenshots reviewed; theme restored to light. Backend requests
  in preview returned500, not fixed by styling. No service restart or auth changes.
- Frontend240/build passed; isolated-temp backend2810/four explicit opt-in skips/
  zero network attempts. No safety assertion/replay source/process/data changes.
- Local only. Next scoped hosted frontend release and hosted visual verification;
  never include unrelated dirty changes or expose local API/MT5 in this UI release.

## 52. Landing and access-page design continuation

- Read `docs/strategy-research/2026-10-10-account-page-clarity.md`. Owner clarified
  continue other pages rather than deploy. Clarity.css extends landing overview,
  onboarding/referral and admin-review card spacing/typography/accents.
- Local landing screenshot reviewed; authenticated local onboarding/admin visual
  verification unavailable without provider config. No fake auth/session bypass.
- Frontend240/build passed; isolated-temp backend2810/four explicit opt-in skips/
  zero network attempts. Campaign alive/source stable. No hosted deployment or
  auth/execution/service/environment/data changes.
- Next simplify Markets and Settings grouping, retain provenance/status/safety.
  Hosted release is separate; research features still require full label coverage.

## 53. Markets and Settings clarity

- Read `docs/strategy-research/2026-10-10-markets-settings-clarity.md`. Clarity.css
  improves headings/spacing, strategy-plan panel and read-only Settings facts/buttons.
  No API/plan validation/execution behavior changes. Provenance and unavailable,
  unverified and analysis-only states retained. Local screenshots reviewed.
- Frontend240/build and isolated-temp backend2810/four explicit opt-in skips/zero
  network attempts passed. Campaign alive/source stable. Hosted unchanged.
- Next Journal and Research readability; distinguish fills/simulation/evidence.
  Full label coverage remains required before feature extraction/model fitting.

## 54. Minimal Research dashboard

- Read `docs/strategy-research/2026-10-10-research-minimal.md`. Research uses a
  single column and collapsed market browsing, overlays, filters and audit notes.
  Full caveats remain available; negative-edge and unverified status stay visible.
  Duplicate general-dashboard symbol/timeframe header omitted on Research.
- Frontend 240 tests/build passed; isolated-temp backend 2,810/four explicit
  opt-in skips/zero external network attempts. Initial TypeScript build failure
  and its correction are disclosed. Safety assertions retained.
- Local disclosure interaction/screenshot reviewed; catalog API HTTP 500 means
  populated charts/catalog were not visually verified. Hosted unchanged.
- Next resolve read-only research API failure, then simplify Journal. No campaign
  source/data/process change; complete coverage still gates features and ML.

## 55. Account-first workstation

- Read `docs/strategy-research/2026-10-10-workstation-account-layout.md`. New row
  shows balance/equity/free margin/realized UTC P/L, reported currency, observation
  time and account-details disclosure. Missing/error amounts remain unavailable.
  Chart height increased; existing decision/execution evidence retained.
- Frontend 240 tests/build and backend 2,810/four opt-in skips/zero external
  network attempts passed; full backend log is
  `reports/workstation-account-backend-20261010.txt`. Local unavailable view and
  dropdown reviewed; actual populated views remain blocked by API failure.
- No backend/replay source, process, data, safety or environment changes. Hosted
  unchanged. Next resolve read-only API failure, then simplify Journal. Full label
  coverage remains required before feature extraction or model fitting.

## 56. Deriv visual review and workstation arrangement

- Read `docs/strategy-research/2026-10-11-deriv-layout-completion.md`. Signed-in
  Home/value breakdown/Options and public Trader visually reviewed on web/mobile.
  Compact balance disclosure, large chart/setup rail, records below, mobile bottom
  navigation and on-demand AI implemented. No Deriv product/execution integration.
- Frontend 240/build and offline backend 2,810/four explicit opt-in skips/zero
  network attempts passed. Old layout-location assertion updated for activity area;
  all broker record/P&L/safety assertions retained. Failure logs preserved.
- Local screenshots show unavailable views; populated API verification blocked.
  Frontend relaunched after absent listener on October 11; backend/MT5 untouched.
  No deployment/replay/campaign/data/environment/safety changes.
- Next resolve read-only API availability, then simplify Home/Overview market cards.
  Complete campaign coverage remains required before feature extraction or ML.

## 57. Chart icons and read-only restoration

- Read `docs/strategy-research/2026-10-11-chart-icons-backend-restoration.md`.
  Icon controls preserve accessible names/tooltips and original test assertions.
  Canonical loopback API launched after absent listener with execution disabled.
  Populated demo balance/equity and FX20/M5 chart verified via API/browser.
- Frontend 240/build passed; initial text-label failure corrected without changing
  tests. Backend 2,810 passed/four opt-in skips/zero external network attempts;
  log `reports/chart-icons-backend-tests-20261011.txt`.
  Supervisor remains stale/not alive or unverified; no orders or readiness claim.
- No replay source/data/gates/safety/environment/terminal changes or deployment.
  Next verify populated desktop layout and sustained read-only polling, then Home
  card clarity. Campaign complete coverage still gates feature extraction and ML.

## 58. Populated layout, Home and resumed campaign

- Read `docs/strategy-research/2026-10-11-populated-mobile-home.md`. Populated desktop
  and mobile reviewed; Deriv mobile arrangement informs compact account/chart/nav.
  Home labels/cards simplified locally. No deployment or strategy changes.
- Thirty-six read-only probes passed, maximum 4.0583 seconds; short-run only.
  Home risk-summary vs terminal observation amounts differed: freshness/consistency
  remains unqualified. Supervisor stale, execution disabled.
- Previous campaign owner absent: 11,383 NEW completions plus 231 inherited,
  one unfinished STARTED retained; cause unknown. Owner authorized NEW resume at
  `reports/long-history-label-campaign-resume-20261011-01`, runtime
  `reports/label-resume-runtime-20261011-01`, launcher 10040 / worker 21872.
  Verify saved-result qualification and ledger before continuation; no duplicate
  or replay-source edits. Full coverage still blocks feature extraction and ML.
- Frontend 240/build passed. Full backend result recorded in dated handoff.
  Next campaign coverage/progress audit and Home account-evidence freshness.
- Final backend: 2,810 passed/four explicit opt-in skips/zero external network attempts. Restored worker alive; prior-result verification still pending, no new ledger yet.

## 59. Home account evidence and campaign follow-up

- Read `docs/strategy-research/2026-10-11-home-account-evidence.md`. Home account
  balance/equity now come from read-only terminal observation, with time/currency
  and no stale-risk balance fallback. Saved risk counters/limits remain separate;
  non-fresh badges are amber/stale. Browser matched workstation 141.61 USD.
- Existing campaign worker 21872 / launcher 10040 alive, CPU advancing; no new
  implementation/ledger yet. Saved-result verification pending, no new labels
  claimed. Preserve existing owner/output; do not duplicate or edit replay source.
- Tests/results recorded in dated handoff; initial nullable-currency build failure
  preserved and corrected. No authorization, execution, data or terminal changes.
- Next verify existing campaign ledger advances, then simplify Journal with
  broker provenance retained. Full label coverage still gates features/ML.
- Final checks: frontend 240/build passed; backend 2,810/four opt-in skips/zero external network attempts passed. Home observation timestamp advanced. Polling request-list assertion updated for added GET; abort/safety checks retained.

## 60. Minimal Journal and campaign status

- Read `docs/strategy-research/2026-10-11-minimal-journal.md`. Journal history/P&L
  first; calendar and decisions in disclosures. Mobile keeps time/symbol/side/P&L,
  with complete IDs/quantity/prices/UTC times in row details. Broker records,
  UTC filtering and safety evidence retained. Local only, no deployment.
- Existing worker 21872 / launcher 10040 alive; prior-result verification pending,
  no new ledger/completions. Preserve existing output and source; no duplicate.
- Frontend 240/build passed; backend outcome recorded in dated handoff.
  Next verify campaign progresses, then simplify Positions. Full coverage gates ML.
- Final backend 2,810/four explicit opt-in skips/zero external network attempts passed; final build passed. Populated desktop/mobile history reviewed, decision disclosure retains stale/unarmed supervisor evidence. Campaign still in prior-result verification.

## 61. Compact Positions and campaign follow-up

- Read `docs/strategy-research/2026-10-11-compact-positions.md`. Mobile rows retain
  symbol/side/P&L; keyboard/click details retain exact tickets, volume, prices,
  stop/target. Desktop all columns retained. No order controls or invented levels.
- Browser verified empty broker positions at mobile size; populated live positions
  unverified. New offline disclosure test passed; frontend 241/build passed.
- Existing campaign worker 21872 / launcher 10040 alive, CPU advancing, no ledger;
  prior-result verification remains pending, no new labels claimed. No duplicate,
  restart or replay edits. Full backend outcome in dated handoff.
- Next existing campaign progress/qualification, then Risk Control simplicity
  preserving evidence age/authorization blocks. Full coverage still gates ML.
- Later continuation supersedes preflight status: implementation/resume evidence written; owner 21872 replaying. Snapshot 71 NEW completed/72 started/zero failed/no summary; 11,685 combined saved of 241,938. Full backend 2,810/four skips/zero external network attempts passed. Inspect existing ledger on continuation; no duplicate/source edits.

## 62. Risk layout and partial saved-label audit

- Read `docs/strategy-research/2026-10-11-risk-layout-label-audit.md`. Risk page
  simpler; authorization blocks/reasons, quantity, limits and age remain visible.
  Presentation only, no deployment/authorization/replay changes.
- Twelve saved pairs verified against hashes and registered full-result identities,
  zero sample errors. Ledger snapshot 89 NEW completed/90 started/zero failed;
  combined 11,703 of 241,938. Partial only, no final coverage/ML readiness claim.
  Existing owner 21872; no duplicate or source edits.
- Frontend 241 passed; build/backend outcomes in dated handoff. Next existing
  campaign progress/coverage, then Performance evidence clarity.
- Final validation: frontend 241/build and backend 2,810/four explicit opt-in skips/zero external network attempts passed. Later ledger snapshot 107 NEW completed/108 started/zero failed. Risk stale/quantity-unavailable and age visibly retained.

## 63. Performance evidence clarity and extended sample

- Read `docs/strategy-research/2026-10-11-performance-evidence-ui.md`. Observed API
  history explicitly NOT OOS; unavailable research win rate/drawdown % preserved.
  Execution breakdown collapsed; all original financial values retained.
- Twelve additional chronological saved pairs passed integrity/registered-identity
  checks, 24 disjoint sampled pairs overall; partial only. Ledger snapshot 135 NEW
  completed/136 started/zero failed; combined 11,749 of 241,938. Existing owner
  21872, no duplicate or replay edits. Full coverage still blocks features/ML.
- Frontend 241/build passed; backend outcome in dated handoff. No deployment.
  Next existing campaign progress/coverage and Watchlist clarity.
- Final checks frontend 241/build and backend 2,810/four opt-in skips/zero external network attempts passed. Later ledger snapshot 158 NEW completed/159 started/zero failed (11,772 combined saved). Samples remain partial; no coverage or expectancy claim.

## 64. Minimal Watchlist and campaign progress

- Read `docs/strategy-research/2026-10-11-minimal-watchlist.md`. Watchlist cards
  first, add form in disclosure; symbol/timeframe/cap blocks/reset retained.
  Cap slots remaining explicitly not order authorization. Browser no mutations.
- Existing owner 21872 alive; snapshot 220 NEW completed/221 started/zero failed,
  11,834 combined saved of 241,938. No duplicate/replay edits. Integrity samples
  remain partial; full coverage still gates features/ML.
- Validation in dated handoff. Local only, no deployment. Next campaign progress
  and unavailable/stale cap presentation review; source remains frozen.
- Final checks frontend 241/build and backend 2,810/four opt-in skips/zero network attempts passed. Later ledger 237 NEW completed/238 started/zero failed. Known missing-cap 0/20 fallback/freshness gap is unqualified; next replace misleading unavailable/stale cap presentation, no authorization changes.

## 65. Watchlist cap evidence correction

- Read `docs/strategy-research/2026-10-11-watchlist-cap-evidence.md`. Missing/error/
  stale/future/older-than-60s cap evidence now shows remaining capacity unknown;
  default 0/20 and inferred remaining-slot/reset claims hidden. Timestamp/state
  visible. UI freshness only; no authorization changes.
- Original Watchlist identity test accidentally overwritten, caught/restored exactly;
  new stale/unavailable tests separate. Final frontend 243 passed. Full outcomes
  in dated handoff; no safety assertion removed or weakened in final state.
- Existing campaign snapshot 342 NEW completed/343 started/zero failed, combined
  11,956 of 241,938. No duplicate/replay edits. Next campaign progress and read-only
  cap account-scope/provider provenance qualification. Full coverage still gates ML.
- Final checks frontend 243/build and backend 2,810/four explicit opt-in skips/zero external network attempts passed. Original Watchlist identity test has no content diff; all safety assertions retained.

## 66. Demo execution request and verified recovery preview

- Read `docs/strategy-research/2026-10-11-demo-trading-readiness.md`. Owner requests
  trades; verified existing demo ending 8111. Preflight blocks on persisted
  CLOSE_UNCONFIRMED halt. No armed supervisor/orders launched, no halt cleared.
- Canonical close monitor on NEW SQLite backup copies confirms ticket 569491053
  STOP_LOSS close at 1656.54/net -0.95 USD/0.03 lots, matching broker deals.
  Operator ledger/halt remain unrepaired; copies preserve halt. No source edits.
- Scoped owner authorization pending for operator reconciliation, single verified
  halt clearance with backup/audit, then gated demo supervisor. Original safety
  state boundary requires this exception. Recheck evidence before applying.
  Preserve risk limits/demo checks/read-only API and research source/worker.

## 67. Authorized demo recovery and supervised trading start

- Owner explicitly authorized specific demo recovery/start. See dated readiness
  report. Exact broker evidence rechecked; stores backed up, canonical close
  reconciled, verified CLOSE_UNCONFIRMED singleton cleared in audited transaction.
  Other halts/limits untouched. Future halts do not inherit clearance authorization.
- Existing supervisor launched process-local armed flag, launcher 8224/worker 6976;
  no dotenv/source edits. First cycle RUNNING/14 pairs: ten no-trade/four minimum-lot
  risk sizing failures. No new fill confirmed; do not force/round up/relax risk.
- API remains read-only, existing Weltrade-Demo ending 8111, research worker 21872
  retained/source frozen. Fresh API heartbeat shows alive/non-stale supervisor.
- Frontend 243/build passed; backend outcome in report. Next subsequent cycle and
  fill/reconciliation monitoring; no positive-expectancy or complete-label claim.
- Final offline validation 2,810 backend/four opt-in skips/zero network attempts and frontend 243/build passed. Supervisor still RUNNING with fresh heartbeat after cycle 1; research worker retained. Operational success is not a fill or expectancy claim.

## 68. First confirmed supervised demo fill

- Cycle 2 broker-confirmed SFX Vol 20 SELL 0.02, ticket 572131426, fill 32827.82,
  SL32853.28/TP32772.14. See dated demo readiness report and saved observation.
- Four minimum-lot risk failures retained; no risk relaxation or forced entry.
  Supervisor BLOCKED OPEN_POSITION_LIMIT_REACHED protects existing position.
- API read-only/research worker retained; no source/state/process changes here.
  Next monitor position and canonical close reconciliation. A fill is not expectancy.

## 69. Authorized bounded demo cap five

- Owner selected5; only demo supervisor restarted with process-local cap5.
  Launcher6756/worker21488 supersede previous owners. No dotenv/source edits.
- First cycle14pairs: seven no-trade, six minimum-lot failures, one duplicate-symbol
  rejection; no new fills. Existing ticket572131426 protected. Research21872 retained.
- Focused156tests passed/zero network. See demo readiness report and
  reports/demo-cap-five-20261011. Cap override must be explicit on future launches.
- Next canonical sizing-feasibility diagnosis and broker-close monitoring;
  preserve per-trade risk, equity floor, same-symbol block and all other safeguards.

## 70. Read-only minimum-lot diagnosis

- Logged 2ATR stops of six rejected entries exceed indicative affordable70.805
  price units at USD141.61/0.5% risk/min0.01lots. See dated readiness table.
- Current tick-value estimate is not authoritative order_calc_profit or total costs;
  no reconstructed signals, changed stops/risk/capital or new orders requested.
- Existing SFX Vol20 position observed open with protection intact; supervisor and
  research retained. Next close reconciliation and canonical research feasibility.

## 71. Additional-entry canonical feasibility

- Read trend-add-entry proposal. Canonical engine remains single-position; no
  layered shared-account expectancy evaluation is currently possible.
- Draft bounded two-layer rules documented, unregistered/unevaluated; zero trials.
  No pipeline/engine/execution edits while research source frozen.
- Next complete existing campaign, then qualify multi-layer accounting with exact
  one-layer equivalence before fresh chronological registration/evaluation.

## 72. Local demo operational handoff

- Read docs/strategy-research/2026-10-11-local-demo-operations.md. Supervisor21488
  RUNNING/3cycles; API10sequentialhealth probes pass/max0.158s; loopback listeners.
- Current ticket572131426 remainsopen/protected; research607NEW/12221total at
  snapshot, incomplete. No source/process/state changes or auto-restart created.
- Next broker-close reconciliation then controlled recovery qualification;
  do not claim full operational readiness, uptime or positive expectancy.

## 73. Offline recovery regression check

- Unchanged supervisor/close/reconciliation/observation-health/process suites:
  76passed, zero external network attempts. See local demo operations handoff.
- No running-process faults/source changes/halts cleared; actual reboot recovery
  and auto-rearm remain unqualified. Current ticket stillopen at observation.
- Next broker-confirmed close reconciliation, then isolated startup acceptance.

## 74. Startup acceptance matrix

- Read docs/strategy-research/2026-10-11-startup-recovery-acceptance.md.
  Concrete fail-closed matrix defined, pending fixtures labeled honestly.
- No auto-start/auto-rearm, process fault, store mutation or source change.
- Next actual broker close then isolated durable-intent crash coverage inventory.

## 75. Durable recovery coverage inventory

- Startup matrix now maps exact tests:65durable executor/main/intent recovery
  passed, zero network. Persisted pending/unknown blocks startup; never auto-arm.
- In-memory restart test is not SQLite hard-crash qualification. Separate NEW
  subprocess fake-broker crash-boundary fixtures and Windows mutex checks remain.
- No live faults/source edits. Next isolated harness when campaign source stable.

## 76. Recent history display discrepancy

- Read docs/strategy-research/2026-10-11-recent-history-diagnosis.md.
  Canonical ticket close succeeded; convenience API history uses unshifted UTC
  bounds unlike authoritative server-clock-adjusted snapshot reader.
- 16existinghistory/timestamp tests passed; convenience repair not implemented.
- Broker file is campaign-hashed. Next qualified research-only source transition
  or campaign completion before patch; no in-place source edits/restarts.

## 77. Sleep diagnosis and fifth qualified resume (2026-10-13)

- Read docs/strategy-research/2026-10-13-resume-relaunch.md. Windows event
  log shows repeated unexpected shutdowns; Oct 11 ledger stopped 23:01:47
  with idle-standby 15min AC. Standby/hibernate now zero, reversible,
  evidence reports/power-settings-20261013-01.json. All four "cause unknown"
  interruptions were host power events, not campaign code.
- Dirty tree safety-committed 1fe8179..35a247b without content changes;
  current source still matches the qualified transition contract.
- Fourth interruption inherited state verified: 14,091 unique completions
  (53/178/11,383/2,477), four unfinished STARTED, zero FAILED, no summary,
  all owners dead, ancestor chains exact prefixes.
- NEW segment reports/long-history-label-campaign-resume-20261013-01,
  runtime reports/label-resume-runtime-20261013-01, launcher redirector 1604
  / worker 21232, watcher 5744/19564; 227,847 attempts remaining.
- Launcher did structural preflight only; canonical CLI revalidates all
  inherited artifacts fail-closed before replay (hours, silent). Watcher
  audits all five segments after owner exit or records STOPPED_WITHOUT_
  SUMMARY; never auto-resumes; capacity alert below 12GB. Launch is not
  completion; full coverage still gates features and ML.
- Supervisor remains down (correct Oct 11 22:48 PreflightBlocked
  DAILY_HISTORY_UNAVAILABLE). No ML/candidate/holdout work here.
- Position/cap verification 17:11 UTC, read-only MT5 attach only
  (reports/demo-position-close-check-20261013-01.json): both ledger-open
  positions actually closed at broker Oct 11 after supervisor exit —
  572269526 STOP_LOSS -0.70, 572302885 TAKE_PROFIT +1.13; account 43268111
  balance=equity 138.80 USD, zero open positions, reconciles exactly; no
  integrity halt. Oct 11 daily cap: no overshoot under the implemented
  check (max_trades_daily counts trades CLOSED today, was 4 at the 6th
  entry; closed-trade cap not submission cap — disclosed quirk;
  per-instrument usage 6/20 and 2/20).
- Owner-authorized canonical ledger reconciliation 17:13 UTC
  (tools/inspect_close_history.py --reconcile, backup
  execution_positions-pre-close-reconcile-20261013T171313Z.sqlite3 sha256
  8f983d7c...7730, notify off, attach-only): both rows now
  CLOSE_CONFIRMED matching broker deals exactly, zero open ledger rows,
  halt table empty.
- Owner-authorized supervisor re-arm completed 2026-10-13 17:32–17:43 UTC
  (supersedes the prior "remains down" state). Attempt 01
  reports/demo-supervisor-rearm-20261013-01 preserved: transient WinError 5
  heartbeat atomic-replace contention, zero orders/mutations, fail-closed.
  Attempt 02 RUNNING: launcher 10596/worker 8216, process-local flags only
  (execution=true, cap5, partial management, telegram off; shared dotenv
  unchanged). Verification reads stay sparse to avoid heartbeat contention.
- Cycle 1 (17:35 UTC): 8 NO_TRADE/6 canonical-size rejections, zero orders.
  Cycle 2 (17:40 UTC): first accepted supervised order in this segment —
  SFX VOL 20 M1 BUY 0.02 (order 575159424) filled 33701.24, SL 33672.30/
  TP 33770.94, expected loss 0.66 within authorized 0.694 USD, two 0.01
  portions registered; broker stopped it out 17:42:11 (−0.58 USD, zero
  fees); ledger auto-reconciled CLOSE_CONFIRMED, partial row CLOSED.
  Account flat 138.22 USD; closed trades 1/5, daily loss 0.42% vs 3%,
  submissions SFX VOL 20 1/20. No risk relaxation or min-lot rounding.
  A fill/stop-out is operational evidence, not expectancy. Evidence:
  reports/demo-supervisor-rearm-20261013-02/verification.json.
- Supervisor trading continuation (18:22 UTC snapshot): five orders total;
  three closes realized +1.66 USD net (zero fees) — first live
  partial-management execution on 575166027 (0.01 at +1.5R +0.54, stop
  moved to +0.5R PROTECTED, remainder TP +0.61) plus TAKE_PROFIT +1.09 on
  575192335; two positions open (575179941/575213140); duplicate-symbol
  guard blocked correctly; closed 3/5, submissions 4/20 + 1/20; balance
  140.46 exact. Snapshot reports/supervisor-campaign-monitor-20261013-01.json.
  Campaign still in silent inherited-artifact verification (worker CPU
  advancing, no ledger yet). Not expectancy evidence.
- Supervisor session close 18:29:18 UTC (evidence reports/supervisor-daily-
  cap-stop-20261013-01.json): stopped fail-closed at cycle 11 —
  DAILY_RISK_LIMIT_REACHED (5/5 closing deals, UTC day; the 18:29:16 partial
  close of 575213140 was the 5th; cap counts broker closing deals so partial
  halves consume slots) + READ_ONLY_PREFLIGHT_NO_ORDER_INTENT. Launcher
  10596/worker 8216 dead, zero residual supervisor processes. Daily count
  resets at 00:00 UTC; re-arm NOT performed (section-77 authorization was
  launch-scoped; no auto-restart exists).
- All five positions broker-confirmed closed: 575159424 -0.58 SL; 575166027
  +1.15 (partial +0.54 at +1.5R, remainder TP +0.61); 575192335 +1.09 TP;
  575213140 +1.12 (second live partial: +0.50 at +1.5R, stop to +0.5R
  PROTECTED, remainder TP +0.62 at 18:31:28 after exit); 575179941 -0.64 SL
  18:32:57 at its original stop. Session net +2.14, zero observed fees,
  balance 138.80 -> 140.94, account flat (read-only probe 23:58 UTC). Ledger
  rows for 575179941/575213140 remain unreconciled (no close-monitor cycle
  after exit); next supervisor start auto-reconciles them before trading;
  no manual repair; halt table empty, zero unresolved intents.
- Campaign: inherited-artifact verification finished 19:43:49 UTC (first new
  file), then steady ~5.3s/attempt; 2,894 new + 14,091 inherited = 16,985/
  241,938 at 00:01 UTC, zero FAILED, worker 21232 alive, no summary; sampled
  saved-artifact audit PASS 10 pairs/zero errors (read-only
  reports/audit-qualified-label-sampled-20261013-01.py, evidence
  reports/qualified-label-sampled-audit-20261013-01.json). ~2 weeks projected
  remaining at current pace; full coverage still gates features/ML.
- Owner-authorized re-arm 2026-10-14 00:06 UTC (new authorization; the
  section-77 one was launch-scoped). Launcher reports/launch-demo-supervisor-
  rearm-20261014-01.py asserted stop heartbeat/dead pid, halt-free intents,
  exactly the two broker-verified pending ledger rows (any other unreconciled
  row aborts), CLEAR stop, >12GB disk; redirector 19320/worker 16492,
  process-local flags only (execution=true, cap5, partial management, telegram
  off; shared dotenv unchanged). Evidence
  reports/demo-supervisor-rearm-20261014-01/verification.json.
- Startup catch-up reconciliation before the first preflight: 575179941 ->
  CLOSE_CONFIRMED STOP_LOSS -0.64 and 575213140 -> CLOSE_CONFIRMED UNKNOWN
  +1.12 (mixed partial+TP), both matching broker deals exactly; partial row
  575179941 self-healed READY -> CLOSED. No manual repair.
- Cycle 1 (00:10 UTC): 14 pairs - 7 NO_TRADE/6 pre-submission rejections/1
  accepted order 575518694 SFX VOL 20 M1 BUY 0.02 planned 34554.64 fill
  34561.27 SL 34528.08/TP 34607.76, two 0.01 portions READY, expected loss
  0.53 within authorized 0.7047; daily 0/5, halt-free, zero unresolved
  intents, balance 140.94. Operational evidence, not expectancy.
- Cycle 2 (00:15:10 UTC) accepted order 575522313 SFX VOL 99 BUY 0.02 (still
  open at checkpoint, +0.08 floating). Order 575518694 closed 00:22:12 UTC
  TAKE_PROFIT +0.96; close monitor auto-reconciled CLOSE_CONFIRMED; balance
  140.94 -> 141.90 exact (equity 141.99); daily 1/5 closed deals today UTC;
  halt-free, zero unresolved, CLEAR. Cycle 3 heartbeat 00:25:03 UTC.
- Local read-only frontend session for owner review (no deployment):
  read-only API uvicorn api.app:app 127.0.0.1:8000 (launcher 10888/server
  16748, observation API orders Disabled) + Vite dev pid 12156; URL
  http://localhost:5173/ (IPv6-bound; 127.0.0.1 refused), workstation at
  /workstation (dev-only direct render, frontend/src/main.tsx:13).
  Populated views verified 00:23-00:25 UTC: DEMO account 141.90 USD, FX Vol
  20 M5 chart with EMA50/EMA200 LIVE, open position 575522313, decision card
  NO TRADE/Risk BLOCKED (evidence only), terminal panel supervisor RUNNING
  cycle 3 DEMO ****8111 balance 141.9/equity 142 realized net UTC +0.96.
  Known display lag: History tab misses the newest close because convenience
  Mt5Gateway.get_trade_history (broker/mt5_gateway.py:920-928) passes
  unshifted UTC bounds (server-offset trail; the AGENTS section-76
  diagnosis) — authoritative snapshot reader and the close monitor are
  correct. Evidence reports/frontend-session-20261014-01/ (session.json,
  workstation-desktop.png, logs).
- Campaign checkpoint 00:33 UTC: 3,200 new + 14,091 inherited = 17,291/
  241,938; one active, zero FAILED, owner 21232 alive, no summary; 76.45GB
  free. A take-profit close and a populated UI are operational evidence,
  not expectancy.
