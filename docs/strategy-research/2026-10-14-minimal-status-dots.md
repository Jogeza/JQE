# Minimal text and status dots across pages — 2026-10-14

Local presentation only, nothing committed or deployed. Remaining pages reviewed for
duplicated messaging: each fact now appears once. The green/red dot language is extended
across pages: green pulse = live/fresh, red = stale/unavailable/error, muted gray =
loading/unknown. State words remain in the DOM (visually hidden) for screen readers and
existing tests. No backend/replay/strategy/terminal/execution/environment/safety change.

## What changed

- Header connection pill (`Header.tsx`): Wifi icon and ONLINE/STALE/OFFLINE word removed;
  a single dot carries the state (green pulse / red / gray) with `role="img"` aria-label
  and title "Broker connection ...". The environment dot previously used `--quant-*`
  variables that `editorial.css:99` neutralizes to `#eee` inside the header — it now uses
  `--status-green` (DEMO) / `--status-red` (PROD) / muted.
- Telemetry ribbon (`App.tsx`): per-feed rows are dot + NAME + @time; the FRESH/STALE/
  OFFLINE word moved into a visually-hidden span. `editorial.css:184` flattens every
  `.status-dot` to `background: currentColor`; scoped clarity.css overrides re-enable
  green/red/muted colors and glow for the ribbon.
- Market chart (`MarketChart.tsx`): four redundant header badges removed (CACHED · STALE ·
  DEGRADED, FRESHNESS UNKNOWN, UNAVAILABLE, duplicate live badge); the source dot carries
  state (title "source · STATE", aria-label "Data state LIVE"). Only the ERROR "retained
  data" badge remains. Important fix: inside `.quant-panel.chart-panel`,
  `editorial.css:169` neutralizes `--quant-red/--quant-amber` to `#ddd`, so chart
  stale/unavailable/error dots were previously gray; they now use `--status-red`.
- Home (`OverviewPage.tsx`): account note "Terminal · USD · time" no longer duplicated on
  both Balance and Equity cards; shown once (Equity).
- Markets (`MarketsPage.tsx` + css): three status badges replaced by one dot row
  ("BROKER · CURRENT" with green/red/muted dot); stale/degraded words append only when true.
- SyntX (`SyntXMarketsPage.tsx`): hero sub trimmed to "Native Weltrade synthetic indices";
  the cached-closes / not-live-quotes disclaimer appears exactly once (footer); duplicate
  footer referral link removed (hero "Open Account" remains).
- Watchlist (`WatchlistPage.tsx`): cap evidence line = dot + formatted UTC timestamp with
  hidden "Cap evidence current|stale|unavailable"; green CURRENT, red STALE/UNAVAILABLE.
  Per-card "remaining capacity unknown" safety note unchanged.
- Tokens: `--status-red: #EF4444` added to theme.css (header/chart scopes neutralize the
  quant red, so a non-neutralized token was required). `.state-text-hidden` utility added
  to index.css.

## Browser verification (2026-10-14 ~01:10–01:25 UTC, read-only API)

Observed via browser-use computed styles (screenshots blocked,
`NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`):

- Workspace chart dot: LIVE, rgb(34,197,94), pulse animation active, title
  "Weltrade · fresh · closed candles · LIVE".
- Header pill: LIVE green, pulsing. Ribbon: FRESH rows green with glow; probes of red
  rgb(239,68,68) and muted rgb(171,171,171) render correctly.
- Home: "Terminal ·" occurs once (Equity only).
- Markets: one "BROKER · CURRENT" green dot row, zero badge elements.
- SyntX: dedup confirmed (one not-live-quotes occurrence, zero footer links); card cache
  dots red for STALE.
- Watchlist: cap evidence observed green CURRENT then naturally aged to STALE — red dot
  rgb(239,68,68), timestamp "2026-10-14 01:19:22 UTC", safety notes retained.

Evidence: `reports/frontend-session-20261014-01/ui-minimal-dots-evidence.json`.

## Follow-up: Markets chart controls adjusted (owner report)

Owner: "the charts in markets aint adjusted". Root cause: the flat chart-control styling
from the earlier workspace pass (clarity.css — border 0, transparent background, 36px
targets, 8px header) was scoped to `.app-container .workspace-chart` only, so the Markets
(and equally the Overview) chart panels kept native browser button chrome — 2px outset
border and the dark-mode gray face — plus the roomy 16px header. Extended the same rules
to `.app-container .chart-panel` (buttons, hover color, header padding, density label).
Browser-verified: Markets/Overview/Workspace chart controls all now render flat
(border 0px, transparent, 36x36 and 45x36) with 8px header padding; workspace unchanged.
The Research page chart was not mounted (known catalog API gap) but uses the same
component. Frontend 243 tests + build re-run after the change and passed.

## Validation

Frontend 243 passed (43 files) and `npm run build` passed after the final edits.
Full offline backend suite: 2,810 passed, four explicit opt-in skips, zero external
network attempts, exit 0 — isolated TEMP/TMP and `-p tests.offline_research_guard`
(active campaign owns the global OS lock); log
`reports/frontend-session-20261014-01/backend-tests-minimal-dots.txt`.

## Campaign and supervisor (read-only)

Campaign segment `long-history-label-campaign-resume-20261013-01`: ledger 3,681 NEW
completed + 14,091 inherited = 17,772 of 241,938, one active, zero FAILED, no summary.
Supervisor worker 16492 RUNNING since the 2026-10-14 00:06 re-arm; last checkpoint order
575518694 closed TAKE_PROFIT +0.96, 575522313 open, balance 141.90 exact. Operational
evidence, not expectancy.

## NOT proven / next

Screenshots were blocked, so verification is DOM/computed-style based. Live red-state
capture exists only for the watchlist cap flip; ribbon/markets red states were verified by
CSS probe on current-green data. Nothing is committed; all UI work stays local pending
explicit instruction. Full label coverage still gates feature extraction and ML.

Final backend: 2,810 passed/four explicit opt-in skips/zero external network attempts,
exit 0 (`reports/frontend-session-20261014-01/backend-tests-minimal-dots.txt`).
Full backend after the chart-control change recorded in
`reports/frontend-session-20261014-01/backend-tests-markets-chart.txt`.
