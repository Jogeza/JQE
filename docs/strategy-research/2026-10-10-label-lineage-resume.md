# Exact-contract label resume — 2026-10-10

The reviewed serialization change now has an explicit, hash-bound resume contract. Default resume still rejects changed source. This exception binds only the original stopped segment and the exact reviewed implementation; it does not authorize arbitrary mixed-source results.

## Qualification and evidence

- Registration: `reports/long-history-label-registration-20261009-01/protocol.json`, unchanged. Ten native Weltrade M5 symbols; training evaluation July 10, 2026 16:40 UTC through October 8, 2026, half-open. The original full indicator prefixes and fixed costs/risk remain unchanged.
- Original segment: `reports/long-history-label-campaign-20261009-01`. All 53 completed results were reconstructed and verified under their original source identity; one unfinished STARTED attempt is preserved for retry. No original artifacts were overwritten.
- Exact integration contract: `reports/lineage-integration-qualification-20261010-02/contract.json`, SHA-256 `b340813a530b6dce2d7c91aff7fcba3a8ab417abc95eaf4e8ce02ac96275fe7d`. It binds the previously qualified evidence contract, old/approved/current source identities, archived sources, dependencies and input hashes.
- Real preflight: `reports/qualified-label-resume-preflight-20261010-01.json`, PASS for all 53 inherited completions and one interruption. Qualification/preflight dispatched no labels.
- Canonical replay module AST remains identical apart from its CLI dispatch block. Strategy, indicators, accounting, risk and dependencies are protected. Resume results retain their own segment source identity; the final auditor checks both ancestors and the final summary.
- New focused tests cover altered contracts, protected-source/dependency changes, incorrect ancestors/result identities, active owners and missing ancestors. Focused suite: 62 passed; FRVP isolated rerun: five passed. Frontend: 240 passed and production build passed (existing chunk-size warning).

## Failures retained

The first qualification invocation rejected a digest-format mismatch: old evidence contains both bare and prefixed SHA-256 strings. Verification now normalizes only that representation and continues to reject changed bytes. Its failure log is retained at `reports/lineage-integration-qualification-20261010-01.log`.

The first full backend run recorded 1 failed, 2,808 passed and four explicit opt-in skips. The failing FRVP test correctly rejected source drift while the digest-format correction was being made. That run is retained at `reports/lineage-integration-backend-20261010-01.txt`; no assertion was weakened. Final stable-source validation and launch status are recorded below when available.

## Recommendation and NOT proven

Final stable-source backend validation passed 2,810 tests with four explicit opt-in skips and zero external network attempts (`reports/lineage-integration-backend-20261010-02.txt`). Authorized NEW segment launched at `reports/long-history-label-campaign-resume-20261010-01`; launcher PID 19864 and one-shot watcher PID 20364 are recorded in `reports/qualified-label-resume-runtime-20261010-01`. There are 241,885 new attempts remaining. Startup is not completion; verify the current owner/ledger on continuation.

Accept this exact lineage integration for the authorized training-label resume after stable-source validation. Keep all failed/interrupted evidence. This is label infrastructure, not a strategy candidate: zero new strategy parameter configurations, ML fits or holdout evaluations.

Complete coverage, full-campaign throughput/storage, historical fee/calendar qualification, independent sample sufficiency, out-of-sample expectancy and profitability are NOT proven. Independent opportunity labels are not stateful portfolio returns. Feature extraction remains blocked until the complete canonical coverage audit passes.

Next: monitor the existing resumed segment without editing replay source or launching a duplicate; after completion, verify all 241,938 unique event/cost pairs and all 3,099 predeclared censor dispositions before feature extraction.

Startup snapshot at 04:59:39 UTC: worker 19124 alive, source stable, four NEW completions, one active attempt, zero FAILED entries and no final summary. The original 53 completions remain inherited separately. Evidence: `reports/qualified-label-resume-startup-20261010-01.json`. This is partial runtime observation, not saved-artifact coverage qualification or a throughput forecast.
