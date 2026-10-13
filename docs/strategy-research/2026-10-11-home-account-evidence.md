# Home account evidence and campaign follow-up — 2026-10-11

## Diagnosis and local change

Home previously presented balance/equity from `get_risk_status`, which intentionally reads the last durable risk-cycle snapshot. The workstation uses current read-only terminal observation. The historical snapshot showed 142.56 USD while current terminal evidence showed 141.61 USD. This was a source/age mismatch, not evidence of an accounting calculation error.

Home now consumes the same terminal-observation resource as the workstation. Balance/equity require a connected demo observation without resource error/staleness; otherwise unavailable, with no fallback to saved risk amounts. Currency and observation time are displayed. Home now includes terminal observation in its polling profile, using the existing 8-second cadence/backoff and hidden-tab behavior; without this it would retain a prior workstation read or be unavailable on a first Home visit. Risk-cycle limits and counters remain separate; non-fresh evidence receives a stale amber badge rather than available/permitted. No risk authorization or persisted state changed.

Browser verified Home balance/equity 141.61 USD, matching the workstation at the observed moment. Daily loss and trades today remained marked STALE. Screenshot: `reports/home-terminal-account-20261011.png`. Matching one snapshot is not a sustained synchronization guarantee; legacy execution/open-P&L resources remain separately sourced.

## Campaign follow-up

Existing restored worker PID 21872 (launcher 10040) is alive and consuming CPU. NEW segment `reports/long-history-label-campaign-resume-20261011-01` has no implementation/ledger yet and stderr is empty. Canonical dispatcher is still checking saved results before replay; no new label completions are claimed. Prior segments retain 11,614 saved completions of 241,938, including 11,383 in the most recent prior segment. Cause of prior process loss remains unknown. No duplicate, stop, restart or Python source change performed this turn.

## Validation

Initial frontend tests passed, but TypeScript build rejected nullable currency; corrected to explicit undefined without weakening tests. Failure log retained: `reports/home-account-build-20261011.txt`. Final frontend: 240 passed/build passed, logs `reports/home-account-tests-20261011-05.txt` and `reports/home-account-build-20261011-05.txt` (existing bundle-size warning). Polling-profile test initially failed after the intended extra GET; exact expected request list now includes terminal observation, with abort assertions retained. Failure log `reports/home-account-tests-20261011-04.txt` preserved. Full backend: 2,810 passed/four explicit opt-in skips/zero external network attempts, exit 0, log `reports/home-account-backend-20261011.txt`. Browser observation timestamp advanced from 15:49:49 to 15:50:47 on Home. No safety assertions changed; no deployment, orders, terminal reconfiguration, environment or safety-state changes.

## NOT proven / next

Complete campaign coverage, causal feature readiness, ML fit, strategy expectancy, sustained polling reliability and live execution readiness are not established. Next verify that prior-result validation finishes and the existing campaign ledger advances. Then simplify Journal while preserving broker record provenance. Do not edit replay source while the campaign runs.
