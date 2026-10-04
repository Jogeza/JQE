# Pipflow reference and JQE implementation

Reference reviewed 4 October 2026: https://pipflow.org/ and https://pipflow.org/demo . Public product pages are reference material, not verified access to Pipflow's internal implementation or trading results.

Visual inspection also covered the existing signed-in overview and chart workspace at https://pipflow.org/chart . Captured chart reference: reports/monitor-setup-20261004/pipflow-visual-reference.png. Observed patterns: near-black backgrounds, purple primary actions, grouped left navigation, a slim drawing toolbar, top instrument/timeframe controls, a dominant chart, and a persistent right-side panel with Chat / Jessica / Trade / Strategies tabs and short contextual prompts. No analysis request, account connection, subscription or trade was submitted during the visual review. These layouts are references for a future JQE design iteration, not features claimed as implemented by the status update.

Useful product patterns include chart-adjacent research AI, visible strategy reasoning, explicit draft/backtest/live stages, outcome history and clear risk controls. JQE retains its own branding and Weltrade synthetic demo scope. Pipflow's markets, connectivity claims, subscriber counts and performance claims are not copied into JQE.

## First implemented increment

- Independent GET-only analysis loop refreshes the configured four watchlist pairs through JQE's canonical active-analysis API. It records actual broker freshness and keeps order execution unavailable in that process.
- Backend journal projection distinguishes analysis process health from execution supervisor health. Stale or missing process evidence cannot produce a current status.
- Frontend shows fresh analysis coverage and execution status separately. A running research loop does not imply that trading is armed.
- Telegram language is friendlier while preserving actual prices, targets, demo labels, rejection reasons and HTML escaping. Existing chart branding remains consistent.

Live verification: GET-only analysis process reports all four configured pairs current. The local journal API reports analysis RUNNING (4/4) and execution STOPPED_OR_STALE separately. Frontend deployed to Vercel production EBBHf1wax5vLU31gUiYV5VCPtGJo. Backend validation: 2,495 passed, four skipped across 18 offline groups (reports/backend-analysis-tone-20261004); focused API/analysis checks: 50 passed. Frontend: 169 passed and production build passed. The execution safety halt remains intact; no TP1 add-on or pending limit order was submitted.

## Next implementation gates

1. Repair and verify the broker deal-history timestamp mismatch. Reconcile existing closed positions and retain an auditable safety recovery before restarting execution.
2. TP1 management: define an actual TP1 distinct from final broker TP, closed volume fraction, broker minimum/step handling, spread/fees-aware break-even, remaining protective levels and durable action IDs. A target hit alone is not a fresh entry signal. Proposed one-add-on behavior remains pending the owner's answer and implementation.
3. Pending buy/sell limits: owner approved at most two pending orders, counting pending orders plus positions toward the existing total cap of five. execution/pending_limits.py now prepares pure limit drafts and checks capacity, complete broker evidence, duplicate keys, same-symbol blocks, directional prices and explicit risk approval (13 focused tests passed, including malformed metadata). It cannot submit orders. Live support still needs typed BrokerGateway/AsyncTradeExecutor plumbing, pending-order observations, expiry/cancellation, durable reserved aggregate risk and recovery for fills during disconnection. Existing BUY_STOP/SELL_STOP types are not buy/sell limits.
4. Research draft UI: describe rules, show an editable draft, validate chronological backtests with costs, then review guarded demo promotion. AI output must not directly authorize orders or silently replace the live strategy.
5. VPS migration and cloud snapshot history follow docs/cloud-vps-setup.md. Current PC-off trading is not available.

JQE does not automatically learn to hold trades from journal entries. Trade management changes need explicit rules, offline verification, recovery coverage and reviewed demo evidence. Never remove stop-loss protection merely to hold a losing trade longer.

Final preparation validation: reports/backend-pipflow-preparation-20261004 contains all 18 backend group exits at zero, 2,506 passed and four skipped. Two subsequent malformed-metadata cases passed in the 13-test focused policy run. Frontend remains 169 passed with a successful production build. These checks validate preparation and observation behavior, not live pending-order execution.
