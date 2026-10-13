# Separate longer-history canonical label pilot

The new `--long-history-label-pilot REGISTRATION --output NEWDIR` command runs
through `python -m backtesting.backtest`. It consumes the unchanged frozen
all-symbol registration `754e420b1b5c18d8b384584643e3242a1fd364e2146529b52c90339fb6b3f9a8`.
The fixed selection is the first three eligible events chronologically for each
of ten symbols, with all three registered costs: 30 events and 90 attempts.
Selection is saved before any outcomes. This is an inspected past-TRAIN
implementation pilot, not portfolio performance or untouched OOS evidence.

`LongHistoryOpportunity` is a separate immutable contract. It binds event identity,
native symbol, full dataset hash and original July10 prefix, signal index/time,
direction/confidence, USD50/1% risk, unchanged execution assumptions and costs.
The complete contiguous i-3 through i+19 horizon must fit inside TRAIN; gaps fail
even if a hypothetical early exit precedes them. Only the target canonical signal
may queue. Mismatched signals fail before queueing; later entries and end-of-data
liquidation are forbidden. Existing SFX99-only restrictions remain intact.

Every registered input and archived baseline hash is checked. Dependencies and
canonical strategy/risk/indicator/accounting modules must match the completed
training source. The implementation separately records differences in
backtesting/backtest.py, the new backtesting/long_history_labels.py, the three
previously changed broker files and config/settings.py. These hashes are not
claimed equal. Current live split sizing/partial management is excluded from
research. The pilot archives 106 verified source files without environment files.

SDK initialization, login, shutdown, selection, order submission, historical reads
and profit/margin probes are blocked in the pilot process. Frozen bundle/spread
identity and chronology are checked; all outcomes use the canonical replay.
Complete result preimages and append-only STARTED/COMPLETED/FAILED records remain
in reports/long-history-label-pilot-20261009-01. Failures stop dispatch and remain
visible; this pilot does not implement automatic resume or full label dispatch.

Focused checks: 23 passed, including first-fill equivalence for all ten symbols
using explicit offline doubles, unchanged original SFX99 tests, event tampering,
altered capital/horizons/provider, mismatched signals and an after-early-exit gap.
Full backend: 2,742 passed, four explicit opt-in skips, zero external network
attempts. Frontend: 240 passed; build passed with the existing chunk-size warning.

The original 241,938-attempt campaign has not started. No features, ML fits,
candidate or holdout evaluation are authorized by this pilot. Historical fees,
financing/margin/calendar, effective 89.3056-day evaluation, dependent overlapping
labels and a fresh chronological ML registration/holdout remain qualification
limits. Next implement immutable resumable full dispatch and a complete coverage
audit after pilot qualification; never treat this bounded pilot as full coverage.

Completion: all 90 attempts finished with stable source, no failed replay attempts.
Saved-artifact audit reports PASS_PILOT_SAVED_ARTIFACTS, zero errors. Two executed
labels and 88 NON_EXECUTABLE dispositions retain their rejection reasons and null
returns. One executed pilot trade exactly matches the saved baseline's first fill;
the other independent event was position-blocked in the stateful baseline, so its
outcome is not a portfolio return or another baseline-fill equivalence claim.
The all-symbol synthetic first-fill tests supplement this limited observed match.

The independent audit checks each complete result hash preimage, all 90 distinct
event/cost pairs and ledger states, USD50/risk/execution/model/spread identities,
the original arithmetic indicator prefix and target regime, exactly one target
decision and at most one fill, actual exit/rejection-bar close availability, and
the 106-file source archive. It preserves overlapping event/cost observations;
these are not 90 independent training samples. Audit and per-label availability:
reports/long-history-label-pilot-audit-20261009-01/audit.json.

Audit script reports/audit-long-history-label-pilot-20261009.py is saved separately
from the replay source. Its first invocation lacked the repository import path;
that invocation/log was retained, the script path was corrected, and the subsequent
complete audit passed. It did not cause a replay retry or change replay artifacts.
No terminal, supervisor, service, execution gate, safety state or dotenv changes
were made during implementation or validation.
