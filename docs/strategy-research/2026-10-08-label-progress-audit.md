# Training-label campaign: partial evidence audit

At October 8, 2026 09:33 Kampala time, the existing canonical campaign remained
running with no final summary. No duplicate run was started, and research source
was left unchanged. This is a partial saved-artifact audit, not a performance
evaluation or completed campaign claim.

The audit checked all 211 completed ledger/artifact pairs available at its
snapshot. No duplicate completed event/cost identities or missing artifacts were
found. All correspond to registered eligible events. The current source snapshot
matches the frozen implementation plan.

Executed artifacts contain exactly one trade, original signal identity, entry at
the next five-minute bar, exit within the 19-entry-bar horizon and availability
at exit-bar close. No END_OF_DATA outcomes were accepted. Net R matches net P&L
divided by positive planned stop cash. Independent starting capital remains USD
50 and quantities remain typed MT5 lots. Non-executable artifacts contain no
trade, null return and explicit rejection reasons. No audit errors were found.

| Cost case | Executed | Non-executable |
|---|---:|---:|
| Zero commission | 49 | 21 |
| Assumed USD 3/lot/side | 14 | 57 |
| Doubled spread/commission | 0 | 70 |

Unequal totals reflect the in-progress chronological loop, not independent
samples or comparable completed performance windows. Do not infer strategy
expectancy from this partial or overlapping label table. All 8,499 planned
attempts and the final source/coverage audit remain required.

[Machine-readable checks](2026-10-08-label-progress-audit-01.json) preserve this
snapshot. Source/data, terminal, processes, execution gates and safety state were
not changed during this audit. No new tests or backtest were required for this
read-only inspection; the prior reliability validation remains 2,646 backend
passes/four opt-in skips and 240 frontend passes/build pass.

## NOT proven and next work

Complete coverage, final label qualification, causal features, sufficient history,
verified historical costs, ML readiness and positive OOS expectancy remain
unproven. No models or strategy candidates were fitted, and sealed holdouts were
not read. Next check the same running campaign and its final summary; retain all
failures if it stops, then complete the full availability/coverage audit before
feature extraction or ML fitting. Do not change replay source mid-campaign.
