# Entry-quality research foundations — 2026-10-08

Recommendation: **needs more data**. This change implements offline research
foundations from the external-repository audit and documents Qoder's strategy-v2
fixes. It does not adopt a strategy or claim improved expectancy.

## Scope and identity

Qoder's `ff879e9` corrected bearish momentum reachability, confidence-floor
alignment, HIGH_VOLATILITY protection and the shared unknown-spread fallback.
The old v1 baseline remains in `2026-10-08-entry-quality.md`; its results do not
validate v2. No additional signal or risk thresholds were changed here.

Canonical replay identity schema 2 now binds the effective evaluation window
(inclusive start, exclusive end, timestamps, 200-bar warmup), provider/source,
supplied manifest content hash and a source/dependency snapshot. Dataset hashes
remain identities of market content; provider differences change the run identity.
Empty or reversed effective windows fail. Explicit provider/manifest conflicts fail.
The runner rejects source/dependency drift detected between replay start and finish.
Research catalog records and new diagnostic audit evidence retain this context.

The source allowlist covers Python modules under backtesting, core, strategy,
intelligence, risk, config, analytics, broker and data, plus research runner,
campaign provenance and the backtest-only execution simulator dependency. Reading
that simulator for hashing does not modify execution. Environment files, operator
state, datasets and terminal sessions are excluded from source snapshots.
Python, numpy, pandas and pydantic versions are recorded. This is a conservative
source identity, not a complete OS/package lock or proof of loaded-code equivalence:
use a fresh CLI process and avoid concurrent edits. Changes reverted between the
two snapshots cannot be detected. Legacy direct result builders retain schema 1.

## Offline qualification evidence

Command:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --qualify-research-data reports/research-foundations-20261008-final
```

The immutable M5 bundle inventory found 17 bundles, with no load/hash errors:

| Check | Result |
|---|---:|
| Closed-bar provenance rejected | 9 bundles |
| Diagnostic provenance checks passed | 8 bundles |
| Disclosed discontinuities | 15 |
| Qualified for promotion | 0 |
| Strategy/candidate configurations tried in this change | 0 / 0 |
| Performance replays in this change | 0 |

Exact symbols, timeframes, date windows, retrieval timestamps, hashes, gap counts
and source/dependency identity are in
[`2026-10-08-qualification.json`](2026-10-08-qualification.json).
Every bundle remains blocked: terminal contract economics and spread/commission
evidence are unverified, and untouched-holdout status cannot be certified offline.
Previously inspected data cannot become fresh evidence by relabelling its splits.
The first preflight was repeated after extending the source allowlist; both
inventories were retained under reports. Neither performed strategy evaluation.

Diagnostic audit protocols now explicitly disclose unverified holdout status and
retain result hashes/context. This removes the old hardcoded historical assertion
that no outcomes had been inspected. Existing reports were not rewritten.

## Next research sequence

1. Obtain separately authorized native Weltrade history through HistoricalDataService
   into new provider-pinned files; capture closed-bar status, gaps, contract economics
   and observed costs without touching existing research datasets.
2. Preregister windows, one falsifiable hypothesis, parameter bounds and trial ledger.
   Freeze a canonical v2 baseline with source/dependency identity before examining
   the untouched chronological test partition.
3. Diagnose training losses by regime, signal direction, entry timing and stop distance.
   Tune only on training/validation; compare baseline and candidate on identical test
   data/costs once, then run the declared doubled-spread/commission sensitivity.
4. Report expectancy in verified account currency and R, PF, win/loss distribution,
   drawdown, Sharpe/Sortino, exposure, MAE/MFE, duration, uncertainty and all trials.
   Reject an OOS failure and preserve it. No strategy promotion on current evidence.

Marked-to-market accounting, conservative gap-fill validation, confidence calibration,
trial-registry enforcement and UI evidence remain later stages. The legacy catalog's
`controlled_comparison` flag is insufficient for research acceptance; manually verify
equal evaluation windows, provider, costs, capital and risk assumptions. Rust remains
deferred pending profiling and canonical equivalence tests. External code was not
installed, imported or executed.

## Validation

Focused offline research/reproducibility/runner/audit tests: 31 passed, no external
network attempts. Full backend: **2,587 passed, 4 skipped**, exit 0, 170.81 seconds,
`EXTERNAL_NETWORK_ATTEMPTS=0`, using
`D:\JQE\venv\Scripts\python.exe -m pytest -p tests.offline_research_guard -q -rs`.
The skips are the existing live-MT5 opt-in and three archived-forensics fixtures.
Frontend: `npm test -- --run` passed **238 tests across 40 files**;
`npm run build` passed, retaining the large-chunk warning (852.67 kB main bundle).
Pytest discovery is now confined to `tests/`, preventing downloaded audit snapshots
under reports from entering JQE collection; no safety assertions were removed.

## NOT proven

- Positive expectancy or improvement from strategy v2; no candidate was evaluated.
- An untouched OOS sample or completed walk-forward campaign.
- Verified account-currency results, spread/commission, terminal contract economics.
- Intrabar MAE/MFE ordering, marked-to-market drawdown or realistic gap fills.
- A complete environment lock, thread-safe source capture or third-party security certification.
- Live/demo execution readiness or any reason to change execution gates.

No changes were made to main.py, execution files, environment files, persisted
safety state, existing market datasets, the terminal or running services.
