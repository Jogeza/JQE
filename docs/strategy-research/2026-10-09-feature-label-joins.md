# Training feature–label joins and purge qualification

Result: **PASS_TRAINING_JOIN_NOT_ML_READY**. One frozen join/purge configuration;
zero fitted models, performance evaluations or holdout reads. Saved evidence was
qualified through the canonical backtest CLI without signal or economic replay:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --qualify-feature-label-joins reports/feature-label-joins-20261009-01
```

Scope remains Weltrade SFX Vol 99/M5, September 8 00:00 through October 8 00:00 UTC
half-open. This inspected training history does not become OOS by splitting it.
New output contains protocol/input/source hashes, `joined-events.json`,
`purge-diagnostics.json` and final `summary.json`. Previous labels/features remain
immutable with their original separate source identities.

## Complete joins

All **2,876 unique events** are retained, with one feature vector per event and
three nested cost dispositions. Exact registered event identities, directions,
signal times and censor statuses match. Existing audit, feature/summary/plan and
registration hashes were checked, including source/input stability during joining.

The [saved join/purge audit](2026-10-09-feature-label-join-audit.json) independently
checked saved hashes and strict grouped boundary membership: PASS, zero errors.
There are **1,545 distinct events with any executed label**, not 3,338 independent
executed examples. Dependence between nearby events remains unquantified.

| Event–cost disposition | Count | Meaning |
|---|---:|---|
| Executed | 3,338 | Finite conditional USD/R labels with actual availability |
| Non-executable | 5,161 | Null return with explicit canonical rejection reason |
| Censored | 129 | 43 registered events × three cases; null return |
| Total | 8,628 | 2,876 events × three cases; overlapping observations |

Censored dispositions are carried forward, not newly calculated returns. Every
eligible event has all three cost labels. Missing/extra/duplicate identities,
future or incomplete feature vectors, nonfinite returns, unexplained rejects and
labels crossing train end fail closed. Null outcomes are never coerced to zeros.
The join preserves unavailable features for six gap-censored events.

## Actual-availability purge diagnostics

Two expanding splits and a **95-minute embargo** were fixed in the output protocol
before joining. They are engineering diagnostics, not an ML registration, tuned
embargo or strategy validation. Train begins September 8; times below are UTC and
evaluation windows are half-open. Training requires decision and label availability
strictly before evaluation start minus embargo. Evaluation labels must resolve
strictly before its right boundary; equality is excluded.

Each event's executed cost cases remain grouped by their latest actual label
availability. This conservatively prevents one cost sibling resolving into a
different partition. Null/censored outcomes stay in the join but have no invented
return-fit membership or artificial label end.

| Diagnostic window | Unique train events | Unique evaluation events | Zero-fee train/eval | Assumed-fee train/eval | Double-cost train/eval |
|---|---:|---:|---:|---:|---:|
| September 22–29 | 992 | 510 | 992 / 510 | 653 / 502 | 261 / 341 |
| September 29–October 8 | 1,528 | 12 | 1,528 / 12 | 1,169 / 12 | 604 / 1 |

Counts are executable conditional labels, not independent portfolio trades or
performance. Later training overlaps earlier evaluation because these are
expanding inspected-training diagnostics. The late window's 12 executable events
(one at doubled costs) reveals thin chronological coverage under frozen economics;
do not move boundaries, raise capital/risk or delete affordability rejections to
manufacture adequacy. No return averages or model selection were computed.

Twenty-six focused join/governance checks passed. Tests cover duplicate/missing
cost joins, exact-time boundaries, future features, nonfinite returns, null reject
preservation and conservative cost-sibling purging. Existing safety assertions
remain unchanged.

Full validation: backend **2,678 passed**, four explicit opt-in skips, zero external
network attempts; frontend **240 passed**, production build passed with existing
bundle-size advisory. Logs: `reports/feature-label-join-tests-20261009.txt`,
`reports/feature-label-join-frontend-tests-20261009.txt` and
`reports/feature-label-join-frontend-build-20261009.txt`. Diff whitespace check passed.

## NOT proven and next work

No positive OOS expectancy, baseline improvement, effective independent sample
size, sufficient chronological/regime coverage, exact historical tariff/calendar,
ML inference equivalence or readiness is established. Grouped cost cases are not
additional independent events. Fitting only executable labels would estimate a
conditional target and still needs a registered treatment of feasibility/selection.

Next inventory and qualify longer native historical-service coverage, then register
new immutable acquisition files if needed. The existing 41.7-day source history
does not meet the project's 90-day readiness floor; that floor is not a statistical
guarantee. Keep exact cost/financing reconciliation and a fresh independent ML
registration/holdout as separate unresolved gates. No fitting or original EMA50
holdout inspection is authorized by this qualification.
