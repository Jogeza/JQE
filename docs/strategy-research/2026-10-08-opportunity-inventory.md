# Canonical opportunity coverage and history inventory

Training window: 2026-09-08 00:00 UTC inclusive to 2026-10-08 00:00 UTC exclusive.
This is an extraction of saved corrected canonical backtest results, not a new
performance experiment. No signals were regenerated, models fitted, parameters
tuned, or validation/test partitions read. Existing baseline metrics remain in
[the accounting report](2026-10-08-accounting-correction.md).

The extractor checks canonical result hashes, provider/timeframe, unique signal
observations, indicator-to-decision coverage, trade-to-signal matching and label
availability. Next-bar EXECUTION_REJECTED events are not extra signal opportunities.
Decision availability is signal bar open plus five minutes; executed-label
availability is exit bar open plus five minutes. No counterfactual result is
invented for rejected or unfilled signals. Features are not yet exported.

| Coverage | Count |
|---|---:|
| Canonical signal-close observations, ten symbols | 86,320 |
| BUY/SELL opportunities | 27,459 |
| Executed baseline labels | 266 |
| Unlabelled opportunities | 27,193 |
| SFX Vol 99 opportunities | 2,876 |
| SFX Vol 99 position-blocked opportunities | 1,322 |

All executed labels belong to SFX Vol 99 in the optimistic zero-commission case.
QUEUED does not mean executed: subsequent minimum-stop, quantity and margin checks
can reject entry. Cost cases overlap and must not be pooled as independent labels.
Executed-only labels cover 0.97% of all opportunities; this is an explicit
state-selection problem, not evidence that the remaining signals would earn money.

Machine-readable [coverage and source hashes](2026-10-08-opportunity-inventory.json)
accompany the full JSONL in `reports/opportunity-inventory-20261008-02`.
Extraction is available through the canonical entry point:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --opportunity-inventory reports/entry-training-20261008-02 --inventory-campaign reports/entry-campaign-20261008-04 --output reports/opportunity-inventory-20261008-02
```

## History limits

The ten campaign manifests each contain 12,000 M5 bars from August 27 11:20 UTC
through October 8 04:15 UTC, about 41.7 calendar days. Only the frozen 30-day train
partition was used above. These are simultaneous markets, not 417 independent
calendar days. The known six gaps per series remain; no prices were filled.

The [existing-bundle metadata inventory](2026-10-08-history-inventory.json)
contains 34 manifests, each spanning at most 1.74 days. Seventeen fail the simple
last-bar-closed-at-retrieval check. Manifest metadata alone neither verifies
content nor resolves old timestamp errors; these bundles are not promoted or used
for labels. Existing provenance qualification remains authoritative. No immutable
dataset was edited, and no terminal connection was made for this work.

## Recommendation and next work

Keep ML fitting blocked. Next implement a narrowly scoped canonical training-only
counterfactual replay protocol for the executable SFX Vol 99 opportunities,
retaining minimum-lot, risk, margin and cost constraints. Define how independent
opportunity labels differ from stateful strategy P&L before writing the labeler;
the final filtered strategy must still be tested as one stateful canonical replay.
Acquire any additional history only through HistoricalDataService into new files,
then qualify it. Freeze a separate ML holdout before fitting the proposed single
linear model. The existing EMA50 holdouts remain sealed.

## NOT proven

No counterfactual labels, full causal feature dataset, new ML model, baseline
improvement, positive OOS expectancy, verified universal fee/calendar, 90-day
training history, or live plan equivalence has been established. The extraction
does not itself authorize a strategy change or execution.

Validation: full backend run 2,630 passed, four explicit opt-in skips and zero
external network attempts. The final added coverage guard was subsequently
checked in the focused extractor suite: six passed. Frontend: 238 passed;
production build passed with its existing bundle-size advisory. Diff check passed.
