# Demo startup and recovery acceptance matrix — 2026-10-11

Design only. No scheduled task, service, auto-restart, execution-policy change or operator-store mutation. Existing running campaign source remains frozen. Applies only Weltrade demo8111; API stays read-only. Default future startup should observe status; execution requires separately explicit process-local authorization and successful canonical reconciliation/preflight.

| Scenario | Required result before signal evaluation | Evidence/qualification |
|---|---|---|
| Missing process-local execution flag | Refuse execution even if shared setting is true | Existing offline supervisor regression passed |
| Wrong account/server or real account | Fail demo/identity checks; never log in to another account as fallback | Existing guards; require isolated startup fixture matrix |
| Existing supervisor owner | Second owner refuses mutex; first owner unaffected | Require isolated two-process lock test, no operator mutex experiment |
| Restart with open broker position | Reconcile same ticket/quantity/protection; prevent same-symbol duplicate | Require isolated durable-intent restart fixture |
| Order accepted before process crash | Broker history/positions reconcile durable intent; no resubmission | Require pending/unknown/confirmed-fill crash-point fixtures |
| Closed position, complete history | Record exact net cashflows/remaining volume/reason once | Offline close tests pass; current runtime close still awaited |
| Closed position, incomplete history | CLOSE_UNCONFIRMED durable halt; no guessed outcome or auto-clear | Existing close-monitor regression passed |
| Missing/corrupt operator state | Fail closed; preserve damaged evidence, restore only approved backup | Require isolated corrupt/unreadable SQLite fixtures |
| Broker unavailable or history partial | No new submission; accurate blocked/stale status | Require isolated timeout/SDK-error/recovery sequence |
| Pending partial protection | Block new entries until canonical protection is confirmed | Require isolated partial-management startup sequence |
| Position cap reached | Continue monitoring/reconciliation; no new entry until capacity returns | Existing supervisor retry tests pass |
| Midnight/day change | Reconstruct authoritative daily state, retain limits and risk accounting | Require isolated UTC boundary and financing fixtures |
| Supervisor cancellation/crash | STOPPED heartbeat when possible; stale heartbeat detects hard death | Existing graceful/crash regression passed; forced death isolated fixture needed |
| Host reboot | Broker protection persists; execution remains unarmed until verified recovery | Unverified; no actual reboot authorized |

Each new acceptance fixture must use NEW temporary stores, fake injected broker SDK, core.processes health checks, and strict no-network guard. Do not use current operator DBs, terminal or running processes for fault injection. Preserve existing safety tests. Record exact fail/pass logs and remaining uncovered branches; offline pass cannot prove real reboot/broker availability.

Implementation sequence: inventory current coverage by scenario; add missing isolated fixtures only after source stability permits changes; run focused/full offline suite and frontend checks; prepare a default-unarmed startup design and review concrete launch/recovery behavior. Do not introduce automatic rearming while durable recovery remains unqualified. Execution startup permission must not authorize clearing future integrity halts.

Success criteria: every failure case makes zero submissions; restart never duplicates accepted orders; broker/ledger quantities and net close cashflows agree; terminal/demo identity unchanged; API cannot arm; single owner; operator-visible state and timestamp accurate. Positive expectancy and pyramiding edge are separate research gates.

Next priority: current runtime close reconciliation; then coverage inventory for durable-intent crash points. No live faults required.

## Durable-order coverage inventory

Inspected exact assertions, then ran unchanged test_executor.py, test_main_durable_executor.py and test_resolve_intent.py:65passed in20.52s, zeroexternalnetworkattempts. No live fault or operator mutation. Coverage:

| Case | Existing test | Limit |
|---|---|---|
| Concurrent/restarted executor | test_restart_and_concurrent_attempts_do_not_duplicate, test_executor.py | Fake in-memory records, not hard kill |
| Persisted terminal intent | test_terminal_record_survives_restart_without_resubmission, test_main_durable_executor.py | SQLite fixture with mocked canonical runtime |
| Pending/unknown startup | test_unresolved_record_blocks_startup_without_reconciliation | Zero submissions; unresolved status preserved |
| Ambiguous/unrelated evidence | test_unresolved_record_without_evidence_remains_unchanged | Does not infer accepted identity from symbol |
| Recovery broker unavailable | test_unresolved_record_with_unavailable_broker_remains_unchanged | Fail-closed mocked error |
| Absence resolution | test_absence_requires_confirm_then_backs_up_and_audits_exact_intent, test_resolve_intent.py | Explicit offline operator resolution, not automatic restart |
| Broker match/history gap | test_broker_match_halts_even_with_confirm; test_unreadable_history_never_recommends_rejection | No false non-execution conclusion |

In particular, main startup deliberately BLOCKS unresolved intents rather than auto-reconciling and arming. A wrapper must preserve that behavior. In-memory executor restart evidence must not be reported as SQLite crash atomicity. Remaining isolated acceptance gap: two subprocesses with NEW durable fixture stores, abrupt exits at pending-before-submit, broker-accept-before-local-accept, accepted-before-ledger-write and ledger-before-alert; fake durable broker receipts; second process must observe zero duplicate submissions and retain halt for missing/ambiguous evidence. Also require Windows mutex owner exit/reacquisition in a NEW lock path.

No new fixtures/source changes during source-frozen research campaign. Next implement isolated crash-boundary fixture harness after campaign stability permits, then full offline validation. No auto-rearm or actual supervisor termination authorized by this inventory.
