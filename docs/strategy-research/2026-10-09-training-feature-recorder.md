# Canonical training-only feature recorder

Result: corrected recording complete; [saved-row coverage audit](2026-10-09-training-feature-audit.json)
**PASS**. All 2,876 registered event identities are preserved. Of these, 2,870
have finite eight-feature rows and six have explicit unavailable features from
three-bar history gaps. All **2,833 eligible labelled events have features**;
the six unavailable rows are gap-censored. All 24 gap and 19 boundary censors
remain present, regardless of whether entry-time features are available.

The export is `reports/training-features-20261009-02/features.json`; final
`summary.json`, `coverage-audit.json` and `implementation-plan.json` bind coverage,
availability, input hashes and separate source identities. No economic outcomes
were rerun. Status text copied from the immutable original registration still
says eligible/not-yet-labelled; it is a pre-outcome disposition, not a claim that
the completed separate label campaign is missing.

The full frozen candle bundle was reloaded and content-verified after recording;
`post-recording-data-check.json` retains its content/CSV hashes. This is a post-run
recheck, not continuous filesystem monitoring. Saved-row audit confirms unique
identities, exact close-time availability, finite allowlisted features, preserved
censor dispositions, final source/input hashes and zero eligible missing rows.

The recorder is dispatched only through `python -m backtesting.backtest
--record-training-features CONTRACT --output NEWDIR`. It observes canonical
generate_trading_signal decisions inside run_backtest with the original retained
indicator prefix. Feature-only mode forbids economic models/single-opportunity
replay, does not process or queue trades, and returns no performance result.
Normal backtests retain their existing economic processing.

## Scope and verification

Frozen scope: Weltrade SFX Vol 99/M5; training signal bars September 8 00:00 UTC
inclusive through October 8 00:00 UTC exclusive. One frozen eight-feature design;
zero model fits, candidate trials or holdout evaluations. Previous training history
was inspected; this is not untouched OOS evidence.

Before recording, verify the feature contract/checksum, completed label-audit
hash and summary hash, label registration/event hashes, all registered inputs,
native provider/symbol/timeframe, closed bars, original dataset prefix and content
hash. Recorded spreads must match acquisition checksum/content identity, exact
bar timestamps, row count, nonnegative integer points and frozen point size.
The acquisition code captured spreads from the historical-service SDK response
and checked OHLC correspondence; this recorder verifies that preserved evidence,
not an independent historical executable bid/ask path.

At each registered signal, require matching original direction/confidence,
canonical reason prefix and saved EMA50/EMA200/RSI/ATR observations. Stateful
portfolio/risk reasons remain distinct. Extra/missing/duplicate events or changed
source/input hashes fail the recording. No direct SignalEngine calls are added.
One feature row per event, not three repeated cost rows. Preserve censored events
and any unavailable features with explicit reasons; no imputation or scaling.
Labels remain in separate immutable files and are not entry features.

## Failed attempt retained

`reports/training-features-20261009-01` failed before export because its original
comparison incorrectly required the entire baseline reason list to equal signal
reasons. BacktestEngine.queue_signal appends occupancy/risk reasons. The correction
requires exact canonical reason prefix plus direction/confidence; it does not
remove an assertion about signals or change strategy. A regression test verifies
that mismatched canonical reasons/directions still fail. The failed directory and
log remain intact; the corrected attempt uses a new directory.

## NOT proven and next work

Validation: 23 initial focused checks passed, then nine recorder checks passed
after the reason-prefix regression. Initial backend run: 2,667 passed/four opt-in
skips; final source run: **2,668 passed/four opt-in skips**, zero external network
attempts. Frontend **240 passed**, production build passed with existing bundle-size
advisory. Logs: `reports/feature-recorder-final-tests-20261009.txt`,
`reports/feature-recorder-frontend-tests-20261009.txt` and
`reports/feature-recorder-frontend-build-20261009.txt`. Safety assertions unchanged.

No model has been fitted, candidate evaluated or positive OOS expectancy shown.
Feature observation is not a new portfolio simulation. All fee/financing, longer
qualified history and fresh chronological ML registration/holdout requirements
remain. Original EMA50 holdouts remain sealed. New recorder source hashes are
disclosed separately from frozen feature semantics and historical label sources.

Next qualify event-level feature/label joins and actual-availability purge rules,
then extend qualified history through HistoricalDataService into new immutable
files. Do not convert coverage counts into independent sample size or use this
training export as a reason to fit before the remaining gates are met.
