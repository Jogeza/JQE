# Guarded demo supervisor recovery

Following the session interruption, no execution supervisor or MT5 process was
present and the supervisor heartbeat contained NUL bytes. Current process
inventory and durable recovery were checked before restarting the previously
authorized demo loop. The existing configured demo session initialized and
verified account identity, server and terminal path. Balance/equity:143.91 USD;
zero open positions; no unresolved durable intents. Daily history was
AUTHORITATIVE and preflight reported only READ_ONLY_PREFLIGHT_NO_ORDER_INTENT.
No integrity halt was cleared during this recovery.

The damaged heartbeat was copied to
`state/backups/supervisor-heartbeat-interrupted-20261006-024348.json`.
Canonical supervisor restarted with its own execution flag and separate logs;
shared dotenv files and the API remained execution-disabled. Actual PID3080.
Logs: `logs/execution-20261006-024348.stdout.log` and matching stderr log.
Existing risk/caps, idempotency, demo verification and broker reconciliation
remain unchanged. No pending-limit submissions or experimental strategies were
activated. No Windows service, reboot startup or VPS purchase was added.

This was an operational recovery, not a source-code change. The previous full
validation remains 2,565 backend passed/four skipped and 177 frontend passed.
