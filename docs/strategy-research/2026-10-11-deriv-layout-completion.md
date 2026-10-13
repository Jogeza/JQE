# Deriv-style workstation continuation

Signed-in Deriv Home, value breakdown and Options overview were visually reviewed
on web/mobile after owner sign-in. Public Trader was also reviewed in both sizes.
Only navigation/disclosures were used; no financial actions or account switches.

JQE now uses a compact dark balance/account bar, with equity, free margin, realized
UTC net P/L and masked identity inside its disclosure. The chart dominates the
desktop canvas beside a 280-pixel setup rail; positions/history move below it.
Duplicate decision overlay removed; the same decision card remains in the rail.
AI opens on demand rather than occupying a persistent desktop column. Mobile has
bottom quick navigation and stacked chart/setup/records. Weltrade-only identity,
unavailable states, provenance and guarded demo execution remain intact.

This matches structural patterns, not every Deriv feature or pixel. JQE does not
gain Deriv options, stake/payout controls, deposits or real-account switching.
Existing unrelated workspace edits were preserved. No backend/replay source,
campaign, environment, safety state or terminal/process changes were made.

## Validation

- Final frontend: 240 passed; build passed with the existing bundle-size warning.
  Logs reports/deriv-layout-tests-20261010-04.txt and
  reports/deriv-layout-build-20261010-04.txt.
- Full offline backend: 2,810 passed, four explicit opt-in skips, zero external
  network attempts. Fresh process-local temporary directory isolated campaign lock.
  Log reports/deriv-layout-backend-20261010.txt.
- Initial frontend run failed one old layout-location assertion. Updated it to
  require the activity container; broker record/P&L/state assertions retained.
  Failure preserved in reports/deriv-layout-tests-20261010-final.txt.
- Desktop/mobile unavailable views reviewed. Screenshots:
  reports/deriv-matched-jqe-web-20261010.png and
  reports/deriv-matched-jqe-mobile-20261010.png. Populated account/chart views remain
  unverified because the API was unavailable. Hosted deployment unchanged.
- October 11 continuation found no listeners on 5173/8000; frontend loopback preview
  launched again. No existing process stopped or restarted; backend/MT5 untouched.

Next resolve read-only API availability and verify populated views, then continue
Home/Overview market-card simplicity. Full campaign coverage still gates ML.
