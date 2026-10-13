# Research dashboard simplicity

Research now uses one main column, a shorter heading and a Charts tab. Market
browsing, Fibonacci controls, experiment filters and detailed audit notes are
collapsed native disclosure sections. The duplicate general-dashboard symbol and
timeframe header is omitted on Research because its controls do not select the
research chart. Notifications and feed status remain available.

The negative-edge warning remains visible; its full qualification text is retained
under Research limits. Experiment results remain labelled unverified simulations
with audit pending. Filter behavior, comparison identities, costs and pagination
are unchanged. No Python, execution, environment, campaign data or process changes
were made for this task. Existing unrelated working-tree changes were preserved.

## Validation

- Frontend: 240 tests passed; final build passed. Build retains the bundle-size
  warning. Logs: reports/research-minimal-tests-20261010-04.txt and
  reports/research-minimal-build-20261010-05.txt.
- Full offline backend: 2,810 passed, four explicit opt-in skips, zero external
  network attempts. Process-local fresh TEMP/TMP isolated the active campaign lock.
  Log: reports/research-minimal-backend-20261010-01.txt.
- The initial encoding attempt failed while reading a second file; subsequent
  edits used UTF-8. Build 04 failed on an unreachable backtesting comparison after
  the header change; the stale title branch was removed and build 05 passed.
  No assertions were removed or weakened.
- Local browser review confirmed the filters expand and collapse. Screenshot:
  reports/research-minimal-20261010.png. The catalog API returns HTTP 500, so loaded
  catalog records and charts were not visually verified. This is a local preview;
  the hosted deployment was not updated.

## Next

Resolve the read-only research API failure to verify populated views, then simplify
Journal. Full campaign coverage remains required before feature extraction or ML.
This UI change establishes no trading performance evidence.
