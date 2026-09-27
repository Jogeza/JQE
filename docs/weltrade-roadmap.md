# Weltrade research standards and delivery roadmap

## Current evidence

The committed scope-research script explicitly reports no candidate with demonstrated positive expectancy. Preserve losing results, sample-size limitations and costs. Do not describe a strategy as profitable because of an in-sample win rate or one successful run.

## Research protocol

1. Acquire native Weltrade terminal history with UTC timestamps, exact symbol, timeframe, provider, retrieval date and immutable dataset hash. Check ordering, duplicate timestamps, missing bars and closed-bar status.
2. Separate volatility-family and jump-family hypotheses. Compare trend continuation, mean reversion and jump-exclusion hypotheses to simple baselines; do not assume a single indicator configuration is best for every instrument.
3. Freeze the hypothesis and parameter search bounds before evaluation. Use chronological training/validation/test splits and rolling walk-forward evaluation. Fit transformations only on the training partition and avoid overlapping labels across boundaries.
4. Include observed spread, commission, slippage, gaps and conservative same-bar stop/target ordering. Use actual terminal tick size, tick value, lot step and minimum volume. Reject unknown contract economics; generic simulation units are not Weltrade account-currency profit.
5. Report net expectancy, drawdown, number of trades, exposure, turnover, profit factor and uncertainty intervals. Use dependence-aware resampling, disclose multiple trials and test cost sensitivity. Keep a final untouched holdout.
6. Forward-test the frozen candidate on demo. Reconcile decisions, orders, fills and positions, recording divergence from backtest assumptions. Promotion requires sufficient samples and stable behavior across time windows, not a profit screenshot.

## Delivery sequence

- Finish Weltrade-only runtime, API and test migration; remove obsolete selectable brokers while retaining auditable historical evidence.
- Verify read-only terminal identity, native symbols and cached history on the user's PC. Record terminal limitations rather than silently filling gaps.
- Build reproducible cost-aware research reports and compare family-specific candidates against baselines. Existing experimental scripts do not establish a production edge.
- Improve the workstation around connection health, data provenance, active safety blocks, research evidence and journaled results. Keep simulated outcomes visually separate from broker fills.
- Design real-account release criteria only after demo evidence is reviewed. Real trading is not enabled by this migration.
- Add partner-or-paid entitlements once the owner supplies the partner link and the supported verification/payment mechanisms. Enforce entitlements server-side with auditable events, revocation and credential isolation.

## Engineering acceptance

Weltrade only in configuration, factory, operator controls and new history acquisition; no hidden cross-broker fallback. Preserve emergency stop, explicit risk approval, position limits, duplicate prevention and UNKNOWN/PENDING recovery. Full backend tests, frontend tests and production build must pass before claiming migration completion.
