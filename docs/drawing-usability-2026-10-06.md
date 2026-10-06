# Drawing persistence and compact Markets layout

Chart annotations now persist in sessionStorage by Weltrade symbol/timeframe.
Returning to a market or reloading the same browser tab restores its drawings.
The UI reports the drawing count and whether saving is available. Clear affects
only the selected chart. Storage errors leave drawing tools usable temporarily.
Saved data is bounded to 50 drawings, validates numeric time/price anchors,
colors, note length and unique IDs, and ignores malformed records. Notes remain
React-rendered text. No broker mutation, cloud upload or order authorization is
attached to annotations. Closing the tab ends this storage session; drawings
do not sync across devices and do not include account credentials.

The Markets heading and strategy strip are compacted, with a two-column
snapshot grid on narrow screens, retaining provenance and no-plan warnings.
Pipflow's public demo (https://pipflow.org/demo) informed the chart-oriented
presentation; JQE broker identity and safety behavior remain unchanged.

At inspection on 6 October, previous Python/MT5/Cloudflare processes were absent
and the supervisor heartbeat contained NUL bytes. Execution was not verified
running. This UI work did not restart or rearm trading or rewrite that heartbeat.
The existing read-only API/connector were restored after the owner explicitly
approved their external authenticated monitoring exposure. Automatic approval
review had initially rejected that restart; no workaround was used.
API health passed, relay listens on 127.0.0.1:8766 and Cloudflare connections
registered. A DNS resolver timeout remains logged. Authenticated end-to-end
broker delivery is not established by these service checks.
Browser visual validation remains unavailable; automated tests and production
bundle checks cannot establish authenticated end-to-end chart appearance.

Frontend validation: 177 passed; production build passed, retaining the existing
chunk-size and React act warnings. Backend evidence is recorded in
`reports/backend-drawings-20261006`.
Full backend: 2,565 passed, four skipped, all 19 group exit codes zero.
Production deployment `dpl_DjWMJBzxXisu6K96eP7ChCiFuxoV` is READY; the custom
domain serves the new drawing-persistence and Markets bundle.
