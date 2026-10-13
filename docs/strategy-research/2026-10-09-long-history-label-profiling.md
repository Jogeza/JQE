# Authorized campaign stop and canonical profiling

The owner explicitly authorized **stopping only the offline research campaign for
profiling** after the early throughput projection indicated weeks if sustained.
Verified command lines identified launcher19044/worker16240; only those processes
were stopped. MT5, live services, gates, safety state and dotenv were untouched.
The watcher exited normally with STOPPED_WITHOUT_SUMMARY; it never restarted.

The original directory remains immutable: **53 COMPLETED, one unfinished STARTED,
zero recorded FAILED, no final summary**. A stopped saved-artifact audit passed
all53 completed pairs, including full preimages/shared objects, source archive,
canonical original prefix/regime, target identities, ledger states and null
rejection availability. All53 were NON_EXECUTABLE/null labels. Evidence:
`reports/long-history-full-label-stopped-audit-20261009-01.json` and log; verified
process identities at `reports/long-history-label-authorized-stop-20261009-01.json`.
This intentional stop is disclosed; it is not unexplained process loss.

## Fixed profiling budget and observed costs

One read-only saved-verification profile produced no replay or new label. It took
2.73 seconds with profiler overhead, mostly repeated `_normalize`/canonical JSON
hashing. This is not a measured attribution of the whole campaign's runtime.
Evidence: `reports/saved-label-verification-profile-20261009-01`.

A separate canonical command profiled **one fixed diagnostic replay**, the first
eligible SFX99 event at zero commission. Selection/one-attempt budget/source
snapshot were saved before replay; no parameter configuration was changed.

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --profile-long-label-attempt reports/long-history-label-registration-20261009-01 --output reports/long-history-label-replay-profile-20261009-01
```

It retained the complete original prefix, USD50/1% risk, fixed costs and target
canonical signal. Terminal calls were blocked. The profiled target was
NON_EXECUTABLE (zero trades). All result fields matched saved pilot084 after
restoring only the original source snapshot and recomputing its dependent
fingerprint; native new-source result/preimage remains saved separately. This
limited diagnostic is not evidence of general acceleration, OOS or new labels
for campaign completion. The source used by the profile was copied and verified
in its own `source-archive` before subsequent verifier changes.

| Measured component | Cumulative profiled seconds | Scope |
|---|---:|---|
| Canonical runner plus result serialization | 11.50 wall | Excludes dataset load and dispatcher storage |
| `BacktestResult.to_dict` | 6.38 | Within above, complete normalized payload/serialization |
| `run_backtest` | 5.13 | Within above, pipeline and result construction |
| Pandas `iterrows` | 2.22 | Within runner, not additive to runner time |

Repeated dataclass conversion, deep copies and JSON normalization occur inside
these totals. Cumulative subcalls overlap; do not add them together. Profiler
overhead and one early null target prohibit using this table as a throughput ETA.

The equivalence verifier was subsequently strengthened to validate original/new
result preimages and each fingerprint before permitting the source-only
comparison. The stored profile passed this stronger verifier without replay.
Six regression cases reject altered trade outcomes, indicators, risk,
fingerprints or preimages and accept a valid disclosed source-only transition.
The initial archived verifier and current verifier are distinct source identities.

## Recommendation and next work

First acceleration hypothesis: eliminate redundant complete-payload conversion
and normalization during serialization, preserving **identical canonical JSON
bytes/result hashes**. No acceleration implementation, benchmark improvement or
resume was adopted in this step. Do not change indicator formulas, strategies,
risk, stops or label semantics to improve runtime.

Next implement and benchmark that one hypothesis with adversarial serialization
tests and all90 saved pilot golden payloads, then representative canonical
executed/null replays. Preserve all failed trials. Current strict same-source
resume will reject the old segment after code changes; a separately audited
source-transition/equivalence contract is required before reusing53 labels in a
NEW resumed segment. Never weaken that guard or claim old/new source hashes match.
Until qualification succeeds, the campaign stays stopped and no duplicate/full
restart is authorized by a benchmark result alone.

## NOT proven

Full coverage, faster campaign throughput, universal equivalence, positive
expectancy/OOS edge, ML readiness and verified historical costs/calendar remain
unproven. The diagnostic budget was one replay, zero new strategy parameter
configurations and zero ML fits. Original campaign/holdouts remain intact;
features and fitting remain blocked.

Focused validation34 passed/zero network attempts; full backend and frontend
results are appended after completion. No existing safety assertions removed.

Final validation: backend2,776 passed/four explicit opt-in skips, zero external
network attempts; frontend240 passed/build passed (existing chunk warning).
Logs: `reports/long-label-profile-focused-20261009-01.txt`,
`reports/long-label-profile-backend-20261009-01.txt`,
`reports/long-label-profile-frontend-20261009-01.txt` and
`reports/long-label-profile-build-20261009-01.txt`. Original stopped53-artifact
audit preceded profiling CLI/source changes. Prior source snapshots are retained;
their hash validation must not be transferred to the current implementation.
