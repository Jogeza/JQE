# Interrupted training-label campaign: validated resume

Completion update: all 8,499 attempts finished and the complete coverage audit
passed with zero errors. See the [completion report](2026-10-08-complete-label-coverage.md).
The pending statements below describe the launch-stage controls and are retained
as historical context. No feature extraction or ML fit occurred.

The original process was absent on continuation, with 4,900 completed ledger
entries and one unfinished STARTED entry; no final summary. The interruption's
cause is unknown. All original files and ledger entries are preserved. No failure
or completion was invented for the unfinished entry.

Before resume, the original source/dependency snapshot matched the current tree.
The source change adds only resume orchestration in backtesting/backtest.py,
label_pilot.py and label_resume.py. The canonical run_backtest function body was
hashed before editing and must match afterward. All strategy, risk, execution,
economics, indicator, dataset and dependency hashes remain unchanged. Source
snapshots are disclosed separately; old/new fingerprints are not called identical.

Resume validates completed artifact identities, ledger transitions, null rejection
labels, executed-trade cardinality, capital, typed quantities, label chronology and
net-R arithmetic. It hashes every preserved artifact and prior plan/ledger into
new lineage evidence. Those hashes are checked again at completion. Duplicate or
failed prior attempts require explicit review rather than silent reuse.

The new campaign directory is `reports/counterfactual-campaign-resume-20261008-01`.
Its plan reuses 4,900 validated labels and dispatches 3,599 remaining attempts,
including a retry of the unfinished entry. Original registration, all 2,833 events,
three cost cases, USD 50/1% risk, native execution constraints and 43 predeclared
censors are unchanged. Replay still runs only through the canonical backtest CLI:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --counterfactual-campaign reports/counterfactual-protocol-20261008-01 --inventory-campaign reports/entry-campaign-20261008-04 --cost-terms reports/entry-cost-terms-20261008-01.json --resume-labels-from reports/counterfactual-campaign-20261008-01 --output reports/counterfactual-campaign-resume-20261008-01
```

The existing output cannot be overwritten. The campaign and one-shot completion
auditor are detached Windows processes, so losing a chat tool session does not
terminate them. PID evidence and stdout/stderr logs are in reports/label-resume-*
and reports/label-coverage-watcher-*. Check liveness with core.processes, not
os.kill on Windows. Do not start a duplicate or change source during replay.

## Completion criteria

The one-shot checker waits for the final summary, then requires all 8,499 unique
event/cost pairs across both ledgers, exactly one completed label per pair, the
disclosed unfinished-entry retry, all saved artifacts and all 43 censors. It
checks original/current plans, input/source lineage and prior-file hashes; no
END_OF_DATA label or boundary-crossing availability is accepted. Failed replay,
missing summary or audit errors block completion and feature extraction.

Output will be `coverage-audit.json` and `executed-label-intervals.json` in the new
campaign directory and docs/strategy-research/2026-10-08-complete-label-coverage-resumed.json.
Until those exist with PASS and full coverage, this campaign remains incomplete.
Compact artifacts are not full result-hash preimages; that limitation is retained.

Validation: ten focused resume/canonical replay tests passed. Full backend 2,650
passed, four explicit opt-in skips, zero external network attempts. Frontend 240
passed and production build passed with the existing bundle-size advisory.

## NOT proven and next work

No feature extraction, ML fit, new strategy candidate, sealed-holdout evaluation,
positive OOS expectancy or historical-cost qualification occurred here. Independent
event labels remain distinct from stateful strategy returns. Next finish the
resumed campaign and review its complete coverage audit before causal feature
qualification. Longer history, exact costs and a fresh ML registration remain
separate prerequisites.
