# Hosted latency and relay diagnosis — 6 October 2026

Continues `aedde91` and `docs/chart-latency-2026-10-06.md`. Measurement was
read-only; no quota, authentication, risk, execution-gate or safety state
changed. Unrelated uncommitted backups (`data/historical.pre-*.sqlite3`),
`design/` and operator state are preserved.

## Instrumentation

The loopback relay now records its own evidence instead of untimestamped
saturation warnings only:

- one `origin fetch` line per origin read with `queue_ms` (wait for an origin
  slot), `fetch_ms` and the normalized query;
- one `request` line per finished response with `status`, `shared`
  (deduplicated concurrent read), `total_ms`, and for refusals the reason
  (`origin-queue`, `pending-full`, `origin-error`);
- saturation warnings keep the route and add the measured `queue_ms`.

Lines carry paths, queries, status and millisecond timings only — no
credentials, headers or bodies. The module logger writes INFO to the relay's
stderr, captured in `logs/relay-delivery-<timestamp>.stderr.log`.

## Hosted client scheduling change

The four-second client tick previously activated whole cohorts whose expensive
MT5-backed members monopolized the relay's four origin slots; cheap routes then
queued past the one-second budget and failed with 503. The workspace profile now
staggers steady-state refreshes across distinct ticks: chart and heartbeat
together; risk and safety four seconds later; terminal observation and execution
eight seconds later; watchlist +4 s, offline monitoring +8 s, cap usage +12 s,
notification status +20 s, assistant status +28 s (broker status keeps its own
tick). Refresh deadlines (15 s / 60 s after completion) are unchanged — only the
success path is offset, so initial loads, manual refresh, navigation,
symbol/timeframe changes and failure backoff still fire immediately, and the
15/30/60-second failure backoff still resets on success. No response, evidence
or permission is cached by the schedule.

## Before evidence (hosted, pre-stagger bundle)

Two windows of real owner traffic through the production chain:

1. Pre-instrumentation relay (started 10:03:27, stopped for reload 13:27):
   114 origin-queue saturation warnings — journal 18, execution/safety 14,
   terminal observation 13, watchlist 13, offline monitoring 12, execution 11,
   cap usage 11, notification status 10, risk 7, broker status 5.
2. Instrumented relay, 13:28:16 → 13:35:17, owner session still on the
   pre-stagger bundle: 551 finished responses (about 79/minute), 89 of them
   503 `origin-queue`, with 85 saturation warnings.

| route | n | median ms | p90 ms | max ms | max queue ms |
|---|---:|---:|---:|---:|---:|
| market/active-analysis | 23 | 7595 | 9160 | 9850 | 2202 |
| market/summary | 12 | 2978 | 3084 | 4493 | 787 |
| market/candles | 11 | 2907 | 3055 | 3099 | 926 |
| brokers/status | 20 | 1724 | 3300 | 4211 | 732 |
| signal | 12 | 1636 | 2897 | 3800 | 916 |
| research/paper-diagnostics | 17 | 491 | 562 | 1558 | 969 |
| monitoring/offline | 24 | 103 | 859 | 4291 | 308 |
| brokers/terminal-observation | 26 | 91 | 2834 | 4734 | 532 |
| system | 9 | 85 | 1679 | 1759 | 933 |
| observation/health | 42 | 71 | 1397 | 2776 | 0 |
| watchlist/cap-usage | 23 | 68 | 1215 | 4701 | 859 |
| execution | 35 | 65 | 1814 | 3104 | 851 |
| watchlist | 22 | 61 | 811 | 1439 | 981 |
| risk | 37 | 60 | 1638 | 3705 | 860 |
| performance | 18 | 54 | 91 | 98 | 608 |
| execution/safety | 39 | 49 | 1472 | 2434 | 847 |
| notifications/status | 22 | 46 | 129 | 860 | 867 |
| execution/paper-runtime | 20 | 46 | 107 | 2026 | 746 |
| execution/recovery | 18 | 44 | 85 | 1640 | 716 |

Routes that complete in 35–70 ms when uncontended queued up to 0.9–1.0 s and
were refused under load (risk, watchlist, cap usage, notifications, execution,
safety, heartbeat). `market/active-analysis` held a median 7.6 s (max 9.9 s)
with 2.2 s queue waits on its reserved chart slot; terminal observation, broker
status and offline monitoring reached 4.2–4.7 s. Of the 89 refusals, 41 hit
routes shared by both profiles, 45 hit legacy-profile-only routes (`system`,
`market/summary`, `market/candles`, `signal`, `performance`, recovery and
paper-runtime routes) and 3 hit the chart. Route-level attribution is inferred
from profile membership; the relay records routes, not browser windows. Two
sources remain visible: same-tick cohorts of expensive MT5-backed reads
monopolizing the four origin slots, and non-workspace tabs, which still bypass
per-resource deadlines and re-fire the whole 18-resource legacy profile on
every tick (effective cadence ≈ batch duration under load). The latter is
unchanged in this phase and is now the dominant browser-side residual.

## Deployment and verification

- Backend validation of the relay change: 19/19 bounded offline groups —
  2,574 passed, 4 skipped (reports/backend-20261006-132345). Relay tests 17
  passed; schedule tests 27 passed; full frontend suite 205 passed; production
  build passed. No code changed after this validation (documentation only).
- Relay reload was gated on that report: old listener stopped, new read-only
  relay started via `tools.start_monitor` with verified command line. Only the
  loopback relay restarted — API, MT5 terminal, supervisor, execution gates and
  safety state untouched. An unauthenticated loopback request still returns 403.
- Frontend production deployment `jqe-gr8hy4fis-joki-holdings.vercel.app`,
  aliased to https://jqe.vercel.app; the served bundle
  `assets/index-GTOmPRxq.js` was verified by content to contain the offset
  marker (content, not artifact hash).
- Incident during the deploy: the first attempt ran from a shell whose working
  directory was `D:\JQE\logs`, which holds a pre-existing Vercel link for a
  project named `logs`; that created one SSO-protected deployment of the log
  directory (302 to Vercel SSO, never publicly reachable) which was removed
  immediately. The `jqe` project was unaffected. Deploy `jqe` only from the
  repository root.

## After window (owner reload, 13:41:06 → 13:49:06)

The owner session returned at ~13:41 (initial 18-route sweep 13:41:04–17, then
continuous legacy-route traffic). Of the 909 finished responses in this window
(~114/minute), 177 were refused — all `origin-queue`, 19.5 % of responses
(compare the pre-stagger 16.2 %). The relay logged 702 origin fetches and 173
saturation warnings. Refusals per minute: 13:41 — 1, 13:42 — 15, 13:43 — 11,
13:44 — 25, 13:45 — 30, 13:46 — 27, 13:47 — 43, 13:48 — 23, 13:49 (partial) — 2.

| refused route | n | | refused route | n |
|---|---:|---|---|---:|
| risk | 27 | | research/paper-diagnostics | 7 |
| market/candles | 22 | | performance | 4 |
| execution | 21 | | notifications/status | 4 |
| system | 18 | | execution/safety | 4 |
| market/summary | 18 | | execution/paper-runtime | 3 |
| watchlist/cap-usage | 14 | | brokers/terminal-observation | 3 |
| signal | 14 | | execution/recovery | 1 |
| monitoring/offline | 9 | | | |
| watchlist | 8 | | | |

87 refusals hit legacy-profile-only routes (`system`, `market/summary`,
`market/candles`, `signal`, `performance`, recovery, paper-runtime and
paper-diagnostics routes); 90 hit routes shared by both profiles. The chart
(`market/active-analysis`) was never refused: 12 fetches, all 200, `queue_ms=0`
throughout and `fetch_ms` up to 9,978 ms — the chart's cost is origin-side
(MT5-backed read), not queueing, when the whole-profile cohorts leave it alone.
Terminal observation also reached only 3.1 s max and 3 refusals.

Interpretation: the sampled client was on a legacy tab — its 18-resource
cohorts refire on effectively every completed batch (~9 s under load), exactly
the residual listed below. The staggered workspace signature (chart + heartbeat
alone, then a few routes per tick) is absent from the window; workspace-profile
routes appear only in the initial sweep and in sparse chart fetches. Because
legacy tabs behaved identically in both bundles, the window cannot show which
bundle the browser held, and it confirms the stagger only protected the
workspace tab — the owner's Journal session saw no improvement.

## Follow-up fix — legacy tabs join the schedule (ed16a76)

The refetch-every-tick path for non-workspace tabs was removed: every profile
now filters through the observation schedule, so legacy tabs fetch only due
resources (15 s / 60 s deadlines, same offsets) between navigation sweeps.
Navigation, tab switches, symbol/timeframe changes and manual refresh still
sweep the full profile immediately via `replaceInFlight`, and failure backoff is
unchanged. Validation before deploy: new polling regression test (legacy cohort
stagger), App polling tests 25 passed, full frontend suite 208 passed,
production build passed. Deployed as `jqe-a600dd7v5-joki-holdings` (alias
jqe.vercel.app); the served bundle `assets/index-B-Aw0Sel.js` was verified by
content — calendar markup present, and the workspace-only poll short-circuit is
absent (the two remaining `!=="workspace"` comparisons are the Header and
telemetry-ribbon conditionals). Re-measurement of this fix needs the next owner
reload; expected signature: legacy ticks with a single due resource or a small
cohort, no repeated whole-profile refetch.

## Residual work

- The relay remains the throttle: four concurrent origin reads, one-second
  queue budget, no completed-response caching.
- Non-workspace pages now follow the same 15 s / 60 s deadlines as the
  workspace; their product freshness expectations should be confirmed with the
  owner (a cadence tweak is a one-line change in `observationSchedule.ts`).
- Re-measure the legacy-tab stagger after the next owner reload against this
  window's baseline.
