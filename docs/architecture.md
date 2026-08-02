# JQE Architecture

## Status

This document reflects the state of the codebase after **Milestone 1 —
Foundation**. It will be revised at the end of every milestone.

## Layering

JQE follows a loose Clean Architecture split, moving from "things that
change often" (strategy/risk parameters) to "things that change rarely"
(configuration, logging):

```
config/          Validated runtime settings (Pydantic Settings + .env)
core/            Shared kernel: exceptions, logging, MT5 connection,
                 market data, indicators, regime detection, the
                 composition-root engine (JQEEngine)
strategy/        Signal generation
risk/            Position sizing and trade approval
execution/       Order/trade simulation
analytics/       Performance measurement
backtesting/     Historical replay
```

Dependency direction: outer modules (strategy, risk, execution,
analytics, backtesting) depend on `core` and `config`; `core` and
`config` depend on nothing else in the project. This is what keeps
`config` and `core.logging_config`/`core.exceptions` safe to import
from anywhere without circular imports.

## Foundation layer (this milestone)

### `config/`

Replaces the previous flat `config.py` (an unvalidated dataclass) with
a `pydantic-settings`-based `Settings` model. Every field is validated
at startup — a bad `risk_percent` or `log_level` fails immediately and
loudly, rather than surfacing as a mysterious bug three modules deep.

Values come from, in order of precedence: explicit constructor
kwargs (mainly for tests) > environment variables (`JQE_`-prefixed) >
`.env` file > field defaults. See `.env.example` for the full list.

`config.get_settings()` is an `lru_cache`-wrapped factory rather than a
bare module-level singleton, so importing `config` never performs I/O.
`config.settings` is a convenience alias to the same cached instance.

### `core/logging_config.py` + `core/logger.py`

All logging goes through [loguru](https://github.com/Delgan/loguru).
`core/logging_config.py` is the single place that decides *how* JQE
logs (console + rotating file sinks, format, level) — driven entirely
by `config.settings`, so log level/rotation/retention are configurable
without touching code. `configure_logging()` is idempotent, so it's
safe to call from multiple import sites without duplicating sinks.

`core/logger.py` is kept as a **thin backward-compatible shim** — five
existing modules (`risk/risk_manager.py`, `core/symbol_manager.py`,
`core/regime.py`, `core/data_validator.py`, `core/mt5_connection.py`)
already do `from core.logger import logger`. Rather than touch five
call sites for an internal implementation swap, the configuration
logic moved to `logging_config.py` and `logger.py` re-exports the same
object. This is a single-responsibility split, not duplicated logic —
there is exactly one code path that configures sinks.

### `core/exceptions.py`

A small exception hierarchy rooted at `JQEError`, so failure handling
is explicit and typed instead of `return None` / `print("failed")` /
bare `except:`. Subclasses: `ConfigurationError`,
`BrokerConnectionError`, `MarketDataError`, `RiskViolationError`,
`StrategyError`, `ExecutionError`. Each accepts a message plus
arbitrary keyword context (e.g. `MarketDataError("bad data",
symbol="XAUUSD")`) that's rendered into the exception string, so a
single `logger.error(str(exc))` at a composition boundary carries full
context.

## A significant discovery: `main.py` and `backtesting/backtest.py` were not functional

While wiring the new logging/config/exception layers into `main.py`
and `backtesting/backtest.py`, it became clear that **both files
predate the current module APIs and were never actually runnable**:

* `main.py` imported `get_candles` from `core.market_data` — that
  module only ever exported a `MarketData` *class*, never that
  function.
* `backtesting/backtest.py` imported `get_market_data` (same issue)
  and `add_indicators` from `core.indicators`, which only exports
  `calculate_indicators`.
* `main.py` imported `generate_signal` from `strategy.signal_engine`
  and `evaluate_trade` from `risk.risk_controller`, and instantiated an
  `ExecutionSimulator` class from `execution.simulator`. **None of
  these exist.** The real APIs are `SignalEngine.generate(intelligence)`,
  `approve_trade(signal, market_data)`, and a free function
  `simulate_trade(signal, current_index, dataframe)` — different
  names, different arguments, different expected input shape (an
  "intelligence" dict describing trend/momentum/volatility/regime, not
  a raw OHLC DataFrame + regime string).
* Even `backtesting/engine.py`'s own `BacktestEngine.execute_trade`
  calls `approve_trade(signal)` (missing the required `market_data`
  argument) and `simulate_trade(signal, candle)` (missing the required
  `current_index` argument) — so the backtest engine could not have
  executed a single trade without raising `TypeError`, independent of
  anything in `backtest.py` itself.

This is not a regression introduced by this milestone — it's
pre-existing drift between an older, simpler pipeline design (flat
functions: data → indicators → regime → signal → risk → execution) and
the current, more sophisticated one (`core.engine.JQEEngine` →
`core.market_scanner.MarketScanner` → `core.decision_pipeline.
DecisionPipeline` → `strategy.signal_engine.SignalEngine` +
`strategy.scoring.signal_scorer`), which several modules had already
moved to but `main.py`/`backtest.py` never caught up with.

**Decision for this milestone:** per the instruction not to change
trading logic unless required for the new architecture, `main.py` and
`backtest.py` were *not* force-wired to either the old broken calls or
a freshly-invented integration — that would mean designing real
strategy/risk/execution integration under time pressure, which is a
trading-logic decision, not a foundation one. Instead:

* Both files now stop at the last **verified-real** step (market data
  fetch → validation → indicators → regime detection) and log an
  explicit `logger.warning(...)` that downstream wiring is pending,
  rather than crashing on an `ImportError`/`AttributeError` or
  silently producing wrong results.
* `docs/roadmap.md` adds a new, high-priority **Pipeline Integration**
  item to design and wire the signal → risk → execution path against
  the *current* module APIs.

## MetaTrader5 and testability

`MetaTrader5` is a Windows-only package — it cannot be installed on
Linux/macOS, including most CI runners. Several modules import it at
module scope, which would make anything importing them (including
`main.py`) impossible to even collect during testing on non-Windows
systems.

For this milestone, `tests/conftest.py` installs a `MagicMock` stand-in
for `MetaTrader5` in `sys.modules` if the real package isn't present.
This is a **test-time-only** shim — it changes no production code, and
on a machine with the real package installed (e.g. a Windows CI runner
with a licensed terminal), the real package is used untouched.

This is a stopgap, not the permanent design. **Milestone 2 — Broker
Abstraction** introduces a `BrokerGateway` interface (with `MT5Gateway`
and `SimulatedGateway` implementations) so that no module needs
`MetaTrader5` importable at all unless it's actually talking to a live
MT5 terminal — eliminating the need for the conftest stub entirely.

## Requirements

`requirements.txt` now includes the full target stack (`scipy`,
`pydantic`, `pydantic-settings`, `loguru`, `fastapi`, `uvicorn`,
`SQLAlchemy`, `alembic`, `pytest-cov`) grouped by concern.
`MetaTrader5` is now marked `; sys_platform == "win32"` so
`pip install -r requirements.txt` succeeds on non-Windows dev/CI
machines instead of hard-failing on an uninstallable package.
