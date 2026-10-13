# Offline accounting correction — 2026-10-08

Status: all 30 corrected canonical training replays completed in `reports/entry-training-20261008-02`, without source/dependency drift. This is an accounting correction following [the model review](2026-10-08-model-review.md), not a strategy search. The original 30-case campaign remains immutable.

## Frozen scope

Model identity changes from `frozen-weltrade-cfd-v1` to `frozen-weltrade-cfd-v2`. Canonical strategy v2, ten native Weltrade symbols, September 8–October 8 half-open UTC training window, 200 warmup bars, USD 50 per independent symbol, 1% risk, existing 1.5/3 ATR stop/target, 19-bar limit and all three declared cost cases remain identical. No candidate is implemented; validation and final test remain sealed. The new replay protocol and append-only trial ledger bind source, dependencies and outcomes before and during evaluation.

Corrections:

1. Validate BUY SL/TP against the bid opening quote and SELL SL/TP against opening ask proxy, using final tick-rounded protective prices. Fill slippage no longer distorts the minimum-stop check.
2. Compute combined stop-plus-exit-slippage loss at its adverse tick-rounded executable price before cent rounding. Add fees and the existing financing reserve, retaining lot-step flooring and rejecting minimum lots that exceed the original unrounded budget.
3. Use the same adverse tick-rounded exit price function for sizing, closing and bar-close liquidation marks.

The existing signal bridge remains `strategy.pipeline.generate_trading_signal()`. No live execution code, gate, terminal, environment file, persisted safety state or existing dataset is modified by these corrections or replays.

## Regression coverage

Five new cases cover both BUY/SELL quote-side stop rejection, BUY/SELL liquidation-mark equality with immediate close on a fractional-tick quote, and the USD 0.318 combined-loss counterexample including exact USD 0.32 acceptance. Existing tests and assertions remain intact. Focused suite: 15 passed, zero external network attempts. Full backend: 2,609 passed, four explicit live/archive opt-in skips, zero external network attempts. Frontend: 238 tests passed; production build passed with its existing large-chunk warning. No assertions were weakened or removed.

## NOT proven

Even a corrected replay remains conditional training evidence. Exact commission, historical financing calendar/rates and executable historical bid/ask quotes are unverified; live-plan equivalence and untouched OOS performance remain unproven. No accounting correction authorizes candidate adoption or live execution.



## Original versus corrected training results

All nine previously non-trading symbols still have zero trades at all three costs. Their expectancy and trade statistics remain undefined; zero exposure/drawdown is retained. Only SFX Vol 99 has an executed sample, exclusively TRENDING. This comparison is an accounting correction on training data, not a tested strategy improvement or portfolio result.

| Metric | Original zero fee | Corrected zero fee | Original assumed fee | Corrected assumed fee | Original double costs | Corrected double costs |
|---|---:|---:|---:|---:|---:|---:|
| Trades | 279 | 266 | 175 | 164 | 72 | 69 |
| Expectancy, modeled USD/trade | -0.01158 | -0.00842 | -0.05709 | -0.05287 | -0.12444 | -0.10696 |
| Expectancy, net R/trade | -0.02331 | -0.01318 | -0.23442 | -0.20808 | -0.55216 | -0.46119 |
| Profit factor | 0.93849 | 0.95455 | 0.70540 | 0.72744 | 0.43470 | 0.49898 |
| Win rate % | 35.842 | 36.466 | 35.429 | 35.976 | 30.556 | 33.333 |
| Net modeled USD | -3.23 | -2.24 | -9.99 | -8.67 | -8.96 | -7.38 |

Corrected training 95% three-day block-bootstrap intervals for mean R: zero fee [-0.20949, 0.14229], assumed fee [-0.40674, -0.05646], doubled costs [-0.87683, -0.22124]. Resampling remains 10,000 draws with seed 20261008. No interval is OOS evidence. Different eligible trade sets and balances require these full replays; no old trades were selectively removed to manufacture corrected metrics.

[All corrected metrics](2026-10-08-accounting-correction-evidence/summary.json), [append-only trial ledger](2026-10-08-accounting-correction-evidence/trials.jsonl), [source-bound protocol](2026-10-08-accounting-correction-evidence/training-replay-protocol.json), and [full artifact hashes](2026-10-08-accounting-correction-evidence/artifact-hashes.json) are preserved. All 30 detailed per-symbol metric files are beside them; full canonical results remain in the ignored report directory.

## Corrected SFX Vol 99 detailed metrics

| Cost | Avg win USD | Avg loss USD | Max close-equity DD USD | DD % at max cash DD | Bar Sharpe | Bar Sortino | Exposure upper bound % | MAE R p10/p50/p90 | MFE R p10/p50/p90 | Holding min p10/p50/p90 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| optimistic_zero_commission | 0.48495 | -0.29160 | 10.40 | 19.604 | -0.00286 | -0.00418 | 24.317 | 0.190/1.067/1.836 | 0.000/0.710/2.385 | 10/30/95 |
| assumed_3usd_per_lot_per_side | 0.39220 | -0.30295 | 9.86 | 19.311 | -0.01936 | -0.02696 | 14.977 | 0.168/1.061/1.752 | 0.018/0.902/2.428 | 10/30/95 |
| double_spread_commission | 0.31957 | -0.32022 | 7.68 | 15.326 | -0.02568 | -0.03400 | 7.083 | 0.325/1.045/1.883 | 0.021/1.312/2.389 | 15/35/95 |

Sharpe/Sortino remain unannualized M5-bar measures. MAE/MFE and holding/exposure are whole-bar upper bounds, not tick-resolved excursions. Marked drawdown uses executable bar-close liquidation equity. Verified historical account-currency expectancy remains unavailable; USD values are explicitly conditional modeled amounts.

## Artifact-level correction check

The [saved-artifact audit](2026-10-08-accounting-correction-audit.json) checks all 30 results for model version 2, joins accepted trades to exact frozen entry-bar opening bid/lagged spread, and verifies both protective distances. It independently reconstructs canonical ATR from the identical warmup/training candles to check combined tick-rounded stop/slippage P/L plus fees and financing reserve against each trade's original unrounded cash-risk budget. Across 499 overlapping cost-case trade observations: **zero stop violations, zero planned cash-risk violations**. Gap losses can still exceed planned risk; this does not assert gap protection or actual broker fills.

## Fee research and recommendation

The concurrent [fee/financing reconciliation](2026-10-08-fee-financing-reconciliation.md) closes the observed ledger residual and three ordinary overnight charges, corroborates all ten current annual-rate magnitudes and the current legal midnight-server-time basis. Zero fee is the best-supported observed-demo interpretation; the positive fee cases are stress assumptions. Public conflicts, unobserved six-symbol fees, historical changes and Friday/weekend semantics remain unverified. No frozen cost case was relabeled or changed during replay.

Recommendation: no adoption; negative training expectancy in every cost case, one traded symbol/regime, no candidate or OOS comparison. The accounting correction is complete within its declared scope. Next work: resolve the remaining external fee/calendar contradiction using the concrete broker-clarification draft or future independently obtained written terms; preserve sealed holdouts and do not tune around these negative results. There is no local code fix that supplies missing historical tariff evidence.

