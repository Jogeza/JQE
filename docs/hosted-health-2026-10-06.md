# Hosted and demo health — 6 October 2026

Read-only verification at approximately 03:12 Africa/Kampala. Existing supervisor
PID 3080, relay PID 9020 and tunnel PID 21092 were alive. The local API returned
health OK, Weltrade-Demo identity, zero positions and zero unresolved intents.
Emergency stop was CLEAR. The safety snapshot was NOT_EVALUATED, not a fresh
authorization to submit an order. No state, gates or processes were changed.

The supervisor heartbeat reported RUNNING, cycle 5, 14 pairs evaluated. Recent
canonical cycle logs reported NO_TRADE_SIGNAL and no order submission.

The logged-in production tab initially held the old upgrade bundle. Reload
loaded the premium page; returning to the workspace and refreshing data first
showed UNAVAILABLE while requests were pending, then visibly completed with
LIVE chart, decision trail and terminal data. Notifications confirmed fresh
closed candles, verified demo and no current alerts. AI showed CONFIGURED;
no provider request was made, so AI response success remains unverified.

Broker balance/equity USD 143.91; zero positions; daily starting balance USD
143.91 reconstructed from broker movements; daily realized net P&L USD 0.00.
Latest M5 candle closed at 03:10 local time. Decision analysis, risk and execution
policy showed BLOCKED / NO_TRADE. Observation API orders stayed disabled,
independent of the separately armed guarded demo supervisor.

Tunnel logs contain recurring DNS resolver timeouts, despite the verified
working hosted data path. Do not equate process liveness with transport health.
Evidence: ignored reports/hosted-health-20261006.png. This was an operational
inspection only; no new code tests or strategy-profitability claims are made.

Recommended next: distinguish initial refresh/loading from failed monitoring
in the UI, and make supervisor status explicit beside observation-API status.
Preserve safety blocks and thresholds; never force a trade to meet the target.
