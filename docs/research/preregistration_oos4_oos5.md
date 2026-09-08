# Pre-Registration Specification: Out-of-Sample Market Structure Validation (OOS_4 & OOS_5)

**Document ID:** `PREREG-PHASE6-MS-001`
**Registration Date:** 2026-09-07T11:25:00Z
**Author:** Quantitative Trading Core / JQE Platform
**Target Symbol:** `XAUUSD`
**Timeframe:** `M15`
**Execution Variant:** `CONFIRMED_SELL_ONLY`

---

## 1. Context and Problem Statement

In the initial Phase 6 exploratory research over 5,704 M15 candles (BASELINE, OOS_1, OOS_2, OOS_3), `CONFIRMED_SELL_ONLY` under conservative simulation friction ($0.50 spread, $0.25 slippage) produced an aggregate loss across 148 trades (Net -$3.32, Expectancy -$0.0225/trade, Profit Factor 0.92).

While OOS_1 (+$0.46) and OOS_2 (+$0.39) exhibited net positive expectancy, OOS_3 suffered severe degradation (-$3.63, 16.3% take-profit conversion). Feature separation analysis revealed that pre-entry downward momentum was a consistent differentiator between winning and losing trades. Specifically, trades entering when `previous_16_bar_return` was below its sample median (-0.004131) yielded higher expectancy across all three exploratory out-of-sample windows.

To establish whether this candidate metric represents a genuine market structure regime edge rather than in-sample curve fitting, this protocol freezes all parameters and registers evaluation criteria prior to acquiring or evaluating fresh historical data.

---

## 2. Frozen Hypothesis

### 2.1 Primary Hypothesis ($H_1$)
On unseen, out-of-sample historical M15 data for XAUUSD, filtering `CONFIRMED_SELL_ONLY` trade entries by:
$$\text{previous\_16\_bar\_return} \le -0.004131241773602634$$
will generate:
1. **Positive net expectancy** ($E > 0.0$) after conservative simulation costs ($0.50 spread + $0.25 slippage) in both validation windows independently.
2. **Profit Factor $\ge 1.05$** under conservative simulation costs.
3. **Superior performance relative to the unfiltered baseline** and the upper split ($\text{previous\_16\_bar\_return} > -0.004131$).

### 2.2 Null Hypothesis ($H_0$)
The filtered slice fails to generate positive net expectancy under conservative costs ($E \le 0.0$) or fails to outperform in one or more validation windows, indicating the exploratory effect was driven by window-specific sample variance.

---

## 3. Strict Chronology & Information Boundary

All trades and indicators must adhere to the verified Phase 6 no-look-ahead chronology:

```text
Candle i closes       -> Signal generated if indicators meet trend-continuation rules.
Candle i+1 closes     -> Confirmation evaluated: regime must remain TREND_DOWN.
                         Feature candle: close, ATR, RSI, EMAs, and previous_16_bar_return
                         are computed strictly from candle i+1 and preceding closed bars.
Candle i+2 opens      -> Entry executed at candle[i+2].open if filter passes.
```

- **Feature Computation**:
  $$\text{previous\_16\_bar\_return} = \frac{\text{close}_{i+1}}{\text{close}_{i+1-16}} - 1.0$$
- **Invariant**: $T_{\text{feature}} < T_{\text{entry}}$ strictly holds for every evaluated trade.

---

## 4. Frozen System Parameters (Zero Retuning Allowed)

No parameters, thresholds, or multipliers may be adjusted during or after evaluation:

| Parameter | Frozen Value | Notes |
| :--- | :--- | :--- |
| **Fast EMA** | `50` | Exponential moving average on close |
| **Slow EMA** | `200` | Exponential moving average on close |
| **RSI Period** | `14` | Relative Strength Index on close |
| **ATR Period** | `14` | Average True Range |
| **Confirmation Condition** | `TREND_DOWN` on bar $i+1$ | Evaluated at bar $i+1$ close |
| **Stop Loss Multiple** | `1.5` $\times$ ATR | Measured from entry price |
| **Take Profit Multiple** | `3.0` $\times$ ATR | Measured from entry price |
| **Max Holding Period** | `19` candles | 285 minutes; exit on bar 19 close |
| **Collision Policy** | `STOP_LOSS_WINS` | Conservative same-candle priority |
| **Gap Fill Policy** | `AT_TRIGGER_PRICE` | Trigger price fill |
| **Conservative Spread** | `$0.50` | Per trade |
| **Conservative Slippage** | `$0.25` | Per trade |
| **Fixed Fee** | `$0.00` | Per trade |
| **Starting Balance** | `$50.00` | Per window evaluation |
| **Risk Limit** | `1.0%` of account balance | Fixed account fraction authorization |
| **Candidate Threshold** | `$\le -0.004131241773602634$` | Frozen median split |

---

## 5. Targeted Validation Windows

The validation datasets are defined as non-overlapping historical intervals entirely preceding the exploratory baseline and OOS_1–3 windows:

1. **Window OOS_4**:
   - Start: `2026-01-15T00:00:00Z`
   - End: `2026-03-01T00:00:00Z`
   - Target Interval: 45 calendar days (~3,000 M15 candles)
2. **Window OOS_5**:
   - Start: `2025-11-01T00:00:00Z`
   - End: `2025-12-15T00:00:00Z`
   - Target Interval: 45 calendar days (~3,000 M15 candles)

---

## 6. Pre-Registered Pass / Fail Criteria

To be considered a **STABLE_REGIME_EDGE**, the candidate must pass ALL of the following criteria:

- [ ] **Criterion 1 (Net Expectancy)**: Filtered net expectancy $> \$0.00$ per trade under conservative costs in OOS_4 and OOS_5 individually.
- [ ] **Criterion 2 (Profit Factor)**: Filtered profit factor $\ge 1.05$ under conservative costs in both windows.
- [ ] **Criterion 3 (Directional Separation)**: Low-split expectancy exceeds high-split expectancy in both windows ($E_{\text{low}} > E_{\text{high}}$).
- [ ] **Criterion 4 (Sample Sufficiency)**: At least 20 filtered trades generated per window.
- [ ] **Criterion 5 (Risk Compliance)**: Max realized loss $\le 1.0\%$ of equity on every single trade; no balance drawdowns below $\$40.00$.

If any criterion fails, the hypothesis is deemed **REJECTED** or **INCONCLUSIVE**, and the candidate rule will NOT be promoted to production.
