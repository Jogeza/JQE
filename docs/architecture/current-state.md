# JQE Current Architecture — Phase 0 Forensics

*Inspected: 2026-08-10 · Python 3.13.14 · 244 tests passing*

---

## Repository Tree

```
D:\JQE\
├── main.py                        # Async cycle: connect → candles → indicators → regime → signal → risk → submit
├── pyproject.toml                 # asyncio_mode = "auto" (pytest-asyncio)
├── requirements.txt               # pandas, pydantic, pydantic-settings, loguru, MetaTrader5, ...
├── .env.example                   # JQE_* env variable reference
│
├── broker/                        # ✅ SOLID — async BrokerGateway abstraction
│   ├── base.py                    # ABC: connect/disconnect/candles/ticks/submit_order/positions/history
│   ├── factory.py                 # get_gateway(settings) → SimulationGateway | MT5Gateway | DerivGateway
│   ├── simulation_gateway.py      # Deterministic sim gateway (seeded random OHLC)
│   ├── mt5_gateway.py             # MetaTrader5 integration (read+write; write is guarded)
│   ├── deriv_gateway.py           # Deriv WebSocket API integration
│   └── types.py                   # Pydantic: Candle, Tick, OrderRequest, OrderResult, Position, ...
│
├── config/
│   └── settings.py                # Pydantic-Settings: JQE_* env vars, account_balance=50, risk_percent=1.0
│
├── core/                          # Mixed: some well-designed, some legacy
│   ├── indicators.py              # ✅ calculate_indicators(df) → EMA50, EMA200, RSI, ATR
│   ├── regime.py                  # Re-export shim → intelligence.market_regime.detect_regime
│   ├── market_scanner.py          # ⚠️  Uses MarketData directly (MT5), not BrokerGateway
│   ├── market_data.py             # ⚠️  Raw MetaTrader5 import — not broker-agnostic
│   ├── decision_pipeline.py       # 🐛 BUG: decide(*args) positional sniffing
│   ├── engine.py                  # JQEEngine: scan_markets + evaluate_trade (thin wrapper)
│   ├── data_validator.py          # validate_market_data(df) → bool (OHLC column checks)
│   ├── exceptions.py              # JQEError hierarchy: BrokerConnectionError, MarketDataError, ...
│   ├── logger.py                  # Loguru logger (re-export)
│   ├── logging_config.py          # Loguru setup (file + console sinks)
│   ├── mt5_connection.py          # connect() → mt5.initialize()
│   ├── portfolio.py               # Portfolio stub (empty — no real tracking)
│   └── symbol_manager.py          # MT5 symbol resolver (aliases: GOLD→XAUUSD, etc.)
│
├── intelligence/                  # ✅ Well-structured analyzers
│   ├── confidence_model.py        # ✅ ConfidenceModel: 6-factor weighted score (Pydantic)
│   │                              #    Trend(25) + Structure(20) + Liquidity(20) + Momentum(15) + Volatility(10) + Risk(10)
│   │                              #    ⚠️  NOT WIRED into the live signal path (known gap)
│   ├── market_regime.py           # detect_regime(df) → TREND_UP|TREND_DOWN|RANGE|NO_TRADE
│   │                              #    ⚠️  Vocabulary mismatch vs SignalEngine (TRENDING|RANGING|...)
│   ├── market_state.py            # MarketState.analyze() → snapshot dict (uses MarketScore, not ConfidenceModel)
│   ├── market_score.py            # ⚠️  LEGACY 4-factor scorer still wired into scanner path
│   ├── trend_engine.py            # TrendEngine: EMA20/EMA50 → BULLISH|BEARISH|SIDEWAYS|UNKNOWN
│   ├── volatility_engine.py       # VolatilityEngine: ATR → HIGH|MEDIUM|LOW|UNKNOWN
│   ├── momentum_engine.py         # MomentumEngine: RSI → STRONG|MODERATE|WEAK|UNKNOWN
│   └── liquidity_engine.py        # LiquidityEngine: spread → GOOD|MEDIUM|LOW|UNKNOWN
│
├── strategy/
│   ├── pipeline.py                # ✅ generate_trading_signal(df, symbol, regime) → {signal, confidence, ...}
│   │                              #    Manually bridges naming conventions with rename shim
│   ├── signal_engine.py           # SignalEngine.generate(intelligence) → {action, reason, confidence, quality}
│   │                              #    BUY only when regime=TRENDING + trend=BULLISH + momentum=STRONG
│   ├── features/
│   │   ├── feature_engine.py      # FeatureEngine.analyze(df) → {trend, momentum, volatility, confidence}
│   │   │                          #    Uses EMA_50/EMA_200/RSI_14/ATR_14 column names
│   │   ├── indicators.py          # Indicators.add_all(df) → EMA_50, EMA_200, RSI_14, ATR_14
│   │   └── market_regime.py       # (duplicate regime logic — different from intelligence.market_regime)
│   └── scoring/
│       └── signal_scorer.py       # SignalScorer.evaluate(intelligence, signal) → {action, score, quality, reasons}
│
├── risk/
│   ├── risk_controller.py         # approve_trade(...) → approval + authorized account-currency risk
│   │                              #    Uses hardcoded MIN_CONFIDENCE=75, MAX_RISK_PERCENT=0.5
│   ├── dynamic_risk.py            # DynamicRisk stub
│   └── position_sizing.py         # Canonical typed execution authorization; raw-lot helpers are backtest-only
│
├── execution/
│   ├── simulator.py               # simulate_trade() + calculate_stop_target() — backtest-only, no look-ahead
│   ├── trade_lifecycle.py         # Isolated legacy lifecycle invariant validation; no submission
│   └── position_manager.py        # PositionManager.open_position() — dict builder
│
├── backtesting/
│   ├── backtest.py                # ✅ run_backtest(): gateway → candles → indicators → signal → engine
│   └── engine.py                  # ✅ BacktestEngine.execute_trade(): approve_trade + simulate_trade
│
├── analytics/
│   └── performance.py             # calculate_performance(trades, equity_curve) → Sharpe, drawdown, ...
│
├── data/
│   ├── historical.py              # HistoricalDataService: gap-filling, SQLite cache
│   ├── storage.py                 # SQLite candle store
│   └── ...
│
└── tests/
    ├── conftest.py                # ✅ MT5 stub if not installed
    ├── [44 real pytest files]     # 244 passing tests
    └── [12 legacy demo scripts]   # See "Non-pytest files" below
```

---

## Data Flow (Actual, as-built)

### Live path (`main.py`)
```
BrokerGateway.connect()
  → get_candles(symbol, timeframe, count)
  → pd.DataFrame([candle.model_dump()])
  → core.indicators.calculate_indicators(df)   # adds EMA50, EMA200, RSI, ATR
  → core.regime.detect_regime(df)              # → TREND_UP | TREND_DOWN | RANGE | NO_TRADE
  → strategy.pipeline.generate_trading_signal(df, symbol, regime)
      → [rename shim: EMA50→EMA_50, RSI→RSI_14, ATR→ATR_14]
      → strategy.features.feature_engine.FeatureEngine.analyze(df)   # → {trend, momentum, volatility, confidence}
      → [regime map: TREND_UP→TRENDING, RANGE→RANGING, NO_TRADE→UNKNOWN]
      → strategy.signal_engine.SignalEngine.generate(intelligence)   # → {action, reason, confidence}
      → strategy.scoring.signal_scorer.SignalScorer.evaluate(...)    # → {score, quality, reasons}
  → BrokerGateway.get_account_info() + get_trade_history()
  → reconcile_daily_history(trades, balance)
  → risk.risk_controller.approve_trade(signal, df, balance, enforce_limits=True)
  → if approved: TradePlanBuilder.build(...)
  → require TradePlan.is_valid()
  → BrokerGateway.submit_order(OrderRequest built from TradePlan)
```

### Scanner path (`core.market_scanner.MarketScanner`)
```
core.market_data.MarketData.get_market_data(symbol)   # MT5 direct — NOT broker-agnostic
  → symbol_info_tick() → {price, bid, ask, spread}
  → get_candles() → list[dict]
  → intelligence.trend_engine.TrendEngine.analyze()
  → intelligence.volatility_engine.VolatilityEngine.analyze()
  → intelligence.momentum_engine.MomentumEngine.analyze()
  → intelligence.market_state.MarketState.analyze()
      → intelligence.liquidity_engine.LiquidityEngine.analyze(spread)
      → intelligence.market_score.MarketScore.calculate()   # LEGACY 4-factor
  → {symbol, trend, volatility, momentum, liquidity, market_score, trade_ready, price, atr, rsi}
```

---

## Previously confirmed bugs and current disposition

### Fixed bug — `execution/trade_lifecycle.py` direction handling
```python
# Current invariant enforcement:
# BUY:  stop_loss < entry < take_profit
# SELL: take_profit < entry < stop_loss
```

The isolated legacy lifecycle and the live `TradePlan.is_valid()` path both
reject violations. `TradeLifecycle` itself is not yet wired into `main.py`.

### Fixed bug — `core/decision_pipeline.py` argument handling

The former positional `decide(*args)` sniffing was replaced with an explicit
`decide(signal, score, risk, market_data, symbol)` contract. This remains a
legacy, noncanonical path despite the bug fix.

### Compatibility bridge — indicator column naming
- `core/indicators.py` → `EMA50`, `EMA200`, `RSI`, `ATR`
- `strategy/features/indicators.py` → `EMA_50`, `EMA_200`, `RSI_14`, `ATR_14`
- `core/indicators.py` now emits canonical names and legacy aliases;
  `strategy/pipeline.py` remains the mandatory translation boundary.

---

## Wiring Gaps

| Gap | Status |
|---|---|
| `ConfidenceModel` (6-factor) | Integrated through `StrategyEngine`; threshold reconciliation remains |
| `MarketScanner` uses raw MT5, not BrokerGateway | Known, deferred |
| `Portfolio` is an empty stub | Known |
| `TradePlan` model and builder | Live and validated before submission |
| Unified risk engine | Live through `risk_controller`; duplicate legacy `risk_manager` removed |
| Daily limits | Partial: closed history reconciled; open executions not reliably counted |
| Execution policy | Integrated into the canonical durable executor; direct compatibility remains Simulation-only |
| Minimum confidence setting | Incomplete: stored by strategy engine but not enforced; risk threshold remains separate |
| Position sizing | Typed `ExecutionQuantity` is canonical; Simulation risk is provable, Deriv fails closed, MT5 is disabled |
| Dashboard API layer | Implemented |

The risk dashboard exposes broker-neutral risk authorization separately from
broker-specific typed execution quantity. Simulation quantity may be observed
when canonical sizing verifies it; Deriv quantity authorization remains
fail-closed, and MT5 execution remains disabled. `recommended_lot_size` is a
deprecated API compatibility field that stays at zero and is never executable.

The canonical durable cycle publishes its latest risk result into the existing
SQLite execution-safety observation store. The API is a read-only consumer and
is the authority for freshness, using `risk_observation_freshness_seconds`.
The default is 15 seconds, matching the existing execution-safety observation
window; the exact threshold boundary remains fresh and older records are stale.
Fresh observations may expose verified typed Simulation quantity. Stale,
missing, future-dated, or malformed observations never expose an executable
quantity; Deriv remains unverified and MT5 remains disabled. The dashboard is
observational and is not an execution-authorization surface.

Persisted risk authority is additionally bound to the exact active broker,
environment, and broker-neutral `AccountInfo.account_id`. The durable cycle
persists the already-observed account identity; the API rejects context
mismatches without broker access and exposes no quantity. Schema-v1 records
without account identity fail closed and cannot become current authorization.

---

## Non-pytest Files in `tests/`

These files execute code at module-level (no pytest functions) and are counted in *collection* but not in the 244 passing tests:

| File | Type | Action |
|---|---|---|
| `test_trade_lifecycle.py` | Demo script (print output) | Convert to real pytest |
| `test_market_regime.py` | Demo script | Convert (shadowed by `test_regime_detection.py`) |
| `test_core_engine.py` | Debug script | Convert |
| `test_autonomous_scanner.py` | Demo script | Convert |
| `test_candles.py` | Empty/stub | Convert or delete |
| `test_market_loader.py` | Import test | Convert |
| `test_market_data.py` | Debug script | Convert |
| `test_market_score.py` | Debug script | Convert |
| `test_indicators.py` | Debug script | Convert |
| `decision_pipeline.py` | Empty file (no `test_` prefix either) | Delete |
| `market_scanner.py` | Empty file | Delete |
| `portfolio.py` | Empty file | Delete |

---

## MT5 Integration Points

| File | MT5 Usage |
|---|---|
| `core/market_data.py` | `mt5.symbol_info_tick()`, `mt5.copy_rates_from_pos()` |
| `core/mt5_connection.py` | `mt5.initialize()` |
| `core/symbol_manager.py` | `mt5.symbol_info()` |
| `broker/mt5_gateway.py` | Full MT5 API (guarded by connection check) |

MT5 is mocked in `tests/conftest.py` via `sys.modules` stub when not installed.

---

## Execution / Order Submission Paths

| Path | Submits Live Orders? |
|---|---|
| `main.py` → `gateway.submit_order()` | Direct compatibility submission is Simulation-only |
| `execution/executor.py` → `gateway.submit_order()` | Canonical durable boundary after policy, reservation, reconciliation, and durable claim |
| `broker/simulation_gateway.py` | Paper simulation only — no real orders |
| `broker/mt5_gateway.py` | YES — must not be called during development |
| `broker/deriv_gateway.py` | YES — must not be called during development |
| `execution/simulator.py` | No — backtest-only, no broker calls |
| `execution/trade_lifecycle.py` | Isolated legacy lifecycle; no broker submission boundary |
| `execution/policy.py` | No — pure fail-closed decision logic, no gateway calls |

### Phase 6 execution architecture decision

`execution.policy.ExecutionPolicy` is the pure authorization boundary. It
does not construct/connect a gateway, submit orders, mutate broker state, or
own an authoritative position ledger. Broker positions and history remain the
source of truth.

The synchronous legacy `OrderManager` was removed. Broker submission is
limited to the Simulation-only direct compatibility branch in `main.py` and
the async, gateway-injected durable executor.

The Phase 6 policy is deliberately conservative:

* emergency stop blocks every new submission;
* explicit risk approval is mandatory;
* missing or unreadable safety state fails closed;
* daily and open-position limits reject at their configured boundaries;
* any existing same-symbol position blocks another order until hedging or
  pyramiding is explicitly designed;
* reused idempotency keys reject.

The non-live execution boundary now includes a SQLite-backed
`IntentRecordStore`. It persists UTC intent state, uses a unique key with
transactional `BEGIN IMMEDIATE` claims, and guards state transitions. The
store does not reconcile broker executions; that remains the gateway/state
coordinator's responsibility. It is not wired into `main.py` until durable
deployment policy and broker-specific correlation are complete.

Current broker correlation is limited. MT5 exposes broker order, position, and
deal identifiers plus a fixed gateway comment/magic value; Deriv exposes
contract IDs and portfolio/history records. Neither shared gateway contract
propagates the JQE idempotency key. Symbol/side matches are therefore only
conservative duplicate guards, not proof that a particular intent executed.
For an unknown outcome, both a symbol match and an absent visible position are
ambiguous evidence and never permit blind resubmission.

## Pre-Live Operational Safety

`JQE_INTENT_STORE_PATH` configures the absolute-resolved SQLite intent store;
the default is `state/intent_records.sqlite3`, never a temporary directory.
The store uses WAL, `synchronous=FULL`, a five-second busy timeout, atomic
transactions, and guarded transitions. Deployments must use consistent SQLite
backups and restore unresolved `PENDING`/`UNKNOWN` records before recovery.
Database uncertainty prevents broker submission. The read-only `inspect()`
method exposes state, timestamps, and known order IDs. These safeguards are
technically implemented, but durable Deriv correlation, production filesystem
validation, and backup/restore operations remain prerequisites for live use.
Unresolved submission outcomes emit an allowlisted diagnostic record containing
non-secret intent, broker, state, timestamp, and error-category fields.

### Intent identity and recovery

`ExecutionIntent.idempotency_key` is generated by the caller, persisted by
`IntentRecordStore`, and retained by the executor. It is currently lost at
the shared `OrderRequest` boundary because that broker DTO has no client
correlation field. MT5 requests use a fixed comment and magic number, while
Deriv returns broker-generated contract IDs; neither mechanism preserves the
JQE key. Broker order/deal/position IDs are therefore evidence associated
with an intent, never replacements for its identity.

The correlation contract distinguishes `CONFIRMED_MATCH`,
`CONFIRMED_ABSENCE`, `AMBIGUOUS`, and `UNAVAILABLE`. With current APIs,
symbol/side matches and missing visible positions remain ambiguous. Unknown
submissions stay unresolved and cannot be retried. Future live wiring
requires a broker-supported, recoverable client identity plus historical
reconciliation before any correlation can be considered confirmed.

The execution boundary now preserves the JQE key in an execution-specific
envelope. The Deriv gateway maps it deterministically to the documented Buy
`passthrough` object (`{"jqe": {"idempotency_key": "..."}}`) and preserves
the returned contract and transaction identifiers on the immediate result.
Deriv documentation does not establish that passthrough is retained by later
portfolio or history records, so this does not establish durable historical
correlation.

The Deriv reconciliation adapter can confirm a known contract ID or
transaction ID against current portfolio/history DTOs. Symbol/side evidence
remains ambiguous, and absence remains non-proof. `UNKNOWN` intents therefore
stay fail-closed unless exact broker evidence is supplied.

### Broker Correlation Evidence Model

The reconciliation boundary distinguishes the authoritative JQE
`idempotency_key` from broker execution evidence. `CorrelationEvidence` is an
immutable, broker-neutral record containing the broker name, any identifiers
actually returned by that broker, descriptive fields, source, and a
`CorrelationStrength` of `EXACT`, `AMBIGUOUS`, `ABSENT`, or `UNAVAILABLE`.
Broker order, deal, position, contract, transaction, and request identifiers
are evidence only; none is substituted for the JQE key.

`EXACT` is allowed only when a caller-supplied broker identifier is found.
Symbol, side, volume, timestamps, MT5 magic/comment, and MT5 request IDs are
not exact identity keys. Deriv passthrough persistence is unproven, and MT5
request IDs are terminal-generated and not restart-safe. Empty successful
queries produce `ABSENT`; broker failures produce `UNAVAILABLE`; approximate
matches produce `AMBIGUOUS`.

The Deriv and MT5 adapters own their broker-specific lookup and identifier
semantics. The generic executor consumes only broker-neutral reconciliation
results. Evidence is not persisted speculatively: durable storage remains for
JQE intent state until a broker-supported correlation contract is proven.
This model does not create durable correlation where the broker does not
provide it, and `UNKNOWN` outcomes remain unresolved without exact evidence.

### MT5 Terminal and Account Lifecycle Safety

MT5 configuration may provide an explicit terminal executable path through
`JQE_MT5_TERMINAL_PATH`, an account login, server, and expected environment
(`demo` or `live`). When supplied, the path is resolved and validated; JQE
does not scan for or silently choose another terminal. The gateway verifies
`account_info()` login/server, `terminal_info()` connectivity and trading
permissions, and the documented account trade mode before marking a strict
connection usable. A successful `mt5.initialize()` alone does not authorize
execution.

If identity or health information is missing or mismatched, connection fails
closed. Shutdown is explicit and reconnects do not resubmit uncertain orders;
broker state must be reconciled and exact evidence obtained first. MT5
supports netting and hedging account modes, so account-mode and partial-fill
handling remain future reconciliation work. Demo/live verification relies on
the documented account trade mode; unknown modes are rejected when an
environment is expected.
Production-configured MT5 gateways require an expected environment; development
and test gateways may omit strict identity checks while the executor remains
non-live.

### Deriv PAT/OTP Authentication Boundary

`broker.deriv_auth` defines a broker-specific, transport-injected PAT/OTP
session boundary. It validates App ID and PAT presence, sends Bearer-authenticated
OTP requests through a supplied transport, validates the returned session URL,
account identity, and explicit `demo`/`real` environment, then establishes the
authenticated WebSocket session. Tokens are excluded from representations and
authentication errors contain only stable failure codes.

The boundary now includes a production-capable, dependency-injected REST/OTP
transport and WebSocket connector, alongside the in-memory fake used by tests.
The production transport targets the documented account OTP endpoint and only
connects to the returned authenticated URL; it is not wired to `main.py` or
trading. The existing direct legacy-style `authorize` WebSocket path is not
assumed compatible with newly registered Native Apps. Expired, revoked,
malformed, unavailable, mismatched, or unverifiable authentication state
remains not-ready and cannot authorize trading. PATs never enter execution
models, SQLite, logs, or diagnostics. **No real Deriv authentication has been
performed.**

The aligned Options flow uses `POST /trading/v1/options/accounts/{accountId}/otp`
with `Deriv-App-ID`, Bearer authorization, and JSON content type, then connects
only to the returned `wss://api.derivws.com/trading/v1/options/ws/demo?otp=...`
URL with the App-ID header. The configured account value is treated explicitly
as an Options account identifier via `JQE_DERIV_OPTIONS_ACCOUNT_ID`, not inferred
or transformed from a login ID. A Deriv login ID is not an Options account ID.
OTP values are credentials and are never logged or persisted. Legacy endpoints,
fallbacks, and retries are forbidden. Authoritative account verification remains
blocked until the authenticated session supplies independently verifiable
identity; live execution remains disabled.
The prior controlled 404 investigation identified ambiguous account identity as
the remaining authentication blocker; configuration now uses an explicit
Options account ID field.
