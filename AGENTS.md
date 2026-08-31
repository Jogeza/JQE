# AGENTS.md — JQE AI Development & Architecture Guide

This document is the authoritative developer and AI agent guide for the **JQE Quantitative Trading Platform**. It reflects the verified execution architecture at the start of `phase6-execution`.

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
- **`risk/`**: `RiskEngine` authorizes account-currency risk and typed broker quantities. Legacy raw-lot helpers are backtesting-only.
- **`execution/`**: pure execution policy and lifecycle invariants; `Simulator` remains backtest-only. Broker mutation stays behind `BrokerGateway`.

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
  8. reconcile broker trade history; approve_trade(..., enforce_limits=True)
  9. TradePlanBuilder.build(...) and plan.is_valid()
 10. construct OrderRequest from the valid plan
 11. gateway.submit_order(order)
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
   - The live path currently rejects violations through `TradePlan.is_valid()`.
   - `TradeLifecycle` enforces the same relationship in its isolated legacy path but is not yet wired into `main.py`.
3. **Dead-Code Caution:**
   - `core.engine.JQEEngine`, `core.market_scanner.MarketScanner`, and `core.decision_pipeline.DecisionPipeline` are legacy dead-code paths. Do NOT build live logic on top of them.
4. **Environment Execution:**
   - Always run Python commands and tests via `D:\JQE\venv\Scripts\python.exe` and `D:\JQE\venv\Scripts\pytest.exe`.

5. **Phase 6 Execution Policy:**
   - `execution.policy.ExecutionPolicy` is a pure, fail-closed authorization policy. It must not construct/connect gateways, submit orders, or own authoritative position state.
   - Emergency stop blocks every new submission.
   - Upstream risk approval must be explicitly `True`.
   - Missing or unreadable safety state rejects execution.
   - Open-position limits reject at or above the configured limit.
   - Any existing position for the same symbol blocks another order; hedging and pyramiding remain undesigned.
   - Reused idempotency keys reject.
   - Broker-reported positions and history remain the source of truth.
   - The synchronous legacy `OrderManager` has been removed. Do not recreate an execution boundary outside `main.py` or `execution.executor.AsyncTradeExecutor`.

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
