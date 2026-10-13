# Risk layout and partial label audit — 2026-10-11

Local presentation-only Risk page change: shorter heading, calmer two-column mobile metrics and removal of the duplicate loss-meter scale. Loss/maximum labels, authorization block/reason, trades/cap, authorized amount, execution quantity/reason and observation timestamp/age remain visible. No authorization logic, broker quantities, backend, replay source, terminal, environment or safety state changed. No deployment.

## Partial saved-label audit

Existing owner 21872 remains the campaign owner. Frozen ledger snapshot contained 89 NEW COMPLETED, 90 STARTED, zero FAILED; no full completion is claimed. Verified first six and last six saved pairs (12 distinct pairs): artifact hash/path, shared full-result reconstruction, full-result hash, registration event/cost/window/data/model identities and canonical target-decision semantics through existing verification helpers. No replay or signal recreation. Output: `reports/risk-ui-label-audit-20261011.json`, ledger SHA256 e4a1f3b3228d8d7e22f76e112f4a99b11f10a8ee1d7993482a9d92b617cd6953.

Zero errors on the sample; this is not complete coverage or expectancy evidence. Combined saved completions at snapshot: 11,703 of 241,938 (11,614 inherited plus 89 new). No duplicate campaign or source edit; keep existing owner/ledger on continuation. Full final audit requires all segments and completed dispatch summary.

## Validation

Frontend 241 tests passed; build/full backend results recorded after completion. Browser Risk unavailable/stale evidence reviewed; screenshot `reports/risk-minimal-20261011.png`. Existing RiskPanel authorization/quantity logic and safety tests unchanged.

## NOT proven / next

No complete label coverage, feature readiness, ML fit, positive expectancy or execution readiness. Partial sampled integrity does not validate every label. Next inspect campaign progress and extend saved-label coverage audit without editing replay source; then clarify Performance's separation of broker observations and canonical research evidence.

Later ledger check: 107 NEW completed/108 started/zero failed; combined 11,721 saved attempts. Browser settled snapshot shows STALE, unavailable authorized risk/quantity and full observation age. Build passed (`reports/risk-ui-build-20261011.txt`); existing bundle-size warning retained.Final backend: 2,810 passed, four explicit opt-in skips, zero external network attempts, exit 0; reports/risk-ui-backend-20261011.txt. Frontend 241/build passed. All checks retain safety assertions.
