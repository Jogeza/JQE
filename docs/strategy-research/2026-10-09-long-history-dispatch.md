# Longer-history offline preflight and separate dispatcher (2026-10-09)

The frozen design remains unchanged. Offline preflight passed all ten native
symbols against the October 8 terms: exact shared contract fields, eight finite
matched profit probes per symbol, and positive finite margin probes in both
directions at multiple lot sizes supporting a common conservative ratio.
These are compatible captured snapshots, not verified historical economics.

Final evidence: `reports/long-history-preflight-20261009-02/preflight.json` and
`implementation.json`. Attempt 01 is preserved; attempt 02 adds explicit finite
profit and two-sided/multi-size margin checks. Both produced zero outcomes.
All frozen input/helper hashes, original replay dependency hashes (apart from
separately bound CLI routing), dependency versions, full prefixes, closedness,
conditional Sunday coverage and timestamp-bound spreads passed offline.

`backtesting.long_history_training` implements a separate canonical CLI dispatcher.
It preserves original bundle manifests and full prefixes; the old campaign
acquisition gate is unchanged. It invokes canonical run_backtest with the frozen
risk/execution configuration and corrected model for all 30 symbol/cost cases.
All-symbol preflight precedes every outcome; inputs/source are checked around
replays. New-only output, append-only trial states and failed-attempt evidence
are retained. Full results, metrics and conditional independent-account summaries
are saved. There is no automatic resume. SDK session/history/order/economics calls
are blocked at dispatch. Source identity is disclosed separately from the design.

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --long-history-training reports/long-history-training-registration-20261009-01 --preflight-only --output reports/NEW-PREFLIGHT
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --long-history-training reports/long-history-training-registration-20261009-01 --output reports/NEW-TRAINING
```

No real-data outcome campaign has been dispatched. Runner integration is not yet
qualified by a completed longer-history replay. Fees, historical margin,
financing/timezone/calendar, live-fill equivalence and ML readiness remain open.
Original holdouts remain sealed; live execution, services, terminal and safety
state were untouched. Next: run the fixed training campaign on stable source,
then audit all 30 saved identities/results and report negative/no-trade outcomes.

Validation: final focused 28 passed, zero external network attempts; frontend
240 passed and build passed with the existing chunk-size warning. Full backend
result is recorded below after completion. Logs use `reports/long-history-dispatch-*`.

Full backend: 2,701 passed/four explicit opt-in skips, zero external network
attempts. This run collected the initial three new dispatcher tests; the fourth
preflight-only test was added during validation and passed in the final 28-check
focused run. The final finite-probe strengthening also passed fresh real-data
preflight and that focused run; do not describe the full run as collected after
those final edits. Frontend 240/build passed. Existing safety assertions retained.
