# JQE Roadmap

Status legend: ✅ done · 🔜 next · ⏳ planned

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

## 🔜 Milestone 2 — Broker Abstraction

* `BrokerGateway` interface (connect, disconnect, get account info,
  get candles, get tick, place/modify/close order).
* `MT5Gateway` implementation wrapping the existing MT5 calls.
* `SimulatedGateway` implementation for backtesting/tests.
* Refactor `core/mt5_connection.py` and `core/market_data.py` to depend
  on the interface, injected rather than imported directly.
* Make `MarketData`/the gateway timeframe-aware (currently hardcoded to
  H1 internally) instead of silently ignoring a requested timeframe.
* Once complete, `tests/conftest.py`'s `MetaTrader5` stub becomes
  unnecessary for most of the codebase.

## ⏳ Milestone 2b — Pipeline Integration (newly identified, high priority)

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
* Decide whether `main.py`'s flat pipeline or `core.engine.JQEEngine`'s
  scanner/decision-pipeline model is the canonical live-trading path
  going forward (they currently diverge) — see `architecture.md`.

## ⏳ Milestone 3 — Risk Engine Consolidation

* Merge `risk/risk_controller.py`, `risk/risk_manager.py`,
  `risk/dynamic_risk.py`, `risk/position_sizing.py` into a single
  `risk/risk_engine.py` behind one interface.
* Full type hints, docstrings, and tests; deprecate/remove the
  duplicates.

## ⏳ Milestone 4 — Fix the Test Suite

* Nine pre-existing test files fail to collect or fail at runtime,
  independent of this milestone's changes:
  * `tests/test_data_manager.py`, `tests/test_indicators.py`,
    `tests/test_market_loader.py`, `tests/test_market_regime.py`,
    `tests/test_signal_engine.py`, `tests/test_signal_scorer.py` all
    import a `data` package (`data.data_manager`, `data.historical_data`,
    `data.market_loader`) that does not exist anywhere in the
    repository.
  * `tests/test_core_engine.py` and `tests/test_autonomous_scanner.py`
    are manual debug scripts (module-level code with `print()`
    statements, no `test_*` functions) rather than real pytest tests,
    and fail at runtime once collected (`TypeError` comparing a mocked
    MT5 tick value) because they require a real MT5 connection.
* Either build the `data/` package for real (note: `data/` is
  currently in `.gitignore`, which would silently exclude it — fix
  that first) or rewrite these tests against the current module
  structure.
* Rewrite the two debug scripts as real, mocked pytest tests.

## ⏳ Milestone 5 — `main.py` as a Composition Root

* Once Milestone 2b defines the real pipeline, turn `main.py` into a
  proper orchestrator (`TradingEngine` or similar) with dependency
  injection, replacing the current procedural `run()`/`main()` pair.

## ⏳ Further out

* `strategies/` (plural, per the target structure) with a formal
  strategy interface; `portfolio/`; `journal/`; `api/` (FastAPI);
  SQLAlchemy models + Alembic migrations; Next.js dashboard; AI-assisted
  optimization.
