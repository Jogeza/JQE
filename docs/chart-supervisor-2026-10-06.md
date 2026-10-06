# Chart usability and supervisor visibility — 6 October 2026

The active chart defaults to a left price axis, with left/right and compact/full
controls. Scale changes update the chart in place; the drawing overlay offsets
by the actual left-axis width, preserving time/price anchors. Support,
resistance and range lines use short names and omit their price-axis badges.
Mobile drawing tools use a horizontally scrollable bottom rail. Timeframe
buttons have 44px touch targets. Existing drawing lock, undo, erase, clear and
validated symbol/timeframe session storage are retained.

Live chart/status cards have a subtle border glow. Loading, stale, unknown,
unavailable and error chart states do not animate. The reduced-motion media
rule disables the new animations. Supervisor evidence is visible independently
of terminal observation and includes state, timestamp, age, cycle, process
liveness and stale status. It is read-only evidence, not trading authorization.

Inspection confirmed a fresh RUNNING supervisor heartbeat with process liveness
and cycle 14; later local observations showed cycle 16. No execution process,
risk limit, quota, environment file, terminal or safety store was changed.
Existing market-only timeframe refreshes and cancellation guards were retained.

Validation:

- Focused frontend: 114 passed; complete frontend: 183 passed.
- Local production build and Vercel production build passed.
- Backend: 2,567 passed, four skipped; all 19 group exit codes zero.
  Evidence: `reports/backend-20261006-035504`, including per-group logs/XML,
  summary and totals. Live MT5 and immutable archived forensics remain opt-in.
- Local browser: 390px mobile, 820px tablet, 1440px desktop; mobile/desktop
  document width matched the viewport. Touch target heights were 44px.
  Compact/full and left/right controls were exercised; right-axis overlay
  offset was zero and left-axis offset matched its actual width.
- Reduced-motion CSS was inspected in the loaded browser stylesheet; the OS
  preference was not changed. Supervisor stale expiry is covered with a fake
  clock, including terminal-unavailable evidence and removal of live glow.

Production deployment `dpl_GYivw9kG3AREZY9GDXMGDFa3V7tT` is READY and assigned
to `https://jqe.jokiholdings.com`. The authenticated production page loaded the
new supervisor panel. Before deployment, hosted M5 and a fresh heartbeat were
visible. Post-deployment M1 and M15 selection changed correctly, but live data
verification is incomplete: monitoring requests returned 503 after transport
timeouts. Vercel logs recorded TimeoutError; Cloudflare tunnel logs recorded
canceled origin requests. The local API continued observing terminal data.
No quota bypass, authentication weakening or process restart was attempted.

The deployed frontend includes existing working-tree features; unrelated
accounting, recovery, backend, reports and database changes remain uncommitted.
The phase commit selects only chart/persistence files and the new supervisor
UI/test hunks. Existing chart session persistence is included as its dependency.

Limitations: full price strings can still set a minimum axis width larger than
the compact requested width; drawings persist only in the current browser tab.
The existing large-bundle warning, React act warnings and deployment dependency
audit (three moderate, one high) remain. Reduced motion is stylesheet-verified,
not tested by changing the system preference.

Recommended next phase: diagnose authenticated relay queuing/timeouts and
complete hosted M1/M5/M15 candle-spacing and heartbeat verification, then
reduce polling contention and bundle size based on measured evidence.
