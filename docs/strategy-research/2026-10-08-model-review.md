# Frozen offline economics model review — 2026-10-08

Outcome: **model correction required before any candidate or holdout evaluation**. This is a second-pass code/evidence review by the same agent, not independent external assurance. No strategy parameters, execution code, terminal, existing datasets or saved replay results were changed. No new strategy configuration or backtest was evaluated.

## Confirmed findings

### P1 — minimum-stop validation uses the wrong reference after slippage

`backtesting/engine.py:_enter_frozen()` compares fill-to-stop distance against minimum stop plus spread. However, the adverse entry fill already includes slippage and tick rounding. MT5 protection distances use the opposite current quote: BUY SL/TP against Bid, SELL SL/TP against Ask. This rule is documented in [the official MT5 guide](https://www.mql5.com/en/book/automation/symbols/symbols_spreads_levels).

The exact audit joins each saved trade to its immutable entry-bar bid open and preceding closed-bar spread, using the recorded cost multiplier. It checks BUY `bid_open - SL` and `TP - bid_open`; SELL `SL - ask_open` and `ask_open - TP`. Snapshot stop constraints are unchanged. Across the three SFX Vol 99 cases, **36 of 526 trade observations** have insufficient opposite-quote protective distance:

| Cost case | Saved trades | Violations |
|---|---:|---:|
| Zero assumed commission | 279 | 13 |
| Assumed USD 3/lot/side | 175 | 13 |
| Doubled spread/commission | 72 | 10 |

These are overlapping observations from three alternative replays, not 526 independent entries. The nine no-trade symbols have no accepted fills to inspect. This is a violation of the declared frozen quote proxy, not proof of actual broker rejection: historical executable quotes and contract stability remain unverified. An earlier conservative bound excluding slippage detected zero; the exact quote-side calculation supersedes that bound. Both artifacts are preserved.

Fix: validate final tick-rounded SL/TP against declared bid/ask opening quotes, independent of modeled fill slippage; cover both directions and exact boundaries. Preserve all existing constraints and the old results. A corrected replay requires a new model identity and new output directory, never an overwrite.

### P1 — separately rounded risk components can understate the cash loss

`backtesting/economics.py:FrozenMarketModel.quantity()` rounds stop loss and exit slippage separately. The engine instead combines the stop and slippage into one final tick-rounded exit price and then rounds its P/L to cents. Rounding these paths separately can accept a quantity whose actual modeled stop loss exceeds its risk budget.

Executable offline reproduction: balance USD 31.80, 1% risk = USD 0.318; BUY entry 1000, stop 969.60, exit slippage 1.40, minimum/step/max quantity 0.01 lots, zero fee/swap. The model accepts 0.01 lots. Its separate rounded components total USD 0.31; the engine-equivalent combined loss at 968.20 is USD 0.32. This exceeds the budget. This is an accounting reproduction, not a new trading configuration evaluated for performance.

No saved trade in the 526 observations has a realized net loss above its own 1% budget. That does **not** establish that all accepted hypothetical stop losses were within budget; the counterexample establishes the implementation defect. Fix by calculating worst-case stop execution with the same outward tick rounding and combined cash P/L as closing, then add cent-rounded fees and the financing reserve. Include equality and just-over-budget tests without rounding the risk budget upward.

### P2 — liquidation marks omit executable tick rounding

`_mark()` applies spread/slippage and computes P/L directly, whereas `_close()` rounds the exit price adversely to the contract tick. Marks can overstate liquidation equity relative to a contemporaneous close. This is identified by code inspection; its campaign-wide amount has not been quantified. Reuse the same pure exit-price accounting function for marks and fills. Do not relabel the old drawdown as corrected.

## Fee and financing reconciliation

The saved evidence contains 18 deal observations across four symbols and a single nonzero aggregate swap value of -USD 0.13. It retains distinct fee/commission ratios and swap amounts, but no complete position identifiers, side/entry/exit timestamps, volume changes, or booking timeline. Consequently this snapshot cannot reconstruct that swap charge, identify separate commission balance postings, or verify the tariff on the only traded research symbol SFX Vol 99.

The [Weltrade SyntX overview](https://help.weltrade.com/en/articles/13434918-trading-account-types-overview-cent-micro-pro-syntx-and-raw-spread) advertises commission from USD 3/lot, without an exact account-specific per-side schedule. A newly located [official Copy Trading SyntX schedule](https://docs.weltrade.com/syntx-trading-limits-and-conditions.pdf) gives symbol-dependent commissions and deal minima, including SFX Vol 99 USD 4/lot with USD 0.04 minimum. **Its stated scope is Copy Trading. It does not establish this demo account's tariff and must not replace the campaign's assumptions.** It reinforces that a universal USD 3 assumption is not account verification.

[Weltrade swap guidance](https://help.weltrade.com/en/articles/14485261-swap-in-trading-what-it-is-and-how-it-works-on-weltrade) states weekday midnight EET booking and an instrument-specific triple day. [MT5 symbol definitions](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants) define interest-current calculation from the swap-time instrument price using a 360-day year. Neither source resolves the campaign's historical ending-day convention, actual booking clock/DST, changing rates, price proxy or account-specific exceptions. Exact fee/financing status remains **UNVERIFIED**.

Required evidence, before cost qualification: an account-specific dated fee schedule covering all ten exact native contracts, charge side(s), minimum fee/rounding, demo applicability and exceptions; plus a read-only complete position/deal and balance-charge timeline sufficient to reconcile at least one nonzero rollover and triple-day event. Do not submit orders to manufacture evidence or contact anyone without explicit authorization.

## Evidence and validation

- [Initial conservative review](2026-10-08-model-review-evidence.json): all 30 saved metric files bound by SHA-256, zero lower-bound violations, no realized losses above budget.
- [Exact quote-side review and executable risk counterexample](2026-10-08-model-review-exact-evidence.json): 36 violations and risk rounding failure. Source script hashes are added separately; scripts retained under ignored `reports/` are read-only artifact analysis, not alternative signal/replay paths.
- The completed campaign and its trial ledger remain unchanged. Prior green tests (2,604 backend; 238 frontend/build) did not cover these defects and must not be treated as model certification.

## Recommendation and next work

Freeze strategy research. Repair the three offline accounting defects with targeted regression coverage, bump the model identity, then run the complete canonical 30-case training campaign into NEW artifacts at identical data, capital, risk, signal settings and costs. Run the full safety-preserving backend/frontend checks after implementation. Keep this as an accounting correction, not a favorable parameter trial, and compare the corrected results transparently with the original flawed-model baseline. Resolve fee/financing evidence separately; correction alone cannot unlock promotion.

## NOT proven

No corrected baseline, candidate improvement, verified fee tariff, swap reconciliation, live-plan equivalence, untouched OOS expectancy or independent certification. The previous negative training results are retained as flawed-model diagnostics; no corrected trade count or metric is inferred by dropping the 36 affected observations. Their rejection would alter balances and subsequent eligibility, requiring a complete canonical rerun.
