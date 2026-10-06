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

## After window — pending owner reload

The staggered bundle is live, but a hosted page only replaces it on reload, and
the owner's session kept the previous bundle throughout the sample above, so no
after-window exists yet. Expected signature once a reloaded client is observed
in `logs/relay-delivery-20261006-132757.stderr.log`: chart with heartbeat alone
at one tick in roughly sixteen seconds, at most a few routes per tick, and the
ancillary resources spread over distinct ticks instead of one 60-second cohort.
The table above is the comparison baseline.

## Residual work

- Extend per-resource deadlines to non-workspace tabs (whole-profile refetch
  every tick) — the largest remaining browser-side source; needs its own
  product decision on freshness for those pages.
- The journal route was the top saturation source in the long window; it is
  part of the same legacy-profile path.
- The relay remains the throttle: four concurrent origin reads, one-second
  queue budget, no completed-response caching.
