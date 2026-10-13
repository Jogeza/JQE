# Compact chart controls and read-only API restoration

The existing Lucide SVG system now supplies compact indicator and price-axis
controls, with rounded 36-pixel targets, tooltips and accessible names. Timeframe
labels remain short; data freshness, provenance and safety states remain visible.
The chart remains the existing Weltrade candlestick/indicator renderer, not Deriv
price data or an options product. No external icon assets/dependencies added.

Owner authorized restoring the read-only backend. No 8000 listener was present;
launched canonical uvicorn api.app:app on 127.0.0.1:8000, PID 21272, session 60939.
api.app forces broker execution disabled and rejects armed settings. No source or
environment file modification; terminal, gates and safety state unchanged.
Log reports/read-only-backend-20261011.txt. Health returned OK; correct
/api/v1/brokers/terminal-observation returned CONNECTED, balance/equity/candle
present and execution_enabled false. An initial request without /api/v1 returned
404; corrected route was used, no backend patch required.

The active-analysis route returned canonical context/candles/signal/setup.
Browser displayed populated FX Vol 20/M5 closed-bar candlesticks, balance and
expanded equity/free-margin/realized-UTC-P/L. Compact-price toggle switched its
accessible state. Screenshot reports/populated-dashboard-20261011.png. Initial
tab navigation timed out but completed; later bound the successfully loaded tab.
One account locator failed; visible text locator succeeded. No orders submitted.

Supervisor evidence remains STALE/not alive or unverified. API connection and
charts do not establish execution readiness or performance. Runtime checks are
short-run observations, not sustained availability certification.

## Validation

Frontend 240 passed, build passed (existing bundle-size warning). Initial run
failed textContent assertion after replacing the price label with an icon; label
retained as visually hidden text with accessible name and original tests unchanged.
Failure log reports/chart-icons-tests-20261011.txt; pass log
reports/chart-icons-tests-20261011-02.txt; final build
reports/chart-icons-build-20261011-03.txt.
Full backend: 2,810 passed, four explicit opt-in skips, zero external network
attempts. Log reports/chart-icons-backend-tests-20261011.txt uses fresh
process-local TEMP/TMP, offline guard and existing assertions.

Next verify desktop populated layout and sustained read-only polling, then simplify
Home/Overview cards. No hosted deployment, research replay source, campaign data,
account/server switch or execution authorization changes. ML remains coverage-gated.
