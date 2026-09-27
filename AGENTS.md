# AGENTS.md — JQE AI Development & Architecture Guide

This document is the authoritative developer and AI agent guide for the **JQE Quantitative Trading Platform**. The supported deployment is Weltrade synthetic indices through the local Windows MT5 terminal. The previous phase is committed at `d6d00e1`; the Weltrade-only migration is the current work. Read README.md and docs/weltrade-roadmap.md first.

---

## 1. Core Architecture & Layering

JQE follows a strict Clean Architecture pattern. The Quant Core is completely broker-agnostic.

```text
Quant Core -> BrokerGateway -> WeltradeGateway -> MetaTrader5 Python API -> local Weltrade MT5
```

### Layer Rules:
- **`config/`**: Validated Pydantic Settings (`JQE_` prefix).
- **`core/`**: Shared kernel (logging, exceptions, indicators). Never import broker SDKs into `core/`.
- **`broker/`**: `BrokerGateway` ABC + implementations. Only `broker/factory.py` constructs gateways.
- **`data/`**: `CandleStore` (SQLite) + `HistoricalDataService` (gap-filling & incremental cache).
- **`intelligence/`**: Feature engines, market regime detection, 6-factor `ConfidenceModel`.
- **`strategy/`**: Signal generation. `strategy/pipeline.py` is the canonical bridge.
- **`risk/`**: `RiskEngine` authorizes account-currency risk and typed broker quantities. Legacy raw-lot helpers are backtesting-only.
- **`execution/`**: pure execution policy and lifecycle invariants; `execution/simulator.py` remains backtest-only. Broker mutation stays behind `BrokerGateway`.

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

# Execute one configured Weltrade cycle (inspect execution gate first; not an unconditional dry-run)
& D:\JQE\venv\Scripts\python.exe main.py

# Execute historical backtest
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest
```

## 5. Weltrade-only product contract

- Weltrade is the only configurable/selectable broker; MT5 is its transport. Reject unsupported configured or persisted identities without silently falling back.
- New dashboard and research history must come from the Weltrade terminal and be stored under the Weltrade provider. Do not substitute Deriv history or generated prices.
- Only native Weltrade synthetic indices are in deployment scope. Validate symbols through `broker/weltrade_symbols.py` and the terminal catalogue. Never equate Deriv aliases with Weltrade contracts.
- The current gateway is demo-only. Preserve server/account verification, terminal ownership, pre-submit checks and durable recovery. This migration does not authorize real-account execution or new orders.
- Backtest simulation and fake test gateways are internal research/testing tools, not selectable brokers. Keep tests offline with explicit injected doubles; do not loosen production validation to satisfy old tests.
- MT5 contract economics determine account-currency sizing. Do not label simulation units, assumed tick values or inferred volume as verified Weltrade lots or exchange volume.
- Keep old broker evidence and databases intact. Legacy adapters may remain during migration; their presence does not imply supported deployment. Update or retire obsolete product paths deliberately with coverage.
- Never read/log secrets wholesale. Do not change `.env`, `.env.ai`, running terminals, execution gates or persisted safety state as a side effect of tests.
- Use `D:\JQE\venv\Scripts\python.exe -m pytest` if the pytest launcher cannot start. Frontend checks are `npm test` and `npm run build` in `frontend/`.

## 6. Research and product standards

- Professional/institutional quality is a target, not a claim of verified profitability. Current scope research has not demonstrated positive expectancy.
- Use provider-pinned immutable datasets, closed bars, chronological holdouts, walk-forward tests, explicit costs and uncertainty intervals. Preserve negative results and disclose sample sizes and parameter trials.
- All live strategies use the canonical pipeline. Specialized research scripts are experimental unless equivalence with the live path is proven.
- Present live connection, stale evidence, simulated outcomes and broker fills accurately in the UI. Surface actionable blocks and data provenance; never imply readiness from a green connection badge alone.
- Future commercial access is verified Weltrade partner registration OR a paid JQE licence. It is not implemented. Obtain actual partner/payment/verification details before implementing entitlements; no invented API or client-side bypass.
- Before claiming completion, run relevant tests, then the full backend suite and frontend tests/build. Record remaining failures honestly in the handoff. Never delete safety assertions to make a migration green.

## 7. Windows validation and health checks

- Use `core.processes.is_process_alive()` for process health. Never use
  `os.kill(pid, 0)` on Windows: signal zero is a console control event and can
  interrupt the application, pytest, and its parent runner.
- `venv\Scripts\python.exe tools/check_backend_groups.py` validates all backend
  modules in bounded offline groups, with temporary configured stores and blocked
  real MT5 calls. It preserves verbose logs, JUnit XML and totals in a fresh
  `reports/backend-*` directory. Inspect every group exit code, not only totals.
- Archived forensic integration tests require `JQE_ARCHIVED_FORENSICS_ROOT` and
  the complete immutable campaign/database fixtures. Never substitute current
  operator databases to make these tests pass.
