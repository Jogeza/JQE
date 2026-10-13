# Longer-history all-symbol opportunity/label design (2026-10-09)

Frozen registration: `reports/long-history-label-registration-20261009-01/protocol.json`.
SHA256: `754e420b1b5c18d8b384584643e3242a1fd364e2146529b52c90339fb6b3f9a8`.
This is an inspected past-TRAIN design, not an untouched OOS registration.
Ten native symbols/M5, original July10 full prefix/200 observed warmup bars,
evaluation July10 16:40 through October8 00:00 UTC half-open (89.3056 days).
One design, zero new label outcomes, ML fits, candidate or holdout evaluations.

| Frozen pre-outcome census | Events |
|---|---:|
| All canonical BUY/SELL opportunities | 81,679 |
| Eligible/unlabelled | 80,646 |
| Gap-censored | 978 |
| Training-boundary censored | 55 |
| Planned eligible event/cost attempts | 241,938 |
| Censored cost dispositions to retain | 3,099 |

All thirty full saved result hashes and archived replay source hashes verified.
Every symbol's canonical signal-close index/time/direction/confidence agrees across
its three cost siblings; observations cover every evaluation bar. EXECUTION_REJECTED
is a next-bar disposition, never another opportunity. Portfolio-blocked, pending-
blocked and risk-rejected BUY/SELL signals remain opportunities. Baseline state
is retained for diagnostics only, excluded from the frozen eight-feature allowlist.
Event IDs bind the new registration/prefix/content; old labels cannot transfer.

Every prospective event resets USD50/no open or pending position/1% risk. Preserve
frozen-weltrade-cfd-v2, broker lot/minimum-stop/margin constraints, stop1.5ATR,
target3ATR, holding19 observed bars, stop-first collision, adverse stop-gap fills,
lagged recorded spreads,0.05ATR slippage, and unchanged three conditional costs.
Only canonical generate_trading_signal inside run_backtest can queue the target;
no later entry after its exit. Original full indicator prefix must match saved
baseline before labels. Existing SFX99-only label dispatcher is incompatible;
never alter its restrictions or old registrations to force all-symbol reuse.

Require the entire contiguous M5 window i-3 through i+19 before outcomes, with
last required close <= train end. Conditional Sunday closures remain raw gaps:
any crossing censors the whole event even if it might exit before the closure.
No boundary liquidation can rescue a censored event. Every cost retains rejects
and censors as null returns, not zeros. Independent overlapping labels are not
stateful portfolio returns or independent samples.

Executed return availability is actual exit-bar close; non-executable disposition
uses rejected entry-bar close. Purge cost siblings by latest actual availability,
synchronize symbols by UTC, and fit transformations only in training folds.
Feature semantics/provenance need separate new-prefix qualification; no features
were exported here. Entry gaps, MAE/MFE and outcomes are forbidden entry features.
Full label-horizon contiguity does not independently qualify feature lookbacks.

This design binds the completed baseline's hash-verified source archive. Current
live even-lot sizing/partial exits/profit-stop management is excluded. Any new
canonical dispatch implementation needs separate source identity, source-difference
disclosure, signal/indicator/fill equivalence tests and all-symbol one-target pilot.
No claims of matching old/new source hashes or live-policy performance validation.

Design audit `design-audit.json`: PASS_DESIGN_ONLY/zero errors, all81,679 IDs,
censors, closed-bar availability and input hashes independently reverified against
CSV timestamps. Event export contains no label/return/exit/features fields.
Relevant offline governance checks29 passed/zero external network attempts.
No application code changed; latest complete unchanged-source validation remains
backend2,725/four explicit skips and frontend240/build passed. No terminal, session,
execution setting, running service or safety changes were made in this step.

Next: separate canonical all-symbol one-target dispatcher and equivalence pilot,
then immutable resumable training-label dispatch only after qualification. Costs,
historical margin/financing/calendar, independent sample sufficiency and a fresh
chronological ML registration/holdout remain open. Original EMA50 holdouts sealed.
This large planned campaign was not started; never report its census as labels.
