# JQE Institutional Architecture & Meta Model (AI) Integration Roadmap

This document is the authoritative engineering roadmap and architectural specification for evolving JQE into an institutional-grade quantitative trading platform, including the decoupled integration of Meta AI / Llama models into the JQE intelligence layer.

---

## Part 1: Institutional Engineering Blueprint & Architecture

An institutional quantitative system is governed by four immutable principles:
1. **Mathematical & Statistical Rigor**: Elimination of data snooping, survivorship bias, and lookahead leakage via out-of-sample holdouts and Deflated Sharpe Ratio metrics.
2. **Microstructure & Cost Realism**: Accounting for variable spreads, slippage models, tick granularity, and execution latency budgets.
3. **Fail-Closed Risk & Execution Sovereignty**: Independent, deterministic pre-trade risk checks and automated reconciliation that cannot be bypassed.
4. **Data Provenance & Auditability**: Every signal, trade plan, and execution fill is cryptographically traceable to immutable source bars.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Market Data Layer (UTC)                         │
│   MT5 Terminal (Weltrade SyntX) -> UTC Normalization -> CandleStore    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Bounded, Immutable Closed Bars
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Deterministic Quant Core                         │
│  Indicators -> Regime Detection -> SignalEngine -> Confidence (6-Fac)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Validated Trading Signal
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Risk & Execution Policy                         │
│  RiskEngine (Account-Currency Max Loss) -> Fail-Closed ExecutionPolicy │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Verified OrderRequest
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         Broker Gateway ABC                             │
│       WeltradeGateway (Pre-flight Checks, Demo Guard, Ticket Tracking) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Part 2: Meta Model API (Llama) Integration Specification

### 1. Non-Negotiable Invariants
* **Zero Direct Execution Authority**: Meta models (Llama 3 / Meta Model API) must **never** sit in the critical path of `order_send()`, `TradePlanBuilder`, or risk authorization.
* **Fail-Closed Decoupling**: If the LLM provider times out, returns an error, or hallucinates, the trading engine continues unaffected or gracefully falls back to deterministic rule sets.
* **Zero Secret Leakage**: Prompts sent to external or local model endpoints must be strictly sanitized; no account numbers, API credentials, or internal secrets may ever leave the host.

### 2. Architecture & Service Flow

```text
                               ┌─────────────────────────┐
                               │   JQE Telemetry Stream  │
                               │ (JSON State, Signals,   │
                               │  Risk Authorization)   │
                               └────────────┬────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        JQE AI Assistant Service                        │
│                   (api/v1/assistant/chat & diagnostics)                │
│                                                                        │
│   Prompt Templating Engine:                                            │
│   - Grounding on canonical decision explanations                       │
│   - Injecting regime state, factor scores, risk limits                 │
│                                                                        │
│   Model Layer:                                                         │
│   - Meta Model API (Llama 3.1 / 3.3 via OpenAI-compatible endpoints)    │
│   - Anthropic Claude / OpenAI-compatible / Local Ollama runtimes       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Operator Intelligence UI                          │
│  - Natural-language explanation of NO_TRADE / BLOCKED decisions        │
│  - Daily risk & regime post-mortem digest                              │
│  - Research parameter sensitivity summary                              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Roadmap Implementation Status & Next Phases

### Status Summary Table

| Phase | Component | Focus Area | Status | Deliverables & Artifacts |
|---|---|---|:---:|---|
| **Phase 1** | **Meta Model API** | JQE AI Supervisory Layer | **COMPLETE** | `jqe_ai/client.py`, `jqe_ai/service.py`, `tests/test_jqe_ai_meta_client.py` |
| **Phase 2** | **OOS Research** | Out-of-Sample Partitioning | **COMPLETE** | `research/runner.py`, `tools/run_research_batch.py`, `state/research_batch_results.json` (34 paired runs) |
| **Phase 3** | **Overfitting Analytics**| DSR & Multiple-Testing | **COMPLETE** | `analytics/overfitting.py`, `tests/test_overfitting_analytics.py` (9 passing tests) |
| **Phase 4** | **Execution Realism** | Volatility Parity & Slippage | **COMPLETE** | `backtesting/models.py` (2 ATR-fraction fields), `backtesting/engine.py` (_enter ATR-cost path), `tests/test_phase4_volatility_parity.py` (8 passing tests) |
| **Phase 5** | **Continuous Audit** | Live Terminal Reconciliation | **COMPLETE** | `execution/continuous_reconciliation.py`, `tests/test_continuous_terminal_reconciliation.py` (13 passing tests) |
| **Phase 6** | **Combinatorial CV** | Advanced Regime Partitioning | **COMPLETE** | `research/cpcv.py`, `analytics/pbo.py`, `tests/test_cpcv_and_pbo.py` (17 passing tests) |

---

### Detailed Phase Milestones

#### Phase 1: Meta Model API Integration (Completed)
- **Delivered**:
  - Implemented `MetaModelClient` in `jqe_ai/client.py` using standard-library async HTTP execution via `urllib.request` and `asyncio.to_thread` (zero wheel dependency conflicts).
  - Configured `ai_assistant_provider: Literal["anthropic", "meta", "openai_compatible"]` with privacy-safe settings (`meta_api_key`, `meta_api_base`).
  - Implemented sanitized error classification (`META_AUTH_FAILED`, `META_RATE_LIMITED`, `ASSISTANT_TIMEOUT`).
  - Validated with 5 targeted unit tests and full suite regression.

#### Phase 2: Out-of-Sample Holdout Research Pipeline (Completed)
- **Delivered**:
  - Updated `research/runner.py` to support `TRAIN`, `VALIDATION`, `OOS`, and `FULL` partitions cleanly.
  - Invariant preservation: `TRAIN` partition receives isolated 60% training bars with independent dataset hashing; `OOS` partition evaluates strictly on `[start_index, end_index)` while retaining prior historical bars for indicator warmup (EMA200, ATR14) without lookahead bias.
  - Batch runner (`tools/run_research_batch.py`) executed across all 17 Weltrade watchlist symbols (M1 & M5).
  - 34 paired experiments persisted in `data/experiments/` and summarized in `state/research_batch_results.json`.

#### Phase 3: Deflated Sharpe Ratio & Overfitting Analytics (Completed)
- **Delivered**:
  - Implemented `analytics/overfitting.py` based on Bailey & Lopez de Prado (2014) and Harvey & Liu (2014):
    - `calculate_return_moments`: Sample mean, standard deviation, skewness, and Pearson kurtosis.
    - `calculate_sharpe_ratio`: Annualized Sharpe ratio with configurable risk-free rate.
    - `expected_max_sharpe`: Extreme-value-theory approximation of expected maximum Sharpe under $N$ multiple trials.
    - `deflated_sharpe_ratio`: Deflated Sharpe Ratio adjusting for selection bias, skewness, kurtosis, and sample length.
    - `calculate_haircut_sharpe`: Harvey-Liu haircut discount factor based on trial count and correlation.
    - `calculate_partition_degradation`: Automated detection of profit reversal, win rate collapse, and drawdown expansion.
  - Validated with 9 dedicated unit tests in `tests/test_overfitting_analytics.py`.

#### Phase 4: Volatility Parity & Microstructure Cost Realism (Completed)
- **Delivered**:
  - Added `adverse_slippage_atr_fraction` and `spread_atr_fraction` to `BacktestExecutionAssumptions` in `backtesting/models.py`.
    - Both default to `0.0` (full backward compatibility – zero regressions across all prior tests).
    - Both are validated: must be finite and non-negative.
  - Refactored `BacktestEngine._enter()` in `backtesting/engine.py`:
    - Total adverse fill cost = `fixed_spread + fixed_slippage + ATR × (spread_atr_fraction + adverse_slippage_atr_fraction)`.
    - ATR-scaled component grows proportionally with instrument volatility, automatically making fills more expensive on high-ATR candles.
    - The existing `authorize_execution_quantity(broker="simulation")` call already performs inverse-ATR sizing (cash risk ÷ stop_distance = units), so volatility parity sizing is achieved implicitly — no separate sizing formula needed.
    - Rejection audit log now includes `atr_adverse` and `fixed_adverse` diagnostics for traceability.
  - Validated with **8 new passing tests** in `tests/test_phase4_volatility_parity.py`:
    - Model validation (defaults, valid values, negative/NaN rejection).
    - Fill-price arithmetic (BUY entry is costlier by exactly `ATR × fraction_sum`).
    - Volatility parity (same `$risk_cash` within 1% across 5× ATR difference).
    - PnL impact (costs reduce net balance relative to zero-cost baseline).

#### Phase 5: Automated Real-time MT5 Terminal Reconciliation (Completed)
- **Delivered**:
  - Implemented `TerminalReconciliationAuditor` in `execution/continuous_reconciliation.py`:
    - Evaluates live broker positions from `gateway.get_positions()` against internal `TradePlan`s, `PositionLedger`, and `IntentRecordStore`.
    - Detects untracked broker positions (external manual trades placed outside JQE).
    - Detects foreign MT5 magic numbers (divergent sub-systems or manual intervention).
    - Detects position volume mismatches (e.g. partial manual closure on terminal).
    - Detects symbol or side divergences.
    - Detects phantom internal positions (ledger claims active trade, broker is empty).
    - Handles broker disconnections and malformed broker DTOs fail-closed.
  - Implemented `ContinuousTerminalReconciliationService`:
    - Dedicated periodic background monitoring loop (`run_loop`).
    - Fail-closed circuit breaker (`reconcile_and_protect`): immediately latches `settings.emergency_stop = EmergencyStopState.ACTIVE`, disables order execution (`settings.broker_execution_enabled = False`), publishes durable `ExecutionSafetySnapshot` with `ExecutionAuthorization.BLOCKED`, and executes notification callback.
  - Validated with **13 new unit and integration tests** in `tests/test_continuous_terminal_reconciliation.py`.

#### Phase 6: Combinatorial Purged Cross-Validation (CPCV) & PBO (Completed)
- **Delivered**:
  - Implemented `research/cpcv.py`:
    - `CPCVConfig`: Configures contiguous block division ($N$), test combinations ($k$), informational purging window, and post-test serial correlation embargo.
    - `partition_groups`: Deterministic division of history into $N$ non-overlapping groups with timestamp validation.
    - `generate_cpcv_splits`: Exhaustive combinatorial generation of $\binom{N}{k}$ paths with strict information isolation:
      - Purges training observations preceding test start.
      - Embargoes training observations following test end to prevent autoregressive leakage.
      - Guarantees `train_indices` and `test_indices` are strictly disjoint.
  - Implemented `analytics/pbo.py`:
    - `calculate_pbo`: Non-parametric Probability of Backtest Overfitting (PBO) across multiple strategy configurations and CPCV splits based on Bailey et al. (2016).
    - Calculates relative rank distribution ($\omega_c$), logit distribution ($\lambda_c$), degradation frequency ($\omega_c \le 0.5$), and categorized overfit risk level (`LOW`, `MODERATE`, `HIGH`, `SEVERE`).
    - `calculate_single_model_cpcv_stability`: Evaluates OOS profit reversal rate and performance retention ratio for individual strategies across CPCV splits.
  - Validated with **17 new unit tests** in `tests/test_cpcv_and_pbo.py`.

