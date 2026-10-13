# Longer-history training dispatch: running (2026-10-09)

The fixed 30-case campaign is running in `reports/long-history-training-20261009-01`.
This is startup/progress evidence, not campaign completion. All-symbol preflight
passed before outcomes. Latest observed ledger: two completed, third active,
zero recorded failures. Both completed FX Vol 20 cases had no trades; expectancy
and profit factor remain null. Do not extrapolate to other symbols/costs.

Partial saved-artifact hash/fingerprint/source/null audit passed for those two
cases: `reports/long-history-training-partial-audit-20261009-01.json`.
It does not qualify all 30 runs or establish expectancy, edge or ML readiness.

Detached replay launcher PID 20996, worker 12160; detached audit watcher launcher
20604, worker 21392. PID/log files are under `reports/long-history-training-*`
and `reports/long-history-coverage-watcher-*`. Check current command lines and
`core.processes.is_process_alive` on continuation. Do not launch a duplicate,
change replay source, or automatically retry an interrupted campaign.

One-shot watcher waits for final summary, then runs saved-artifact audit/report:
`reports/audit-long-history-training-20261009.py`, output
`reports/long-history-training-audit-20261009-01`. It reconstructs complete
result/fingerprint hashes, checks exact coverage/configuration/input/source/cost
identities, balances, native lots, quote-side stops and combined risk/margin
sizing, null no-trade metrics and aggregate summaries. It reports end-data exits,
final-bar discarded pending entries and gap-delayed entries. Audit is pending;
script syntax/first-result hash checks are not a completed audit qualification.
Watcher records stopped-without-summary or audit failure and never resumes.

No strategy/runtime source changed during replay. Only new report/audit scripts
and documentation were written. Terminal, services, execution/safety controls,
original holdouts and existing datasets were untouched. No candidate or ML fit.
Historical costs, margin, financing/timezone/calendar remain conditional.

Full validation of the final dispatcher source: 2,702 backend passed/four explicit
opt-in skips/zero external network attempts; frontend 240 passed/build passed
(existing large-chunk warning). Logs: `reports/long-history-campaign-*20261009.txt`.

Next: inspect existing ledger/processes and watcher output, finish the same
campaign, review every audit result, and report all 30 cases honestly. No final
summary exists at this handoff; no completion or performance claim is made.
