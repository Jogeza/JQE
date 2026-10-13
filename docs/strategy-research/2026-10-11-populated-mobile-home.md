# Populated layout, mobile and campaign restoration — 2026-10-11

Local presentation changes only; no hosted deployment or strategy change.

## Visual review

Reviewed signed-in Deriv mobile Trader: compact account strip, dominant chart, controls underneath and bottom navigation. JQE adopts that arrangement with Weltrade identity, candlesticks and existing research/safety evidence. It is not a pixel-exact replica or Deriv product integration. Desktop populated balance/chart/setup rail and mobile populated chart were reviewed. Home now uses shorter labels, quieter cards and a two-column mobile grid. Accessible chart controls and unavailable OOS evidence remain visible.

Screenshots: `reports/populated-desktop-20261011.png`, `reports/mobile-matched-dashboard-20261011.png`, `reports/home-cards-20261011.png`.

## Polling evidence

Twelve completion-paced rounds across health, terminal observation and active analysis: 36 requests, zero failures, maximum response 4.0583 seconds. Evidence: `reports/polling-verification-20261011.json`. This is bounded short-run recovery evidence, not proof of sustained production reliability. Populated Weltrade demo balances and closed-bar FX20/M5 chart were present. Home risk-summary amounts and workstation terminal-observation amounts differed; their freshness/consistency is not certified. Supervisor remains stale; execution remains disabled.

## Campaign

Previous owner/launcher/watcher absent; cause unknown. Previous segment saved 11,383 NEW completions and one unfinished STARTED attempt. With 231 inherited completions, 11,614 saved attempts exist out of 241,938; full coverage remains incomplete. Original artifacts and unfinished ledger entries retained. Source snapshot files matched before restoration.

Owner authorized restoration. NEW output `reports/long-history-label-campaign-resume-20261011-01`; NEW runtime `reports/label-resume-runtime-20261011-01`. Launcher PID 10040 / worker PID 21872. Canonical `python -m backtesting.backtest --long-history-label-campaign` reuses the three earlier immutable segments and qualified lineage contract. No Python source edits. At final check the worker remained alive, stderr empty, with implementation/ledger not yet created: saved-result verification remains pending. Restoration is launched, not yet qualified as replay progress. Saved-result verification precedes implementation/ledger creation; check existing owner and ledger before any continuation. Do not launch a duplicate.

## Validation

Frontend: 240 tests passed; build passed (existing bundle-size warning). Logs `reports/mobile-home-tests-20261011-02.txt` and `reports/mobile-home-build-20261011-02.txt`. Full offline backend: 2,810 passed, four explicit opt-in skips, zero external network attempts, exit 0; log `reports/mobile-home-backend-20261011.txt`. Existing safety assertions retained.

## NOT proven / next

No complete labels, feature-extraction readiness, ML fit, positive expectancy, live readiness, exact Deriv replication or long-term polling guarantee. Next audit resumed campaign progress/coverage; reconcile Home risk-summary freshness with terminal observation. Preserve replay source while campaign runs.
