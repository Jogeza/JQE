# Frontend and read-only MT5 reliability

The owner authorized frontend/read-only MT5 reliability work followed by the
registered training-only label campaign. Demo-only identity, gates, account/server,
orders and persisted safety state remain outside this reliability change.

Research history acquisition polling now waits for each response before scheduling
the next request, pauses while the browser tab is hidden and stops after terminal
job state or cleanup. A slow request cannot accumulate overlapping one-second
polls. This does not cancel or change a server-side acquisition already running.

Weltrade contract-specification observation now requests the exact native symbol
in a worker thread rather than using a synchronous resolver that could select a
Market Watch symbol. Missing contracts fail explicitly; no provider alias fallback
was introduced. This change is limited to the specification reader; other existing
gateway paths have not been certified mutation-free by this work.

Frontend tests initially failed because the new polling test lacked a browser test
environment. The fixture now explicitly uses happy-dom and known visibility state;
all 240 frontend tests and the build pass. Eight focused backend specification/
single-opportunity checks passed. Full backend validation is recorded separately
when it completes. No test assertion was deleted to obtain these results.

The identified backend was restarted to load the observation change under the
owner's expanded process authorization; `/health` returned HTTP 200. Vite loads
frontend changes without a process restart. MT5 was not restarted, logged into by
this validation, switched or reconfigured. Existing dashboard polling remains its
own observation activity, separate from offline research.

## Registered label campaign

Started through `D:\JQE\venv\Scripts\python.exe -m backtesting.backtest
--counterfactual-campaign` against the unchanged registration and frozen input
hashes. Artifacts are in `reports/counterfactual-campaign-20261008-01`.
The pre-run plan includes all 2,833 eligible events and three fixed cost cases:
8,499 attempts. All 43 predeclared censored events are retained separately.

Each replay regenerates its target through the canonical signal bridge, checks
the saved direction/confidence, preserves the full original indicator prefix and
uses unchanged risk/fill logic. Terminal SDK calls are forbidden. Every attempt
has STARTED/COMPLETED/FAILED ledger entries; source drift is checked within each
replay and every 25 events. Full-run output retains compact trade/decision/label
evidence and complete-result hashes rather than duplicating indicator arrays.
Compact files explicitly are not full result-hash preimages.

This dispatcher stops on a failure; automatic resume is not implemented. Completed
immutable attempt files and the ledger remain available for a separately validated
resume design. Do not overwrite them or silently discard failures. Campaign
completion requires all 8,499 attempts and final source/coverage audits, not merely
process startup. The first-three-event pilot remains separate evidence.

## NOT proven and next work

No strategy improvement, OOS edge, ML readiness or sustained terminal reliability
is proven by UI changes or campaign startup. No ML model or new candidate was fitted;
sealed holdouts remain untouched. Next: finish the running training-label campaign,
audit every status and availability interval, then qualify features and longer
history before any separately registered ML fit.

Validation completed: full backend 2,646 passed, four explicit opt-in skips, zero
external network attempts; frontend 240 passed/build passed, existing bundle-size
advisory retained. At this handoff the full campaign remains RUNNING, with 78
completed attempts, one in progress and zero recorded failures of 8,499 planned.
No final summary exists yet. These counts are a progress snapshot, not completion
or a performance report. The active canonical command is managed as session 97044.
