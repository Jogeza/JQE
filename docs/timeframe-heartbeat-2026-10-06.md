# Timeframe refresh and execution heartbeat

Timeframe changes now clear active-analysis and terminal snapshots along with
other market-scoped resources. Responses for those two resources publish as
soon as they arrive, independent of slower monitoring requests. Request IDs
and abort signals reject superseded responses. The regression leaves unrelated
notification requests pending while switching timeframe and receiving terminal
evidence. Existing execution and risk authorization boundaries are unchanged.

GET /observation/health now also projects the actual Weltrade execution JSON
heartbeat through a pure read-only reader. It checks broker context, timezone,
status, PID liveness and timestamp age. Missing, corrupt, future or stale
evidence never reports an armed process. The freshness window follows the
existing observation stale-cycle configuration (600 seconds on this machine).
The UI displays state, timestamp, age, cycle and liveness separately from
observation API permissions. A five-second clock expires retained evidence
even when refresh responses stop. Monitoring status is not order authorization.

Only the loopback observation API was restarted with execution explicitly off;
existing supervisor PID 3080 continued running. Read-only endpoint verification
returned RUNNING, age about five seconds, cycle 9 and process alive. The hosted
browser verified immediate M1 selection, cleared old chart, a returned LIVE M1
chart and RUNNING supervisor with heartbeat age. Screenshot is preserved in
ignored reports/timeframe-heartbeat-20261006.png.
M15 was also verified: immediate selection followed by a fresh LIVE M15 chart
and matching terminal candle, with supervisor RUNNING at cycle 10.
Final production deployment: dpl_8iJqcEZqfsyWqbVJ8ZpYbKRrjK6h.

Validation: 2,567 backend passed/four skipped, all 19 group exits zero in
reports/backend-timeframe-20261006. Frontend 181 passed; production build passed.
Prior uncommitted daily accounting, chart, broker and research work is preserved.
Existing bundle-size and deployment dependency-audit warnings remain.

Recommended next: measure hosted request latency per market/resource and reduce
redundant reads while preserving terminal ownership and snapshot provenance.
