# Local demo operating handoff — 2026-10-11

Scope: existing Weltrade-Demo account ending8111 only. Operational execution has been observed; strategy positive expectancy, production uptime and commercial readiness are NOT proven.

## Verified snapshot, 19:51 Kampala

| Component | Evidence |
|---|---|
| API | loopback127.0.0.1:8000, process21272, /health ok;10 sequential probes passed, max0.158s |
| Frontend | loopback127.0.0.1:5173, listener21360; visual population not rechecked in this step |
| Demo supervisor | worker21488, fresh RUNNING heartbeat,3 completed cycles/14pairs each since cap change |
| Trading limits | process-local max5; per-trade risk and same-symbol block unchanged; USD equity-floor safeguard retained |
| Current position | ticket572131426 SFX Vol20 SELL0.02, SL32853.28/TP32772.14, stillopen; no close result yet |
| Research | worker21872 alive,607new labels plus11614inherited=12221/241938;608started/zeroFAILED at snapshot |

API process remains execution-disabled. More watchlist trades depend on canonical signal, broker minimum lots, account risk, margin and execution policy. Repeated rejection is not grounds to raise risk or shrink stops. Partial-manager broker modifications are owned only by existing explicitly armed supervisor; this handoff performs none.

## Operating checks

Inspect state/weltrade_execution_supervisor_heartbeat.json for owner, timestamp, status and reason; confirm process command identity and core.processes.is_process_alive rather than os.kill. Compare actual terminal observation with position ledger and durable intents, including net close cashflows. A RUNNING heartbeat alone does not prove every pair succeeded. OPEN_POSITION_LIMIT_REACHED blocks submissions as designed; minimum-lot failures are eligibility outcomes. Integrity/partial-protection blocks must remain fail-closed. Do not launch duplicate owners or infer completion from an absent research process.

Keep reports/demo-cap-five-20261011 launch/log/health evidence and immutable campaign segments. Process-local cap5 is not persisted: future authorized supervisor launches must explicitly supply cap5 and execution=true. Shared dotenv remains unchanged. Never automatically clear a halt after a restart. Recheck existing demo identity and broker/ledger recovery before enabling execution again. Existing ticket protection lives at broker; process absence still loses ongoing monitoring and does not establish recoverability.

## Remaining operational work

1. Observe canonical close reconciliation for current ticket and verify net fees/volume/reason against broker history; no manual-close request made.
2. Qualify sustained polling and fail-closed supervisor recovery using offline injected doubles; short sequential health probes are not load or uptime proof.
3. Design separately reviewed reboot/startup recovery and operator visibility. No scheduled task, automatic restart or notification monitor created; startup can unexpectedly rearm and needs explicit design/authorization.
4. Finish241938training-label attempts and audit complete coverage before features/ML. Current partial labels are not portfolio expectancy.
5. Same-symbol additions need qualified canonical multi-layer accounting and fresh chronological registration; retain current execution block.

No implementation changes this check; recent full2810backend/243frontend/build results remain recorded in demo readiness report. Next priority is broker close/reconciliation, then controlled recovery qualification. Local demo operation is enabled; real accounts remain unsupported.

## Recovery regression qualification — 19:53 Kampala

Ran unchanged existing offline supervisor, close-monitor, reconciliation, continuous-terminal-reconciliation, read-only-observation-health and Windows-process-liveness suites:76passed/zeroexternalnetworkattempts. Existing assertions cover process-local authorization, halt-before-signals, canonical-only delegation, cancellation/crash terminal heartbeat, narrowly scoped position-limit retry and broker-close evidence. No fault injected into running services, no source edits or production halt cleared.

This establishes current regression behavior under test doubles, not recovery after actual Windows reboot, broker outage, abrupt process termination or durable-storage corruption in this operator environment. Reboot/startup rearming remains unqualified; no automatic restart introduced. Ticket572131426 observed stillopen at19:52, stop/target intact; wait for actual broker close to verify runtime reconciliation. Next verify real close and then design an isolated restart/recovery acceptance matrix before any auto-start service.
