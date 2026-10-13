# Account-first workstation layout

The workstation now presents balance, equity, free margin and realized UTC net
P/L above the market chart. Amounts use two decimal places and the reported
account currency. Account identity/server and observation details are in a native
disclosure. Unavailable/error observations do not populate the new summary from
retained account values. The observation timestamp remains visible.

The chart height increases from 460 to 560 pixels when the AI dock is closed.
Existing market/timeframe selectors, setup rail, position/history tabs, supervisor
evidence and execution controls remain intact. The account row uses two columns
on small screens and four on larger screens. AI-docked desktop placement reserves
a full-width summary row above chart and dock.

Reference: Deriv's public account and Trader layout documentation:
https://blog.deriv.com/blog/an-introduction-to-dtrader-the-trading-platform
and https://experts.deriv.com/insights/meet-the-new-and-improved-deriv-trader.
The reference is presentation only; no Deriv product/account integration is added.
Realized P/L is not labelled floating P/L, and no missing amount is replaced by zero.

## Validation and limits

Frontend 240 tests passed; build passed with the existing large-bundle warning.
Logs: reports/workstation-account-tests-20261010.txt and
reports/workstation-account-build-20261010.txt.
Full offline backend: 2,810 passed, four explicit opt-in skips, zero external
network attempts. Validation is recorded in
reports/workstation-account-backend-20261010.txt using fresh process-local TEMP/TMP.

Local browser review confirmed account disclosure expansion/collapse and the
unavailable summary above the chart. Screenshot:
reports/workstation-account-20261010.png. API failure still prevents populated
account/chart visual verification; exhaustive desktop/device testing is not claimed.
Local only; no hosted deployment, backend source, environment, execution, MT5,
running campaign or immutable data changes. Existing unrelated edits preserved.

## Next

Resolve the read-only API failure and verify actual account/chart evidence, then
continue simplifying Journal and diagnostic grouping. Campaign complete coverage
still gates feature extraction and ML; this UI work supplies no expectancy evidence.
