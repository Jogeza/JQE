# Equal-half demo partial management (2026-10-09)

Owner selected two equal broker-valid portions within unchanged risk, 50% close
at +1.5 original price R, then remaining stop at +0.5R beyond actual fill.
R is actual fill-to-original stop distance; BUY uses executable bid, SELL ask.
Sizing floors to an even number of lot steps, e.g. authorized 0.03 becomes total
0.02, two 0.01 portions. Each portion must satisfy minimum volume. Insufficient
risk budget skips entry; no lot/capital/risk increase. Reduced sizing is rechecked
by broker P/L and margin probes. Generic/default research sizing is unchanged.

New fills alone are registered after canonical broker/ledger fill verification.
Existing 0.03-lot positions are not adopted or resized. Registry binds account,
position, original fill/stop/volume and state. It claims CLOSE_REQUESTED durably
before reducing volume. Unknown closes are never blindly resent; restart requires
matching position-scoped opening/closing deals and remaining half before protection.
A changed/unverifiable position, missing safety state, emergency stop, persisted
integrity halt or unresolved intent blocks management. All broker mutation stays
behind the gateway; canonical supervisor remains the sole live loop.

Before partial submission, the desired profit stop must fit current stop/freeze
limits with a tick buffer. After confirmed partial, the stop rounds into the profit
zone to the symbol tick grid, target is preserved and a tighter stop is never
loosened. Actual broker stop readback establishes protection. If stop update is
pending/rejected, original protection remains, new entries are blocked and only
stop protection is retried every monitoring pass. A broker/gap/fee outcome is not
guaranteed profit merely because the stop price lies beyond entry.

Settings are opt-in: JQE_WELTRADE_PARTIAL_MANAGEMENT_ENABLED=true in the separate
supervisor environment; JQE_WELTRADE_DEMO_MAX_OPEN_POSITIONS=5 retained. Shared
dotenv/API are not armed. SQLite registry: state/weltrade_partial_management.sqlite3.
Supervisor was stopped during source changes/validation; MT5/positions remain
broker-protected. Activation/runtime status and final validation follow below.

Focused final checks: 102 passed/zero external network attempts. Tests cover
BUY/SELL trigger/stop math, no size increase, broker reprobes, lot/fresh position
constraints, uncertain close no-resend, restart recovery, stop failure/retry,
rounding, TP preservation, tighter-stop retention, account and durable safety
blocks. Existing safety assertions retained. First focused attempt had three
missing-optional-flag failures in older supervisor doubles; default-disabled
handling corrected without enabling management for missing settings. Initial full
run 2,721 passed/four skips preceded final four checks and durable-state tightening;
final fresh full run is recorded below. Frontend 240/build passed (chunk warning).

This execution-policy change is user-authorized demo behavior, not profitable
strategy promotion. Completed frozen TRAIN campaign and audit remain immutable;
their negative outcomes do not validate the new trade management or ML readiness.

Final validation: 2,725 backend passed/four explicit opt-in skips, zero external
network attempts; 102 final focused checks; frontend 240/build passed. Logs:
reports/partial-management-backend-20261009-02.txt and corresponding focused04,
frontend/build01 logs. Earlier validation artifacts retained.

Activation: launcher8988/worker21232; heartbeat STARTING awaiting next scheduled
M5 cycle, clear non-authorizing prerequisite check. Process-local execution/partial
flags true and five-position cap, same forward cache, Telegram flags false.
Registry has zero managed positions at activation; no broker partial close/stop
update has yet been demonstrated. Existing 0.03-lot position not adopted.
Evidence reports/demo-partial-management-20261009-01.json and PID/stdout/stderr.
No MT5/frontend/backend restart, shared dotenv/gate bypass or forced trade.
