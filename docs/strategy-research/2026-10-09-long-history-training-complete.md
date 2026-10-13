# Completed longer-history conditional training (2026-10-09)

Thirty registered canonical TRAIN replays complete. Saved-artifact audit PASS, zero errors; source stable through replay/audit. Full source files were copied and hash-verified before the separately requested live partial-management change.

| Cost | Trades | Mean net R | 95% three-day-block interval | Profit factor |
|---|---:|---:|---|---:|
| optimistic_zero_commission | 319 | -0.104663 | [-0.2671514936910125, 0.04450294803239839] | 0.833333 |
| assumed_3usd_per_lot_per_side | 171 | -0.286770 | [-0.5428446468133816, -0.08619261202651589] | 0.651471 |
| double_spread_and_commission | 63 | -0.579960 | [-1.1060950477388225, -0.3280736028129362] | 0.401975 |

Only SFX Vol 99 traded. Nine symbols/all cost cases retained zero trades and null expectancy/profit factor. All three cost cases have negative mean net R; overlapping observations are not independent events. No OOS/candidate/ML fit, positive expectancy or readiness demonstrated.

Final saved audit reconstructs full result and run fingerprint preimages, source/input/cost identities, exact windows, native quantities, quote-side minimum stops, combined-risk/margin sizing, accounting paths and aggregate summaries. It reports end-data exits, pending entries and gap-delayed entries.

Evidence: reports/long-history-training-20261009-01; reports/long-history-training-audit-20261009-01/audit.json and report.md. Source archive: reports/long-history-training-20261009-01/source-files. Immutable result artifacts remain untouched.

Historical costs, financing, margin, UTC+3/Sunday calendar and live-fill equivalence remain conditional. TRAIN findings do not justify promoting new trade management. The new owner-requested demo partial-management policy has separate source/configuration and has not been evaluated by this frozen campaign.

Replay source validation before campaign: backend 2,702 passed/four skips; frontend 240/build passed. Subsequent management validation is recorded separately.
