# Account fee and financing reconciliation — 2026-10-08

Outcome: observed demo cashflows reconciled; universal account tariff and full financing calendar remain unresolved. This distinction prevents replacing assumptions with unjustified certainty. No orders, logins, Market Watch changes, account switches or terminal/service restarts were performed. Read-only IPC attached only after verifying exactly the configured running Weltrade demo terminal.

## What is now resolved

A new all-returned-history capture queried January 1, 2000 through the observation date plus two days (broad edges avoid clock-cutoff loss). It returned 19 deals: the initial USD 200 balance credit and 18 trade deals forming nine complete simple closed positions. All 18 associated orders were captured. There were zero open positions. Every returned trade deal has zero commission and fee; no separate commission/charge deal was returned.

Sum of every returned deal's profit, swap, commission and fee equals **USD 142.97**, exactly matching the reported account balance and equity, with zero residual. This reconciles the returned ledger, not proof that the server retains all archived records. Raw account identifiers were omitted; position/order/deal identifiers are hashed in the evidence.

Four exact symbols have observed executions: FX Vol 20, FX Vol 60, SFX Vol 20, SFX Vol 99. Zero commission is verified **for those returned executions only**, including one 0.03-lot SFX Vol 99 round trip. There is no fee observation for the remaining six symbols and no supported inference about other lot tiers, future trades or real accounts.

Three FX Vol 20 SELL positions, each 0.02 lots, opened September 23 and closed September 24 in raw SDK clock representation, each booked -USD 0.13 swap. With current captured -2% annual interest, contract size 1 and preceding closed bid proxy 120048.84, one ordinary daily charge is:

`round(120048.84 × 0.02 lots × -0.02 / 360, USD cents) = -0.13`.

All three charges reconcile at the cent. The positions cross the same presumed ordinary rollover under both raw-epoch-as-UTC and raw-epoch-minus-three-hours interpretations. Thus this sample **cannot identify which clock interpretation is correct**. It also cannot identify the exact swap reference price: cent rounding permits a broad price interval. No triple-day/weekend position or SFX Vol 99 overnight position exists in returned history. Per-weekday swap multiplier attributes are unavailable in this Python SDK snapshot; null means unavailable, not zero.

See [machine-readable reconciliation](2026-10-08-fee-financing-reconciliation.json). Captured raw sanitized evidence remains in `reports/account-fee-timeline-20261008-01.json`; its SHA-256 binds the report. The source scripts are retained under `reports/capture_fee_timeline_20261008.py` and `reports/reconcile_fee_timeline_20261008.py`.

## Published fee conflict

| Official source inspected | Stated scope / fee | Research interpretation |
|---|---|---|
| [Weltrade account-type page](https://www.weltrade.com/trading/type_account/) | SyntX commission: No | Consistent with observed demo ledger; not account-specific historical confirmation |
| [SyntX opening guide](https://support.weltrade.com/en/articles/11937642-how-to-open-syntx-account) | Describes zero commissions | Corroborates zero-fee possibility; includes generic symbol examples that must not be mapped to JQE native contracts |
| [Help Center account overview](https://help.weltrade.com/en/articles/13434918-trading-account-types-overview-cent-micro-pro-syntx-and-raw-spread) | SyntX commission from USD 3/lot | Contradicts the no-commission statements; side, account and effective dates unresolved |
| [Copy Trading schedule](https://docs.weltrade.com/syntx-trading-limits-and-conditions.pdf) | Symbol-dependent, e.g. SFX Vol 99 USD 4/lot, USD 0.04 minimum | Explicit Copy Trading scope; do not apply to ordinary JQE demo trading |

These sources do not justify choosing whichever fee produces the better result. Existing three preregistered cost cases remain unchanged. The zero-commission case is now supported by observed executions on four symbols, but is still not a verified universal ten-symbol tariff. Positive commission scenarios remain declared stress assumptions, not claims of actual fees charged.

## Financing gap that cannot be resolved from current records

[Weltrade guidance](https://help.weltrade.com/en/articles/14485261-swap-in-trading-what-it-is-and-how-it-works-on-weltrade) specifies weekday midnight EET and an instrument-dependent triple day. [MT5 definitions](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants) specify interest-current calculation from the swap-time price over a 360-day year. Current terminal terms show Friday triple day, but available positions only cross one ordinary Wednesday/Thursday boundary. These observations cannot identify Friday-versus-ending-day semantics, DST, historical changes or symbol-specific exceptions. No new trades will be created to manufacture evidence.

## Concrete outstanding request — draft only, not sent

Please confirm the following for the owner's configured Weltrade SyntX demo account (identify it privately to Weltrade; no credentials):

1. For exact FX Vol 20/40/60/80/99 and SFX Vol 20/40/60/80/99, is commission zero for ordinary non-copy demo trading? If not, provide per-side/round-trip rates, minimum fees, lot tiers, rounding and effective dates for September–October 2026.
2. Which published page governs this account, given the conflicting no-commission and from-USD-3 statements? Is the Copy Trading tariff excluded?
3. Confirm annual-interest swap rates/mode, the reference price, 360-day basis, currency rounding, exact rollover timezone/DST, and whether Friday triple refers to Friday 00:00 or the ending Friday session. Are Saturday/Sunday charged separately for 24/7 synthetics?
4. Confirm demo applicability and historical rate changes; explain the three FX Vol 20 0.02-lot SELL overnight charges of USD 0.13 each.

No support message has been sent. A user-supplied account-specific written schedule or broker reply is required to resolve the remaining external contradiction and calendar ambiguity. No local code change can establish facts absent from the available evidence.

## Next work / NOT proven

Finish the corrected canonical accounting campaign and artifact checks already running. Then incorporate verified written fee/financing terms only through a separately declared, source-bound replay; preserve current assumptions/results. Until that evidence exists, report conditional modeled USD and leave promotion blocked. No universal tariff, complete financing calendar, historical executable quotes, OOS improvement or real-account economics is proven.

## Deeper official-source research after the owner confirmed no written terms

The live official instrument page's own public JavaScript identifies its read-only data action `tools.getTradingTools` and endpoint `https://www.weltrade.com/api/v1/`. A plain request initially returned HTTP 400; repeating the exact page action with the page session, Origin and Referer succeeded. No authenticated account API, credential or invented broker trading interface was used. Full public response and page/source scripts are preserved in new files under `reports/weltrade-*20261008*`.

All ten exact native symbols are present. Published long/short swap magnitudes are FX 2/4/6/8/10% and SFX 6.5/13/19/25.5/32% annually, exactly matching the absolute terminal rates on both sides. The website's rendering code explicitly labels these ten symbols `% p.a.`. Public values are positive; terminal rates are negative. **Magnitude/unit agreement is verified for the current snapshot, not sign agreement or historical rate stability.** The three observed debit charges support the terminal's negative sign. The public SyntX rows contain no commission field; absence is not zero. See [public-versus-terminal comparison](2026-10-08-public-terminal-swap-comparison.json) and [official specifications](https://www.weltrade.com/trading/tools/).

The official legal page similarly exposes its public content action `tools.getLegalInfo` with region `en`; that exact action was captured into `reports/weltrade-public-legal-20261008.json`, without account access. The [Client Agreement](https://www.weltrade.com/legal/) provides additional distinctions:

- Definitions identify swap as an overnight charge past midnight **server time**. This resolves the published clock basis for current general terms; it does not verify historical server UTC/DST offsets or the exact synthetic triple-day boundary.
- §11.4.5 provides for Copy Trading transaction commission, and §11.8.4 permits SyntX Copy Trading conditions to differ from ordinary SyntX. Thus transferring the Copy Trading PDF tariff to JQE would be unsupported.
- §3.2 permits contract-term changes, and §10.9.3 allows historical aggregation. A current public snapshot cannot prove unchanged historical financing or complete unaggregated archival history.

The Friday/end-of-day footnote in the instrument page belongs to other asset sections, not the SyntX conditions block. It is not synthetic-index calendar evidence. SyntX's own block specifies its separate Sunday trading break and links explicitly to Copy Trading limits; neither establishes a full financing calendar.

Updated conclusion: **zero commission is the strongest supported working interpretation for observed ordinary demo executions**, supported by the reconciled ledger and multiple ordinary-account pages. The USD 3/side case should be described as a stress assumption, not a verified base tariff. Nevertheless the conflicting Help Center overview, missing six-symbol execution evidence and absent account-specific effective dates prevent a universal historical tariff claim. Current annual swap magnitudes and the general midnight server-time basis are corroborated; ordinary FX Vol 20 arithmetic reconciles. Friday/weekend semantics, historical rates and all-symbol financing remain open. No research gate or frozen cost case is changed retrospectively.
