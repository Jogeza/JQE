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

## Status update

The rest of this document (below) reflects Milestone 1 — Foundation.
This section covers **Phase 1 — Broker Foundation**, the first
milestone under the revised Quant Platform mission (multi-broker,
Deriv included).

## Broker layer

### Design

```
                    Quant Core
       (market intelligence, strategy, risk,
        execution, analytics — broker-agnostic)
                        |
                        | depends only on
                        v
              broker.BrokerGateway (ABC)
                        ^
        ┌───────────────┼───────────────┬──────────────────┐
        |                |                |                  |
 SimulationGateway   DerivGateway    MT5Gateway      (future: Binance,
 (in-memory,         (websockets,    (wraps existing   Interactive
  no network)         async)          core.mt5_*,       Brokers, ...)
                                       sync SDK wrapped
                                       via asyncio.to_thread)
```

`broker/base.py` defines the interface: `connect`/`disconnect`/
`is_connected`, `get_account_info`, `get_candles`, `stream_ticks`,
`submit_order`, `get_positions`, `get_trade_history` — plus
`__aenter__`/`__aexit__` so `async with gateway:` always disconnects,
even on error. `broker/types.py` defines the only shapes that cross the
interface (`AccountInfo`, `Candle`, `Tick`, `OrderRequest`,
`OrderResult`, `Position`, `TradeHistoryEntry`, plus the `Timeframe`,
`OrderSide`, `OrderType`, `OrderStatus` enums) — Pydantic models, so
they're validated and JSON-serializable for free. No gateway leaks a
broker-native object (an MT5 struct, a Deriv `contract` dict) past its
own boundary.

**Per this milestone's explicit instruction, this is read/connect
scope only** — `submit_order` exists because "order submission
interface" was one of the eight required services, but no risk sizing,
strategy validation, or trade-management policy lives here or anywhere
in `broker/`. That's the Risk/Execution Engine milestones' job; this
layer only ever executes the exact request it's handed.

### Why the interface is async

`BrokerGateway`'s methods are `async def`. This was a deliberate choice
over keeping it synchronous (matching the rest of the pre-existing
codebase):

* Tick streaming is inherently a long-lived, I/O-bound concern —
  natural for `async for tick in gateway.stream_ticks(...)`, awkward
  to express as a blocking call.
* Deriv's API is a WebSocket protocol; an async client
  (`websockets`) is the natural fit and avoids inventing thread/queue
  plumbing just to look synchronous.
* The target stack already includes FastAPI (async-native) for a
  future API layer — an async broker interface composes with that
  directly instead of needing a sync-to-async bridge at that boundary
  too.

The cost: `MT5Gateway` wraps the `MetaTrader5` SDK's blocking calls in
`asyncio.to_thread(...)` throughout, since that SDK has no async
support. This is a standard, well-documented pattern for adapting a
sync SDK into an async interface — not a hack, but worth naming as the
one place this design choice adds friction.

### `SimulationGateway` — built first, on purpose

Per the milestone's own ordering, `SimulationGateway` exists before
`DerivGateway`/`MT5Gateway` are relied on for anything: a deterministic
(seeded), in-memory implementation with no network dependency at all.
`config.settings.broker` defaults to `"simulation"`, so the platform
runs out of the box — `python main.py` works immediately with zero
credentials. Every future Quant Core module should be developed and
tested against this gateway first.

### `DerivGateway` — connection multiplexing

Deriv's API is one persistent WebSocket carrying both request/response
traffic (correlated by a `req_id` the client assigns) and subscription
push messages (ticks). `DerivGateway` runs a single background reader
task (`_read_loop`) that demultiplexes every incoming message to
either a pending request's `asyncio.Future` (by `req_id`) or a live
subscription's `asyncio.Queue` (by symbol). Without this, a
request/response call and an active tick subscription would race to
read from the same connection.

**Not integration-tested against a live Deriv server** — this sandbox
has no network access to `wss://ws.derivws.com`. Tests
(`tests/test_deriv_gateway.py`) exercise `DerivGateway`'s own logic
(request correlation, error mapping, DTO construction) against a
scripted fake connection. See "Remaining technical debt" below for
what a live/demo-account verification pass still needs to confirm —
particularly `submit_order`'s mapping onto Deriv's Multipliers contract
type, including the currently-fixed `multiplier` value.

### `MT5Gateway` — composition, not reimplementation

`MT5Gateway` reuses `core.mt5_connection.connect`/`disconnect` and
`core.market_data.MarketData` (both already hardened with
config/logging/exceptions in Milestone 1) rather than reimplementing
MT5 session/candle handling — per "adapt the existing repository
instead of destroying working components." It calls the raw
`MetaTrader5` SDK directly only for capabilities with no existing
wrapper: account info, order submission, position/history retrieval.

### `main.py` and `backtesting/backtest.py` now depend only on `BrokerGateway`

Both were rewired from directly calling `core.mt5_connection`/
`core.market_data.MarketData` to `broker.factory.get_gateway(settings)`
— the one place that turns `settings.broker` into a concrete instance.
Neither file imports `MetaTrader5` or any broker-specific module
anymore; both became `async def` to use the gateway's async interface,
entered via `asyncio.run(...)` at the top level.

One immediate, practical benefit: `backtesting/backtest.py` no longer
requires MT5 at all by default (`settings.broker` defaults to
`"simulation"`), so it's directly runnable without a Windows terminal
or `tests/conftest.py`'s stub.

### What's deliberately *not* touched in this milestone

`core.engine.JQEEngine`, `core.market_scanner.MarketScanner`, and
`core.decision_pipeline.DecisionPipeline` still call
`core.market_data.MarketData` directly rather than going through
`BrokerGateway`. Per Milestone 1's findings, this pathway has no live
caller today (`main.py` never used it) — migrating it now would be
speculative surgery on dead code rather than Broker Foundation work.
It becomes real scope once Milestone 2b (Pipeline Integration) decides
whether this scanner/decision-pipeline model or a rebuilt flat pipeline
is the canonical path forward; at that point it should be migrated
onto `BrokerGateway` as part of that same effort, not before.

`core.mt5_connection.py` and `core.market_data.py` are unchanged and
still directly importable — `MT5Gateway` composes them rather than
replacing them, and the `JQEEngine` pathway above still depends on them
directly. They'll be candidates for deprecation once every caller has
migrated to `BrokerGateway`.

## Pipeline Integration (Milestone 2b)

### The decision: `main.py`'s flat pipeline, not `JQEEngine`

Milestone 2b's job was to decide whether `main.py`'s flat pipeline or
`core.engine.JQEEngine`'s scanner/decision-pipeline model is canonical,
then wire signal -> risk -> execution for real. **`main.py`'s flat
pipeline wins**, because `JQEEngine.evaluate_trade(signal, score,
risk)` turned out to be broken by design, not just unused:

```python
def decide(self, *args):
    symbol = "UNKNOWN"
    data = None
    for item in args:
        if isinstance(item, str):
            symbol = item
        else:
            data = item
    ...
```

Called as `evaluate_trade(signal, score, risk)` — three dict
arguments, none of them strings — this loop simply overwrites `data`
with each one in turn and keeps only the *last* (`risk`), silently
discarding `signal` and `score` entirely. It doesn't crash; it just
produces a meaningless result. Building live trading on top of this
would mean either fixing `decide()`'s call contract (a real API change
to a class nothing currently calls successfully) or working around it
— neither is "wiring," so `JQEEngine`'s scanner pathway remains
untouched, per Milestone 1's original finding.

### `strategy/pipeline.py`: three more integration gaps, found and bridged

Tracing the actual call chain (`FeatureEngine` -> `SignalEngine` ->
`SignalScorer`, and separately `risk_controller.approve_trade` /
`execution.simulator.simulate_trade`) surfaced three more mismatches,
all pre-existing:

1. **Column naming.** `calculate_indicators()` (used by `main.py`/
   `backtesting/backtest.py`) produces `EMA50`, `EMA200`, `RSI`, `ATR`.
   `FeatureEngine.analyze()` needs `EMA_50`, `EMA_200`, `RSI_14`,
   `ATR_14`. Bridged with a column-rename dict.
2. **Missing regime.** `FeatureEngine.analyze()` never sets a
   `"regime"` key on the intelligence dict it builds.
   `SignalEngine.generate()` branches almost entirely on that key —
   without it, every signal falls through to `"WAIT"`, regardless of
   trend or momentum. In other words: **as originally wired, this
   pipeline could never produce a BUY or SELL signal.** Bridged by
   computing regime with the already-tested `core.regime.detect_regime`
   (the same function `main.py` already called for logging) and
   mapping its vocabulary (`TREND_UP`/`TREND_DOWN`/`RANGE`/`NO_TRADE`)
   onto `SignalEngine`'s (`TRENDING`/`RANGING`/`UNKNOWN`) — reusing
   existing, tested classification logic rather than inventing new
   regime rules.
3. **Key naming.** `SignalEngine` returns `{"action": "BUY"/"SELL"/
   "WAIT", ...}`. `risk_controller.approve_trade` and
   `execution.simulator.simulate_trade` both expect `{"signal": "BUY"/
   "SELL"/"NO_TRADE", ...}`. Bridged with a value-mapping dict.

`strategy/pipeline.py`'s `generate_trading_signal()` calls
`FeatureEngine`, `SignalEngine`, and `SignalScorer` directly rather
than through `DecisionPipeline.analyze()` — that class's own
"scanner intelligence" (dict) branch expects yet another, different
confidence key (`"market_score"`) than `FeatureEngine` produces
(`"confidence"`), which would silently zero out confidence if routed
through it. `DecisionPipeline` itself remains unused by the live path
as a result; it's still exercised by (broken) test files tracked under
"Known test debt" in `docs/roadmap.md`.

### `risk/risk_controller.py`: real balance instead of a hardcoded `50`

`approve_trade()` computed position size via `calculate_position_size(
balance=50, ...)` — a hardcoded literal, completely ignoring the
account's actual balance. Fixed by adding a `balance` parameter
(default `50`, preserving prior behavior for any caller that doesn't
pass one) that callers now populate from
`BrokerGateway.get_account_info()`. The sizing *formula* itself is
untouched — this is a wiring fix (let the real value flow through),
not a new risk model.

### `execution/simulator.py`: stop/target extracted, reused for live orders

`simulate_trade()`'s stop-loss/take-profit calculation (entry ± ATR
multiples) was embedded inline and only reachable from within its
forward-looking, backtest-only search loop. Extracted verbatim into
`calculate_stop_target(entry, atr, direction)` so `main.py` can compute
the same levels for a live `OrderRequest` before submission —
`simulate_trade()` itself is still backtest-only (it needs the future
price path to determine WIN/LOSS/TIMEOUT, which live trading doesn't
have).

### `backtesting/engine.py`: fixed argument-count bugs

`BacktestEngine.execute_trade(signal, candle)` called
`approve_trade(signal)` (missing the required `market_data` argument)
and `simulate_trade(signal, candle)` (missing `current_index` —
`simulate_trade` needs a full DataFrame plus a position within it to
search forward from, not one candle). Both would have raised
`TypeError` on first use; neither had ever actually been exercised.
Fixed to `execute_trade(signal, current_index, dataframe)`, passing
`dataframe.iloc[:current_index + 1]` to the risk engine (so it only
ever sees history, not the future) and the full `dataframe` plus index
to `simulate_trade` (which enforces its own no-look-ahead guarantee
internally).

### Result: `main.py` and `backtesting/backtest.py` now run a real cycle

`main.py`'s `run()` now goes all the way from broker connection through
signal generation, risk evaluation, and — if approved — order
submission via `BrokerGateway.submit_order()`. `backtesting/
backtest.py` replays the same `generate_trading_signal` +
`approve_trade` + `BacktestEngine`/`simulate_trade` path candle by
candle, so a backtest and a live run share the exact same decision
logic. Verified end-to-end against `SimulationGateway` with both
forced-approval (confirms order construction and submission) and
realistic (confirms the risk engine's filters genuinely reject most
signals from synthetic random-walk data, as expected) scenarios.

### Remaining gaps in this pipeline (not addressed here)

* `SignalEngine`'s branching logic is fairly coarse (bullish/bearish +
  strong momentum only, in a trending regime) — tuning or replacing it
  is a strategy decision belonging to Milestone 5 (Strategy Engine),
  not integration work.
* `risk_controller`'s `MIN_ATR = 1.0` and `MAX_SPREAD = 30` thresholds
  are unvalidated against real instrument characteristics (they
  reasonably reject most `SimulationGateway` synthetic data, which has
  a much smaller price scale) — recalibrating them belongs to Milestone
  4 (Risk Engine).
* `DecisionPipeline`/`SignalScorer` remain unused by the live path (see
  above) — worth either deleting or formally deprecating once Milestone
  4's test-suite cleanup touches the files that still reference them.

## Data layer (Phase 2)

### Package naming vs. the brief

This milestone's brief described `data/historical.py` as an "MT5
history download" module. Built against `broker.base.BrokerGateway`
instead — the Quant Core (which this module is part of) must never
import a broker SDK directly, per the Broker Foundation milestone's
own architecture. A caller who specifically wants MT5 history gets it
by constructing an `MT5Gateway` and passing it in; nothing in `data/`
hardcodes a broker choice. `.env.example`/README wording follows suit.

### Why SQLite, not Parquet/CSV

The candle cache (`data/storage.py::CandleStore`) uses Python's stdlib
`sqlite3` rather than a file-per-series format. Reasons: no new
dependency (Parquet needs `pyarrow`); a `PRIMARY KEY (symbol,
timeframe, time)` makes overlapping incremental saves idempotent for
free via `INSERT OR REPLACE` (no separate "have I already got this
candle" check needed at the call site); and range queries (`get_
coverage`, gap-scoped `load_candles`) are simple, indexed SQL rather
than hand-rolled file/offset bookkeeping.

### `.gitignore`: separating the `data/` *package* from cache *output*

The original `.gitignore` had a blanket `data/` rule, which would have
silently excluded this entire package's source files from version
control the moment they were added — exactly the bug flagged in
Milestone 1. Fixed by never routing cache output through `data/` at
all: `CandleStore`'s database lives under `config.settings.cache_dir`
(default `cache/`, a sibling of `data/`, not inside it), and it's
`cache/` that's git-ignored. This mirrors the existing `logs/`
convention (a runtime-output directory separate from the `core/`
source that writes to it) rather than trying to carve holes in a
single directory's ignore rules.

### `BrokerGateway.get_candles` gained an `end` parameter

Gap *filling* (not just detection) requires asking a broker for a
specific historical window, not only "the latest N candles" — the
original Broker Foundation interface only supported the latter. Added
`end: datetime | None = None` (default preserves every existing
caller's behavior exactly):

* **DerivGateway**: trivial — `ticks_history` already accepts `end` as
  an epoch (or `"latest"`) directly.
* **MT5Gateway**: no existing wrapper supports a range query, so this
  calls `mt5.copy_rates_from` directly (same "raw SDK for capabilities
  `MarketData` doesn't have" pattern as `submit_order`/`get_positions`)
  — like the rest of `MT5Gateway`, unverified against a live terminal.
* **SimulationGateway**: `end` only anchors the *timestamps* assigned
  to generated candles — the synthetic price path still just continues
  the gateway's in-memory random walk regardless of the requested
  window. Consistent with this gateway never claiming realistic
  simulation; documented in its docstring.

### `HistoricalDataService`: automatic loading, incremental sync, gap fill

`data/historical.py::HistoricalDataService` is the single entry point
("automatic loading" from the brief): `get_candles(symbol, timeframe,
count)` transparently checks the cache, downloads only what's missing,
optionally fills gaps, and returns — callers never manage cache vs.
download themselves.

* **Incremental, not full, updates**: `_sync_recent` compares the
  cache's latest candle to now and downloads only enough candles to
  bridge that gap (`int(staleness / step) + 1`), not a full
  re-fetch of `count`. Falls back to a full download only when nothing
  is cached yet.
* **Gap detection**: `data.storage.find_gaps` (shared by
  `CandleStore.validate` and `HistoricalDataService.fill_gaps`, so
  detection has exactly one implementation) flags any interval between
  consecutive cached candles more than 1.5x the timeframe's expected
  step — a small tolerance for broker jitter without missing real
  gaps.
* **Gap filling**: for each detected gap, requests just enough
  candles (`span / step + 2`, a small buffer) ending at the gap's far
  edge via the new `end` parameter, filters to only what actually
  falls inside the gap window, and saves it. `CandleStore.save_candles`
  being an upsert means overlapping edges never create duplicates.
* **`sync()`** combines incremental download + gap fill + validation
  into one call with a structured `SyncReport` — the shape a scheduled
  background job would call.

### Legacy broken data-layer tests: recommend deletion, not repair

`tests/test_data_manager.py`, `tests/test_market_loader.py`, and four
others (see docs/roadmap.md, "Known test debt") import `data.
data_manager.DataManager`, `data.market_loader.MarketLoader`, `data.
validator.DataValidator`, and `data.historical_data.HistoricalData` —
a third, different, never-built data-layer design, predating even the
Quant Platform pivot. None of these names were ever implemented, and
they don't match `data/storage.py`/`data/historical.py` as specified
in the approved migration roadmap. Renaming the new modules to match
old speculative test scripts (themselves manual debug scripts with no
real assertions, same pattern as `test_core_engine.py`) would mean
designing around dead code instead of the current spec. Recommend
deleting these six files in Milestone 4 rather than rewriting them.
