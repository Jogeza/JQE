# Deriv visual layout review before further edits

Owner requested visual inspection of web/mobile and Options before matching the
layout. No JQE source, process, environment or data changes in this review.

## Directly observed

The official Deriv Trader page links Try now to https://dtrader.deriv.com/.
The legacy app.deriv.com entry redirected to marketing home. Public Trader loaded
without authentication and displayed a real market chart; no order buttons were
activated and no trade parameters were changed.

- Web: thin left navigation rail, compact market/type tab row, login/account area
  at top right, dominant chart and narrow right parameter panel. Chart tools sit
  near the lower-left canvas; price scale at right and time scale at bottom.
- Mobile at 390x844: compact logo/account header, market/type tab underneath,
  chart above a rounded control tray; Rise/Fall switch and duration/stake settings
  use short labels. Bottom navigation has Home/Trade/Automate/Menu.
- Market/type picker opens a full-screen mobile view with horizontal contract
  tabs, category chips, grouped instruments and percentage changes. Search and
  favourites are available. Observed tabs include Rise/Fall, Accumulators,
  Matches/Differs, Over/Under, Even/Odd, Multipliers, Touch/No Touch,
  Higher/Lower, Turbos and Vanillas. These are Deriv products, not JQE capabilities.

Screenshots: reports/deriv-options-web-20261010.png and
reports/deriv-options-mobile-20261010.png. Desktop was additionally checked at
1440x900; mobile used viewport emulation, not a physical-device/app inspection.
Viewport override was reset after review.

## Unavailable

Home navigated to home.deriv.com/dashboard/login?session_absent=1. Actual signed-in
balances, account dropdown, home cards and account switching were not inspected.
The official illustrated account/trader reference was viewed separately but does
not qualify as an interactive signed-in account review. Requested owner to open
an existing authenticated dashboard; no credentials requested or entered.

## JQE implementation mapping

Continuation: after the owner signed in, Home and Options overview were inspected
at desktop and mobile viewport sizes. Home has a dark total-value header, horizontal
account cards, shortcut icons and a desktop left sidebar/mobile bottom navigation.
The total-value disclosure groups wallet and trading balances. Options overview
has a dark balance header, market cards with mini charts and platform/type sections.
Real/demo selectors were observed without switching accounts. No deposits,
transfers, orders or account changes were made. Private balances/identity are not
copied into JQE or this report. This supersedes the earlier sign-in limitation.

Replace the large account-summary card with a compact account balance/dropdown;
keep masked identity, source time and unavailable states. Give the chart most of
the canvas, one setup/risk rail on desktop and a compact tray on mobile. Put record
tabs below the chart; remove duplicate decision overlay only if the same evidence
remains accessible beside/below it. Use native Weltrade instruments and existing
guarded controls. Do not import stake/payout, options contracts or account switches
that JQE does not implement. Preserve source and safety indications.

Next: inspect authenticated Home/account layout, then implement the final matching
workstation arrangement and verify both viewport sizes plus complete test suites.
Public reference: https://deriv.com/trading-platforms/deriv-trader and
https://experts.deriv.com/insights/meet-the-new-and-improved-deriv-trader.
