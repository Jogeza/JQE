# Serialization acceleration: one tested hypothesis

Hypothesis: reusing one normalized complete result snapshot eliminates redundant
dataclass conversion without changing canonical bytes, hashes or trading behavior.
One acceleration candidate was implemented; zero strategy/risk/cost parameters
changed. The campaign remains stopped at53 completed/one unfinished attempt.
No new segment or full campaign was launched.

`BacktestResult.to_json_bytes()` now takes the complete normalized payload once,
makes a shallow preimage copy excluding provider exactly as before, and invokes
the unchanged `_sha256` and `_canonical_json`. It no longer obtains the hash by
converting the same dataclass again. No global cache, incomplete payload, changed
hash definition or stale mutable result is introduced. The label dispatcher uses
the already serialized/verified `result_hash` instead of requesting another full
property conversion. All entry/accounting/safety arithmetic is unchanged.

## Equivalence and fixed measurements

Eight typed regression cases exercise executed and null results, nested values,
Unicode/enums/mixed dictionary keys, timezone conversion, mutation, nonfinite
numbers and naive timestamps. Serialized bytes exactly match the prior algorithm;
rejection behavior is retained. Relevant reproducibility, profile and immutable
resume tests also passed:39 focused tests/zero network attempts.

`--qualify-long-label-serialization NEWDIR` compares all90 audit-bound saved pilot
results against the verified owned archived serializer. It alternates old/new
timing order, checks exact bytes, full saved payloads and original result hashes,
rehashes inputs and binds the new source archive. The hydrated objects retain
normalized saved JSON values; this storage microbenchmark is supplemented by typed
unit tests and a real canonical replay, not represented as90 fresh replays.

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --qualify-long-label-serialization reports/serialization-qualification-20261009-01
```

One fixed first-eligibleSFX99/zero-commission diagnostic replay was profiled again
through the canonical module into `reports/long-history-label-replay-profile-20261009-02`.
It matched golden pilot084 in every field after only the disclosed source identity
and dependent fingerprint adjustment; original/new full hashes are validated
separately. Its actual new-source result and source archive are retained. It was
NON_EXECUTABLE/zero trades, not an executed-real-data equivalence demonstration.
This is one new diagnostic replay in this step, two cumulative profile replays;
neither contributes to full campaign label coverage or strategy selection.

| Profile component | Before seconds | After seconds |
|---|---:|---:|
| Runner plus complete serialization wall time | 11.50 | 9.73 |
| `to_dict` cumulative | 6.38 | 4.28 |
| Runner cumulative | 5.13 | 5.44 |

These are one-target profiles with instrumentation overhead under different loads;
the after measurements overlapped other validation. Subcalls overlap. The observed
serialization reduction supports the hypothesis but does not establish whole
campaign throughput, a reliable ETA or universal speedup. All trials/results,
including these limitations, are retained.

## Source transition remains unqualified

Changing `backtesting/models.py` changes a protected source hash. The existing
canonical arithmetic dependency and same-source resume guards remain unchanged:
ordinary dispatch/resume will reject this changed implementation. Do not loosen
the guards to use the old53 labels. Golden serialization equivalence is evidence
for an explicit, separately audited transition contract, not source-hash equality.
The old campaign and profile source archives remain immutable.

Next qualify an exact source transition: bind old/new archives, restrict the
allowed edits to reviewed serialization/orchestration changes, check representative
canonical executed/null targets and prior artifacts, then permit only NEW-segment
resume with lineage for every inherited completion. Keep the interruption/retry
explicit. Do not broaden the optimization hypothesis or launch a duplicate.

## NOT proven

Full coverage, sustainable fast replay, general executed-real-data equivalence,
universal source transition, positive expectancy/OOS edge, verified historical
costs/calendar, new causal features and ML readiness are not established. Original
holdouts remain sealed. No live path, execution files, terminal/services, gates,
safety state or dotenv changes were made. No fits or parameter search occurred.

Complete90-payload audit and full-suite figures are appended after completion.

Final golden audit: `reports/serialization-qualification-20261009-01/audit.json`
reports PASS_90_BYTE_HASH_EQUIVALENT_SERIALIZERS,90 comparisons/zero errors.
All90 retained original result hashes and exact bytes. Total timed serialization:
archived83.3436s, candidate64.2594s, observed ratio1.2970 (about23% less elapsed
serialization time). Alternating order limits systematic order bias, but timing
overlapped tests/profile; this is neither a dedicated-host benchmark nor full
campaign speedup. Both executed and null saved pilot payloads were preserved.
There was one implementation candidate/reference comparison, no tuning grid.

Final backend2,784 passed/four explicit opt-in skips/zero network attempts;
frontend240 passed/build passed with the existing chunk warning. Logs:
`reports/serialization-acceleration-focused-20261009-01.txt`,
`reports/serialization-acceleration-backend-20261009-01.txt`,
`reports/serialization-acceleration-frontend-20261009-01.txt`,
`reports/serialization-acceleration-build-20261009-01.txt`,
`reports/serialization-qualification-20261009-01.log` and
`reports/long-history-label-replay-profile-20261009-02.log`.
Recommendation: retain this byte-equivalent serialization change as a qualified
microbenchmark improvement; do not resume full labels until exact source-transition
and representative real-data executed/null replay prerequisites are satisfied.
