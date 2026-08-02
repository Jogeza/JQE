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

## 🔜 Milestone 2b — Pipeline Integration

* Design and implement the actual signal → risk → execution wiring
  against the *current* module APIs:
  * `strategy.signal_engine.SignalEngine.generate(intelligence)` needs
    a defined "intelligence" payload — likely sourced from
    `core.market_scanner`/`core.market_state`, not raw OHLC + a regime
    string.
  * `risk.risk_controller.approve_trade(signal, market_data)` and
    `execution.simulator.simulate_trade(signal, current_index,
    dataframe)` need correct call sites — including inside
    `backtesting/engine.py`'s own `BacktestEngine.execute_trade`, which
    currently calls both with the wrong number of arguments.
* Decide whether the `main.py` flat pipeline or
  `core.engine.JQEEngine`'s scanner/decision-pipeline model is the
  canonical live-trading path going forward — and migrate whichever
  one survives onto `BrokerGateway` (see "What's deliberately not
  touched" in `docs/architecture.md`).

## ⏳ Phase 2 — Data Layer

* `data/storage.py`, `data/historical.py`.
* Fix `.gitignore`'s blanket `data/` exclusion first — it would
  silently swallow this package as currently written.
* This also resolves 6 of the pre-existing broken test files (see
  "Known test debt" below), which import a `data` package that has
  never existed.

## ⏳ Phase 3 — Intelligence & Confidence Model

* Consolidate `core/market_state.py`, `core/regime.py`,
  `analytics/trend_analysis.py`, `analytics/volatility.py`,
  `analytics/momentum.py` into `intelligence/`.
* Build `intelligence/liquidity_engine.py` and
  `intelligence/confidence_model.py` (the weighted scoring system —
  trend/structure/liquidity/momentum/volatility/risk → a single
  confidence percentage), both currently nonexistent.

## ⏳ Phase 4 — Risk Engine

* Consolidate `risk/risk_controller.py`, `risk/risk_manager.py`,
  `risk/dynamic_risk.py`, `risk/position_sizing.py` into
  `risk/risk_engine.py` + `risk/position_sizing.py`.
* Build `risk/drawdown_manager.py`, `risk/exposure_manager.py` (new).
* Dynamic position sizing (balance, equity, drawdown, volatility,
  confidence, prior performance) — no fixed lot sizes.

## ⏳ Phase 5 — Strategy Engine

* Rebuild `strategy/strategy_engine.py`/`signal_generator.py` against
  Phase 3's actual confidence-model output shape.

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
  repository. Resolved by Phase 2.
* `tests/test_core_engine.py` and `tests/test_autonomous_scanner.py`
  are manual debug scripts (module-level code with `print()`
  statements, no `test_*` functions) rather than real pytest tests,
  and fail at runtime once collected (`TypeError` comparing a mocked
  MT5 tick value) because they require a real MT5 connection. Should
  be rewritten as real, mocked pytest tests as part of whichever
  milestone finally wires up `core.engine.JQEEngine` for real (see
  Milestone 2b).

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
* `core.engine.JQEEngine` pathway not yet migrated onto `BrokerGateway`
  (see "What's deliberately not touched" in `docs/architecture.md`).
