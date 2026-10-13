# Lossless shared storage for canonical labels

`jqe-shared-full-result-v1` preserves complete result preimages without repeating
the same 25,894-row arithmetic series in every label file. This changes saved
research storage only. Signals, indicator calculations, risk, costs, fills and
live execution were not changed. Full label dispatch has not started.

## Reconstruction and immutable evidence

Each NEW segment owns its content-addressed gzip objects. It shares the complete
indicator series with regime set to null and the embedded source snapshot. Every
result keeps its exact regime overrides and every other original field. Object
references bind both canonical JSON content hashes and compressed-file hashes.
Loading checks the schema, reference shape/path, dependency hashes, override
indices and complete original result hash after reconstruction. The provider field
is excluded from that hash exactly as in the existing result serializer; no hash
definition was changed. Missing/corrupt dependencies fail rather than returning
partial results.

The writer rejects changed arithmetic for the same symbol/dataset, never mutates
the input result, creates result files exclusively and fsyncs artifacts before a
completion can be logged. An interrupted partial file is retained and requires
diagnosis; it is not repaired in place. Resume and full coverage audit reconstruct
the full result, retain dependent object hashes in their evidence, and recheck
them before completion. Previous full gzip artifacts remain readable and hash
verified, but the existing same-source resume restriction still applies. There
are no previous full campaigns to migrate; the original pilot remains immutable.

Storage qualification uses the canonical CLI:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --qualify-long-label-storage reports/shared-label-storage-20261009-01
```

This reencodes the 90 existing audit-bound pilot results into NEW files, compares
every reconstructed field against the original, verifies all original preimages,
retains input/dependency/source hashes and checks source stability. It is not a
new replay, label campaign or alternate signal pipeline. The proof directory must
not be passed as a campaign resume segment. Old pilot source/archive and all
negative training evidence remain intact.

## Validation and limits

Focused validation: 51 passed, zero network attempts, including all-symbol target
equivalence, unchanged SFX99 restrictions, interrupted resume and new storage
corruption tests. Missing objects, corrupted compressed bytes, altered object
hashes, path traversal references, duplicate overrides, altered outcomes, unknown
schemas and arithmetic drift reject. Legacy preimages and two distinct regimes
sharing one arithmetic object reconstruct exactly. Initial resume-only checks
also passed (19 tests); all logs are retained.

Storage and full-suite completion figures are recorded below after qualification.
No safety assertions were removed. No terminal, running service, execution gate,
safety state or dotenv changes were made.

## NOT proven

The 90 saved pilot results are early inspected training evidence. Their storage
size cannot guarantee later-result sizes, filesystem overhead, audit/ledger size,
campaign runtime, full coverage, sufficient independent samples or OOS edge.
Historical fee/margin/financing/calendar qualification, new causal features and a
fresh chronological ML holdout remain unresolved. No new labels, ML fits,
candidates or holdout evaluations occurred.

Next: assess the completed storage proof and a conservative disk budget, then run
the registered 241,938-attempt training-only canonical campaign with stable source
and immutable segments. Obtain complete saved coverage PASS before features.

## Completed proof and capacity estimate

Saved audit `reports/shared-label-storage-20261009-01/audit.json` reports
PASS_LOSSLESS_PILOT_STORAGE_NOT_NEW_LABELS, 90/90 complete reconstructions, zero
errors and stable source. All original pilot/audit inputs and used shared objects
were rehashed. Shared objects/index files total 11,299,182 bytes. Individual result
envelopes are 11,119–11,326 bytes, median 11,133. Median extrapolation plus shared
objects is **2,704,794,936 bytes (about 2.70 GB)** for 241,938 attempts, versus
80,466,432,000 observed free bytes. The former 286 GB estimate described the old
repeated full-gzip layout and remains preserved evidence.

The proof took 239.11 seconds, including repeated full reconstruction/input
verification. This is storage-proof duration, not replay runtime. For planning,
reserve at least 12 GB for envelopes, filesystem allocation, ledgers, summaries,
audits and limited resumed segments, and monitor actual growth. This allowance
is an engineering estimate, not a measured upper bound or a guarantee for unlimited
resumes. Current free capacity supports this estimate; full campaign runtime and
growth still require observation. No full campaign was launched in this step.

Final validation: 2,770 backend passed, four explicit opt-in skips, zero external
network attempts; frontend 240 passed/build passed with the existing chunk-size
warning. Logs: `reports/shared-label-storage-focused-20261009-02.txt`,
`reports/shared-label-storage-backend-20261009-01.txt`,
`reports/shared-label-storage-frontend-20261009-01.txt`,
`reports/shared-label-storage-build-20261009-01.txt` and
`reports/shared-label-storage-qualification-20261009-01.txt`.
Next: recheck stable source, capacity and existing campaign absence, then launch
the registered canonical training-only campaign with monitoring and complete
saved-artifact audit. ML/feature gates remain closed until complete qualification.
