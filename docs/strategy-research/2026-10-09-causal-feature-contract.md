# Causal feature semantics and prefix qualification

Recommendation: use the frozen eight-feature semantics for a subsequent canonical
training-only recorder. This step exports zero research feature rows and fits no
models. [Contract](2026-10-09-causal-feature-contract.json) and
[checksum](2026-10-09-causal-feature-contract.sha256.json) freeze formulas, timing,
scope, source identity and label lineage before extraction.

Scope is unchanged: Weltrade SFX Vol 99/M5; previously inspected training signal
bars September 8 00:00 through October 8 00:00 UTC, half-open. All 2,876 registered
events must remain represented, including 43 censors and cost-specific null
rejections. Three cost cases share one feature row per event; they are not
independent examples. One feature contract, zero model configurations evaluated.

## Exact formulas

Here i is the signal bar and A is its canonical ATR. All values become available
at signal-bar close (opening timestamp plus five minutes).

| Feature | Formula |
|---|---|
| rsi | Canonical RSI[i] |
| ema_distance_atr | (close[i] − EMA50[i]) / A |
| ema_slope_atr | (EMA50[i] − EMA50[i−1]) / A |
| atr_price_ratio | A / close[i] |
| return_1_atr | (close[i] − close[i−1]) / A |
| return_3_atr | (close[i] − close[i−3]) / A |
| range_atr | (high[i] − low[i]) / A |
| lagged_spread_atr | Recorded spread_points[i] × point / A |

Returns here are price differences scaled by ATR, not percentage returns. EMA
slope uses one bar; neither directions nor outcomes determine a feature's sign.
Spread is lagged relative to next-bar entry i+1, not relative to the signal bar.
Its historical sidecar is a conditional fill proxy, not a verified contemporaneous
tradable quote. Require the original same-response timestamp/OHLC/manifest binding.
Never substitute the strategy's unknown-spread fallback as recorded broker cost.

## Implemented semantics and evidence

`research/causal_features.py` is experimental pure feature computation, not a
signal path, labeler, trainer or exporter. It selects raw bars through i before
calling the existing canonical indicator function. It ignores supplied indicator
columns and requires an explicit original-prefix start, at least 200 warmup bars,
strict timestamps, valid positive OHLC, contiguous three-bar return history,
positive ATR and finite recorded spread with the exact signal-bar timestamp.
The caller still must verify provider, dataset hash, prefix identity and spread
binding. A timestamp argument alone is not provenance verification.

The original complete indicator prefix matters: EMA recursion starts at the
original baseline dataset_start, while volatility/regime classifications also
use prefix means. Do not reset these calculations at each opportunity. No signal
generation is added here; any recorder must remain inside canonical backtest
dispatch and use generate_trading_signal for decisions.

Nine focused tests passed, covering future-price perturbation, poisoned indicator
columns, prefix equivalence, shortened history, invalid/future spread and gaps.
Fixtures are synthetic offline test data, never Weltrade research evidence.
A separate saved-indicator audit compared all **8,832** original rows against
canonical indicators recomputed from the verified immutable original dataset
prefix: **PASS, zero mismatches**. Evidence: `reports/causal-prefix-audit-20261009.json`.
This verifies indicators, not full signal/fill or feature-export equivalence.

Full validation: backend **2,659 passed**, four explicit opt-in skips, zero
external network attempts; frontend **240 passed**, production build passed
with the existing bundle-size advisory. Logs are `reports/causal-feature-tests-20261009.txt`,
`reports/causal-feature-frontend-tests-20261009.txt` and
`reports/causal-feature-frontend-build-20261009.txt`. Frozen source/input checksum
verification and diff whitespace checks passed. Safety assertions remain intact.

Missing/invalid input must preserve the registered event with explicit unavailable
features. No global imputation, forward-looking fill, clipping or scaling occurs.
Future fills, entry gaps, MAE/MFE, exits and returns are forbidden entry features.
Any later scaling/imputation must be fitted inside chronological training folds.
Actual executed-label close times drive purging/embargo; cost overlaps and
non-executable labels retain their identities and null outcomes.

## NOT proven and next work

No complete feature dataset, canonical feature recorder equivalence, model fit,
positive OOS expectancy, baseline improvement or deployment readiness is proven.
The completed label audit remains an immutable historical source identity; adding
this helper creates a new feature source snapshot, not replacement label hashes.
Historical tariffs/financing, longer history and a fresh ML holdout remain open.
The original EMA50 validation/test partitions remain sealed.

Next implement a training-only recorder through `python -m backtesting.backtest`,
bind every event to its original prefix and sidecar, and prove feature timing and
signal identity before exporting into NEW files. Do not rerun label outcomes or
fit ML merely because the feature formulas have been frozen.
