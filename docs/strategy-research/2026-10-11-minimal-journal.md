# Minimal Journal and campaign status — 2026-10-11

Local presentation changes only. Journal now opens on the broker-window P&L summary and execution history. Calendar and decision evidence use native expandable disclosures. On mobile, the history list shows time, symbol, side and realized P&L; trade ID, quantity and prices remain in expandable row details with UTC timestamps. Desktop retains all columns. Calendar UTC filtering, day-filter clearing, broker-source labels, decision reasons and supervisor evidence are preserved. No records or safety assertions removed.

Browser reviewed populated 14-record Weltrade history, the calendar disclosure and expanded row details. Screenshot `reports/journal-minimal-20261011.png`. These are observed broker history records, not canonical OOS strategy evidence; their win rate does not qualify strategy performance. No strategy, Python replay source, API, terminal, execution gate/state or environment changes. No deployment.

## Campaign

Existing worker 21872 / launcher 10040 remains alive and CPU is advancing. Prior-result verification remains pending: no implementation/ledger yet, stderr empty. No new label completions claimed. Prior immutable segments contain 11,614 saved completions out of 241,938. No duplicate, restart or source edit. Check existing owner/ledger on continuation; process presence is not completion or full coverage.

## Validation

Frontend 240 passed/build passed: `reports/journal-tests-20261011-02.txt`, `reports/journal-build-20261011-03.txt`; existing bundle-size warning remains. CSS selector was narrowed to execution-history headers, avoiding any effect on calendar/decision columns. Full backend: 2,810 passed/four explicit opt-in skips/zero external network attempts, exit 0; `reports/journal-backend-20261011.txt`. Separate desktop tab also verified 14 Weltrade records and decision disclosure showing STOPPED_OR_STALE / not verified as armed. Read-only health probe returned HTTP 200 in 0.17 seconds. Tests retain broker/P&L/date/authorization assertions.

## NOT proven / next

Complete labels, feature readiness, ML fit, positive expectancy, sustained service reliability and live readiness remain unproven. Next verify resumed campaign progress, then simplify Positions with the same mobile row/detail pattern. Keep replay source frozen while the campaign runs.
