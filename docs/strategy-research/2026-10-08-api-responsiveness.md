# API responsiveness investigation

This is an operational investigation, not strategy research or evidence of an
entry-quality improvement. Frontend HTTP serving worked while direct backend
health and its proxy timed out. No backend/terminal restart was performed.

## Finding and change

The demo-verification evidence database contained 233,831 rows and about 67.8 MB.
`ApplicationService._get_latest_demo_verifications` fetched every verification
row, then retained only the latest per normalized broker. The async live broker
status method called its synchronous status reader twice on the event loop.
A read-only measurement observed 1.371 seconds for the old reader versus 0.406
seconds for a latest-only SQL query returning three rows. These are individual
measurements, not a controlled latency benchmark or proof of the sole root cause.

The reader now selects MAX(id) per LOWER(TRIM(broker)), preserving the original
latest-record semantics while avoiding transfer of all historical payloads.
It opens SQLite explicitly read-only with a one-second lock timeout. Both durable
status reads now run through asyncio.to_thread, allowing unrelated requests to
proceed while SQLite waits or reads. Identity/safety interpretation and fresh
post-session evidence rereading remain unchanged. No evidence was deleted,
indexed, rewritten or migrated; no gate or persisted safety state was changed.

Regression checks verify newest normalized-broker selection, byte-identical
evidence after reading, off-event-loop status reads and cancellation propagation.
Existing broker-status tests continue to verify the fresh post-session identity.
Eighteen targeted checks passed. Measurements are retained in
[the diagnostic evidence](2026-10-08-api-responsiveness.json).

## Limits and next work

The running backend still has its previously imported code. Its live health
recovery is **not proven**. The user's explicit boundary forbids changing running
processes, so applying the fix requires authorization to restart only the API
process started in this session. MT5, frontend, execution gates and safety stores
must remain untouched. After that, measure direct/proxied health during concurrent
dashboard observation polling before claiming resolution. If stalls persist,
investigate remaining synchronous work and SDK/session contention independently.

Once API responsiveness is verified, resume the registered complete training-only
counterfactual campaign. No ML fitting or sealed-holdout evaluation occurred here.

Final validation: 18 targeted checks passed. The full backend run had 2,643
passed, four opt-in skips and one failure: API bootstrap's existing 20-second
subprocess import timeout. Both bootstrap safety tests passed unchanged on the
isolated rerun (17.06 seconds total). Preserve the original failure log at
`reports/api-responsiveness-tests-20261008.txt` and rerun log at
`reports/api-bootstrap-recheck-20261008.txt`; do not describe the full run as
entirely green or assume the timing cause is proven. Frontend 238 passed and
build passed with the existing size advisory; diff check passed. A fresh single
read measured 0.531 seconds with the updated reader, retaining three broker groups.

## Authorized backend restart and verification

On October 8 the owner explicitly authorized restarting only the backend. The
port-8000 listener's current command line was verified as the JQE uvicorn process
before stopping PID 18912 and launching the same loopback command with the
prepared fix. Frontend and MT5 process identities/start times were retained.
No source, environment, execution gate or safety-state edit was part of restart.

Twenty concurrent read-only GET probes covered direct backend health,
frontend-proxied health, dashboard observation health and risk. All returned HTTP
200, zero failures; maximum observed latency was 0.3001 seconds. Dashboard polling
also resumed in the backend access log. Raw evidence:
`reports/backend-restart-verification-20261008-01.json`; fresh server logs:
`reports/backend-restart-20261008-01.stdout.log` and `.stderr.log`.
This is observed short-run recovery, not proof of sustained latency or elimination
of every potential SDK/session stall. No order endpoint was tested.

Next: resume the registered complete canonical training-only label campaign;
retain runtime health monitoring and all ML/holdout qualification requirements.
