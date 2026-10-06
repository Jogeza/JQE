# Active analysis and blocked safety refresh

The active strategy view was stale despite fresh terminal observations because
Weltrade history conflicted with an existing cached closed candle at Unix time
1791117600. `CandleStore.save_candles` correctly rejected the overwrite, and the
API previously fell back to the entire stale cached batch.

The observation API now handles cache errors by fetching a separate broker
batch, excluding forming bars and validating chronological ordering and OHLC
data. It reports `CACHE_WRITE_FAILED` alongside current broker observation.
Invalid or unavailable broker observations still fall back truthfully to cache.
No conflicting historical data is overwritten, deleted or silently relabelled.
The canonical strategy pipeline and all execution/risk gates remain unchanged.

Live verification on 5 October at 12:48 Kampala: FX Vol20 M5 latest closed bar
was 12:45, matching the expected close; FRESH and SYNCHRONIZED with NO_TRADE.
This repairs current observation availability, not the historical conflict.
Stored research datasets remain untouched. The context's legacy
`latest_stored_candle_close` field is populated from the observed batch;
`CACHE_WRITE_FAILED` explicitly identifies that this batch was not persisted.

The read-only safety evaluator now includes persisted integrity-halt evidence.
`tools.refresh_readonly_preflight` verifies the already connected demo session
without logging in, backs up the safety database and publishes BLOCKED evidence.
The 12:48 preflight confirmed AUTHORITATIVE daily broker history, no unresolved
intents and PERSISTED_INTEGRITY_HALT/CLOSE_UNCONFIRMED. The safety snapshot expires
normally while the execution supervisor is stopped; no periodic refresh or
execution loop was activated to make readiness appear green.

The read-only API was restarted to load these fixes. Production frontend remains
https://jqe.jokiholdings.com through the existing authenticated relay. No hosted
deployment, order submission, supervisor launch, halt clearing, terminal/account
switch, secret change or VPS purchase occurred. Shared Windows log rotation
still produces file-lock warnings and remains separate follow-up.

Focused validation: 14 cache/freshness tests and four preflight tests passed.
Frontend: 172 tests and production build passed. Final full backend: 2,555
passed, four skipped; all 19 groups exited zero. Evidence is in
`reports/backend-synchronization-final-20261005`.
