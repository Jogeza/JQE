# Immutable resumable all-symbol label dispatch

The separate full dispatcher is implemented through the canonical backtest CLI.
The frozen registration and 90-attempt pilot/source archive are unchanged. No full
campaign has been launched in this step; no new labels, features, ML fits,
candidates or holdout evaluations were generated.

The workspace already contained prepared full-dispatch/resume modules when this
continuation began. They were reviewed and validated rather than duplicated.
The complete coverage audit was strengthened to require the last segment's final
summary and exact agreement with every verified completion. A ledger containing
all expected pairs alone cannot establish clean campaign completion.

## Fixed scope and storage

All 80,646 eligible events across ten native symbols and three fixed overlapping
cost cases are dispatched: 241,938 planned attempts. All 1,033 registered censors
remain separate (3,099 cost dispositions). Original full indicator prefixes,
USD50/1% per-event risk, frozen v2 accounting and target-only canonical signals
remain unchanged. Live partial management is excluded. Independent labels are
not stateful portfolio returns or independent samples.

Each NEW segment saves a separate implementation identity, source archive,
resume evidence, censor list and fsynced append-only trial ledger. Complete result
preimages are stored as exclusively created gzip JSON with deterministic gzip
timestamps; result and artifact hashes are bound to completions. Compression does
not replace full-prefix verification. Source/input changes reject dispatch.

A shared OS lock rejects concurrent full dispatch and is released by process loss.
Resume only accepts full segments with the same registration, complete selection,
source/dependencies and verified archives. Pilot reuse is forbidden. Prior owner
processes must be absent. Every ancestor must be supplied explicitly. Completed
pairs are verified and reused; unfinished STARTED attempts remain disclosed and
may be retried only into a NEW segment. Recorded failures reject automatic resume
and require diagnosis. Prior files are never rewritten.

## Canonical commands

Use a fresh, unused output directory. Before launch, check existing campaign
processes/ledgers, source stability, disk capacity and preserved result size; the
241,938 full-prefix results have not yet been timed or storage-budgeted at scale.
Do not claim this test suite establishes large-campaign runtime or capacity.

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --long-history-label-campaign reports/long-history-label-registration-20261009-01 --output reports/long-history-label-campaign-20261009-01

# Only after the original owner is absent; append every ancestor segment.
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --long-history-label-campaign reports/long-history-label-registration-20261009-01 --resume-long-labels-from reports/long-history-label-campaign-20261009-01 --output reports/long-history-label-campaign-resume-20261009-01

# After final summary; supply every original/resumed segment.
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --audit-long-history-labels reports/long-history-label-registration-20261009-01 --resume-long-labels-from reports/long-history-label-campaign-20261009-01 --output reports/long-history-label-coverage-20261009-01
```

The coverage audit verifies every expected distinct pair, complete result preimage,
capital/risk/cost/model/data identities, target decision, original arithmetic
prefix, actual exit/rejection-bar close availability and null rejects. Exact final
summary/ledger agreement and all registered censors are mandatory. No partial
coverage may unlock feature extraction or ML.

## NOT proven and next work

Full coverage, production-scale dispatch endurance, storage sufficiency, OOS edge,
positive expectancy, verified historical fees/margin/financing/calendar, causal
features for this expanded prefix, sufficient independent events and a fresh ML
holdout remain unproven. No terminal, process, execution gate, safety state or
dotenv changes were made. Negative training findings and original holdouts remain
intact.

Next: inventory capacity using preserved pilot results, then launch the registered
full training-only campaign once source is stable. Finish all attempts and obtain
a PASS complete audit before causal feature extraction. Keep all ML gates closed.

Capacity inventory now blocks launch with the current layout. Ninety preserved
pilot JSON results compress to 1,161,434–1,208,962 bytes (median 1,181,453.5).
Median extrapolation to 241,938 attempts is 285,838,496,883 bytes (about 286 GB),
versus 80,480,124,928 free bytes observed on D:. This is an early-pilot estimate,
not a full-campaign measurement or guaranteed lower bound. Evidence is saved at
`reports/long-history-label-capacity-20261009-01.json`. No launch occurred.
Next is hash-verifiable storage that shares immutable data while reconstructing
the complete result preimage, or sufficient additional capacity. Do not silently
drop full-result evidence or use compact labels as its hash preimage.

Focused validation: 42 passed, zero network attempts. It includes all-symbol
first-fill tests, unchanged SFX99 restrictions, exclusive artifacts, lock recovery,
interrupted dispatch/new-directory resume, tampering, active owners, failed and
duplicate attempts, pilot/source mismatch, actual null/exit availability, and
missing/altered/duplicate final summaries. Full-suite results are recorded below
after completion.

Final validation: backend 2,761 passed/four explicit opt-in skips, zero external
network attempts; frontend 240 passed and build passed with the existing large
chunk warning. Logs are `reports/long-history-full-label-focused-20261009-01.txt`,
`reports/long-history-full-label-backend-20261009-01.txt`,
`reports/long-history-full-label-frontend-20261009-01.txt` and
`reports/long-history-full-label-build-20261009-01.txt`. No assertions were removed.
