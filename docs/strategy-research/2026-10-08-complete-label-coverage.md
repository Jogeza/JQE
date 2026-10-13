# Complete training-label coverage

Recommendation: accept the registered campaign's coverage for subsequent causal
feature qualification. ML fitting and strategy promotion remain blocked. The
[saved-artifact audit](2026-10-08-complete-label-coverage-resumed.json) passed at
2026-10-08 18:15:21 UTC with zero errors and matching final source snapshot.

## Scope and completion

Weltrade **SFX Vol 99 / M5** only. Signal-bar window: September 8, 2026 00:00 UTC
inclusive through October 8, 2026 00:00 UTC exclusive. This is previously inspected
training history, not untouched out-of-sample evidence. One registered label design,
three fixed overlapping cost cases; zero ML fits or strategy candidates.

All 2,876 registered opportunities are accounted for: 2,833 eligible events and
43 predeclared censored events (24 gap, 19 partition boundary). Each eligible
event has exactly one completed label in each cost case: **8,499 / 8,499**.

| Fixed cost case | Executed return labels | Non-executable, null returns | Total |
|---|---:|---:|---:|
| Optimistic zero commission | 1,545 | 1,288 | 2,833 |
| Assumed USD 3 / lot / side | 1,186 | 1,647 | 2,833 |
| Double spread and commission | 607 | 2,226 | 2,833 |

The 3,338 executed event-cost observations overlap. They are not independent
samples or portfolio trades. Execution eligibility is conditional on fixed USD
50 capital, 1% risk and frozen native constraints. Rejections are not zero returns.
The positive-commission cases remain declared stresses, not verified tariffs.

## Interruption and source lineage

The original process stopped without a summary after 4,900 completed attempts;
its cause remains unknown. Those artifacts and ledger remain unchanged. The
[validated resume](2026-10-08-label-campaign-resume.md) generated 3,599 remaining
attempts into a new directory, including one explicitly disclosed unfinished-entry
retry. There were zero recorded FAILED entries; the interruption is retained.

The two source snapshots differ in three disclosed orchestration modules. The
canonical replay function body, strategy, risk, fill accounting, datasets, costs
and dependencies remained unchanged. Replay used only the canonical backtest CLI;
the completion auditor reads saved artifacts and does not generate signals.

## Coverage verification

The audit checked exact registered event/cost identities across both ledgers,
unique completions, summary/artifact agreement, retry transitions and all censors.
It checked registered input hashes, current source identity, preserved prior files
and lineage evidence. Executed labels have one trade, matching target signal,
next-bar entry, bounded exit and actual exit-bar-close availability within training.
Capital, quantity units, stop/entry/target ordering and net-USD/net-R arithmetic
passed. Non-executable labels have no trades, explicit reasons and null returns.

Artifacts are in `reports/counterfactual-campaign-resume-20261008-01/`: final
`summary.json`, `coverage-audit.json` and `executed-label-intervals.json`. Original
results remain in `reports/counterfactual-campaign-20261008-01/`. Compact artifacts
are not complete preimages of their referenced full result hashes; the audit binds
saved files and checks hash references, rather than reconstructing full results.

Validation for the resume implementation: ten focused checks passed; full backend
2,650 passed, four explicit opt-in skips and zero external network attempts.
Frontend 240 passed and production build passed with the existing size advisory.
No replay source changed during the resumed run.

## NOT proven

This does not establish positive expectancy, baseline improvement, OOS performance,
portfolio Sharpe/drawdown, universal fee terms, historical financing stability,
live-plan equivalence or ML readiness. No features were extracted, no model fitted
and no sealed holdout evaluated. Independent reset-account labels cannot substitute
for a stateful baseline/candidate comparison.

Next: freeze and validate causal feature semantics against the original canonical
indicator prefix and closed-bar availability before extraction. Use actual label
availability for purging and embargo. Longer qualified history, exact cost evidence
and a fresh chronological ML registration/holdout remain separate prerequisites.
