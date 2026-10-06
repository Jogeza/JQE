# Delivery cadence and dependency remediation — 6 October 2026

Continues `16e4288`. Unrelated uncommitted accounting, recovery, research,
design, backups and operator state are preserved.

The old successful-workspace schedule could launch twelve observations every
four seconds (180 requests/minute for a fast origin). It now checks resource
deadlines: chart, terminal, actual heartbeat, risk, safety and execution refresh
no sooner than fifteen seconds after completion; ancillary resources refresh
no sooner than sixty seconds. With four-second deadline checks, a fast warm
workspace sends approximately 28.5 requests/minute, about 84% fewer than before.
This is a scheduling estimate, not a measured network throughput claim.
Hidden tabs pause automatic Workspace polling. Repeated failures back off to thirty,
sixty and 120 seconds, reset by success. Manual refresh, navigation and market
changes bypass those deadlines. Timeframe changes still fetch only the three
market-dependent resources. Client concurrency is reduced from four to three.
The relay's total four-request origin limit and quota are unchanged.
Failed chart/heartbeat requests publish their error promptly instead
of waiting for a slower ancillary request. Retained evidence is not relabelled
as live.

Origin baseline: a sequential read-only probe observed active analysis taking
13.736 seconds, terminal 1.344 seconds, risk 1.384 seconds, broker status 1.665
seconds and cap usage 0.015 seconds. One health request exceeded twenty seconds;
a later isolated health probe succeeded in 2.93 seconds. The supervisor's
separate actual heartbeat was RUNNING, process alive, fresh, cycle 77. Unsigned
relay health remained 403. Probe timestamps and variability mean these values
are illustrative, not an origin service-level guarantee. No process was
restarted during this baseline measurement.

The first reduced-polling deployment still showed intermittent failures.
Origin logs showed overlapping journal and legacy-profile reads beyond the
active Workspace schedule. The relay now shares a single task for authenticated
concurrent identical path/query reads, with query order normalized but duplicate
parameter order preserved. Different symbols/timeframes remain separate.
Completed tasks and errors are evicted immediately: no response cache or stale
heartbeat replay is introduced. Every caller independently passes authentication,
allowlist and the existing 600/minute quota. Distinct pending keys are bounded
at 32. Client cancellation does not cancel a shared read needed by another
caller. Of the existing four origin slots, one is reserved for observation
health and three serve other routes, preventing chart contention from consuming
the entire heartbeat budget. The twelve-second origin timeout remains.

Dependency review identified six npm findings in development/build tooling,
not a demonstrated compromise of the deployed static client. Updated Vite
5.4 to 7.3.7, Vitest 3.2 to 4.1.11 and React plugin 4.3 to 5.2.0; compatible
transitive patches include esbuild 0.28.2 and source-map-js 1.2.2. Vitest no
longer includes the vulnerable tinypool dependency. Node 24.18 locally and
Vercel project's configured Node 24.x satisfy the upgraded tools. Both full
and production-only npm audits reported zero vulnerabilities on this run.

Reviewed advisories:
- https://github.com/advisories/GHSA-85c8-ppgw-ccpr (tinypool prototype pollution)
- https://github.com/advisories/GHSA-82fw-gwwq-j7x9 (Vitest mock redirect traversal)
- https://github.com/advisories/GHSA-fx2h-pf6j-xcff (Vite Windows path deny bypass)
- https://github.com/advisories/GHSA-68fv-2mgg-jv7q (source-map-js denial of service)
- https://github.com/advisories/GHSA-67mh-4wv8-2f99 (esbuild development-server access)

Validation so far: focused polling tests 26 passed; all frontend 191 passed
in 31 files; TypeScript/Vite production build passed (1,937 modules). Tests
exercise cadence separation, capped/resetting backoff, hidden-tab pause/resume,
manual refresh override, abort behavior and market-only switching. Existing
chart/drawing/reduced-motion/supervisor tests also pass. Large bundle warning
remains. The deployment ignore list excludes unrelated /design/ artifacts.

Initial backend validation: 2,568 passed, four skipped; every one of nineteen
groups exited zero, with 188 test files (`reports/backend-20261006-092854`).
Intermediate production deployment `dpl_4jYySXt5yMLRBbHf5sKTX7Ze7KUC` reached READY:
https://jqe-o0grcw66c-joki-holdings.vercel.app. Production install audit also
reported zero findings and the production build passed. No trade, risk limit, execution gate, quota,
authentication rule, permission, paid checkout or persisted safety state was
changed by this phase.

Final validation: all frontend 191 passed and production build passed again
after the client concurrency change. Relay/hosted focused tests: 19 passed.
Full final backend suite: 2,572 passed, four skipped, all nineteen groups exit
zero (`reports/backend-20261006-093912`, 188 files). Relay tests verify eight
identical reads share one call, subsequent reads fetch again, rejected callers
cannot join, M1/M5 isolation, cancellation, error eviction and a health read
succeeding with three occupied market slots. Existing quota and mutation-denial
tests pass.

Final frontend deployment `dpl_DGH292PKaB5yy71iHWfrsxDGu8ZM` reached READY:
https://jqe-i9owpxt6u-joki-holdings.vercel.app. Production npm audit: zero findings.
Only the loopback read-only relay was reloaded (listener PID 24372, port 8766);
the API remained PID 23276, supervisor PID 3080 and terminal PID 10200.
New relay log: logs/relay-delivery-20261006-094539.stderr.log. A post-reload
local health read returned 200 in 0.08 seconds; actual heartbeat RUNNING,
cycle 81, fresh, process alive. Unsigned relay health remained 403.

Final rollout: the uncommitted relay revision above is validated and reloaded.
The complete backend group runner passed: 2,577 tests, 2,573 passed, four
skipped, zero failures and zero errors across nineteen groups with 188 files
(`reports/backend-20261006-095120`; totals.json checked). Only the loopback
read-only relay was reloaded: listener PID 28244, launcher PID 22376, log
logs/relay-delivery-20261006-100327.stderr.log. The API (PID 23276), supervisor
(PID 3080) and terminal (PID 10200) were not restarted and were still alive at
this writing. Unsigned relay health remained 403. Sustained hosted verification
observed the supervisor heartbeat advancing to cycle 87, fresh, process alive
(10:15:45 to 10:19:27). During that window the relay logged 108 bounded-queue
saturation warnings, answered as 503 with Retry-After: 2 instead of unbounded
queueing; intermittent monitor gaps under bursts remain possible and are
reported, not hidden.

Mobile/UX pass from the same phase: the Workspace mobile top header now
retracts after 48px of downward scroll and restores on upward scroll, tab
change or near the top; mobile timeframe buttons are compact in one row beside
the Compact-prices toggle; chart shapes are selectable, movable and deletable
on touch (tap to select, drag to move, Delete bar or Delete/Backspace, Escape
resets); duplicated workspace copy was removed; and a first-sign-in quick tour
(once per device) covers navigation, the chart, drawing and evidence labels
without any execution claim.

Final frontend validation: all frontend tests 202 passed in 34 files;
TypeScript and Vite production build passed (1,939 modules; the pre-existing
large-bundle warning remains). Final production deployment
https://jqe-ajwecdfsj-joki-holdings.vercel.app is aliased to
https://jqe.vercel.app; the served bundle was verified to contain the
header-retraction, compact-timeframe, drawing-edit and quick-tour code. On
this run `vercel --prod` without `--scope` returned "Not authorized";
deploying with `--scope joki-holdings` succeeded.

Limitations: hosted pixel-level verification of the new UX requires an owner
session and was not performed; the served production bundle and HTTP response
were verified instead. Strategy SL/TP overlay rendering still cannot be
visually verified while the strategy reports NO_TRADE. No trade, risk limit,
execution gate, quota, authentication rule, permission, paid checkout or
persisted safety state was changed by this phase.

Privacy gating: source and operational disclosures in the Workspace and
Dashboard are now owner-only. Per-panel "Source details" provenance, the
Settings "Connection and operational checks" block (including Readiness),
"Snapshot details", "Observation details", "Safety evidence" and API path
prefixes render only when the local workstation or a server-verified admin
session is active, computed once as `internalDetails = workstation || admin`.
The default is false; no email address is embedded in the client. A hosted
owner gains visibility only after the Supabase profile role is set to 'admin'
(`update public.jqe_profiles set role = 'admin' where id = '<verified-auth-user-uuid>';`,
see docs/hosted-auth-deployment.md); without it the compact public view is
shown. Metric values, state chips, reason codes, terminal observation and the
supervisor heartbeat remain visible to every signed-in user; only provenance
and internal operational detail are withheld.

Card wording was compacted to a value-forward layout: one label, one value and
at most one short muted caption per metric; trading permissions render as
coloured ✓/✗/· glyphs instead of a slashed sentence; the duplicated NO_TRADE
reason line on the Strategy score stage was removed; and the removed
explanatory prose was consolidated into one collapsed "Metric definitions and
platform notes" disclosure that remains visible to all users. No metric,
threshold, security or execution semantics changed; new tests assert both the
non-admin absence of gated strings and their presence for the owner.

Final validation for this phase: focused workspace tests 57 passed; all
frontend 204 passed in 34 files; TypeScript and Vite production build passed
(1,939 modules; the pre-existing large-bundle warning remains).

Privacy follow-up: source and observation details were removed from every
normal user-facing page for every user, including the owner. The Workspace
decision/market view no longer renders per-panel "Source details", "Snapshot
details", "Observation details", "Safety evidence" or API path prefixes even
when internal details are enabled; those disclosures were consolidated into
one "Source and observation details" block that renders only inside the
Settings configuration view and only for the owner (`internalDetails`,
unchanged role gate). The Dashboard "Connection and data provenance" block was
extracted into a dedicated owner evidence panel that likewise renders only in
Settings. The SyntX market cards no longer display per-card backend provenance
("Weltrade MT5 terminal" / "Weltrade MT5 shadow archive"); the backend DTO and
card metrics are unchanged. Research experiment catalog provenance (dataset,
run and result hashes) and the Markets market-data-source badge remain, as
research metadata and product-level data transparency. Tests were refreshed to
assert both the absence of gated strings in the plain owner view and their
presence in the owner Settings view, and the non-admin absence. Focused
workspace tests 57 passed; all frontend tests 204 passed in 34 files;
TypeScript and Vite production build passed (1,940 modules; the pre-existing
large-bundle warning remains). No trade, risk limit, execution gate, quota,
authentication rule, permission, paid checkout or persisted safety state was
changed by this follow-up.

Production deployment for the privacy follow-up:
https://jqe-898939ftt-joki-holdings.vercel.app reached READY (38 s) and is
aliased to https://jqe.vercel.app. Deployed from the repository root with
`vercel --prod --scope joki-holdings` (the project root directory is
`frontend`). The served bundle was verified after deployment: index 200 and JS
bundle 200 (829,629 bytes) containing "Source and observation details" and
zero "Snapshot details"/"Observation details"; the only remaining "Safety
evidence" string is the actionable blocked-execution alert in Notifications.
The CSS asset hash matches the local build; the JS hash differs because Vercel
inlines its environment values at remote build time.
