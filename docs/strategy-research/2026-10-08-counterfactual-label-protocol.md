# Counterfactual training-label protocol v1

Recommendation: proceed to a canonical labeler implementation and equivalence
checks; ML fitting remains blocked. This freezes one label design, not a strategy
candidate. No counterfactual outcome was calculated and no model was trained.

The [machine-readable protocol](2026-10-08-counterfactual-protocol.json) and
[file checksum](2026-10-08-counterfactual-protocol.sha256.json) bind the event list,
source snapshot, immutable dataset and contract/cost evidence. The complete event
list is retained in `reports/counterfactual-protocol-20261008-01/events.json`.
Registration occurred after inspecting historical training baseline outcomes;
it is explicitly **not** an untouched out-of-sample preregistration.

## Scope and census

Exact provider/symbol: Weltrade SFX Vol 99, M5. Signal bars are in September 8
00:00 UTC inclusive through October 8 00:00 UTC exclusive. SFX99 is selected
because it alone produced executable trades at the frozen USD 50 capital/risk
settings; findings must remain symbol-specific. Other symbols' affordability
blocks are retained, not bypassed to manufacture training labels.

| Pre-outcome disposition | Opportunities |
|---|---:|
| Canonical BUY/SELL signals | 2,876 |
| Eligible for future replay | 2,833 |
| Gap censoring | 24 |
| Training-boundary censoring | 19 |
| Counterfactual outcomes calculated | 0 |

One label-design configuration was registered. Zero ML configurations, model
fits or strategy candidates were evaluated. Three fixed cost scenarios would
produce at most 8,499 opportunity/cost replay attempts. They are overlapping
observations of 2,833 events, not 8,499 independent training samples.

## Replay contract

Each event starts an independent simulated account with USD 50, 1% risk and no
open/pending position. Preserve the corrected frozen-weltrade-cfd-v2 contract,
minimum stop distance, lot step/minimum, margin checks, risk reserve, adverse
tick rounding, lagged spreads and financing assumptions. Use all three existing
cost cases without tuning: zero commission; assumed USD 3/lot/side; USD 6/lot/side
with doubled spread. Each retains 0.05 ATR adverse slippage per fill. Fee and
financing qualification limitations remain unchanged.

Generate signals only through `strategy.pipeline.generate_trading_signal` inside
the canonical backtest. Preserve the original training replay's full indicator
prefix, including its original 200 warmup bars; restarting EMA history at each
opportunity would change the strategy. Only the target signal may be queued.
No later entry is permitted even if the target trade exits early. The target
must match its original canonical signal before any outcome can be accepted.

Signal bar i becomes available at its close. Entry occurs at bar i+1 open, using
the prior closed-bar spread and existing fill logic. Preserve 1.5 ATR stop,
3 ATR target and stop-first collision handling. The maximum 19-bar holding
window includes entry bars i+1 through i+19. A label becomes available at the
actual exit bar's close. Neither entry gaps nor subsequent fills/outcomes become
entry features.

Before outcomes, require contiguous five-minute bars from i-3 through i+19,
and the last required close at or before train end. Exclude the whole event
if this fails, even if it might exit before a gap. Do not shorten the horizon
and fabricate an END_OF_DATA return. Earlier source gaps remain disclosed;
the fixed original history and indicator treatment remain unchanged.

Executed labels contain net modelled USD and net R using rounded planned stop
cash as denominator. Canonical risk/quantity/stop/margin rejects have explicit
NON_EXECUTABLE status and null return. Censored events have null return and an
explicit reason. A labeler must account for every registered event in every
cost case, including rejects; it cannot report only winners or filled trades.

## Statistical meaning and implementation checks

These labels estimate a single opportunity's conditional outcome at fixed
capital. Resetting account state intentionally differs from the baseline's
changing equity and position occupancy. Sums of overlapping event returns are
not a portfolio equity curve, strategy expectancy, Sharpe or drawdown. Do not
compare independent-label returns directly with the stateful baseline metrics.

Before using labels, prove original target-signal identity, identical indicator
history and fills, one-entry-only behavior, native constraints and boundary/gap
handling. Later candidate performance must come from a separate stateful
canonical replay against an identical-data/cost baseline. Purge overlapping
labels by actual availability and preserve chronological synchronized folds.

## NOT proven and next work

No complete labels or causal feature dataset exists yet. No baseline improvement,
positive OOS expectancy, universal exact tariff/calendar, 90-day qualified history
or live-plan equivalence is proven. The original EMA50 validation/test partitions
were not read and stay sealed. A separate ML registration and untouched future
holdout remain required before fitting; current research readiness is unchanged.

Next: implement the one-target replay restriction within the canonical backtest,
test equivalence and rejection handling, then execute the registered training-only
label attempts with an append-only failure/completion ledger. Additional history
must come through HistoricalDataService into new immutable files and be qualified
before inclusion. No terminal or execution changes are part of this protocol.

Validation: eleven focused protocol/inventory checks passed; full backend 2,636
passed, four explicit opt-in skips, zero external network attempts. Frontend 238
passed and production build passed with the existing bundle-size advisory.

Owner subsequently authorized starting the frontend/backend and read-only live
terminal checks. Both loopback services passed HTTP health checks, including
the frontend-to-backend proxy. A separate existing-terminal IPC observation
verified the configured Weltrade demo identity, connected status, SFX99 quotes
and zero open positions. No login, symbol selection or order calls were made by
that smoke check. Its first script-path invocation failed before imports; the
module invocation passed. Evidence: `reports/live-observation-smoke-20261008-01.json`.
This operational observation is not a backtest, fill test or strategy result.
