# Markets and Settings clarity

Presentation-only clarity.css changes increase spacing and heading hierarchy on Markets and Settings. Strategy-plan facts now sit in an opaque rounded panel, with existing BUY/SELL, stop/target, valid-plan and analysis-only semantics retained. Settings cards have larger supporting text, more readable key/value rows, wrapping navigation buttons and visible keyboard focus. No requests, safety validation or execution behavior changed.

Local mobile-sized browser review completed for both pages; screenshots `reports/markets-clarity-20261010.png`, `reports/settings-clarity-20261010.png`. Existing API errors remained visible: UNAVAILABLE, DEMO ONLY/UNVERIFIED and NO VALID PLAN, with no fabricated broker evidence. No live action or service restart. Hosted production unchanged.

Validation logs: `reports/markets-settings-tests-20261010-01.txt`, `reports/markets-settings-build-20261010-01.txt`, `reports/markets-settings-backend-20261010-01.txt`; final results below. Backend uses process-local isolated temporary stores/locks to avoid campaign contention; no assertion skipped or changed.

Next: simplify Journal and Research views, keeping actual fills separate from simulations and making provenance/qualification limits readable. Campaign completion and full coverage remain required before features or ML.

Final validation: frontend240 passed/build passed (existing bundle warning); backend2810 passed/four explicit opt-in skips/zero external network attempts. Campaign worker alive/source stable. No hosted deployment or replay-source changes.
