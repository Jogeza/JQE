# Canonical engine test — 5 October 2026

The engine passed functional tests, but this historical screen did **not**
demonstrate profitable execution. No candidate was promoted, no broker order
was submitted, and the demo supervisor and persisted safety halt were preserved.

## Test and evidence

`tools/audit_engine_expectancy.py` reads Weltrade provider rows through read-only
SQLite, freezes each dataset to a JSON artifact with a canonical hash, rejects
short/disconnected fragments, and uses closed bars only. It evaluated all 14
existing watchlist pairs: 35,098 candles in total, with 3,000 M1 bars and 2,014
M5 bars per pair. M5 history was shortened to a contiguous segment rather than
filling cache gaps. Dataset dates and hashes are in each result artifact.

Signals go through `strategy.pipeline.generate_trading_signal`, with canonical
indicators and regime detection. The shared `BacktestEngine` handles next-bar
entry, risk screening, stop/target collision ordering and realized outcomes.
Each independent simulated account starts at 100 simulation currency units,
with 0.5% risk and a confidence floor of 75. Stop/target distances are the current
defaults of 1.5 ATR and 3 ATR, respectively. No live settings were changed.

The protocol was written before evaluation. After 200 warmup candles, the
remaining bars were split chronologically 60% development, 20% validation,
20% final test. The baseline and confidence thresholds 80 and 85 were compared
in development and validation; selection was locked before final testing.
Qualification required at least 30 validation trades and a positive lower
95% moving-block-bootstrap confidence bound. No variant qualified. Baseline
final-test results are below; R is the simulated account risk at entry.

| Pair | Final-test trades | Mean net R | 95% interval |
| --- | ---: | ---: | --- |
| FX Vol 20 M1 | 9 | -0.082 | -1.000 to +0.950 |
| FX Vol 20 M5 | 13 | +0.198 | -0.421 to +0.817 |
| FX Vol 40 M1 | 17 | -0.237 | -0.590 to +0.063 |
| FX Vol 40 M5 | 4 | -0.568 | -1.000 to -0.137 |
| FX Vol 60 M1 | 7 | -0.031 | -1.000 to +1.255 |
| FX Vol 60 M5 | 16 | +0.429 | -0.112 to +1.013 |
| FX Vol 80 M1 | 9 | -0.372 | -0.898 to +0.193 |
| FX Vol 80 M5 | 8 | -0.338 | -0.872 to +0.444 |
| FX Vol 99 M1 | 18 | -0.452 | -0.884 to +0.070 |
| FX Vol 99 M5 | 16 | +0.024 | -0.487 to +0.537 |
| SFX Vol 20 M1 | 0 | unavailable | insufficient trades |
| SFX Vol 20 M5 | 0 | unavailable | insufficient trades |
| SFX Vol 99 M1 | 19 | +0.017 | -0.415 to +0.463 |
| SFX Vol 99 M5 | 11 | -0.138 | -0.683 to +0.407 |

There were 147 final-test trades across independent pair replays: four positive
point estimates, eight negative estimates, and two pairs without trades. No
positive estimate has a lower uncertainty bound above zero. These small samples
do not establish a strategy edge. Summing the independent account results would
not represent a shared live portfolio.

## Costs and limits on interpretation

The run used the stored September contract spread survey, half-spread entry
slippage and a separate double-spread stress scenario. These are explicitly
historical sensitivity assumptions. Commission and observed exit slippage are
not established by this test. It uses simulation quantities, not verified
Weltrade lot sizing, minimum-lot feasibility, margin or broker P&L. Account
currency results must not be inferred from its simulated returns.

Other limitations: realized-balance rather than mark-to-market drawdown;
trigger-price gap fills; stop-first OHLC collision ordering; default 19-bar
timeout; expanding indicator history versus live rolling 500 bars; and no
shared position/daily-limit portfolio model. The cache was previously explored,
so its chronological final partition is not a pristine untouched holdout.
The protocol discloses three threshold trials per pair, 42 comparisons overall;
intervals are descriptive and not adjusted for those comparisons. No interval
alone authorizes live promotion.

## Findings for further improvement

Trade confidence currently comes from the legacy feature score (maximum 80),
while the computed six-factor confidence breakdown is recorded separately.
A threshold of 85 therefore blocks every trade, and a threshold of 80 does
not improve the existing eligible trade population in this screen. Changing
the authoritative score is a substantive strategy change requiring a frozen
new experiment, tests and fresh evaluation; it was not silently switched here.

Momentum also labels RSI above 60 as STRONG regardless of trend direction,
while RSI below 40 is WEAK. The signal engine requires STRONG momentum for
both BUY and SELL. Directional momentum alignment needs a separately defined
experiment, rather than tuning it against these final-test outcomes.

The older MTF research script assumes a two-ATR stop; today's default canonical
trade plan uses 1.5 ATR. Older specialized script results are not evidence of
equivalence to the live path. Broker-sized, gap-aware, rolling-window replay
with current contract economics and fresh forward data is required before a
profitable-execution claim can be defended. Existing risk limits must remain
in place even if that prevents a minimum-lot trade.

## Reproduction

Use the repository venv and a fresh output directory:

```powershell
& D:\JQE\venv\Scripts\python.exe -m tools.audit_engine_expectancy --output reports/engine-expectancy-new-run
```

Frozen protocol, datasets and results: `reports/engine-expectancy-20261005`.
Functional engine checks: 165 passed in `reports/engine-focused-20261005`.
Frontend tests: 172 passed; production build passed with the existing size warning.
Full backend suite: 2,527 passed, four skipped; all 18 group exit codes zero
(`reports/backend-engine-20261005/totals.json`). Research code hashes were saved
in `reports/engine-expectancy-20261005/code-provenance.json`.
