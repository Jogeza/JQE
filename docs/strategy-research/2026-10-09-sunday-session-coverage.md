# Conditional Sunday-session coverage and new immutable history

Result: **PASS_CONDITIONAL_SESSION_COVERAGE_NOT_ML_READY**. One frozen session
assumption was implemented and acquired into NEW files. Default continuous
Weltrade coverage is unchanged; no execution safety assertion was removed.
No model, candidate or performance configuration was evaluated.

## Frozen assumption and safeguards

`reports/session-calendar-20261009-01/policy.json` and checksum were written
before acquisition. They bind the unchanged 90-day history registration, prior
gap diagnosis/classification and a dated official-source evidence excerpt.
Weltrade's current SyntX conditions list a Sunday 06:50–07:00 EET real/demo break.
[Official source, inspected October 9](https://www.weltrade.com/za/trading/tools/).
The observed gaps align under fixed historical UTC+3, but EET wording does not
verify historical UTC+3/DST or continuity of the published terms.

The opt-in `FrozenWeltradeSundayResearchPolicy` is bounded to July 10–October 8,
exact native FX/SFX Vol 20/40/60/80/99, M5, matched provider/canonical symbols.
Only Sunday opens 03:50 and 03:55 UTC are excluded. No broad weekend exclusion,
future dates, arbitrary aliases or inferred holiday rules are accepted. Missing
other expected bars still fails completeness; duplicate timestamps, returned bars
in declared closures and scope mismatches fail closed. Nine focused tests also
prove default continuous coverage still rejects these gaps and the documented
historical service retains its completeness rejection for unexpected omissions.

HistoricalDataService accepts the explicit research policy only for this opt-in
caller. Acquisition verifies policy checksum/input hashes before use and again
at completion, labels the calendar conditional and keeps ML fitting unauthorized.
No runtime service or terminal was restarted/reconfigured. Existing datasets,
failed attempts, execution gates and operator safety state remain intact.

## Same history registration, attempt 04

```powershell
& D:\JQE\venv\Scripts\python.exe -m tools.acquire_entry_campaign --output reports/history-acquisition-20261009-04 --bars 25920 --attach-existing --history-only --protocol reports/history-registration-20261009-01/protocol.json --session-policy reports/session-calendar-20261009-01/policy.json
```

July 10 00:00 through October 8 00:00 UTC is half-open. The original October 9–30
EMA50 validation/test windows stay sealed. Existing demo identity/current offset
verified; Market Watch unchanged. HistoricalDataService supplied new store and
bundles. SDK spread metadata came from the same response and passed OHLC/time
binding. No later request, synthetic fill, old-store repair or price shifting
was used to create the sidecars.

| Scope | Result per symbol |
|---|---:|
| Native symbols | 10, all retained |
| Calendar span | 90 days |
| Continuous M5 buckets | 25,920 |
| Excluded buckets under conditional policy | 26 across 13 Sundays |
| Returned closed bars | 25,894 |
| Unexpected missing/returned buckets | 0 / 0 |

The [saved bundle audit](2026-10-09-conditional-history-audit.json) independently
loaded every manifest/CSV, verified exact native identity/content hashes and
closedness, checked requested endpoints and conditional coverage, matched
spread/point/acquisition hashes, and confirmed acquisition source stability.
Raw discontinuities remain in the files: events crossing them must still be
censored under a future frozen label protocol. No bars were manufactured.

Attempt 04's `bundle-qualification.json` binds every manifest/CSV/spread hash.
Its status is conditional acquisition/coverage, not unqualified promotion or
verified account-currency economics. Attempts 01–03 retain their original failed
results. This is one additional calendar configuration, not parameter tuning;
zero ML models fitted and zero strategy candidates evaluated.

## NOT proven and next work

Validation: nine focused checks; full backend **2,698 passed**, four explicit
opt-in skips, zero external network attempts. Frontend **240 passed**, build passed
with existing size advisory. Logs: `reports/sunday-policy-tests-20261009.txt`,
`reports/sunday-policy-frontend-tests-20261009.txt` and
`reports/sunday-policy-frontend-build-20261009.txt`. Whitespace check passed.
Existing safety assertions remain unchanged; qualification is conditional.

No verified historical timezone/session/financing calendar, universal commission
tariff, effective independent sample sufficiency, ML readiness, OOS edge or live
equivalence is established. Ninety source-calendar days is a project floor, not
a guarantee; warmup and purging reduce usable history. This historical source
does not become a fresh ML holdout by renaming it.

**Do not reuse old labels on the expanded prefix.** EMA recursion and prefix mean
regime/features now start earlier. The former 2,833 eligible labels remain valid
only under their frozen original prefix/source identities. No new opportunities,
labels or performance outcomes were generated in this acquisition step.

Next freeze a separate training-baseline/opportunity protocol binding these new
bundles, retained warmup, all ten symbols, the unchanged USD 50/1% risk and explicit
cost/financing assumptions. Canonical replay only; no model fitting or reserved
candidate/holdout use. Keep cost and historical-calendar verification gaps explicit
and obtain a fresh ML registration/holdout before any fit.
