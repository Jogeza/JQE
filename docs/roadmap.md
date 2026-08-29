# JQE Roadmap

Status legend: ✅ Completed · ⚠️ Partially integrated · 🔜 Next · ⏳ Planned · ❌ Known limitation · 🔁 Deferred

**Mission update:** JQE is no longer scoped as an MT5-only trading bot.
It's a modular quantitative trading platform (Market Intelligence,
Strategy, Risk, Portfolio, Execution, Analytics, Notifications, Broker
Layer) where the broker is one interchangeable component behind a
common `BrokerGateway` interface — MT5, Deriv, and future brokers all
implement it; the Quant Core never imports a broker SDK directly. See
`docs/architecture.md`, "Broker layer", for the full design.

---

## ✅ Milestone 1 — Foundation

* `config/` package (Pydantic Settings, `.env` support), replacing the
  flat `config.py`.
* Structured logging standardized on loguru (`core/logging_config.py`),
  with `core/logger.py` kept as a backward-compatible shim.
* All `print()` calls removed from production code (`main.py`,
  `core/engine.py`, `backtesting/backtest.py`) and replaced with
  logging.
* Centralized exception hierarchy (`core/exceptions.py`).
* `requirements.txt` updated with the full target stack; `MetaTrader5`
  marked Windows-only via an environment marker.
* `docs/` created (`architecture.md`, `roadmap.md`,
  `coding-standards.md`); `README.md` rewritten.
* Discovered and documented: `main.py` and `backtesting/backtest.py`
  referenced functions/classes that don't exist anywhere in the
  codebase (see "A significant discovery" in `architecture.md`). Both
  files were reduced to their last verified-working step rather than
  either crashing or having new trading-logic integration invented for
  them.
* `tests/conftest.py` added to stub the Windows-only `MetaTrader5`
  package for cross-platform testing (test-time only, no production
  impact).

---

## ✅ Phase 1 — Broker Foundation

* `broker/base.py` — the `BrokerGateway` abstract interface (async):
  connect/disconnect, account info, candles, tick streaming, order
  submission, positions, trade history. `broker/types.py` — the
  Pydantic DTOs/enums that are the only shapes crossing the interface.
* `broker/simulation_gateway.py` — `SimulationGateway`, a deterministic
  in-memory implementation with no network dependency. `config.settings.
  broker` defaults to `"simulation"`, so the platform runs out of the
  box with zero credentials.
* `broker/deriv_gateway.py` — `DerivGateway`, a real async WebSocket
  client against Deriv's documented API shape, with request/response
  correlation and tick-subscription multiplexing on one connection.
  **Not integration-tested against a live Deriv server** (no network
  access from this environment) — see "Remaining technical debt".
* `broker/mt5_gateway.py` — `MT5Gateway`, composing the existing
  `core.mt5_connection`/`core.market_data.MarketData` (kept, not
  duplicated) and adapting MT5's synchronous SDK via
  `asyncio.to_thread`.
* `broker/factory.py` — `get_gateway(settings)` selects the
  implementation from `settings.broker`; this is the only place that
  should ever construct a concrete gateway class.
* `main.py` and `backtesting/backtest.py` refactored onto
  `broker.factory.get_gateway` — neither imports `MetaTrader5` or any
  broker-specific module anymore.
* 46 new tests across `broker/`'s four implementation files plus the
  factory; `main.py`/`backtest.py` tests updated for the new async,
  gateway-based flow.
* **Deliberately not touched:** `core.engine.JQEEngine` /
  `core.market_scanner` / `core.decision_pipeline` still call
  `core.market_data.MarketData` directly — this pathway has no live
  caller today (see Milestone 1's findings), so migrating it now would
  be speculative. Revisit as part of Milestone 2b.

---

## ✅ Milestone 2b — Pipeline Integration

* Decided `main.py`'s flat pipeline is canonical, not
  `core.engine.JQEEngine`'s scanner/decision-pipeline model —
  `JQEEngine.evaluate_trade`'s underlying `decide(*args)` silently
  drops two of its three arguments by design (see docs/architecture.md,
  "The decision"), so it was never viable to build on.
* `strategy/pipeline.py` (new): bridges `FeatureEngine` ->
  `SignalEngine` -> `SignalScorer` to `risk_controller`/`simulator`'s
  expected shapes — fixing three independent pre-existing mismatches:
  indicator column naming, a missing `"regime"` key that made the
  pipeline incapable of ever producing BUY/SELL (always fell through to
  WAIT), and a `"action"`/`"signal"` key mismatch. Full detail in
  docs/architecture.md.
* `risk/risk_controller.py`: `approve_trade` now accepts a real
  `balance` parameter instead of a hardcoded `50`.
* `execution/simulator.py`: stop/target calculation extracted into
  `calculate_stop_target()`, reusable for live order construction
  (not just backtest simulation).
* `backtesting/engine.py`: fixed `BacktestEngine.execute_trade`'s
  argument-count bugs (`approve_trade`/`simulate_trade` were being
  called with too few arguments and would have raised `TypeError` on
  first real use).
* `main.py` and `backtesting/backtest.py` now run the complete cycle:
  data -> indicators -> regime -> signal -> risk -> (live: order
  submission via `BrokerGateway.submit_order`; backtest: `simulate_trade`
  via `BacktestEngine`). Verified end-to-end against
  `SimulationGateway`.
* 42 new tests (`strategy/pipeline.py`, the `risk_controller.py`
  balance parameter, `execution/simulator.py`'s extracted function and
  no-look-ahead guarantee, `BacktestEngine`'s fixed call sites, and
  `main.py`'s new signal/risk/order-submission sequence).
* Remaining, out-of-scope-for-this-milestone gaps (risk threshold
  calibration, `SignalEngine`'s coarse branching, `DecisionPipeline`
  going unused) are listed in docs/architecture.md, "Remaining gaps in
  this pipeline".

---

## ✅ Phase 2 — Data Layer

* Fixed `.gitignore`'s blanket `data/` exclusion — separated the
  `data/` *source package* (now tracked) from the cache's *runtime
  output* (`cache/`, git-ignored), mirroring the existing `logs/`
  convention rather than carving exceptions into one directory's
  rules.
* `data/storage.py` (new): `CandleStore`, a SQLite-backed local candle
  cache (stdlib `sqlite3`, no new dependency) — save/load, latest-N
  loading, coverage queries, cache validation (ordering, OHLC sanity,
  gap detection), and clearing.
* `data/historical.py` (new): `HistoricalDataService` — automatic
  loading (cache-or-download transparently), incremental updates
  (downloads only the gap since the cache's last candle, not a full
  re-fetch), gap detection + filling, and a `sync()` report for
  scheduled jobs.
* `broker.base.BrokerGateway.get_candles` gained an optional `end`
  parameter (historical range queries, needed for gap filling) —
  backward compatible, implemented across all three gateways.
* Built against `BrokerGateway`, not MT5 directly — see
  docs/architecture.md, "Package naming vs. the brief", for why this
  generalizes the brief's "MT5 history download" framing.
* 42 new tests (`CandleStore`, `find_gaps`, `HistoricalDataService`,
  plus `end`-parameter coverage on all three gateways).
* Recommends deleting (not rewriting) 6 of the pre-existing broken
  test files in Milestone 4 — they reference a third, different,
  never-built data-layer design that predates this one. See
  docs/architecture.md.

---

## ✅ Phase 3 — Intelligence & Confidence Model

* Consolidated `core/market_state.py`, `core/regime.py`,
  `analytics/{trend_analysis,volatility,momentum}.py`, and
  `analytics/market_score.py` into `intelligence/`, renaming to match
  the target architecture (`TrendEngine`, `VolatilityEngine`,
  `MomentumEngine`). `core/regime.py` kept as a backward-compatible
  shim (3 live importers); the rest updated directly (single-digit
  importers each).
* `intelligence/liquidity_engine.py` (new): promotes `MarketState`'s
  old binary spread threshold into a real GOOD/MEDIUM/LOW classifier —
  incidentally makes `MarketScore`'s previously-unreachable `MEDIUM`
  liquidity branch reachable. Disclosed behavior change, low risk
  (`MarketState`/`MarketScanner` have no live caller).
* `intelligence/confidence_model.py` (new): the weighted 6-factor
  scorer from the platform's Quant Intelligence Engine design (Trend
  25 / Structure 20 / Liquidity 20 / Momentum 15 / Volatility 10 /
  Risk 10 = 100). Structure and risk have no dedicated analyzer yet
  (`pattern_engine.py` was explicitly deferred — see below); scored via
  simple, transparent, isolated proxy functions
  (`classify_structure`/`classify_risk_conditions`) that a real
  pattern engine can later replace without touching the scoring logic
  itself.
* `config.settings.min_confidence_threshold` (default 70) added —
  not yet consumed; wiring `ConfidenceModel` into the live pipeline is
  Phase 5.
* 92 new/updated tests (liquidity engine, market state — including a
  regression test for the now-reachable MEDIUM branch, regime
  detection, and thorough confidence-model coverage including every
  partial-credit branch).
* `intelligence/pattern_engine.py` (structure/chart-pattern detection)
  explicitly **not** built this phase — out of the approved scope: see
  "Phase 3b" below.

---

## ⏳ Phase 3b — Pattern Engine (newly identified)

* `intelligence/pattern_engine.py`: real market-structure analysis
  (support/resistance, swing highs/lows, breakout confirmation) to
  replace `confidence_model.classify_structure`'s current simple
  range-position proxy.
* Once built, reconcile `MarketState`/`MarketScore` (4-factor, no
  structure/risk) with `ConfidenceModel` (6-factor) — most likely
  retiring the former, alongside `JQEEngine`'s broken pathway (see
  Milestone 2b/Broker Foundation debt) if that pathway is formally
  deprecated rather than fixed.

---

## ✅ Phase 4 — Risk Engine (verified state as of b2c0e8b / phase4-complete)

Phase 4 was delivered across four commits: `ab4a974`, `db18614`,
`24738e0`, and `b2c0e8b` (tagged `phase4-complete`). The section below
reflects what was verified in the repository — not what was planned.

### Delivered and tested (source + tests exist)

* **`intelligence/trade_plan.py`** — `TradePlan` (Pydantic model) and
  `TradePlanBuilder` implemented. `TradePlan.is_valid()` enforces the
  BUY/SELL directional invariants and a minimum R:R of 1.5.
  `TradePlanBuilder.build()` derives entry/SL/TP from ATR and performs
  price gating, ATR gating, and position sizing.
  Comprehensive test coverage in `tests/test_trade_plan.py` (172 lines).

* **`execution/trade_lifecycle.py`** — BUY/SELL direction bug fixed.
  The pre-Phase 4 code used hardcoded `price ± 10`/`price ± 20` for
  both directions, which placed the SELL stop *below* entry (wrong).
  Replaced with explicit caller-supplied SL/TP + hard directional
  invariant validation: BUY requires `stop_loss < entry < take_profit`;
  SELL requires `take_profit < entry < stop_loss`. Violating trades
  are rejected, not silently accepted.
  Comprehensive test coverage in `tests/test_trade_lifecycle.py` (339 lines).

* **`core/decision_pipeline.py`** — argument-dropping bug fixed.
  Pre-Phase 4 `decide(*args)` positionally sniffed for a symbol string
  and silently discarded `score` and `risk` arguments. Replaced with
  explicit `decide(signal, score, risk, market_data, symbol)` interface;
  all arguments are consumed and echoed back in the result for caller
  verification.
  Test coverage updated in `tests/test_decision_pipeline.py`.

* **`core/indicators.py`** — updated to emit both naming conventions.
  Now emits canonical names (`EMA50`, `EMA200`, `RSI`, `ATR`) **and**
  legacy aliases (`EMA_50`, `EMA_200`, `RSI_14`, `ATR_14`) so both
  the new canonical pipeline and old feature-engine callers work
  without column-name mismatches.

* **`intelligence/market_regime.py`** — `detect_regime()` added as
  the canonical regime classifier. Returns `TRENDING`, `RANGING`,
  `HIGH_VOLATILITY`, or `UNKNOWN`. The older `detect_legacy_regime()`
  function (returns `TREND_UP`/`TREND_DOWN`/`RANGE`/`NO_TRADE`) is
  retained for backward compatibility.

* **`risk/risk_engine.py`** — new `RiskEngine` class consolidating
  capital protection, confidence gating, market-condition gating,
  daily-loss/trade-count limit tracking, and dynamic risk percent
  scaling. Reads `settings.max_daily_loss` and `settings.max_trades_daily`
  at construction time. Daily-limit enforcement is opt-in
  (`enforce_limits=False` by default). The live path now opts in and
  reconstructs state from broker closed-trade history before evaluation.
  This remains partial: open executions are not counted reliably until
  they appear in closed history.

* **Documentation added:** `docs/architecture/current-state.md` and
  `docs/testing/baseline.md` created in `ab4a974`.

* **Local market datasets removed from Git tracking** (`db18614` removed
  the three CSV files at `data/storage/symbols/`; `24738e0` added them
  to `.gitignore`; `b2c0e8b` restored the rest of the `data/` source
  package which was accidentally removed alongside the CSVs in
  `db18614`). The `data/` source package is now correctly tracked;
  only runtime-generated market data is git-ignored.

---

### Phase 4 limitations / remaining integration work

The following components exist and are tested but are **not wired into
the live `main.py` trading pipeline**. They will not affect live
behaviour until Phase 5 integration work is completed.

> [!IMPORTANT]
> These are known limitations, not completed work. Do not treat the
> existence of a source file as evidence that the feature is live.

* ✅ **`TradePlanBuilder` is used by the live pipeline.**
  `main.py` builds a plan, requires `plan.is_valid()`, and constructs the
  broker `OrderRequest` from its symbol, direction, position size, stop,
  and target. `execution.simulator.calculate_stop_target()` is now
  backtest support rather than the live order-construction path.

* ❌ **The canonical `intelligence.market_regime.detect_regime()` is
  not the live regime path.**
  `main.py` imports `from core.regime import detect_regime`, which is a
  backward-compatible shim that re-exports `detect_legacy_regime`
  (vocabulary: `TREND_UP`/`TREND_DOWN`/`RANGE`/`NO_TRADE`). The newer
  canonical `detect_regime()` (vocabulary: `TRENDING`/`RANGING`/
  `HIGH_VOLATILITY`/`UNKNOWN`) is not called from `main.py`.

* ❌ **`settings.min_confidence_threshold` is not enforced.**
  The setting exists (default 70) and is validated by Pydantic, but
  `main.py` does not read it. Signals below the threshold are not
  blocked.

* ⚠️ **`settings.max_daily_loss` and `settings.max_trades_daily` are
  partially enforced.**
  `main.py` reconciles recent closed broker history and calls
  `approve_trade(..., enforce_limits=True)`. Closed-trade losses and counts
  therefore block at their configured limits. Open executions are not
  counted reliably, so the trade-count protection is not yet complete.

* ❌ **Duplicate / legacy risk components.**
  `risk/` contains `risk_engine.py` (new, canonical), `risk_controller.py`
  (backward-compatible shim over `RiskEngine`), `risk_manager.py`
  (legacy — standalone functions with a different position-sizing formula
  and ATR multipliers), and `dynamic_risk.py` (legacy — confidence/regime
  risk scaler, not called by the live pipeline). The live path uses only
  `risk_controller.py` → `risk_engine.py` → `position_sizing.py`.

* ❌ **Two incompatible position-sizing formulas co-exist.**
  `risk/position_sizing.calculate_position_size()` uses `pip_value=10.0`
  as the default multiplier. `risk/risk_manager.calculate_position_size()`
  uses `tick_value=1` as the default. These will produce different lot
  sizes for the same inputs. No numerical comparison or canonical
  selection has been made.

* ❌ **`TradeLifecycle` / `OrderManager` / `PositionManager` are not
  the live execution path.**
  These classes exist in `execution/` and are tested
  (`tests/test_trade_lifecycle.py`), but `main.py` bypasses them entirely:
  it calls `gateway.submit_order(order)` directly. `TradeLifecycle.process()`
  requires explicit `order_manager` and `position_manager` objects and
  is not wired to a `BrokerGateway`.

* ❌ **Duplicate / legacy data-layer code.**
  `data/` contains both the Phase 2 implementation (`storage.py`,
  `historical.py`) and pre-Phase 2 legacy files (`data_manager.py`,
  `historical_data.py`, `market_loader.py`, `symbol_manager.py`,
  `validator.py`, `types.py`). The legacy files use the old
  `HistoricalData`/`MarketLoader` design that was superseded by Phase 2.
  They are tracked in Git but not used by the live pipeline or the
  Phase 2 test suite.

* ❌ **Fresh-clone test reproducibility issues.**
  Several test files are problematic on a clean clone:

  - `tests/test_data_manager.py` is a debug script (module-level
    `manager.collect()` calls, no `test_*` functions). It will produce
    a collection error and attempt MT5 connections at import time.
  - `tests/test_autonomous_scanner.py`, `tests/test_jqe_engine.py`,
    and related files exercise `core.engine.JQEEngine`, which requires
    an MT5 connection. These will error unless MT5 is available and
    connected.
  - Live-connection tests (`tests/test_live_*.py`,
    `tests/test_mt5_connection_live.py`) unconditionally require a live
    broker and will fail or skip unpredictably on a fresh clone.
  - The above issues mean the full test suite cannot be run to
    zero-failure from a clean clone without a live MT5 terminal.

---

## 🔜 Phase 5 — Risk Engine Integration & Production Hardening

Phase 5 wires the Phase 4 components into the live pipeline and closes
the enforcement gaps identified above. Tasks are ordered by dependency:
test reproducibility first (so subsequent changes can be verified), then
regression coverage (so the live pipeline is protected before behavioral
changes are introduced), then behavioral integration tasks.

### Task 1 — Fresh-clone test reproducibility (Completed: ⚠️ Partial)

**Goal:** Zero collection errors, zero unexpected failures, environment-
dependent MT5 tests skip cleanly when MT5 is unavailable.

* Ensure every file under `tests/` is either a real pytest test module
  (all test logic inside `test_*` functions) or explicitly not collected
  by pytest (moved out of the `tests/` tree or excluded via `conftest.py`).
* `tests/test_data_manager.py`: convert to a proper pytest test or
  remove (it requires an MT5 connection and has no `test_*` functions —
  the data layer it exercises is superseded by Phase 2).
* MT5-dependent tests: add `pytest.skip` / `pytest.importorskip` guards
  so they are skipped, not errored, when MT5 is unavailable.
* Live-connection tests: mark with a custom `@pytest.mark.live` marker
  and exclude from the default run via `pyproject.toml`.
* Do NOT solve this by committing local market dataset CSV files.

The complete default suite currently passes, and scanner tests use mocks.
However, legacy module-level debug scripts and demo-named execution tests
remain in `tests/`, and a dedicated live-test marker policy has not been
implemented. The zero-failure goal is met; the requested test hygiene is not
fully complete.

### Task 2 — End-to-end live-cycle regression test (Completed: ✅)

**Goal:** A regression test that exercises the actual `main.run()` function
end-to-end using `SimulationGateway`, verifying the `OrderRequest` produced
by the live pipeline (action, symbol, volume, stop_loss, take_profit).

* This test must run from a clean clone with no external dependencies.
* It protects the live pipeline against behavioral regressions before
  the Phase 5 integration changes are introduced.
* Extend `tests/test_main.py` (which already exists) or add a new
  `tests/test_main_regression.py`.

### Task 3 — Enforce minimum confidence (Completed: ❌)

**Goal:** Wire `settings.min_confidence_threshold` into the live trading
path so signals below the configured threshold are rejected before risk
evaluation.

* Read `settings.min_confidence_threshold` in `main.py` after
  `generate_trading_signal()` returns.
* If `signal["confidence"] < settings.min_confidence_threshold`, log
  and return without proceeding to `approve_trade` or order submission.
* Add boundary tests: at threshold, just below, just above, and at
  the extremes (0, 100).
* Do not modify the threshold default or the risk engine's own
  confidence check (75 hardcoded in `RiskEngine`) at this time —
  reconcile the two thresholds as a separate documented decision.

### Task 4 — Integrate TradePlanBuilder (Completed: ⚠️ Partial)

**Goal:** Wire the Phase 4 `TradePlanBuilder` into the live pipeline to
replace the current manual stop/target calculation in `main.py`.

Before an order is submitted:
1. Build the `TradePlan` via `TradePlanBuilder.build()`.
2. Call `plan.is_valid()`.
3. If invalid, log the reason and return without submitting.
4. If valid, construct `OrderRequest` from the plan's fields.

* Preserve the existing backtesting behavior in `backtesting/backtest.py`
  unless there is a verified reason to change it.
* Add regression tests covering the rejection paths (invalid ATR,
  invalid price, failed R:R) to ensure `main.py` does not submit orders
  that `TradePlanBuilder` would reject.

The live integration and valid end-to-end regression exist. Builder-level
invalid ATR/price/R:R tests exist, but `main.run()` does not yet have focused
no-submission regression tests for each invalid-plan path.

### Task 5 — Reconcile position sizing (Completed: ❌)

**Goal:** Determine which position-sizing implementation is canonical for
the live trading path and document the decision.

* `risk/position_sizing.calculate_position_size()` uses `pip_value=10.0`.
* `risk/risk_manager.calculate_position_size()` uses `tick_value=1`.
* These produce materially different lot sizes for the same balance/risk
  inputs.

Steps:
1. Write numerical tests that compare the two formulas on identical
   inputs and document the difference.
2. Determine which formula is appropriate for the target instruments
   (XAUUSD, Deriv Multipliers, etc.) — this is a risk-exposure decision
   and must not be changed silently.
3. Document the decision in this roadmap and in a code comment.
4. After selection, deprecate or remove the non-canonical formula.
5. Do not change live risk exposure without explicit review.

### Task 6 — Enforce daily risk limits (Completed: ⚠️ Partial)

**Goal:** Implement enforcement of `settings.max_daily_loss` and
`settings.max_trades_daily` so the system stops trading when either limit
is reached within a session.

* `RiskEngine` tracks `_daily_trades_count` and
  `_daily_realized_loss_percent` internally and has `evaluate_limits()`.
  `main.py` now rebuilds those counters from recent broker history and
  calls `approve_trade(enforce_limits=True)`.
* Determine the appropriate scope of "daily session" for this platform
  (single `run()` call, a long-running daemon, or a scheduled job) and
  implement the smallest state/tracking mechanism required.
* Remaining gap: include open/current-cycle executions without
  double-counting them when they later become closed-history entries.
* Add tests verifying the system halts at both the trade-count limit and
  the loss limit, and resumes after `reset_daily_stats()`.
* Do not redesign the portfolio system to accomplish this.

### Task 7 — Dead-code cleanup (Completed: ❌)

**Goal:** After Tasks 1–6 are stable, identify and remove or deprecate
confirmed zero-importer legacy modules.

Candidates (verify zero live importers before deleting):
* `risk/risk_manager.py` — if replaced by Task 5's canonical sizer.
* `risk/dynamic_risk.py` — if not used by `RiskEngine` after Task 6.
* `data/data_manager.py`, `data/historical_data.py`, `data/market_loader.py`,
  `data/symbol_manager.py`, `data/validator.py`, `data/types.py` —
  legacy pre-Phase 2 data layer. Verify no remaining importers.
* Legacy test files exercising the dead `JQEEngine`/`DecisionPipeline`
  scanner pathway.

Rules:
* Verify references before deleting anything — do not delete based on
  appearance alone.
* Keep deletions small and independently reversible (one module per
  commit).
* Do not delete anything that is still imported by working code.

---

## 🔁 Deferred design decisions (not Phase 5 requirements)

The following items are deliberately **not** included in the Phase 5
scope. They are documented here so they are not forgotten, but they
require additional design work before becoming implementation tasks.

* **Reconciling confidence thresholds.** `ConfidenceModel` is now wired
  through `StrategyEngine` and produces the 6-factor breakdown. However,
  `settings.min_confidence_threshold` is stored but not enforced by the
  strategy engine, while `RiskEngine.min_confidence` remains a separate
  threshold. Minimum-confidence enforcement is therefore still incomplete.

* **Replacing `main.py`'s direct `gateway.submit_order()` call with
  `TradeLifecycle`.** `TradeLifecycle.process()` requires `order_manager`
  and `position_manager` objects that are not yet wired to a
  `BrokerGateway`. This is a larger refactor than Phase 5 requires.

* **Fully integrating `OrderManager`.** `OrderManager` exists in
  `execution/order_manager.py` and is tested, but it manages in-memory
  order state independently of the broker gateway. Integrating it
  properly requires a reconciliation design.

* **Fully integrating `PositionManager`.** Same situation as
  `OrderManager`.

* **Creating `intelligence/pattern_engine.py`.** Explicitly deferred
  since Phase 3 — see "Phase 3b" above.

---

## ⏳ Phase 6 — Execution & Trade Management

### WP0/WP1 — Architecture and pure execution policy

* `execution/policy.py` is the pure, deterministic authorization boundary.
  It performs no broker I/O and owns no authoritative position ledger.
* Emergency stop blocks every new submission.
* Explicit upstream risk approval is mandatory; missing or unreadable
  safety context fails closed.
* Maximum-open-position limits reject at or above the configured limit.
* Any existing position for the same symbol blocks another order until
  hedging/pyramiding is explicitly designed.
* Reused idempotency keys reject.
* Broker positions and history remain the source of truth.

### Later Phase 6 work

* Add an async, gateway-injected `execution/order_executor.py` and
  broker-state coordinator such as `execution/trade_manager.py`.
* Do **not** reuse the synchronous legacy `OrderManager` in `main.py`: it
  constructs/connects its own gateway and bridges async calls with
  `asyncio.run()`, conflicting with the live path's existing event loop and
  gateway ownership.
* Integrate the pure policy into the live path only after broker-state,
  idempotency persistence, and submission reconciliation are designed.
* Complete open-execution daily counting, sizing reconciliation, emergency
  stop state ownership, and broker outcome reconciliation without silently
  changing live exposure.
* Deferred purity limitation: importing `broker.types` currently executes the
  broad `broker` package initializer, which imports concrete gateway modules.
  The pure policy never constructs, connects, or calls a gateway, but narrowing
  that package import chain is a separate broker-packaging change and is not
  part of WP1.
* A SQLite-backed `IntentRecordStore` now provides durable, transactional
  claims and guarded transitions for the non-live executor boundary. It is
  intentionally not wired into `main.py`; production deployment, broker
  correlation, and restart-recovery policy remain prerequisites.
* Broker correlation remains unresolved: MT5 provides order/position/deal
  IDs and fixed comment/magic metadata; Deriv provides contract IDs, but the
  shared DTOs carry no JQE intent identity. Unknown outcomes therefore remain
  unresolved when only symbol/side or absence is observable.
* **MT5 Terminal and Account Lifecycle Safety.** Optional explicit terminal
  path, account login/server verification, terminal health checks, trading
  permission checks, and documented demo/live trade-mode validation are now
  available below the gateway boundary. Invalid or ambiguous identity fails
  closed; no terminal discovery or automatic order retry is performed. A
  successful initialization is not execution authorization.
  Production MT5 configuration requires an explicit expected environment;
  development/test construction remains permissive only for non-live use.

## Pre-Live Operational Safety

`JQE_INTENT_STORE_PATH` defines the absolute-resolved SQLite intent database,
defaulting to `state/intent_records.sqlite3`. WAL, `synchronous=FULL`, busy
timeout, atomic claims, guarded transitions, restart persistence, and
read-only inspection are implemented. Deployments require consistent backups
and conservative restoration of unresolved intents. Database uncertainty
blocks submission. These controls are technically implemented, not approval
for live execution; Deriv historical correlation and production deployment
validation remain blocked.
Unresolved submission outcomes also emit allowlisted, non-secret diagnostic
evidence; logging failures are swallowed and cannot affect execution.
* The non-live Deriv execution envelope now carries the JQE key into the
  documented Buy `passthrough` object and preserves immediate `contract_id`
  and `transaction_id` metadata. Historical passthrough propagation remains
unverified; unknown outcomes remain fail-closed.
* Deriv-specific reconciliation now preserves and can match known contract
  and transaction identifiers outside the generic executor. Symbol/side and
  absence remain ambiguous; durable historical intent correlation is still
  not established.
* **Broker Correlation Evidence Model.** `execution.reconciliation` now
  separates the authoritative JQE `idempotency_key` from immutable broker
  evidence. `CorrelationStrength` is explicitly `EXACT`, `AMBIGUOUS`,
  `ABSENT`, or `UNAVAILABLE`; broker-generated IDs are never treated as JQE
  identity. Deriv and MT5 lookup remains adapter-specific, and approximate
  symbol/side/time, MT5 magic/comment, and terminal `request_id` evidence stay
  ambiguous. No speculative broker evidence is persisted, and `UNKNOWN`
  remains fail-closed when exact evidence is unavailable.
* **Deriv PAT/OTP Authentication Boundary — non-trading.** A transport-injected
  session now supports both an in-memory fake and a production-capable REST
  OTP/WebSocket transport. It validates PAT/App ID configuration, the
  account-specific OTP response, returned session URL, account identity, and
  explicit demo/real environment. It does not assume the legacy direct
  WebSocket `authorize` flow is compatible with new Native Apps. The real
  transport is not wired to `main.py`, is not invoked by tests, and has made no
  real Deriv request. Tokens never enter execution persistence or logs; all
  failures remain not-ready and non-live.
* **Deriv Options protocol alignment.** The non-trading transport now follows
  the documented JSON REST headers and validates only the returned demo Options
  WebSocket host, path, and required OTP query parameter. The configured
  `JQE_DERIV_OPTIONS_ACCOUNT_ID` is an explicit Options account identifier; no login-ID conversion,
  legacy fallback, or retry is permitted. Independent account verification is
  still a blocker until the authenticated session exposes authoritative
  identity. Live execution remains disabled.
  The earlier controlled 404 was attributed to this account-identifier
  ambiguity; the required configuration is now explicit.
* `ExecutionIntent.idempotency_key` is durable in the intent store but is not
  propagated through the shared `OrderRequest`. Do not treat MT5's fixed
  comment/magic or Deriv contract IDs as substitutes. A future correlation
  package must add only broker-supported, recoverable metadata and must keep
  unknown outcomes unresolved until it can prove an exact match.

---

## ⏳ Phase 7 — Backtesting

* Fix `backtesting/engine.py` against the now-real Phase 3–6
  interfaces. Add Sharpe ratio, profit factor, and the other
  statistical measures not already in `analytics/performance.py`.

---

## ⏳ Phase 8 — Telegram Intelligence

* `notifications/telegram.py` — pre-trade analysis messages and
  post-trade reports, reporting on an already-working pipeline.

---

## ⏳ Phase 9 — AI Assistance

* Pattern recognition, strategy optimization, ML-assisted decision
  support — only once Phases 1–7 produce a reliable, backtested
  system, per the platform's own stated development principle.

---

## Remaining test hygiene debt

The complete default suite currently collects and passes without a live
broker. Remaining issues are hygiene and isolation risks rather than current
zero-failure blockers:

* `tests/test_data_manager.py` remains a module-level debug script with no
  pytest test functions and should be moved or converted when its legacy data
  path is retired.
* `tests/test_autonomous_scanner.py` now mocks `MarketData`, but still covers
  the noncanonical scanner path.
* Demo-named execution tests instantiate the legacy `OrderManager`; they use
  the configured gateway and must not become the model for Phase 6 tests.
* Live broker integration remains a separate, explicitly controlled concern;
  default tests must continue to avoid real order submission.

---

## Remaining technical debt (Broker Foundation)

* `DerivGateway` is unit-tested against a scripted fake connection
  only — not verified against a live/demo Deriv account. Before using
  it beyond development: confirm the exact `proposal`/`buy` parameter
  names and values for Multipliers contracts (particularly the fixed
  `multiplier` value in `broker/deriv_gateway.py`), and confirm
  `get_trade_history`'s BUY/SELL inference (approximated from price
  movement, since `profit_table` doesn't directly report direction).
* `MT5Gateway.get_trade_history` approximates trade open price from
  the closing deal only; exact pairing of MT5's entry/exit deals by
  `position_id` is deferred.
* `MT5Gateway.get_candles`/`stream_ticks` still can't honor an
  arbitrary `Timeframe` for candles (MarketData is hardcoded to H1
  internally) or push-based ticks (polled instead) — both are
  limitations of the underlying `MetaTrader5` SDK/existing
  `MarketData` class, not of the gateway abstraction itself.
* `core.engine.JQEEngine`'s `decide(*args)` silently drops arguments
  instead of raising — a real bug, not just an unmigrated pathway (see
  docs/architecture.md, "The decision"). Either fix its call contract
  properly and migrate it onto `BrokerGateway`, or formally deprecate/
  delete it along with `core.market_scanner`, `core.decision_pipeline`,
  `strategy.scoring.signal_scorer`, and the two broken debug-script
  tests that exercise it — `main.py`'s flat pipeline is canonical now
  and doesn't depend on any of them.

---

## Remaining technical debt (Pipeline Integration)

* `risk_controller.py`'s `MIN_ATR`/`MAX_SPREAD` thresholds are
  unvalidated against real instrument characteristics — recalibrate
  as part of Phase 6 (Execution & Trade Management).
* `SignalEngine`'s branching (bullish/bearish + strong momentum only,
  trending regime only) is coarse — revisit as part of a future strategy
  engine pass, not as a wiring fix.
