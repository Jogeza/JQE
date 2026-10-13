# Frontend clarity pass

Owner requested Hostinger-inspired simplicity, specifically login/account screens and clearer cards. This first presentation pass adds `frontend/src/styles/clarity.css`, imported after the existing themes. Authentication, entitlements, requests, orders and safety behavior remain unchanged.

Login/account surfaces now use a quiet canvas, rounded opaque cards, larger fields, clear purple primary actions and visible keyboard focus. Dashboard cards use opaque surfaces, restrained shadows and more spacing. Profit/loss and risk colors retain their existing semantic tokens. The unavailable-chart message receives readable light-theme contrast. Upgrade purchase controls are excluded from the primary-button restyling.

Visual review: loopback landing/login and workstation inspected. Screenshot `reports/frontend-clarity-login-20261010.png`. Mobile login fields, disabled submission, separate JQE-password warning and unavailable-auth notice remain visible. Workstation shows unavailable market/terminal evidence accurately because the backend endpoint was not reachable in this preview. No login submission, account creation or live operation was attempted. Desktop viewport screenshot capture was clipped by the in-app browser surface; do not claim exhaustive desktop/device verification.

The old frontend endpoint refused connection. A new loopback-only Vite development preview was started (`npm run dev -- --host 127.0.0.1`); no existing service or terminal was stopped/restarted. No authentication environment files were read or changed. Design reference: [Hostinger dashboard overview](https://www.hostinger.com/support/1583483-comprehensive-guide-to-hostinger-dashboard-at-hostinger/); this is JQE styling, not a copied brand or new external dependency.

Frontend final tests/build passed; detailed totals and backend result recorded below after validation. Logs: `reports/frontend-clarity-tests-20261010-02.txt`, `reports/frontend-clarity-build-20261010-02.txt`, `reports/frontend-clarity-backend-20261010-01.txt`. Existing large-bundle warning retained.

Frontend final:240 passed/build passed. First backend run2808 passed/four opt-in skips/two failures: the unchanged lock tests hit the active campaign's global OS lock (PermissionError). Failure retained; no assertion altered or campaign stopped. Full rerun uses a NEW process-local TEMP/TMP directory, so test-owned locks are isolated from the production campaign lock while duplicate-lock assertions remain unchanged. Final result pending below.

Campaign health after the changes: worker alive, source unchanged, 2,524 total completions, zero FAILED entries. No replay source/data/cost/registration changes or ML/holdout work. This check is ledger health only, not coverage qualification.

Next: user review of login/card styling, then simplify information grouping on account and workstation pages with the same status/provenance semantics. Campaign completion and canonical coverage audit remain prerequisites for features/ML.

Final validation:frontend240 passed/build passed after the clearer signup heading (`frontend-clarity-tests-20261010-03.txt`, `frontend-clarity-build-20261010-03.txt`). Isolated-temp full backend2810 passed/four explicit opt-in skips/zero external network attempts (`frontend-clarity-backend-20261010-02.txt`). Initial two lock-contention failures remain preserved. No safety assertions changed. Sign-up screenshot also saved as `reports/frontend-clarity-signup-20261010.png`.
