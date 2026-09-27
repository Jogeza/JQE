# Weltrade migration validation — 2026-09-27

## Outcome

Complete offline backend validation: **2,232 passed, 0 failed, 0 errors,
4 skipped**, covering 150 test files in 15 bounded groups. Frontend:
**140 passed** across 19 files, and production build passed. The existing
greater-than-500-kB JavaScript chunk warning remains.

No unresolved failures remain in the executed tests. The skipped coverage is
one opt-in live-MT5 integration test and three archived paper-forensics tests.
The latter require an immutable archive explicitly supplied through
`JQE_ARCHIVED_FORENSICS_ROOT`; they no longer read the operator's mutable
runtime databases. Their baseline hash and outcome assertions remain intact.
These four tests are unverified, not passing.

## Why the earlier run stopped

Observation health used `os.kill(pid, 0)` as a process-existence probe. On
Windows this sends CTRL_C_EVENT. The health test used its own process ID,
interrupting pytest and the parent runner. The bounded reproduction captured
KeyboardInterrupt in `reports/backend-baseline/group-14.log` and
`reports-backend-run.err`. The earlier timing observation did not establish a
timeout; the reproduced process probe was the cause.

The new Windows helper opens a process with SYNCHRONIZE rights, checks its
wait state, and closes the handle without sending a signal. Regression tests
cover invalid IDs, the current process, and exited processes.

Persisted broker-selection errors now fail closed instead of silently falling
back to configured Weltrade. The obsolete operator verification path rejects
Deriv and accepts only Weltrade as a selectable broker. Offline tests use
explicit injected doubles and retain execution/risk assertions. Legacy
low-level adapter and historical evidence coverage remains where appropriate.

## Evidence and repeatability

- `reports/backend-complete/summary.json`: per-group results.
- `reports/backend-complete/totals.json`: aggregate counts.
- `reports/backend-complete/group-*.log` and XML: full per-test output and tracebacks.
- `reports/frontend-final.log` and `reports/frontend-build-final.log`: final frontend checks.
- `reports/backend-runner-verification/`: seven preserved dashboard regression
  tests passed again after the runner's report-output improvements.

Run `venv/Scripts/python.exe tools/check_backend_groups.py` for another bounded
offline run. Each group has a 120-second limit, isolated temporary state,
blocked real MT5 initialization/login/shutdown/order submission, verbose
tracebacks, and saved XML. A fresh report directory preserves earlier evidence.
The full run's group durations total approximately 206 seconds.

## Files changed during this continuation

Earlier migration changes were retained. In particular, the two existing
`api/service.py` fixes and all seven tests in
`tests/test_weltrade_dashboard_regressions.py` were preserved unchanged.

Runtime fixes and validation tooling:

- `api/observation.py`
- `core/processes.py` (new)
- `data/broker_selection.py`
- `tools/demo_synthetic_verification.py`
- `tools/check_backend_groups.py` (new)

Frontend branding and native symbol defaults:

- `frontend/src/App.tsx`
- `frontend/src/components/Header.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/styles/editorial.css`
- `frontend/public/weltrade-logo.svg` (new, sourced from Weltrade's official site)
- `frontend/public/weltrade-logo-source.md` (new attribution)

Test adaptations and coverage:

- `tests/test_api.py`
- `tests/test_broker_selection_and_workflow.py`
- `tests/test_broker_status_and_watchlist_cap.py`
- `tests/test_config.py`
- `tests/test_demo_gateways.py`
- `tests/test_demo_synthetic_verification.py`
- `tests/test_demo_trade_preview.py`
- `tests/test_historical_coverage.py`
- `tests/test_main_deriv_durable.py`
- `tests/test_market_observation_execution.py`
- `tests/test_market_setup_api.py`
- `tests/test_mt5_gateway.py`
- `tests/test_mt5_telemetry.py`
- `tests/test_paper_forensics.py`
- `tests/test_process_liveness.py` (new)
- `tests/test_watchlist_and_telegram_control.py`
- `tests/test_weltrade_gateway.py`

Documentation: `AGENTS.md`, `README.md`, this report, and the appended
`docs/weltrade-resume-checkpoint.md`. Local report/log artifacts remain available;
the reports directory is ignored by Git. Existing whitespace warnings in prior
edits were not cleaned up as unrelated work.

## Frontend preview and safety

The dashboard is open at http://127.0.0.1:5173/ with the official Weltrade logo
visible in the sidebar and mobile drawer. API preview: http://127.0.0.1:8000/.
Screenshot: `reports/weltrade-dashboard.png`.

The API preview was launched with process-local execution and Telegram disabled.
The read-only broker-status endpoint confirmed `execution_enabled=false`.
It contacted the demo terminal for connection evidence; no order was submitted.
No `.env`, `.env.ai`, or persisted execution safety gate was changed.

Final process inspection found no pytest or backend runner left running. The
intentional API preview processes (3604/10916) and frontend preview (18068)
remain available. HEAD is still `d6d00e1`; no reset, commit, or push occurred.
