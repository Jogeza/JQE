# Hosted observation polling recovery — 6 October 2026

Continues chart phase commit `7111e92`. The left price axis, compact/full
scale, clean setup labels, responsive drawing rail, scoped drawing persistence
and reduced-motion-aware live border glow remain deployed.

The observation relay previously allowed an unbounded wait for its four origin
slots. Workspace polling launched twelve requests together; three hidden menu
badge copies independently polled the decision journal. This phase bounds
frontend observation concurrency to four, prioritizes chart/terminal/heartbeat,
publishes heartbeat promptly, reuses that evidence in menu badges, and prevents
overlapping journal refreshes. Timeframe changes request only analysis, terminal
observation and risk. The existing uncommitted market-only refresh optimization
is included as a dependency of this phase.

The relay now rejects saturated queues after one second with 503 and Retry-After
instead of retaining obsolete requests indefinitely. Origin timeout is twelve
seconds. Authentication, owner checks, allowlisted read-only routes, four origin
slots and the existing quota are preserved. Only the loopback read-only relay
was reloaded after validation. MT5, API, supervisor, tunnel, execution gates,
risk limits and safety state were not changed.

Validation: focused frontend 29 passed; focused relay/hosted backend 15 passed;
all frontend 187 passed in 30 files; production build passed. Full offline
backend group suite: 2,568 passed, four skipped, all nineteen group exit codes
zero (`reports/backend-20261006-042259`). Git diff whitespace check passed.

Production deployment `dpl_91AiGN5d9TKFypaTZZmR7ZPxCKqG` reached READY,
URL https://jqe-d6lvfwl1g-joki-holdings.vercel.app, serving the custom domain
https://jqe.jokiholdings.com. Authenticated hosted M15 returned a canonical
FX VOL 20 / M15 snapshot with latest closed candle 04:30 EAT. Hosted M1
returned a canonical FX VOL 20 / M1 snapshot with latest closed candle 09:20
EAT. Hosted M5 returned canonical FX VOL 20 / M5 with latest closed candle
09:20 EAT, matching direct terminal close 119953.62. Terminal evidence followed
the selected timeframe. These are successful snapshot checks, not proof that
all successive requests remain live.

The hosted supervisor panel displayed fresh RUNNING evidence, timestamp,
computed age, cycle number (75, subsequently 76), process alive and stale No.
Observation API orders remained Disabled and the monitoring-only caveat was
visible. A local read-only probe independently confirmed the live process and
fresh heartbeat. Unsigned relay health requests still returned 403.
Browser computed styles confirmed jqe-live-glow on LIVE supervisor evidence
and live cards, and no animation on LOADING/STALE cards. Compact prices toggled
successfully while retaining the left axis and chart. The available in-app
viewport remained 542 pixels wide despite requested 390/820 overrides; at that
observed width there was no document overflow, all four timeframe controls
were 44 pixels high, and the drawing rail scrolled horizontally. Exact requested
breakpoints remain covered by the previous phase validation rather than this
browser session. Screenshots are in ignored reports/production-polling-*-20261006.png.
Previous phase tests cover reduced
motion, scale changes, drawing coordinates/persistence and stale heartbeat.

Limitations: intermittent relay saturation and unavailable ancillary resources
continue; successful data deliveries do not establish sustained reliability.
The old forward collector has stale evidence. The build retains its large
bundle warning; deployment npm audit reported six vulnerabilities (two moderate,
two high, two critical) without dependency changes in this phase. Reduced motion
was stylesheet/test verified, without changing the operator's system setting.
Compact axis width can exceed its requested minimum for long price labels;
drawings persist in the current browser tab only.

Unrelated accounting, research, recovery, design, reports, backups, databases
and secrets remain outside the phase commit. No trade was submitted by this
development work. Recommended next phase: measure per-route origin latency and
reduce aggregate multi-tab polling contention without widening access or quota;
then address dependency audit findings with separate reviewed updates.
