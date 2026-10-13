# Exact source-transition evidence before resume

The serialization implementation now has representative canonical replay evidence:
the two executed saved-pilot examples and the first rejected example all match
their complete golden payloads after only disclosed source identity and dependent
fingerprint adjustment. Result preimages and fingerprints are validated separately.
The campaign remains stopped at53 completions/one unfinished attempt. This step
does **not** enable mixed-source resume or claim completion/ML readiness.

## Fixed diagnostic scope and honest failures

The selection is every executed example from the90-attempt inspected pilot (two)
and the first chronological pilot file with a null rejection (one). Three attempts
are frozen before replay; no trade-return threshold or parameter search is used.
All run through `python -m backtesting.backtest`, canonical signal generation,
original full prefix and frozen costs/risk. Terminal operations are blocked.
These are diagnostic replays, not new campaign completion labels or independent
portfolio trades. Zero strategy parameter configurations changed; zero ML fits.

First attempt `reports/source-transition-replays-20261010-01` failed because the
agent edited qualification source during replay. The source-drift guard rejected
it correctly; log/artifacts are preserved and excluded from proof. This violated
the required stable-source workflow; it was corrected by finishing edits before
the NEW-directory rerun. No result from that failed attempt is promoted.

Stable rerun `reports/source-transition-replays-20261010-02/audit.json`:
PASS_FIXED_EXECUTED_NULL_CANONICAL_EQUIVALENCE_NOT_RESUME_AUTHORIZATION,
three attempts/two executed/one null/zero errors. Selection, complete results,
profiles and verified source archive are retained. There are six planned diagnostic
attempt slots across the failed and stable runs; the failed run did not finish its
budget. Existing pilot results, original53 and holdouts are unchanged.
Specifically, the first run saved one example summary, rejected the second replay
on drift and never reached the third. None of that run is accepted as the final
stable proof. The rerun completed all three, so five actual diagnostic replay
invocations occurred across the two runs (four completed, one rejected).

## Exact reviewed changes and inherited evidence

Compared to the original full-campaign source archive, only three existing files
change: `backtesting/models.py` uses a single normalized snapshot for serialization;
`backtesting/long_history_labels.py` reuses the serialized result hash;
`backtesting/backtest.py` adds qualification CLI commands. Existing canonical
function/class ASTs remain identical. Added modules are profiling, serializer
qualification and source-transition evidence helpers. Dependencies and every
other source file must match the old archive.

The verifier checks exact serializer/dispatcher edits and required file identities,
then archives the current source and validates all53 original completions against
their own old snapshot, original complete result hashes and shared-object/file
hashes. The unfinished STARTED attempt remains explicitly disclosed. The new
archive and original archive are separate; hashes are never claimed equal.

A focused test initially found a missing-file `KeyError`; the implementation was
corrected to explicitly reject removed files. The failure and unchanged test are
retained. Final focused40 passed/zero external network attempts. Tests reject
extra/removed files, strategy/serializer/dispatcher changes and canonical replay
function changes. The corrected evidence verifier differs from the stable replay
snapshot only in `backtesting/source_transition.py`; that difference and both
archives are bound explicitly. Replay functions/serializer must still match.

The evidence command is:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --qualify-long-label-source-transition reports/long-history-label-registration-20261009-01 --output reports/source-transition-evidence-20261010-01
```

Its contract is evidence-only (`resume_enabled=false`). The existing same-source
loader remains unchanged and rejects mixing old/new source. Next integrate the
exact hashed contract into NEW-segment resume and final coverage lineage, with
tests for tampered contracts/proofs, wrong ancestors, active owners and mixed
results. Full dispatch must not start until that integration is qualified.

## NOT proven

Three inspected examples and90 serializer goldens do not prove universal behavior,
full coverage, sustained fast throughput, OOS edge or positive expectancy. Native
historical fees/margin/financing/calendar and fresh chronological ML registration/
holdout requirements remain unresolved. No features, model fits, new strategy
candidate, live execution, terminal/service/gate/safety/dotenv changes occurred.

Evidence-command completion and final full-suite figures are recorded below.

Exact contract completion:
`reports/source-transition-evidence-20261010-01/contract.json` reports
PASS_EXACT_TRANSITION_EVIDENCE_NOT_RESUME_ENABLED,53 inherited completions and
one disclosed interruption. Its file checksum sidecar, all evidence hashes and
current source binding were independently verified. The reviewed diff and new
source archive are retained in that directory. Contract/source checks do not
constitute a cryptographic proof of universal trading behavior; they restrict the
specific reviewed transition. No mixed-source loader modification was made.

Initial full backend run:one failure (the missing-file KeyError),2,790 passed/four
explicit opt-in skips. Its logs remain at
`reports/source-transition-backend-20261010-01.txt`. It began before the correction
and is not final corrected-source validation. Corrected focused40 passed;
frontend240 passed/build passed (existing chunk warning). Final corrected full
backend rerun is recorded after completion. Logs:
`reports/source-transition-focused-20261010-01.txt` (failure),
`reports/source-transition-focused-20261010-02.txt` (pass),
`reports/source-transition-frontend-20261010-01.txt` and
`reports/source-transition-build-20261010-01.txt`.

Final corrected-source backend:2,791 passed/four explicit opt-in skips, zero
external network attempts,154.62 seconds; log
`reports/source-transition-backend-20261010-02.txt`. Relevant focused40 and
frontend240/build passed. No safety assertions removed. Recommendation: accept
the exact transition evidence for implementing guarded lineage; do not treat it
as resume-enabled until that integration and its adversarial tests are complete.
