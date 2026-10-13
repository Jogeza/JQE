# Canonical v2 training baseline — 2026-10-08

Status: all 30 fixed replays complete. Training diagnostics only; no candidate evaluated and no out-of-sample improvement established. Negative outcomes and all nine no-trade symbols are retained.

This continues [the frozen campaign](2026-10-08-v2-campaign.md). The replay protocol was written before outcomes to `reports/entry-training-20261008-01/training-replay-protocol.json`; every started, completed or failed configuration is appended to `trials.jsonl`. Full canonical results and their fingerprints are retained in that new directory.

## Scope and frozen assumptions

Ten exact Weltrade FX/SFX Vol contracts (20, 40, 60, 80, 99), M5. Training is September 8 00:00 UTC inclusive through October 8 00:00 UTC exclusive. Each symbol has 8,632 evaluated closed bars and 200 preceding warmup bars; the missing eight nominal training bars remain missing. Validation October 9–16 and final test October 16–30 remain sealed and unavailable at registration. No registration-day outcomes are evaluated.

One unchanged canonical v2 strategy configuration, zero candidate configurations, three fixed cost cases, 30 planned replays. Each symbol starts with an independent modeled USD 50 account and 1% cash risk. This is not a shared-capital portfolio. Existing replay defaults remain 1.5 ATR stop, 3 ATR target and 19-bar holding limit. Live TradePlanBuilder uses different stop/target assumptions: live-plan equivalence is NOT established. Canonical signals retain their existing unknown-spread fallback; recorded spreads affect modeled fills only.

| Cost case | Commission assumption per lot per side | Spread multiplier | Adverse slippage per fill |
|---|---:|---:|---:|
| Optimistic | USD 0 | 1 | 0.05 ATR |
| Assumed fee | USD 3 | 1 | 0.05 ATR |
| Doubled spread/commission | USD 6 | 2 | 0.05 ATR |

Fees are assumptions, not a verified account tariff. [Weltrade's account overview](https://help.weltrade.com/en/articles/13434918-trading-account-types-overview-cent-micro-pro-syntx-and-raw-spread) advertises SyntX commissions **from** USD 3 per lot; it does not settle this account's amount or whether that amount applies per side. Eighteen prior deal observations with zero commission/fee fields do not resolve the discrepancy.

## Offline economics and fill accounting

A separate read-only terminal snapshot captured native USD CFD contract terms, bid-chart mode, volume steps/minima/maxima, stop distances, swap terms and 40 margin probes. Eighty previously captured broker P/L probes and those 40 rounded margin probes pass offline reconciliation. The conservative upper margin ratio consistent with each symbol's rounded probes is frozen. No terminal API calls belong inside replay; the campaign explicitly blocks session, history, order and calculation calls.

Entry occurs on the next bar. Its spread proxy comes from the preceding closed bar to prevent lookahead. BUY fills include spread; SELL exits use an ask proxy. Tick rounding and slippage are adverse, stop wins a same-bar stop/target collision, and a gap beyond a stop fills at the adverse opening price. Take-profit fills do not receive favorable gap improvement. Volume always rounds down; fees, exit slippage, margin and a worst single-rollover reserve must fit the cash-risk budget. A position below the broker minimum is rejected rather than rounded up. Gap losses can exceed the planned budget and are retained.

Financing uses captured current annual interest rates and current-price/360 accounting, with a declared ending-server-day calendar, Monday–Friday charging and Friday triple swap. This calendar, historical rate stability and historical UTC offset are assumptions. The captured server offset is +03:00. See [MT5 contract definitions](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants) and [Weltrade swap guidance](https://help.weltrade.com/en/articles/14485261-swap-in-trading-what-it-is-and-how-it-works-on-weltrade). These modeled charges do not reconstruct historical broker debits.

Equity marks use bar-close liquidation wealth including estimated closing costs. Drawdown is measured on those marks; intrabar drawdown remains unknown. MAE/MFE include whole entry/exit bars and are explicitly upper bounds because tick ordering is unavailable. Holding time and wall-time exposure are also conservative bar-based bounds. Sharpe/Sortino are unannualized; trade-based and M5 bar-based measures are labeled separately. Undefined statistics remain null.

## Validation and trial disclosure

Focused economics/research checks: 36 passed. The initial focused run had one failure from floating-point tick rounding; the implementation was corrected and the original assertion retained. Full offline backend: 2,604 passed, four explicit live/archive opt-in skips, zero external network attempts. Frontend: 238 tests passed; production build passed with its existing large-chunk warning. No safety assertions were weakened.

## NOT proven

No untouched out-of-sample expectancy, strategy improvement, verified commission tariff, historical financing schedule, live-plan parity, executable historical bid/ask quotes, liquidity, stop-out behavior, portfolio capacity or future performance is established. Current broker calculation probes validate a snapshot, not past contract stability. Training statistics cannot qualify adoption. The reserved EMA50-distance candidate remains unimplemented.

The completed replay results and diagnosis follow. Account-specific costs must be reconciled before any candidate or holdout evaluation. Do not raise capital, weaken risk limits or change the strategy in response to these outcomes.

## Completed baseline metrics

All 30 replays completed without campaign source/dependency drift. See the [summary](2026-10-08-v2-training-evidence/summary.json), [trial ledger](2026-10-08-v2-training-evidence/trials.jsonl), [frozen replay protocol](2026-10-08-v2-training-evidence/training-replay-protocol.json) and [artifact hashes](2026-10-08-v2-training-evidence/artifact-hashes.json). All 30 per-symbol metric files are preserved beside them; full canonical results remain under `reports/entry-training-20261008-01`.

Only SFX Vol 99 executed trades. The other nine symbols each had zero trades in every cost case: all five FX contracts and SFX Vol 20/40/60/80. Their expectancy, win rate, average win/loss, profit factor, Sharpe/Sortino, MAE/MFE and holding-time distributions are **undefined**, with zero exposure and zero modeled drawdown. They are retained, not omitted from the universe. The following table therefore describes SFX Vol 99 only; pooling executed trades across all ten produces exactly these same numbers, not cross-symbol validation.

| Training metric | Optimistic zero fee | Assumed USD 3/lot/side | Double spread + USD 6/lot/side |
|---|---:|---:|---:|
| Closed trades | 279 | 175 | 72 |
| Expectancy, conditional modeled USD/trade | -0.01158 | -0.05709 | -0.12444 |
| Expectancy, net R/trade | -0.02331 | -0.23442 | -0.55216 |
| Training 95% block-bootstrap interval, R | [-0.21125, 0.12311] | [-0.44014, -0.09136] | [-0.99323, -0.35909] |
| Profit factor | 0.93849 | 0.70540 | 0.43470 |
| Win rate | 35.842% | 35.429% | 30.556% |
| Average win, modeled USD | 0.49280 | 0.38581 | 0.31318 |
| Average loss, modeled USD | -0.29335 | -0.30009 | -0.31700 |
| Net modeled USD | -3.23 | -9.99 | -8.96 |
| Maximum bar-close liquidation drawdown, modeled USD | 10.06 | 11.05 | 9.07 |
| Percentage at maximum cash drawdown | 18.963% | 21.641% | 18.100% |
| Unannualized M5 bar Sharpe | -0.00429 | -0.02213 | -0.03215 |
| Unannualized M5 bar Sortino | -0.00630 | -0.03070 | -0.04173 |
| Wall-time exposure upper bound | 25.764% | 16.354% | 7.373% |
| Holding minutes upper bound p10 / p50 / p90 | 10 / 30 / 95 | 10 / 30 / 95 | 15 / 35 / 95 |
| MAE R upper bound p10 / p50 / p90 | 0.191 / 1.064 / 1.823 | 0.161 / 1.057 / 1.745 | 0.242 / 1.057 / 1.940 |
| MFE R upper bound p10 / p50 / p90 | 0 / 0.702 / 2.409 | 0.023 / 0.889 / 2.433 | 0 / 1.234 / 2.462 |
| Commission, modeled USD | 0 | 10.50 | 8.64 |
| Financing, modeled USD | 0.18 | 0.18 | 0.15 |

R divides each trade's net P/L by its modeled initial stop cash risk; it is not the larger risk budget including fees/reserves. Bootstrap uses 10,000 circular three-day blocks, seed 20261008, preserving calendar-day simultaneity; it is training uncertainty only. The inherited JSON field `max_realized_drawdown_percent` contains the percentage corresponding to maximum cash drawdown; its frozen-model basis is explicitly `BAR_CLOSE_LIQUIDATION_EQUITY`, not realized balances. No verified account-currency expectancy is reported: that field remains null.

## Diagnosis before any strategy change

**Feasibility dominates nine symbols.** All rejected entries on those nine fail the frozen minimum-lot cash-risk/margin condition. This is a finding about the USD 50, 1% setup and current captured contract terms. It does not demonstrate that unexecuted signals have positive or negative expectancy. Raising account capital or risk in response would be a new configuration, not a correction to this baseline.

**Costs erase a thin gross result on the only traded symbol.** In the assumed-fee case, gross fill P/L is +USD 0.69, commission is USD 10.50 and financing is USD 0.18, yielding net -USD 9.99. Gross fill P/L already incorporates modeled spread/slippage. The optimistic case is negative even without commission. Cost cases have different feasible trade sets and evolving balances; this is an end-to-end cost sensitivity replay, not a same-trade fee subtraction. The lower absolute loss/drawdown under doubled costs reflects fewer trades, not greater quality.

**Stop placement and rejection matter.** SFX Vol 99 has 863 minimum-lot risk/margin rejections and 921 captured minimum-stop rejections in the assumed-fee case. Its 175 executed trades exit by stop 102 times, target 52 times and timeout 21 times. Median MAE exceeds one stop-distance R as a whole-bar upper bound; this cannot be interpreted as verified stop slippage without intrabar quotes. Entry remains next-open with existing ATR distances; no retrospective stop adjustment was made.

**Regime, direction and entry extension:** all executed trades are TRENDING; no other regime has an executed sample. The existing diagnostic groups use signal-close distance from EMA50, with the already registered 2.0 ATR threshold. Assumed-fee SFX Vol 99 clusters:

| Signal group | Trades | Losses | Mean net R |
|---|---:|---:|---:|
| SELL, extended ≥2 ATR | 105 | 68 | -0.25048 |
| SELL, near <2 ATR | 32 | 16 | +0.15737 |
| BUY, extended ≥2 ATR | 26 | 21 | -0.69084 |
| BUY, near <2 ATR | 12 | 8 | -0.14983 |

These are descriptive training clusters, not independent candidate results. Near SELL's positive mean is a small, selected subgroup and cannot justify adoption. Under doubled costs even the near SELL group is negative (-0.49273R, 14 trades). The ledger label `REJECTED_CANDIDATE` denotes existing baseline signal rejection; it does not mean a new research candidate was evaluated. Further signal-subtype and entry-gap/stop-loss clustering is not established by this aggregate table; per-trade RSI, EMA distance and entry-gap ATR remain available in the preserved metrics.

## Hypothesis and recommendation

Reserved falsifiable hypothesis, unchanged: excluding entries beyond 2.0 ATR from EMA50 will raise net expectancy relative to the unchanged baseline on identical untouched chronological data/costs. **Not tested.** Zero new filter configurations were implemented or evaluated. No full-sample or holdout tuning occurred.

Recommendation: **needs more data and verified costs; no adoption.** There is no improvement found and no out-of-sample comparison. Training baseline is negative in every cost case and is confined to one traded symbol/regime. The assumed-fee training case exceeds the 100-trade prerequisite, but fee/financing qualification remains unresolved; this does not authorize candidate or validation evaluation. Stop strategy changes here rather than search for a favorable configuration.

Next work: obtain the exact account-specific commission schedule and reconcile the observed swap booking/calendar, then independently review the frozen sizing/fill model and the nine-symbol feasibility finding. Preserve the current campaign, negative outcomes and future holdouts. Any later capital or execution-assumption experiment requires a separately declared protocol and trial count before outcomes; it cannot replace this baseline.



## Accounting review qualification

The [subsequent model review](2026-10-08-model-review.md) identified three offline
accounting defects, including 36 quote-side stop violations among 526 overlapping
cost-case trade observations. These baseline metrics remain immutable diagnostics
from the flawed model. A complete corrected canonical replay is required; do not
infer corrected metrics by removing affected trades. No strategy or OOS claim is
upgraded by this review. Next work is the accounting correction and validation.
