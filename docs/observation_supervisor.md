# Observation-only supervisor

The forward process is deliberately separate from broker execution:

```text
D:\JQE\venv\Scripts\python.exe -m tools.run_observation_supervisor
```

It requires `JQE_BROKER_EXECUTION_ENABLED=false`, a demo MT5 telemetry
profile, and exactly the durable watchlist entries.  It takes a Windows file
mutex so Task Scheduler cannot create overlapping instances, wakes once after
each M5 close, observes all 34 watch entries, and relies on the durable
observation cursor to deduplicate already-persisted closes.  When a cursor
exists, every closed candle available since that cursor is evaluated in order;
if the telemetry window cannot prove complete catch-up, the cursor is not
advanced and the cycle is unhealthy.  It writes
`state/observation_supervisor_heartbeat.json`; missing, stale, incomplete, or
resolver-failed cycles are unhealthy and cannot authorize execution.

Recommended Task Scheduler settings: run whether the user is logged on,
restart on failure, do not start a new instance if one is already running,
working directory `D:\JQE`, and the command above.  The task is not registered
automatically by this change.
