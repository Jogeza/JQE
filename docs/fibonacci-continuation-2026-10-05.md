# Fibonacci continuation research and hosted service recovery

The owner chose separate symbols under the existing combined position cap,
keeping current stops and targets with an early exit when continuation fails.
No live strategy, execution gate, supervisor or broker order was changed.

`research/directional_momentum.py` tests symmetric RSI confirmation for BUY and
SELL. `research/fibonacci_confluence.py` tests confirmed causal swing pivots,
38.2–61.8% retracements, EMA50/200 direction, RSI momentum, ATR tolerance and
price-turn confirmation. Both are explicitly injected experimental engines
through the canonical strategy bridge; the production engine is unchanged.

The frozen-data comparison is saved in
`reports/fibonacci-continuation-20261005-1226`. It reuses hash-verified completed
baseline/directional results from the interrupted earlier campaign. Trials use
three chronological blocks, observed historical spread and doubled-spread
stress, with dependence-aware uncertainty intervals. These datasets have
already been examined; they are not a new untouched holdout. Simulation units
do not establish feasible MT5 lots or verified account-currency profits.
All 14 pairs completed. Neither the directional momentum variant nor the
Fibonacci variant qualified on any pair under the declared screening criteria.
Positive small-sample outcomes do not establish profitable execution.

`execution/continuation_preparation.py` prepares BUY/SELL limit drafts only.
It requires fresh Weltrade evidence, explicit risk approval, all six factors,
verified USD demo equity, complete exposure snapshots, distinct symbols and
minimum 1.5 reward/risk. Drafts share a maximum 0.5% equity risk budget including
existing reserved risk. It preserves the five combined cap at equity >= USD50
and two pending preparation cap. Every result has submission_authorized=false.
There is no new broker submission path or dashboard integration.

Early-exit advice requires two consecutive closed bars with an opposite trend.
This is a conservative experimental interpretation, not automatic live closing.
Missing or stale observations retain broker stop/target protection.

Validation: 2,552 backend tests passed, four skipped; all 19 groups exited zero
(`reports/backend-continuation-20261005-1226`). Frontend: 172 tests passed and
production build passed. Existing React act and build chunk-size warnings remain.

Production frontend is https://jqe.jokiholdings.com. The local API remains on
127.0.0.1:8000. Its existing authenticated read-only relay on 127.0.0.1:8766 and
Cloudflare connector were restored using saved configuration without printing
credentials. Backend health passed and connector connections registered.
Logs are `logs/relay-20261005-123414.*.log` and
`logs/tunnel-20261005-123414.*.log`; the connector also logged a DNS resolver
timeout, so authenticated end-to-end dashboard verification remains outstanding.
Local Vite remains available, but production is the requested frontend.

The persisted CLOSE_UNCONFIRMED halt remains active despite the separately
confirmed broker close reconciliation. No safety state was cleared. These
session services require the PC to remain on; no VPS purchase or deployment
was performed. Hosted AI context remains quota-blocked/unverified. Markets
layout, drawing persistence and daily starting-balance work remain outstanding.
