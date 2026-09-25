# Step 4 demo learning harness — design only

> No candidate has demonstrated positive expectancy. The earlier grid (FlipX/FiboX/PlusX/SFX Vol) found zero configurations with a confidence interval excluding zero on the positive side; SFX Vol 99 @ M1 was a significant loser. This is instrumentation and learning, not a validated strategy.

## Boundary and state

This design is for Weltrade **demo** only and proposes no current trading change. Execution remains disabled (`JQE_BROKER_EXECUTION_ENABLED=false`), `DemoOnlyGuard` remains in force, and `ExecutionPolicy` must return `DEPLOYMENT_NOT_AUTHORIZED`. The harness is a decision dry run: it records hypothetical decisions, with no fills. Halt and reconciliation paths are exercised by offline tests only while execution is disabled.

The observation daemon (`monitoring/observation_daemon.py`) remains read-only, and its structural test remains untouched. A separate harness module and process uses its own isolated portable MT5 profile. Exactly one process owns each MT5 session. The harness reads immutable daemon evidence; it does not call the daemon's session or add execution code to it. It may reuse the daemon's candle-close timing, durable dedup cursor, and heartbeat patterns by copying the interface design into its own state store. A stale heartbeat, duplicate close, or evidence gap blocks decisions.

The existing execution boundary remains `main.py` / `execution.executor.AsyncTradeExecutor`. The harness does not create another submission route. Any future transition from a dry-run decision to an order requires a separate, reviewed authorization change.

## Scope and preconditions

Symbols are FX Vol 20/40/60/80/99, SFX Vol 20/40/60/80/99, PainX 400/600/800/999/1200, and MAX PainX 1000/2000. Entry timeframes are M1 and M5. H1/H4 provide only an EMA50 versus EMA200 direction check. The canonical signal path remains `core.indicators` → `core.regime.detect_regime` → `strategy.pipeline.generate_trading_signal`. The MTF gate is an additional fail-closed precondition; missing, stale, flat, or conflicting higher-timeframe state rejects the decision.

The dry-run gate records: candle and evidence IDs, signal and MTF bias, broker terms snapshot, spread and stop, gap stress, proposed quantity, risk, cost ratio, net RR, every rejection code, and policy decision. It never substitutes a missing value with a favorable default.

## Capital, risk, and halts

`JQE_MANAGED_CAPITAL_START` is a write-once operator setting. The stored starting amount is immutable and reconciled against a durable ledger at every restart. Managed equity for sizing is start plus **reconciled realized P&L**. The sizing base is `min(managed equity, broker equity)`. If broker history or ledger reconciliation is missing, stale, inconsistent, or incomplete, the harness freezes new decisions and reports `RECONCILIATION_FROZEN`.

The per-trade cap starts at approximately 2% of that sizing base. Tier 0 permits minimum lot only. Higher tiers require predefined forward-test evidence and operator review; equity growth alone never unlocks them. For MT5/Weltrade quantity, the future live path must use `main.py:authorize_broker_execution_quantity` and the gateway's `order_calc_profit`/margin route. A stress loss uses `max(stop loss, worst observed adverse bar)` plus applicable spread and execution costs. If the authorized quantity falls below the broker minimum, return typed `RISK_BELOW_MIN_LOT`; never round up quantity or widen the SL.

Drawdown checks use managed equity **including floating P&L** for the halt snapshot. The daily loss halt is 5% of the day's managed-equity reference, and the peak drawdown halt is 20% from the managed-equity high-water mark. Both block all new decisions. A reset is operator-gated, reasoned, logged, and cannot silently erase the high-water mark or unreconciled loss. Existing positions continue to be observed and reconciled during a halt.

Allow at most one concurrent position per instrument and two overall. The daily cap of 20 is a ceiling, never a trade target or quota. Broker positions and history remain authoritative. A duplicate or uncertain submission state freezes further decisions until reconciled.

## Cost gate and evidence thresholds

Initial, **unvalidated** cost thresholds are round-trip cost ≤10% of stop distance and net reward/risk ≥1.8 after estimated spread, slippage, and commissions. Calibrate these from observed per-bar spread distributions and forward evidence before use. A missing, stale, or anomalous spread sample fails closed. The SFX Vol 60 survey spread is a suspected outlier requiring historical confirmation; no cost exception is inferred from one snapshot.

No candidates currently exist in this scope. Before collecting forward data, freeze the candidate list, entry/exit definitions, risk cap, primary metric, control comparison, confidence level, and multiplicity rule in a dated protocol. A meaningful forward test should target enough independent trades to detect +0.1R at two-sided 5% alpha and 80% power: `ceil(((1.96 + 0.8416) × observed trade-R SD / 0.1)^2)`, increased for serial dependence and multiple candidate tests. The offline report supplies cell-specific preliminary estimates; these are planning numbers, not validation.

## Dashboard and Telegram

Expose mode (`DEMO_DECISION_DRY_RUN`), execution-enabled flag, selected symbol/timeframe, last closed candle and evidence ID, observation and harness heartbeat age, reconciliation status, managed-capital start, realized and floating P&L, managed and broker equity, sizing base, proposed lot and broker minimum, stop and stress loss, estimated cost ratio and net RR, H1/H4 bias, policy decision/rejection code, daily and peak drawdown, open positions per symbol and overall, daily count/cap, tier, and latest operator reset. Alerts include heartbeat stale, reconciliation freeze, below-min-lot, cost/MTF rejection, daily/peak halt, duplicate decision, and any attempted deployment while disabled. Telegram content excludes account identifiers and secrets.

## Fail-closed test list (future implementation)

- Execution disabled always yields `DEPLOYMENT_NOT_AUTHORIZED`, including when all other gates pass.
- Missing or non-demo identity, missing broker terms, missing `order_calc_profit`, bad margin, stale quotes, or missing spread rejects.
- Missing/late/duplicate candle close or evidence cursor rejects; restart preserves the cursor and heartbeat status.
- H1 or H4 unavailable, stale, flat, or disagreeing rejects; higher timeframes never create entry signals.
- Invalid BUY/SELL stop ordering, stop under broker minimum, or net RR/cost gate failure rejects.
- `RISK_BELOW_MIN_LOT` is typed, and quantity is never rounded up or SL widened.
- Reconciliation mismatch freezes decisions; realized P&L is counted once; floating P&L triggers both drawdown halts.
- Daily 5% and peak 20% halts block new decisions; reset requires operator identity, reason, timestamp, and audit record.
- One-per-instrument and two-overall concurrency, 20/day ceiling, idempotency key reuse, and uncertain submission all reject.
- Tier 0 admits only minimum lot; equity growth does not unlock tiers; evidence approval does.
- Observation daemon remains import-independent of the harness and retains its read-only structural test.

## Phase B proposals — not applied

### Watchlist

Proposed diff for `data/watchlist.py:DEFAULT_SYNTHETIC_SEEDS` and the matching `config/settings.py:observation_symbols`: replace the current mixed seeds with the 17 exact Weltrade demo names above, each at M1 and M5 for entry observation; H1/H4 are read only as bias data. Do not include FlipX, FiboX, PlusX, GainX, TrendX, QuadX, or Deriv `R_75` in this Weltrade scope. If the observation daemon's load profile makes 34 entry pairs impractical, the alternative is a separate research watchlist; this must be decided before applying a change.

The persisted `state/watchlist.sqlite3` currently has nine H1 rows, including stale `FIBOX 500`, `MAX 500`, and `QUADX 1000`. Proposed migration: back up and transactionally replace only the Weltrade scope rows with the approved exact names/timeframes; preserve unrelated operator rows only if the operator explicitly wants a mixed watchlist. Verify the resulting rows and rollback on mismatch. The database was read only for this design.

Written diff sketch (proposal only):

```diff
- DEFAULT_SYNTHETIC_SEEDS = (R_75:H1, FX Vol 20:H1, SFX Vol 20:H1,
-   PainX 400:H1, GainX 400:H1, TrendX 600:H1, FiboX:H1,
-   QuadX:H1, MAX PainX 1000:H1, MAX GainX 1000:H1)
+ WELTRADE_SCOPE_SYMBOLS = (
+   FX Vol 20, FX Vol 40, FX Vol 60, FX Vol 80, FX Vol 99,
+   SFX Vol 20, SFX Vol 40, SFX Vol 60, SFX Vol 80, SFX Vol 99,
+   PainX 400, PainX 600, PainX 800, PainX 999, PainX 1200,
+   MAX PainX 1000, MAX PainX 2000)
+ DEFAULT_SYNTHETIC_SEEDS = tuple((symbol, tf)
+   for symbol in WELTRADE_SCOPE_SYMBOLS for tf in ("M1", "M5"))
- state/watchlist.sqlite3: 9 existing H1 rows, including stale names
+ state/watchlist.sqlite3: 34 exact Weltrade symbol × entry-timeframe rows,
+   subject to operator selection and transactional migration
```

The same approved pairs would replace the fallback `observation_symbols` value in `config/settings.py`. Neither file nor the database is changed by this document.

### Open decisions

1. Whether the durable watchlist should hold all 34 M1/M5 entry pairs or a smaller approved subset after offline evidence review.
2. Which forward-test candidates, if any, qualify after the scoped offline results and random-entry control.
3. How to measure adverse-bar stress (high-low conservative proxy versus direction-specific open-to-extreme) and how much history to retain.
4. The final managed-capital start amount, only after reconciliation and operator review.
5. The forward protocol's sample size and multiplicity correction once candidate count and observed SD are known.
