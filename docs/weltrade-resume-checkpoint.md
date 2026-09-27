# Resume checkpoint — 2026-09-27

The working tree was inspected before changes. HEAD remains `d6d00e1`.
All pre-existing tracked and untracked work was retained. No reset, commit,
push, terminal operation, or execution-gate change was performed.

No Python/pytest process remained from the frozen session at inspection.

The two existing `api/service.py` fixes were preserved:

- Dashboard terminal history uses the `weltrade` cache partition rather than
  the ambiguous legacy `broker` partition.
- Risk telemetry matches the configured effective Weltrade account instead
  of accepting the account identifier from the stored snapshot itself.

Added `tests/test_weltrade_dashboard_regressions.py`: seven offline cases
cover new history storage, preservation of old partitions, cache fallback
isolation, matching/mismatched accounts, and missing configured identity.
Risk reads also verify no connection/submission and no stored-snapshot mutation.

Validation:

- New regression tests: 7 passed.
- New regressions plus `test_main_durable_executor.py` and
  `test_recovery_diagnostics.py`: 58 passed in 30.06 seconds.
  Output: `migration-resumed-focused.log`.
- Frontend: 140 tests passed; production build passed with its existing
  greater-than-500-kB bundle warning.
- Full backend suite attempted with configured database paths redirected
  to temporary storage and real MT5 initialize/login/shutdown/order_send
  calls blocked. The runner ended after approximately five minutes at 77%
  without a final summary. Failures/errors were present; no full-suite pass
  or exact totals can be claimed. Output: `migration-resumed-backend.log`.
  Process inspection afterward confirmed no Python/pytest process remained.
- Existing diff whitespace warnings remain in pre-existing edits.

The wider migration is unfinished. Previous failure evidence includes
`tests/test_api.py` constructing the now-unsupported `broker="simulation"`
settings. Continue with isolated injected test doubles, preserving production
broker validation and all execution safety assertions. Run backend validation
in bounded groups with per-test reporting to locate slow/failing cases and
obtain complete summaries; the interrupted output alone is insufficient.

No Phase B research, alerts, trading-cap changes, or commit was attempted.

## Continuation completed — 2026-09-27

The interrupted backend run was reproduced and diagnosed: the observation
health probe called `os.kill(pid, 0)`, which sends CTRL_C_EVENT on Windows.
It interrupted both pytest and the parent runner. This is now replaced with
a non-signalling Windows process-handle check, covered by regression tests.

Complete bounded backend validation: **2,232 passed, 0 failed, 0 errors,
4 skipped** across 150 files and 15 groups. Skips: one opt-in live-MT5 test
and three archived forensic tests requiring an explicitly provided immutable
archive. Frontend: **140 passed**, production build passed with the existing
bundle-size warning. No test processes remain.

The two saved service fixes and seven dashboard regression tests were preserved.
Persisted broker read errors now fail closed; obsolete selectable-broker tests
were migrated to Weltrade or explicit offline doubles while retaining safety
assertions. The official Weltrade logo is visible in the dashboard, open at
http://127.0.0.1:5173/. Broker execution remains disabled; no reset, commit,
push, environment-file edit, or persisted safety-gate change occurred.

See [the detailed validation handoff](weltrade-validation-2026-09-27.md) for
the full changed-file list, evidence paths, remaining unverified coverage,
runner instructions, and intentional preview processes. This update supersedes
the incomplete validation status above; it does not claim research profitability
or completion of future roadmap phases.
