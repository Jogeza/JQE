# Watchlist cap evidence display — 2026-10-11

Presentation-only correction. Watchlist now receives cap resource error/stale state and observed_at. A current display requires a parsed non-future timestamp no older than 60 seconds and a non-stale resource without errors. This cutoff is a UI freshness choice, not execution authorization. A matching cap record with finite nonnegative count and positive limit is also required. Otherwise remaining capacity is unknown: no default 0/20, progress meter, reset inference or green remaining-slot claim is rendered. Observation state/time remains visible; add/remove and authorization paths are unchanged.

Browser verified current populated cap evidence with its timestamp. Offline tests verify stale and unavailable evidence cannot display remaining slots/default capacity. Failure/integration checks are retained. The original Watchlist native-Weltrade/unsupported-alias/no-Telegram assertions were accidentally overwritten during the test edit, caught via Git diff, restored exactly, and the new tests moved into separate WatchlistCapEvidence.test.tsx. Original test file has no content diff. The final run includes all 243 tests.

## Campaign

Existing owner 21872 continues canonical replay. Initial snapshot 325 NEW completed/326 started/zero failed. Later snapshot 342 NEW completed/343 started/zero failed; combined 11,956 saved of 241,938. No duplicate or replay source changes. Previous 24-pair audit remains partial; no new integrity/coverage certification in this turn. Complete coverage still gates feature extraction/ML.

## Validation

Frontend final 243 tests passed. Build/full backend results recorded below after completion. Logs: `reports/watchlist-evidence-tests-20261011-02.txt`, `reports/watchlist-evidence-build-20261011-02.txt`, `reports/watchlist-evidence-backend-20261011.txt`. Screenshot `reports/watchlist-cap-evidence-20261011.png`. Existing backend safety assertions retained. Local only; no deployment, terminal/orders/gates/safety/environment changes.

## NOT proven / next

No full labels, ML readiness, positive expectancy or execution readiness. Current cap timestamp is UI evidence, not account-scope qualification or authorization. Next inspect campaign progress and qualify cap account-scope/provider provenance read-only before calling it authoritative. Keep replay source frozen.
Final checks: frontend 243/build passed; backend 2,810 passed/four explicit opt-in skips/zero external network attempts, exit 0. Existing bundle-size warning retained. Original Watchlist identity test remains unchanged in final Git diff.
