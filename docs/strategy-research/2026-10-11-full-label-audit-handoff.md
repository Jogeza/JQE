# Full-label completion audit handoff — 2026-10-11

Prepared only; no full audit dispatched while owner active/summary missing. Partial samples do not replace complete audit.

Prerequisites: final owner exits cleanly, summary.json status FULL_LABEL_DISPATCH_COMPLETE_AUDIT_REQUIRED_NOT_ML_READY, exactly241938unique expected eligible event/cost records, all immutable four segments retained, original registration and source-transition contract verified. Process absence alone fails completion. Do not edit source to resolve audit errors; preserve failures.

After prerequisites, use canonical entry point with a NEW unused output directory:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest `
  --audit-long-history-labels D:\JQE\reports\long-history-label-registration-20261009-01 `
  --resume-long-labels-from D:\JQE\reports\long-history-label-campaign-20261009-01 `
  --resume-long-labels-from D:\JQE\reports\long-history-label-campaign-resume-20261010-01 `
  --resume-long-labels-from D:\JQE\reports\long-history-label-campaign-resume-20261010-02 `
  --resume-long-labels-from D:\JQE\reports\long-history-label-campaign-resume-20261011-01 `
  --long-label-transition D:\JQE\reports\lineage-integration-qualification-20261010-02\contract.json `
  --output D:\JQE\reports\long-history-complete-coverage-audit-NEW
```

The output name is a placeholder to choose once, never overwrite. Audit reads saved results, not new signal replays or terminal data. Inspected audit verifies exact expected key set/final summary, censor coverage across segments, reconstructed artifact/source hashes, canonical indicator prefixes/target regime, frozen model identities, label derivation and evidence/input immutability. Success must be PASS_COMPLETE_SAVED_LABEL_COVERAGE_NOT_ML_READY/errors0 with correct counts. Keep null non-executable/censored returns; cost cases overlap and are not independent events.

Only after successful complete audit may the next feature-extraction design bind exact verified source/data identities, causal entry features and label availability/purge controls. Full coverage does NOT authorize ML fit: fresh chronological registration, independent history and unresolved cost qualification remain. No original EMA50 holdout reuse. Pending dashboard repair stays deferred per owner instruction.
