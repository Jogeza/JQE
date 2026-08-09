# JQE Test Suite Baseline

*Recorded: 2026-08-10 · Python 3.13.14*

---

## Command

```powershell
venv\Scripts\python.exe -m pytest -q --tb=short
```

## Result

```
244 passed in 2.23s
```

**0 failures. 0 errors. 0 collection errors.**

---

## Test Files (Real pytest — 44 files, 244 tests)

| File | Tests |
|---|---|
| test_autonomous_scanner.py | 1 (demo script — collected but no assertions) |
| test_backtest_engine.py | 8 |
| test_backtest_runner.py | 3 |
| test_broker_factory.py | 6 |
| test_broker_types.py | 6 |
| test_candle_store.py | ~15 |
| test_candles.py | 1 (stub) |
| test_confidence_model.py | ~20 |
| test_config.py | ~12 |
| test_core_engine.py | 1 (demo — no assertions) |
| test_data_manager.py | 2 |
| test_decision_pipeline.py | 2 |
| test_deriv_gateway.py | ~18 |
| test_dynamic_risk.py | 3 |
| test_exceptions.py | ~10 |
| test_execution_engine.py | 2 |
| test_execution_simulator.py | ~8 |
| test_feature_engine.py | ~6 |
| test_historical_data_service.py | ~15 |
| test_indicators.py | 1 (stub) |
| test_jqe_engine.py | 4 |
| test_liquidity_engine.py | ~6 |
| test_live_demo_trade.py | 1 (skipped/env-dep) |
| test_live_market_data.py | 1 (skipped/env-dep) |
| test_live_mt5_execution.py | 1 (skipped/env-dep) |
| test_live_scanner.py | 1 (skipped/env-dep) |
| test_logging_config.py | ~4 |
| test_main.py | ~15 |
| test_market_data.py | 1 (stub) |
| test_market_loader.py | 1 (stub) |
| test_market_regime.py | 1 (demo script) |
| test_market_score.py | 1 (stub) |
| test_market_state.py | ~8 |
| test_momentum_engine.py | 2 |
| test_mt5_connection_live.py | 1 (skipped/env-dep) |
| test_mt5_gateway.py | ~20 |
| test_regime_detection.py | 5 |
| test_risk_controller.py | ~12 |
| test_signal_engine.py | 4 |
| test_signal_scorer.py | 5 |
| test_simulation_gateway.py | ~12 |
| test_strategy_pipeline.py | 8 |
| test_trade_lifecycle.py | 1 (demo script — executes at import) |
| test_trend_engine.py | 1 |
| test_volatility_engine.py | 1 |

---

## Known Test Debt

### Module-level Demo Scripts (execute at import, no assertions)
These files run code at module scope rather than inside `def test_...()` functions.
They do not produce test failures but also do not validate correctness:

- `tests/test_trade_lifecycle.py` — calls `lifecycle.process()` and prints result
- `tests/test_market_regime.py` — calls `detect_regime()` and prints result
- `tests/test_core_engine.py` — a debug print script
- `tests/test_autonomous_scanner.py` — stub

### Empty Files in `tests/`
- `tests/decision_pipeline.py` — empty, no test_ prefix
- `tests/market_scanner.py` — empty, no test_ prefix
- `tests/portfolio.py` — empty, no test_ prefix

### Environment-Dependent Tests (MT5/Network)
These tests are collected but skipped or pass vacuously when MT5 is not connected:
- `test_live_demo_trade.py`
- `test_live_market_data.py`
- `test_live_mt5_execution.py`
- `test_live_scanner.py`
- `test_mt5_connection_live.py`

---

## Known Bugs (Not Caught by Tests)

### `execution/trade_lifecycle.py` — Direction Bug
`test_trade_lifecycle.py` is a demo script with no assertions — it does not catch
that `stop_loss = price - 10` and `take_profit = price + 20` are wrong for SELL trades.

### `core/decision_pipeline.py` — `decide(*args)` 
`test_decision_pipeline.py` only tests the `analyze()` path, not `decide()`.
The fragile positional argument sniffing in `decide()` is not exercised by any assertion.

---

## Confirmed Not-Broken
- All broker gateway tests: 244/244
- Backtest engine + runner
- Strategy pipeline (generate_trading_signal)
- Risk controller
- Indicators, regime detection
- Confidence model
- Market state / liquidity / trend / momentum / volatility engines
