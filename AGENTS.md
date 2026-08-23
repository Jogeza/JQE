# AGENTS.md — JQE AI Development & Architecture Guide

This document is the authoritative developer and AI agent guide for the **JQE Quantitative Trading Platform**. It reflects the verified state of the codebase as of `phase5-foundation`.

---

## 1. Core Architecture & Layering

JQE follows a strict Clean Architecture pattern. The Quant Core is completely broker-agnostic.

```
                    ┌────────────────────────┐
                    │    config / settings   │
                    └───────────┬────────────┘
                                │
                    ┌───────────▼────────────┐
                    │       Quant Core       │
                    │   strategy / risk /    │
                    │ intelligence / data /  │
                    │       execution        │
                    └───────────┬────────────┘
                                │ depends only on
                    ┌───────────▼────────────┐
                    │  broker.BrokerGateway  │ (async interface)
                    └───────────┬────────────┘
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│SimulationGateway │  │   DerivGateway   │  │    MT5Gateway    │
│(in-memory mock)  │  │(async WebSocket) │  │ (sync SDK shim)  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Layer Rules:
- **`config/`**: Validated Pydantic Settings (`JQE_` prefix).
- **`core/`**: Shared kernel (logging, exceptions, indicators). Never import broker SDKs into `core/`.
- **`broker/`**: `BrokerGateway` ABC + implementations. Only `broker/factory.py` constructs gateways.
- **`data/`**: `CandleStore` (SQLite) + `HistoricalDataService` (gap-filling & incremental cache).
- **`intelligence/`**: Feature engines, market regime detection, 6-factor `ConfidenceModel`.
- **`strategy/`**: Signal generation. `strategy/pipeline.py` is the canonical bridge.
- **`risk/`**: `RiskEngine` + `PositionSizing` (dynamic position sizing, limits, capital protection).
- **`execution/`**: `TradeLifecycle` (invariant enforcement) and `Simulator` (backtest engine).

---

## 2. Canonical Entry Points

### 2.1 Live Cycle — `main.py`
The single canonical live execution path is:
```text
main.py:run()
  1. gateway = get_gateway(settings) [async with gateway]
  2. gateway.get_candles(symbol, timeframe, count)
  3. validate_market_data(df)
  4. calculate_indicators(df)
  5. detect_regime(df)
  6. generate_trading_signal(df, symbol, regime)
  7. account = gateway.get_account_info()
  8. approve_trade(signal, df, balance=account.balance)
  9. calculate_stop_target(close, ATR, signal) -> OrderRequest
 10. gateway.submit_order(order)
```

### 2.2 Backtest Cycle — `backtesting/backtest.py`
Replays historical data through the identical signal and risk pipeline via `BacktestEngine`.

---

## 3. Key Invariants & Pitfalls for AI Coding Agents

1. **Strategy Bridge is Mandatory:**
   - Always route signal generation through `strategy.pipeline.generate_trading_signal()`.
   - Direct calls to `SignalEngine` will drop signals because of indicator naming and regime vocabulary translation requirements.
2. **Trade Lifecycle Invariants:**
   - BUY: `stop_loss < entry < take_profit`
   - SELL: `take_profit < entry < stop_loss`
   - Any violation is immediately rejected by `TradeLifecycle`.
3. **Dead-Code Caution:**
   - `core.engine.JQEEngine`, `core.market_scanner.MarketScanner`, and `core.decision_pipeline.DecisionPipeline` are legacy dead-code paths. Do NOT build live logic on top of them.
4. **Environment Execution:**
   - Always run Python commands and tests via `D:\JQE\venv\Scripts\python.exe` and `D:\JQE\venv\Scripts\pytest.exe`.

---

## 4. Development & Testing Workflow

```powershell
# Run the complete test suite
& D:\JQE\venv\Scripts\pytest.exe

# Execute a live dry-run (simulation broker)
& D:\JQE\venv\Scripts\python.exe main.py

# Execute historical backtest
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest
```
