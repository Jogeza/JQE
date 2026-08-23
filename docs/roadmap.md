# JQE Roadmap

Status legend: ✅ done · 🔜 next · ⏳ planned

**Mission update:** JQE is no longer scoped as an MT5-only trading bot.
It's a modular quantitative trading platform (Market Intelligence,
Strategy, Risk, Portfolio, Execution, Analytics, Notifications, Broker
Layer) where the broker is one interchangeable component behind a
common `BrokerGateway` interface — MT5, Deriv, and future brokers all
implement it; the Quant Core never imports a broker SDK directly. See
`docs/architecture.md`, "Broker layer", for the full design.

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

## ✅ Phase 4 — Risk Engine

* Consolidated `risk/risk_controller.py`, `risk/risk_manager.py`,
  `risk/dynamic_risk.py`, `risk/position_sizing.py` into unified
  `risk/risk_engine.py` (`RiskEngine`) and `risk/position_sizing.py` (`PositionSizing`).
* Institutional position sizing based on risk capital, stop distance, and lot bounds.
* Daily loss and trade count limit enforcement tracking.
* Backward-compatible functional interface maintained in `risk/risk_controller.py`.
* 6 new tests in `tests/test_risk_engine.py` covering RiskEngine and PositionSizing limits and bounds.

## 🔜 Phase 5 — Strategy Engine

* Rebuild `strategy/strategy_engine.py`/`signal_generator.py` against
  Phase 3's actual confidence-model output shape and `min_confidence_threshold`.
* Wire `ConfidenceModel` into the canonical `strategy/pipeline.py` signal path.

## ⏳ Phase 6 — Execution & Trade Management

* `execution/trade_manager.py`, `execution/order_executor.py` against
  `BrokerGateway`. Max open trades, duplicate-trade prevention, daily
  loss/drawdown protection, emergency stop.

## ⏳ Phase 7 — Backtesting

* Fix `backtesting/engine.py` against the now-real Phase 3–6
  interfaces. Add Sharpe ratio, profit factor, and the other
  statistical measures not already in `analytics/performance.py`.

## ⏳ Phase 8 — Telegram Intelligence

* `notifications/telegram.py` — pre-trade analysis messages and
  post-trade reports, reporting on an already-working pipeline.

## ⏳ Phase 9 — AI Assistance

* Pattern recognition, strategy optimization, ML-assisted decision
  support — only once Phases 1–7 produce a reliable, backtested
  system, per the platform's own stated development principle.

## Known test debt

Nine pre-existing test files fail independent of any milestone above
(unchanged since Milestone 1):

* `tests/test_data_manager.py`, `tests/test_indicators.py`,
  `tests/test_market_loader.py`, `tests/test_market_regime.py`,
  `tests/test_signal_engine.py`, `tests/test_signal_scorer.py` all
  import a `data` package (`data.data_manager`, `data.historical_data`,
  `data.market_loader`) that does not exist anywhere in the
  repository — and still doesn't after Phase 2, which built
  `data.storage`/`data.historical` per the approved migration roadmap,
  a different (and now real) design. Recommend deleting these 6 files
  rather than rewriting them to match — see docs/architecture.md,
  "Legacy broken data-layer tests".
* `tests/test_core_engine.py` and `tests/test_autonomous_scanner.py`
  are manual debug scripts (module-level code with `print()`
  statements, no `test_*` functions) rather than real pytest tests,
  and fail at runtime once collected (`TypeError` comparing a mocked
  MT5 tick value) because they require a real MT5 connection. Should
  be rewritten as real, mocked pytest tests — or deleted, if
  `JQEEngine`'s scanner pathway is formally deprecated instead of
  fixed (see "Remaining technical debt" below).

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

## Remaining technical debt (Pipeline Integration)

* `risk_controller.py`'s `MIN_ATR`/`MAX_SPREAD` thresholds are
  unvalidated against real instrument characteristics — recalibrate
  as part of Milestone 4 (Risk Engine).
* `SignalEngine`'s branching (bullish/bearish + strong momentum only,
  trending regime only) is coarse — revisit as part of Milestone 5
  (Strategy Engine), not as a wiring fix.
