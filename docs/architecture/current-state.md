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
│   ├── risk_controller.py         # approve_trade(signal, market_data, balance) → {approved, reason, lot_size}
│   │                              #    Uses hardcoded MIN_CONFIDENCE=75, MAX_RISK_PERCENT=0.5
│   ├── risk_manager.py            # calculate_risk/position_size/stop_loss/take_profit (standalone functions)
│   │                              #    ⚠️  DUPLICATE of risk_controller.py — different API, same purpose
│   ├── dynamic_risk.py            # DynamicRisk stub
│   └── position_sizing.py         # Simple lot calculator stub
│
├── execution/
│   ├── simulator.py               # simulate_trade() + calculate_stop_target() — backtest-only, no look-ahead
│   ├── trade_lifecycle.py         # 🐛 BUG: stop_loss=price-10, take_profit=price+20 for ALL directions
│   ├── order_manager.py           # OrderManager.create_order() — validation + dict builder
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
  → risk.risk_controller.approve_trade(signal, df, balance)
  → if approved: calculate_stop_target(entry, ATR, direction)
  → BrokerGateway.submit_order(OrderRequest)
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

## Confirmed Bugs

### Bug 1 — `execution/trade_lifecycle.py` direction bug
```python
# Current (WRONG for SELL):
stop_loss = price - 10      # always below entry
take_profit = price + 20    # always above entry

# Required:
# BUY:  SL < entry < TP
# SELL: TP < entry < SL
```

### Bug 2 — `core/decision_pipeline.py` fragile `decide(*args)`
```python
def decide(self, *args):
    for item in args:
        if isinstance(item, str):
            symbol = item   # positional string sniffing
        else:
            data = item     # discards signal, score, risk separately
```
Called from `core/engine.py` as `self.pipeline.decide(signal, score, risk)` — the `score` and `risk` args are silently discarded.

### Bug 3 — Indicator column naming split
- `core/indicators.py` → `EMA50`, `EMA200`, `RSI`, `ATR`
- `strategy/features/indicators.py` → `EMA_50`, `EMA_200`, `RSI_14`, `ATR_14`
- Bridge shim in `strategy/pipeline.py` (functional but fragile)

---

## Wiring Gaps

| Gap | Status |
|---|---|
| `ConfidenceModel` (6-factor) not in live path | Known, deferred |
| `MarketScanner` uses raw MT5, not BrokerGateway | Known, deferred |
| `Portfolio` is an empty stub | Known |
| No `TradePlan` model | Missing |
| No unified risk engine | Two competing: `risk_controller` vs `risk_manager` |
| No paper trade lifecycle | Missing |
| No dashboard API layer | Missing |

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
| `main.py` → `gateway.submit_order()` | Only if `broker=mt5` AND signal approved |
| `broker/simulation_gateway.py` | Paper simulation only — no real orders |
| `broker/mt5_gateway.py` | YES — must not be called during development |
| `broker/deriv_gateway.py` | YES — must not be called during development |
| `execution/simulator.py` | No — backtest-only, no broker calls |
| `execution/trade_lifecycle.py` | Calls `OrderManager` + `PositionManager` — in-memory only |
