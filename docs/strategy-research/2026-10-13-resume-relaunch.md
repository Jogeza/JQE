# 2026-10-13 — Interruption diagnosis, safety commits, and fifth qualified label resume

## Scope

Diagnose the fourth silent campaign interruption, protect two weeks of
uncommitted work, remove the host-sleep root cause, and relaunch the frozen
registered training-label campaign as a NEW immutable resume segment.
No ML fit, candidate, holdout evaluation, terminal mutation, execution,
gate, safety-state, dotenv or data changes occurred in this work.

## Interruption diagnosis (cause now known)

- Windows System event log (IDs 41/6008) shows repeated *unexpected* shutdowns:
  Oct 6, Oct 8 (x2), Oct 9 (x2), ~Oct 10 22:29, Oct 12 23:05, plus user
  restarts Oct 10/12 10:16 and boot Oct 13 10:47.
- The Oct 11 segment (resume-20261011-01) wrote its last fsynced ledger entry
  at 23:01:47 local and then went silent with no traceback and no FAILED
  states — consistent with host idle-standby, not campaign code. Balanced
  power plan had **standby 15 min AC / 10 min DC, hibernate 15 min AC**;
  Windows user-idle sleep ignores background processes.
- This explains all four documented "cause unknown" interruptions
  (AGENTS.md sections 20/44/49/58).
- The demo supervisor's Oct 11 22:48 exit is separate and correct fail-closed
  behavior: final heartbeat STOPPED/PreflightBlocked with
  DAILY_HISTORY_UNAVAILABLE + DAILY_STATE_NOT_AUTHORITATIVE; the decision
  journal shows BrokerConnectionError entries in the same window. No
  post-fill integrity halt exists; no clearance is needed to restart it.

## Host power change (reversible)

`powercfg -change` set standby/hibernate timeouts to zero (AC and DC).
Before-values and restore command: `reports/power-settings-20261013-01.json`.
Hybrid sleep remains on but is moot with zero timeouts.

## Safety commits (content-identical)

The 192-file dirty tree on `feat/institutional-architecture` was committed in
five scoped commits `1fe8179`..`35a247b` (research infrastructure, runtime,
frontend, dated docs, design). Working-tree contents were not modified by
committing; the current source still matches the qualified transition
contract (`load_transition` binding passed at launch). Secrets scan clean.
Only four ~4.7GB `data/historical.pre-*.sqlite3` backups remain untracked
deliberately.

## Inherited state at relaunch (verified)

| Segment | COMPLETED | Unfinished STARTED |
|---|---|---|
| long-history-label-campaign-20261009-01 | 53 | 1 |
| resume-20261010-01 | 178 | 1 |
| resume-20261010-02 | 11,383 | 1 |
| resume-20261011-01 | 2,477 | 1 |

Total: 14,091 unique completed pairs, 4 interrupted attempts (three already
retried+completed in later segments; `4804fac.../assumed_3usd` remains open),
zero FAILED entries, no summary in any segment, all four owner PIDs dead,
resume-evidence ancestor chains verified as exact prefixes, 72GB free disk.

## Fifth resume launch

- Campaign: `reports/long-history-label-campaign-resume-20261013-01`
  (227,847 attempts remaining of 241,938; same registration and transition
  contract `lineage-integration-qualification-20261010-02/contract.json`).
- Runtime: `reports/label-resume-runtime-20261013-01`; launcher redirector
  PID 1604, real worker PID 21232, watcher PIDs 5744/19564.
- Launcher `reports/launch-qualified-label-resume-20261013.py` performed the
  cheap structural preflight (source binding, dead owners, exact ledger
  counts, ancestor chains, registration hash equality, >12GB disk) and
  launched the canonical CLI detached with `PYTHONUNBUFFERED=1`.
- The canonical CLI revalidates every inherited artifact (load_result/
  verify_result) fail-closed before replay; for 14,091 artifacts this is
  expected to take several hours with no stdout output. At ~20 minutes in,
  worker 21232 was saturating one core (CPU seconds advancing ~1:1 wall).
- Watcher `reports/watch-qualified-label-resume-20261013.py`: after owner
  exit it runs the complete five-segment audit into
  `reports/qualified-label-complete-coverage-20261013-01`, or records
  STOPPED_WITHOUT_SUMMARY; never auto-resumes; capacity alert below 12GB.

## Honest limitations

- Launch is not completion. No new labels exist yet; the CLI preflight must
  finish before the first new attempt. At the observed historical pace the
  full remainder is a multi-day run even without further interruptions.
- Feature extraction and ML remain blocked pending the complete
  241,938-pair/3,099-censor audit PASS.
- Two demo positions (572269526 SFX Vol 20 BUY 0.01, 572302885 SFX Vol 99
  SELL 0.03) were left open by the dead supervisor; their state was
  unresolved in this handoff's first pass. **Resolved 17:11 UTC (see
  below).**
- Possible one-trade overshoot of max_trades_daily=5 on Oct 11 (6 executed
  entries 16:35-19:40 UTC) needed verification before re-arming the
  supervisor; **resolved 17:11 UTC (see below).**
- Estimated ~4.5GB additional shared storage at completion; 76.5GB free now.

## Read-only position and cap verification (2026-10-13 17:11 UTC)

Evidence: `reports/demo-position-close-check-20261013-01.json`. Read-only
MT5 attach only (initialize, no login); no orders, no ledger writes.

- Both "open" ledger positions actually **closed at the broker on Oct 11**,
  after the supervisor's last cycle (22:48 UTC):
  - 572269526 SFX Vol 20 BUY 0.01: STOP_LOSS 21:41:11 UTC @ 32842.84,
    profit -0.70 USD.
  - 572302885 SFX Vol 99 SELL 0.03: TAKE_PROFIT 21:04:49 UTC @ 1616.32,
    profit +1.13 USD.
- Account 43268111 Weltrade-Demo: balance = equity = 138.80 USD,
  margin 0.00, **zero open positions**; reconciles exactly
  138.37 + 1.13 - 0.70 = 138.80. Zero commission/swap observed (scope
  caveat unchanged).
- Ledger rows remain recorded open (reconciliation never ran), but there is
  **no post-fill integrity halt** and no CLOSE_UNCONFIRMED state. The
  supervisor heartbeat is STOPPED (pid 21488 dead).
- Oct 11 daily-cap question: **no overshoot**. The implemented
  `max_trades_daily=5` check counts trades CLOSED today (UTC), rebuilt from
  broker closed-deal history each cycle (main.py:572/887, risk_engine
  evaluate_limits, mt5_gateway counts OUT/INOUT only). The 6th entry
  (19:40:16 UTC) was submitted at closed-count 4 < 5 and is permissible
  under that check; no 7th entry was attempted. Disclosed quirk: the
  global cap is a closed-trade cap, not a submission cap; the
  per-instrument cap (20/day) usage was 6/20 (SFX Vol 20) and 2/20
  (SFX Vol 99).
- Campaign segment 20261013-01 healthy at snapshot: launcher 1604,
  worker 21232, watcher 5744/19564 all alive; campaign dir created but no
  new ledger lines yet (inherited-artifact verification phase). 76.5GB
  free.

## Canonical ledger reconciliation (2026-10-13 17:13 UTC)

Owner-authorized. `tools/inspect_close_history.py --reconcile`, exit 0,
log `reports/demo-position-reconcile-20261013-01.log`, evidence
`reports/demo-position-close-reconciliation-20261013-01.json`.

- Backup first: `state/backups/execution_positions-pre-close-reconcile-
  20261013T171313Z.sqlite3` (sha256 8f983d7c...7730) preserving the
  pre-reconcile open rows.
- Both rows now CLOSE_CONFIRMED matching broker deals exactly: 572269526
  STOP_LOSS -0.70 @ 32842.84, 21:41:11 UTC; 572302885 TAKE_PROFIT +1.13 @
  1616.32, 21:04:49 UTC. Zero open ledger rows remain; halt table still
  empty; notify disabled; attach-only session, no login, no order calls.
- Supervisor re-arm is NOT part of this step and still requires explicit
  authorization; recheck broker daily-history availability at that time.

## Supervisor re-arm and first supervised trade cycle (2026-10-13 17:32–17:43 UTC)

Owner-authorized re-arm with the five-position cap and partial-management
flags (scope: this launch only). All flags process-local; shared dotenv
unchanged. Evidence `reports/demo-supervisor-rearm-20261013-02/
verification.json` (launch-moment record in `launch.json` is superseded by
it and kept immutable).

- Attempt 01 (`reports/demo-supervisor-rearm-20261013-01`) failed closed on
  a transient `PermissionError WinError 5` during the heartbeat atomic
  replace (concurrent reader can briefly block `os.replace` on Windows).
  The worker passed catch-up reconciliation and its first preflight before
  exiting: zero orders, zero ledger/guard mutations. Preserved.
- Attempt 02 RUNNING: launcher 10596 / worker 8216; heartbeat cycle 2
  "14 pairs evaluated", `execution_enabled: true`. Verification reads kept
  sparse (single-shot) to avoid repeating the attempt-01 contention.
- Cycle 1 (17:35 UTC): 8 NO_TRADE; 6 risk-approved candidates rejected by
  canonical sizing — five "MT5 authorized risk is below the broker minimum
  lot risk" (SFX VOL 20:M5, FX VOL 40:M1/M5, FX VOL 60:M5, FX VOL 20:H1)
  and one "Risk budget cannot fund two minimum-volume portions"
  (SFX VOL 20:M1, partial-management rule). Zero orders.
- Cycle 2 (17:40 UTC): first accepted supervised order in this segment —
  SFX VOL 20 M1 BUY 0.02 (order 575159424, deal 543457958) filled 33701.24,
  SL 33672.30, TP 33770.94; planned entry 33705.18, expected loss 0.66
  within authorized 0.694 USD; two equal 0.01 portions registered (READY;
  +1.5R never reached). Same pair had been sizing-rejected in cycle 1 —
  canonical price/ATR-dependent sizing, no rule changed. Four pairs blocked
  by sizing, nine NO_TRADE.
- Broker stopped the position out ~2 minutes later (deal 543460652,
  33672.2, profit −0.58, zero commission/swap). The close monitor
  reconciled the ledger automatically: CLOSE_CONFIRMED at 17:42:15 UTC,
  partial row CLOSED. Balance reconciles exactly 138.80 → 138.22 USD;
  read-only attach (no login, identity verified) confirms zero open
  positions afterward.
- Limits after cycle: closed trades 1/5; daily loss 0.58 USD (0.42% vs 3%
  cap); per-instrument submissions SFX VOL 20 1/20, SFX VOL 99 0/20.
  No risk relaxation, no min-lot rounding, no manual orders, Telegram
  remains disabled.
- A single fill and a stop-out are operational events, not edge or
  expectancy evidence. Future halts do not inherit any prior clearance;
  any future launch must explicitly supply the cap and execution flags.

## Supervisor trading continuation (2026-10-13 18:22 UTC snapshot)

- Cycle 10 RUNNING, steady 5-minute cadence (112 decision rows 17:45–18:21,
  no gaps). Evidence `reports/supervisor-campaign-monitor-20261013-01.json`.
- Five orders total today; all two-portion 0.02 with expected loss 0.39–0.66
  within the authorized 0.694 USD. Three closes, realized net +1.66 USD,
  zero observed commission/swap; balance 140.46 = 138.22 + 1.15 + 1.09 exact.
- 575166027: **first live partial-management execution** — 0.01 closed at
  +1.5R (deal 543480128, +0.54, favorable fill), remaining stop moved to
  +0.5R (store PROTECTED), remainder then exited at TP 33730.46 (+0.61);
  total +1.15, ledger CLOSE_CONFIRMED. `close_reason UNKNOWN` is the close
  monitor's honest classification for mixed exits (partial + TP); PROTECTED
  partial rows are terminal by design in `manage_partials` — the ledger
  holds the final outcome.
- 575192335: TAKE_PROFIT +1.09 (price crossed 1.5R→2R between monitor ticks;
  the whole 0.02 exited at TP and the partial never fired — by design).
- Open at snapshot: 575179941 SFX VOL 99 M5 (−0.13 floating) and 575213140
  SFX VOL 20 M1 (+0.17). Duplicate-symbol guard observed blocking correctly
  at 18:00 while those symbols had open positions.
- Limits: closed trades 3/5; submissions SFX VOL 20 4/20, SFX VOL 99 1/20;
  emergency stop CLEAR; zero unresolved intents; zero halts.
- Campaign segment: worker 21232 alive with 8,060s CPU (actively working),
  still in the silent inherited-artifact verification phase (no ledger yet —
  expected); watcher 5744/19564 alive; 72GB free.
- This is small-sample operational evidence, not expectancy.

## Supervisor daily-cap stop and session close (2026-10-13 18:29 UTC; observed 2026-10-14 00:02 UTC)

Evidence `reports/supervisor-daily-cap-stop-20261013-01.json`. Read-only
verification only; no orders, gates, terminal, dotenv or safety-state changes.

- The supervisor stopped fail-closed at cycle 11, heartbeat 18:29:18 UTC
  STOPPED/PreflightBlocked; launcher 10596 / worker 8216 dead, zero residual
  supervisor processes. Reason: `DAILY_RISK_LIMIT_REACHED` (5/5) +
  `READ_ONLY_PREFLIGHT_NO_ORDER_INTENT`.
- Sequence: the 18:29:16 partial close of 575213140 was the 5th **closing
  deal** of the day; the preflight immediately after that cycle blocked. The
  cap counts closing deals whose `closed_at` is today (UTC), rebuilt from
  broker closed-deal history each cycle (`risk/risk_engine.py:107-126`;
  `broker/mt5_gateway.py get_trade_history` keeps OUT/INOUT only) — so
  partial-management half-closes consume daily-cap slots. Disclosed quirk,
  no rule was changed.
- All five positions are now broker-confirmed closed. Per position:
  575159424 −0.58 (SL 17:42:11); 575166027 +1.15 (partial +0.54 @ +1.5R,
  remainder TP +0.61); 575192335 +1.09 (TP); 575213140 +1.12 (**second live
  partial execution**: 0.01 @ +0.50 at 18:29:16, stop moved to +0.5R
  PROTECTED, remainder TP +0.62 at 18:31:28); 575179941 −0.64 (never reached
  +1.5R, stopped at its original stop 18:32:57).
- Session net realized +2.14 USD, zero observed commission/swap; balance
  138.80 → 140.94 exact. The last two closes happened **after** the
  supervisor exited, with broker-side SL/TP intact — no unprotected exposure.
  Read-only attach (no login, identity verified) shows zero open positions,
  balance = equity = 140.94 USD.
- Ledger: 575179941 and 575213140 remain open/unreconciled (no close-monitor
  cycle ran after 18:29). The supervisor runs `monitor_weltrade_closes`
  before each preflight (supervisor lines 63/83/107), so the next start
  auto-reconciles both rows before any trading; partial registry rows
  self-heal the same way (needs `manage_partials` pass). **No manual repair
  was performed.** Halt table empty; zero unresolved intents.
- The daily cap resets at 00:00 UTC (already passed, 2026-10-14T00:00:00Z).
  Re-arm was **not** performed: the section-77 authorization was scoped to
  that launch, no auto-restart exists, and any new launch must explicitly
  supply the process-local execution/cap/partial flags.

## Campaign progress checkpoint (2026-10-14 00:01 UTC)

- The 14,091-artifact inherited verification finished mid-evening: first new
  result file at 19:43:49 UTC, steady ~5.3s/attempt since. At snapshot:
  **2,894 new completed pairs** + 14,091 inherited = 16,985 of 241,938
  (matches launch baseline 227,847 remaining minus 2,894 = 224,953). Trials
  ledger 5,788 lines (2 per completed + 1 active); zero FAILED; worker 21232
  alive (27,640s CPU), watcher 5744/19564 alive; source binding stable;
  76.5GB free; no summary yet.
- Sampled saved-artifact audit (read-only chronological 10-pair sample):
  `reports/qualified-label-sampled-audit-20261013-01.json` — PASS, zero
  errors: artifact hashes, registered result identities, canonical prefix
  vs original baseline, frozen market model, label timing all verified; all
  10 sampled labels NON_EXECUTABLE/null. **Partial sample only** — the full
  241,938-pair/3,099-censor audit remains the feature/ML gate.
- At ~5.3s/attempt the remaining ~225k attempts project to roughly two weeks
  of continuous runtime; monitor capacity and host power stability.

## Owner-authorized supervisor re-arm (2026-10-14 00:06 UTC)

New explicit owner authorization 2026-10-14 ("re-arm the supervisor"); the
section-77 authorization had ended at the daily-cap stop. Evidence
`reports/demo-supervisor-rearm-20261014-01/` (preflight.json, launch.json,
verification.json); launcher `reports/launch-demo-supervisor-rearm-20261014-01.py`.

- Launcher fail-closed preconditions: previous heartbeat STOPPED/PreflightBlocked
  with dead pid 8216; halt table empty; zero unresolved intents; unreconciled
  ledger rows EXACTLY the two broker-verified closes (575179941, 575213140 —
  any unexpected row aborts); emergency stop CLEAR; disk >12GB. Process-local
  flags only (execution=true, cap 5, partial management, telegram off; shared
  dotenv unchanged). Redirector 19320 / worker 16492; launch 00:06:06 UTC.
- The supervisor's startup catch-up monitor reconciled both pending rows
  canonically **before** the first preflight (lines 63/83/107): 575179941 →
  CLOSE_CONFIRMED STOP_LOSS −0.64 (18:32:57), 575213140 → CLOSE_CONFIRMED
  UNKNOWN +1.12 (mixed partial+TP, 18:31:28) — both matching broker deals
  exactly; partial registry 575179941 self-healed READY → CLOSED. No manual
  repair was needed or performed.
- Cycle 1 (00:10:07–00:10:28 UTC, 14 pairs): 7 NO_TRADE, 6 pre-submission
  rejections (journal bucket `BrokerConnectionError`; canonical sizing reasons
  in the run log), **1 accepted order 575518694** — SFX VOL 20 M1 BUY 0.02,
  planned entry 34554.64, actual fill 34561.27, SL 34528.08 / TP 34607.76,
  authorized risk 0.7047 (expected loss at stop 0.53), two 0.01 portions
  registered READY. Intent ACCEPTED 00:10:09; ledger row open.
- Post-restart safety state: daily 0/5 closed (UTC reset), halt-free, zero
  unresolved intents, emergency stop CLEAR, balance 140.94 (equity 140.82 with
  the open position). One accepted order is operational evidence, not
  expectancy; outcomes reconcile through the supervisor's own close monitor.
- Campaign continues unaffected: ~17,000/241,938 pairs at 00:04 UTC,
  worker 21232 alive, no summary.

## Monitoring checkpoint and local frontend session (2026-10-14 00:33 UTC)

Evidence `reports/frontend-session-20261014-01/` (launch.json, session.json,
workstation-desktop.png, service logs). Read-only loopback services only; no
orders, execution-gate/safety-state, terminal, dotenv or source changes; no
deployment.

- Supervisor worker 16492 RUNNING (heartbeat 00:25:03 UTC, cycle 3). Order
  575518694 (SFX VOL 20 M1 BUY 0.02) closed 00:22:12 UTC **TAKE_PROFIT +0.96**,
  ledger CLOSE_CONFIRMED automatically by the close monitor; balance
  140.94 → 141.90 (equity 141.99). Order 575522313 (SFX VOL 99 BUY 0.02,
  accepted 00:15:10 UTC) still open at snapshot (+0.08 floating). Daily state:
  1/5 closed deals today (UTC), halt-free, zero unresolved intents, CLEAR.
- Campaign: 3,200 new + 14,091 inherited = **17,291 of 241,938**; one active,
  zero FAILED, campaign owner 21232 alive (fresh heartbeat RUNNING 00:32:12
  UTC), no summary; 76.45GB free.
- Local frontend session launched for owner review: read-only API
  (`uvicorn api.app:app`, 127.0.0.1:8000, launcher 10888 / server 16748,
  observation API orders Disabled) and Vite dev server (pid 12156, VITE
  7.3.7). URL **http://localhost:5173/** (IPv6-bound; 127.0.0.1 refused);
  workstation view at **/workstation** (dev-only direct render for local
  hostnames, `frontend/src/main.tsx:13`).
- Populated views verified: account summary Weltrade DEMO 141.90 USD
  observed 00:23:25 UTC; FX Vol 20 M5 chart with EMA50/EMA200 LIVE;
  Execution & history shows open 575522313; decision card NO TRADE /
  Risk BLOCKED / Execution BLOCKED (evidence only); Weltrade terminal panel
  shows supervisor RUNNING / cycle 3 / fresh heartbeat, DEMO ****8111,
  balance 141.9 / equity 142, permissions OK, realized net UTC +0.96,
  starting balance 00:00 UTC 140.94, tick/closed-candle/economics reads.
- Known display lag (not an integrity issue): the History tab does not yet
  list the 00:22:12 close because the convenience reader
  `Mt5Gateway.get_trade_history` (broker/mt5_gateway.py:920-928) passes
  unshifted UTC bounds, trailing by the 10800s server offset — the
  documented 2026-10-11 recent-history diagnosis (AGENTS.md §76). The
  authoritative server-shift snapshot reader and the supervisor's close
  monitor reconciled the close correctly.
- One take-profit close and a populated UI are operational evidence, not
  expectancy.

## Next

1. Monitor the re-armed supervisor (worker 16492): cycles, fills, partial
   management, automatic close reconciliation; keep verification reads sparse.
   No risk/limit changes without explicit owner authorization.
2. Monitor the existing campaign segment (ledger/capacity/watcher).
3. Complete 241,938-pair coverage audit remains the gate before feature
   extraction and ML; holdouts stay sealed.
