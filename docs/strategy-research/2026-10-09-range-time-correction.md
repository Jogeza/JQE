# Read-only range-time correction and Sunday-gap evidence

Result: the three-hour range shift is corrected and confirmed by a NEW bounded
terminal acquisition. The history remains **unqualified under the unchanged
completeness gate**. No strategies, signals, risk settings, orders, live execution
code, gates, persisted safety state or existing datasets were modified. No service
or terminal was restarted; the running backend has not been reloaded by this work.

## Correction and offline evidence

WeltradeGateway.get_candles_range now translates requested UTC boundaries into
the server-clock domain using the same fixed 10,800-second offset subtracted from
returned candle timestamps. It rejects naive/reversed bounds before SDK reads and
rejects out-of-range, duplicate or unordered normalized responses. This changes
the range reader only; it does not certify every legacy MT5 read path or establish
historical DST behavior. The existing fixed offset remains an explicit assumption.

Five offline checks passed: exact inclusive UTC endpoints round-trip through
server queries; invalid bounds do not reach SDK; out-of-window and duplicate
responses fail closed. Injected doubles submit no orders or Market Watch calls.
Production demo/session verification remains unchanged.

## Same registration, new acquisition

Original registration `reports/history-registration-20261009-01` is unchanged:
ten native Weltrade FX/SFX Vol symbols, M5, July 10 00:00–October 8 00:00 UTC,
half-open. Original October 9–30 holdouts stay sealed. Attempt 03 used the documented
historical service, existing-terminal attachment and new isolated evidence/store:

```powershell
& D:\JQE\venv\Scripts\python.exe -m tools.acquire_entry_campaign --output reports/history-acquisition-20261009-03 --bars 25920 --attach-existing --history-only --protocol reports/history-registration-20261009-01/protocol.json
```

| Evidence | Attempt 02, preserved | Attempt 03, corrected source |
|---|---|---|
| First normalized bar UTC | July 9 21:00 | July 10 00:00 |
| Last normalized close UTC | October 7 21:00 | October 8 00:00 |
| Bars per symbol | 25,894 | 25,894 |
| Gaps per symbol | 13 | 13 |
| Service completeness | Failed | Failed; missing buckets remain |

Attempt 03 verified configured demo identity/current offset and unchanged Market
Watch with stable replay/acquisition source. No login/account switch, new orders
or operator-store writes occurred. No failed snapshot was shifted or repaired.
Its `coverage-diagnosis.json` and `gap-classification.json` are saved offline
inspections of the NEW partial store. No qualified bundle or same-response spread
sidecar was exported; this store cannot replace existing label data/cost evidence.

## Gap classification and uncertainty

All ten symbols share the same 13 Sunday windows: missing M5 opens **03:50 and
03:55 UTC**, with observed bars at 03:45 and 04:00. That is 26 missing bars per
symbol, 13 distinct time windows; symbol copies are not independent observations.

Weltrade's current SyntX detailed conditions publish a Sunday **06:50–07:00 EET**
break for real/demo accounts. [Official trading conditions](https://www.weltrade.com/za/trading/tools/)
were inspected October 9, 2026. Under the observed UTC+3 normalization, the
recorded gaps align with 06:50–07:00 server time. This is **conditional schedule
corroboration**, not retrospective confirmation: the public EET label does not
independently establish July–October UTC+3/DST or prove historical terms unchanged.
Contest/Copy Trading conditions were not substituted for ordinary demo terms.

No synthetic bars, shorter windows, disabled coverage assertions or repaired
stores were used to force a pass. An explicit provider/session policy would need
its own frozen evidence, historical timezone assumptions and regression tests;
unexpected gaps must still fail. Current continuous coverage remains unchanged.

## NOT proven and next work

Validation: five focused checks; full backend **2,689 passed**, four explicit
opt-in skips, zero external network attempts. Frontend **240 passed** and build
passed with the existing size advisory. Logs: `reports/range-time-tests-20261009.txt`,
`reports/range-time-frontend-tests-20261009.txt` and
`reports/range-time-frontend-build-20261009.txt`. Diff whitespace check passed.
Safety assertions unchanged; passing tests does not qualify the failed coverage.

No ML-qualified 90-day bundle, verified historical session/financing calendar,
universal fee tariff, ML fitting readiness, candidate improvement or positive OOS
expectancy is established. The server shift correction is a data-reader fix, not
a strategy improvement. No ML model or performance configuration was evaluated.

Next freeze an evidence-bound Sunday-session coverage design, keeping the timezone
uncertainty explicit; implement/review it only with strict unexpected-gap checks.
Then reacquire the SAME history registration into another NEW directory to obtain
bound immutable bundles and same-response spread evidence. Cost/financing and a
fresh ML registration/holdout remain independent gates; no fitting yet.
