# Demo execution authorized and running (2026-10-09)

Owner instruction: “allow mt5 and live execution”. Applied to the supported
configured Weltrade demo account and existing canonical watchlist; no real-account
support, research promotion, safety bypass or risk expansion was introduced.

Existing terminal PID 8016 retained; exact configured demo identity verified.
Algo Trading/Python trading were already enabled, account trading permitted,
zero positions before launch. Read-only prerequisite evaluation returned
AUTHORITATIVE with only READ_ONLY_PREFLIGHT_NO_ORDER_INTENT; that observation
itself did not authorize a trade.

Separate supervisor started process-local execution-enabled, launcher PID 16200,
worker 8004. Shared environment files/API remain unchanged. Existing forward
cache `data/live_monitoring_20261004.sqlite3` reused. Telegram flags disabled in
this process; the user authorized broker execution, not external messages.

Heartbeat RUNNING, first cycle 14 existing pairs: eight NO_TRADE and six BLOCKED.
All six broker connection error codes correspond to “MT5 authorized risk is
below the broker minimum lot risk”. Do not raise risk/capital or round lots up
in response. Zero open positions after first cycle; no new fill demonstrated.
Configured risk 0.5%, daily loss cap 3%, daily trade cap five; all existing
position/idempotency/risk/demo checks remain enforced. These are operating
settings, not a validated-profitability claim.

Evidence: `reports/demo-execution-authorized-20261009-01.json`, PID and stdout/
stderr logs with same stem, and `state/weltrade_execution_supervisor_heartbeat.json`.
Supervisor reevaluates guards before each cycle; no automatic restart was added.

Offline longer-history campaign continues separately; source was not changed.
Latest five completed/sixth active, no final summary; its audit is pending.
Its modeled training findings cannot authorize a candidate or ML promotion.
No code changed in this operation. Previous full validation remains 2,702 backend
passed/four skips and frontend 240/build passed; runtime first-cycle verification
is separate from those offline tests.
