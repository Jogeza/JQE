# Canonical one-opportunity replay implementation

Implemented the frozen one-opportunity mode inside `backtesting.backtest.run_backtest`.
Signal generation still uses `strategy.pipeline.generate_trading_signal`; the
existing BacktestEngine handles risk, quantities, fills and exits. No production
signal, execution, environment, terminal or immutable-data file was changed.

The mode requires SFX Vol 99/Weltrade/M5, USD 50, default 1% risk and the frozen
execution settings. It rejects incomplete 19-entry-bar horizons and local gaps.
Only the target signal is generated/queued, using the complete original prefix.
Direction and confidence must match the saved canonical observation. No later
entry is queued, and END_OF_DATA trades invalidate the result. Fingerprints
explicitly distinguish independent-opportunity research from stateful results.

## Fixed implementation pilot

The first three eligible registered events were replayed under all three frozen
cost cases, selected chronologically before outcomes. Nine attempts completed;
zero failed. Full results, source snapshot, pre-run plan and append-only ledger
are in `reports/counterfactual-pilot-20261008-01`. The original label design and
checksums remain unchanged; the implementation plan binds that design to the new
source snapshot. [Compact evidence](2026-10-08-counterfactual-pilot.json) retains
labels, rejects and source/ledger hashes.

| Cost case | Executed | Non-executable |
|---|---:|---:|
| Zero commission | 3 | 0 |
| Assumed USD 3/lot/side | 0 | 3 |
| USD 6/lot/side + doubled spread | 0 | 3 |

Non-executable attempts retain null returns and explicit rejection reasons.
Cost scenarios overlap: this is three distinct opportunities, not nine independent
samples. The first zero-commission pilot trade exactly matches every serialized
trade field of the corresponding saved stateful baseline trade. All nine target
signals matched the original canonical direction/confidence. This limited check
does not establish equivalence for every future event or cost scenario.

The pilot is dispatched only via the canonical CLI:

```powershell
& D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --counterfactual-pilot reports/counterfactual-protocol-20261008-01 --inventory-campaign reports/entry-campaign-20261008-04 --cost-terms reports/entry-cost-terms-20261008-01.json --output reports/counterfactual-pilot-20261008-01
```

That existing output path cannot be overwritten. Future reruns require new paths
and must be logged as additional attempts. The pilot blocks real terminal SDK
access; the running frontend/backend are separate observation services.

## Verification and limitations

Tests cover matching first fills, full-prefix history, no re-entry after early
exit, target mismatch before queueing, truncated horizons, unregistered capital
and retained native stop rejection. The initial equivalence fixture failed its
intended re-entry assertion because its first trade held until timeout. The
fixture was corrected to force an early stop; no safety assertion was removed.
The focused initial corrected run passed 25 replay/protocol/accounting checks.

This is one unchanged label-design configuration and one fixed implementation
pilot, with nine opportunity/cost attempts. Zero ML models, parameter searches
or strategy candidates were evaluated. Original EMA50 holdouts were not read.

## NOT proven and next work

No strategy improvement or positive OOS expectancy is established. Complete
counterfactual coverage, features, sufficient independent history, exact historical
fees/financing and ML readiness remain unproven. Independent event labels cannot
be summed into a strategy equity curve or used as a baseline performance comparison.

Next: extend the verified dispatcher to the complete registered 2,833-event,
three-cost training campaign (8,499 attempts), with resumable immutable chunks,
source-drift checks and explicit accounting for every reject/censor/failure.
Then audit label availability and causal features before any separately
preregistered ML fit. Additional history and a fresh ML holdout remain required.

Final validation: 2,642 backend tests passed, four explicit opt-in skips, zero
external network attempts. All six new one-opportunity tests also passed in an
independent focused run. Frontend: 238 tests passed; production build passed
with the existing bundle-size advisory. Diff check passed.

Separate operational finding: the existing frontend serves HTTP 200, but direct
backend `/health` and its frontend proxy timed out on repeated checks. Backend
and frontend processes remain present. Cause is not established; neither was
restarted, and execution/terminal settings were unchanged. Diagnose backend
responsiveness before a larger label campaign; passing offline tests does not
prove current service health. This finding does not change the pilot results.
