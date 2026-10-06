# Workspace loading and permission clarity

Initial market and terminal requests now show LOADING and specific progress
messages. Failed requests still show UNAVAILABLE and point to Notifications;
loading does not imply valid trading evidence. Retained candle handling and
safety/risk authorization remain unchanged.

Observation API orders are explicitly scoped to that API. A separate guarded
demo supervisor label states that its status is not supplied in this snapshot.
No status is inferred from API permissions or the observation-only supervisor.
Next: expose the canonical execution supervisor heartbeat through an existing
authenticated read-only boundary, with explicit age and stale-state handling.

Validation: all 19 offline backend groups exited zero, 2,565 passed/four skipped
in reports/backend-loading-20261006; frontend 179 passed and build passed.
Production deployment dpl_97w6qBzqHgL6cxwHWmFEfZgLeJn7 is READY. The logged-in
production browser visibly displayed the new loading messages. Screenshot:
ignored reports/workspace-loading-20261006.png. Existing bundle-size and
deployment dependency-audit warnings remain.

Only this task's UI changes and regression test are staged; prior daily-balance,
chart, broker and research work remains intact and uncommitted. No trading
process, execution gate, quota or payment setting was changed.
