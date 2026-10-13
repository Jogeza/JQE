# Longer native history: registered, acquisition unqualified

Recommendation: **needs range-time correction and gap qualification**. No new
90-day dataset is qualified for ML. No model, signal candidate, performance replay
or sealed-holdout inspection occurred. The existing content-verified ten native
bundles still span only 41.7083 days and have their original immutable identities.

## Frozen acquisition registration

`reports/history-registration-20261009-01/protocol.json` and checksum were saved
before acquisition. One history configuration: all ten Weltrade FX/SFX Vol
20/40/60/80/99 symbols, M5, **July 10 00:00 through October 8 00:00 UTC**,
half-open, 90 requested calendar days. This is availability research, not an ML
experiment or fresh holdout registration. Previously inspected training remains
training. Original October 9–30 EMA50 windows remain sealed.

The documented acquisition tool now has an explicit `--history-only` mode requiring
a frozen native registration and `--attach-existing`. It uses
HistoricalDataService.get_candles_range and forbids latest-position reads, orders
and Market Watch selection. It requires an aware 90-day window ending no later
than October 8. It retains the service's completeness assertions, does not repair
old stores and writes only NEW evidence directories/stores.

```powershell
& D:\JQE\venv\Scripts\python.exe -m tools.acquire_entry_campaign --output reports/history-acquisition-20261009-02 --bars 25920 --attach-existing --history-only --protocol reports/history-registration-20261009-01/protocol.json
```

## Every attempt retained

| Attempt | Result | Evidence |
|---|---|---|
| history-acquisition-20261009-01 | BLOCKED before SDK initialization | No terminal process running; no history acquired |
| history-acquisition-20261009-02 | PARTIAL_ACQUISITION_BLOCKED | Owner opened terminal; existing configured demo verified; all ten range-completeness checks failed |

The agent did not start or reconfigure MT5. On retry, configured path/demo identity
and USD account currency passed; observed server offset was 10,800 seconds.
Market Watch remained unchanged. Gates, operator safety state, live path and
existing datasets were not changed. Verification evidence is isolated.

## Partial evidence and diagnosis

Each of the ten new-store partitions contains **25,894 M5 bars**. All start at
July 9 21:00 UTC and end at October 7 20:55 UTC, with last close at 21:00 UTC.
The whole returned span is 90 days, but it is shifted three hours earlier than
requested. Its in-window coverage is shorter; this does not meet the requested
90-day qualification. No immutable bundle/spread sidecar was promoted/exported.

Every partition has 13 discontinuities; the SFX99 gap inventory records 26 missing
bars. They remain unclassified provider-history gaps, not synthetic fill targets.
The service's completeness gate correctly rejected these ranges. No retry with a
shorter window, relaxed assertion or synthetic candles was used to obtain a pass.

The uniform three-hour shift matches the independently observed server offset.
Code inspection shows the range gateway passes UTC bounds to copy_rates_range
while normalizing returned timestamps with that offset. This is strong evidence
of a boundary/normalization mismatch, not proof that every historical timezone or
DST rule is settled. Review and regression-test the range time contract before
another new-file acquisition; never shift an existing snapshot in place.

Evidence is retained in attempt 02: `acquisition.json`, new `historical.sqlite3`,
`partial-store-inventory.json` and `gap-inventory.json`. Read-only SQL inspection
did not mutate this store. Registration directory also contains the existing
frozen-bundle content inventory. Generic per-symbol MarketDataError records are
retained; partial-store analysis establishes incompleteness without inventing a
complete exception-message trace.

## NOT proven and next work

Validation: six focused registration checks passed; full offline backend **2,684
passed**, four explicit opt-in skips, zero external network attempts. Frontend
**240 passed**, production build passed with existing bundle-size advisory.
Logs: `reports/history-only-tests-20261009.txt`,
`reports/history-only-frontend-tests-20261009.txt` and
`reports/history-only-frontend-build-20261009.txt`. Diff whitespace check passed;
safety assertions retained. Tests passing does not qualify the failed acquisition.

No 90-day qualified sample, gap calendar, historical tariff/financing stability,
fresh ML holdout, independent sample sufficiency, ML edge or positive expectancy
is established. Current P/L probes remain current contract evidence only.

Next correct/prove the read-only range time conversion with offline regressions,
then reacquire the SAME registration into a new directory. Inventory provider gaps
and explicitly qualify or reject coverage without weakening completeness/safety
assertions. ML fitting remains blocked independently by costs and a fresh
chronological registration/holdout. Do not reuse the original EMA50 holdouts.
