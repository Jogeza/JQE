# Longer-history training baseline: frozen design

The separate design is frozen at `reports/long-history-training-registration-20261009-01/protocol.json`, with checksum `06be54a572cd52b608755fa643d12f4f39843aa09ce9dcd3212f1597b884bfa4`. Its ledger records **zero outcomes**. This is a design registration; a compatible canonical dispatcher has not yet been implemented. Do not pass these bundles to the old campaign dispatcher or change their acquisition status to bypass its checks.

## Data and fixed configuration

All ten native Weltrade symbols use NEW attempt-04 immutable bundles, each with 25,894 closed M5 bars. Source window: July 10 00:00 through October 8 00:00 UTC, half-open. The original full prefix starts July 10; the first 200 observed bars are warmup. Evaluation starts July 10 16:40 UTC, lasting **89.3056 calendar days**, not 90 evaluated days. Manifest, CSV, spread, acquisition, calendar, audit, old economics and source hashes are bound in the protocol.

One canonical v2 baseline configuration is planned across ten symbols and three costs: 30 training replays, zero candidate configurations, zero ML fits. Each case has an independent USD 50 account, 1% risk, minimum confidence 70, minimum ATR 1 and maximum signal spread 30. No minimum-lot round-up, increased capital or relaxed risk is permitted after feasibility results.

| Cost case | Commission USD/lot/side | Recorded spread multiplier | Slippage ATR/fill |
|---|---:|---:|---:|
| Optimistic zero commission | 0 | 1 | 0.05 |
| Assumed commission | 3 | 1 | 0.05 |
| Doubled spread and commission | 6 | 2 | 0.05 |

These cases overlap; they are not independent samples. Financing uses declared current-rate/ending-server-day assumptions. Exact fees and historical financing/calendar remain unresolved. Unknown signal spread fallback 1.0 is not cost evidence.

## Mandatory preflight and replay semantics

Before outcomes, implement a separate dispatcher through `D:\JQE\venv\Scripts\python.exe -m backtesting.backtest`. Verify every input and source hash, closedness, conditional coverage, exact native symbols and spread binding. Compare the October 8 contract/margin snapshot against attempt-04 economics for every symbol. Require matched profit probes and conservative margin evidence; reject disagreement, preserve failures and do not infer missing terms. This comparison has **not yet been performed**.

Use corrected `frozen-weltrade-cfd-v2`. Signals must come from `strategy.pipeline.generate_trading_signal()` with the complete new-data prefix. The expanded EMA recursion/prefix changes signal identities: old labels cannot transfer. Bind any new dispatch implementation separately; the current snapshot does not contain it.

Stateful replay enters at the next observed bar, so Sunday gaps can delay entry. The 19-bar holding cap counts observed bars and can extend wall time across a closure. Frozen-model stop gaps fill at the adverse opening price; targets fill at trigger and same-bar collisions use stop first. Disclose end-of-data liquidation and discarded pending entries. Generic descriptor fields do not prove live-plan equivalence. Future counterfactual labels must censor their full predefined gap/boundary intervals even if a hypothetical trade exits earlier.

Keep every symbol and all three costs, including null expectancy/profit factor for no-trade cases. Record modeled USD/R expectancy and uncertainty, win/loss, profit factor, liquidation drawdown, unannualized Sharpe/Sortino, exposure, holding duration and MAE/MFE distributions with OHLC limitations. Diagnose losses by regime, signal type, timing and stop/quantity feasibility. Independent symbol accounts do not establish shared-portfolio performance.

## NOT proven

No longer-history strategy outcomes, positive expectancy, OOS edge, sufficient independent events, historical timezone stability, universal commission tariff, verified historical margin/financing, live fill equivalence or ML readiness are established. The Sunday calendar remains conditional. This is training-only; no fresh ML holdout is registered. Original EMA50 holdouts remain sealed. Live execution, terminal/session state and safety controls were untouched.

Next: implement and validate the separate offline preflight/canonical training dispatcher against this frozen design, with a separately disclosed implementation snapshot. Stop before outcomes if any prerequisite fails.

Validation: full offline backend suite 2,698 passed, four explicit opt-in skips,
zero external network attempts; frontend 240 passed and build passed (existing
large-chunk warning). Logs: `reports/long-history-protocol-backend-20261009.txt`,
`reports/long-history-protocol-frontend-20261009.txt` and
`reports/long-history-protocol-build-20261009.txt`. No strategy/runtime code changed
in this step; the registration utility checks input hashes and identical warmup
boundaries without computing signals or outcomes.
