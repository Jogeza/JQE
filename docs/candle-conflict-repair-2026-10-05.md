# Broker candle conflict reconciliation

The read-only watchlist audit found six stored/broker differences in closed
candles: FX Vol20 M5, FX Vol80 M5, SFX Vol20 M1/M5 and SFX Vol99 M1/M5.
Five changed OHLC prices, with several stored rows resembling partial forming
bars. FX Vol80 differed only by one tick of volume. This is evidence of
incomplete older snapshots, not proof that every old discrepancy has one cause.

`tools.audit_candle_conflicts` verifies the existing configured demo account,
terminal path and server offset, reads native terminal contracts and compares
only completed candles with the provider-qualified cache. Default mode is
read-only. `--repair` writes an audit report and a full SQLite backup before
atomically replacing only verified conflict rows. If a cached row changes after
comparison, the transaction rolls back. No forming candles are inserted, no
history is deleted and no execution/safety state is changed.

Four conflicts were repaired first; two older M1 conflicts fell outside the
moving 1,000-bar window. The comparison was widened to 2,000 bars, those two
were freshly verified and repaired separately. Original evidence remains in:

- `data/historical.pre-conflict-repair-20261005T095717Z.sqlite3`
- `data/historical.pre-conflict-repair-20261005T095859Z.sqlite3`
- `reports/candle-conflict-audit-20261005T095615Z.json`
- `reports/candle-conflict-audit-20261005T095717Z.json`
- `reports/candle-conflict-audit-20261005T095859Z.json`

Current live FX Vol20 M5 analysis now reports FRESH_CACHE, SYNCHRONIZED and FRESH
with the expected latest closed candle. Frozen research JSON datasets remain
untouched; their results continue to describe their original hashes, not the
repaired mutable cache. New research must freeze fresh provider-pinned inputs.
The inspected window does not establish correctness of the entire older cache.
Post-repair audit `reports/candle-conflict-audit-20261005T100059Z.json` found
zero conflicts across all 14 inspected pairs. Validation: 2,557 backend passed,
four skipped; all 19 groups exited zero (`reports/backend-candle-repair-20261005`).
Frontend: 172 passed and production build passed.

The trading supervisor remains stopped and CLOSE_UNCONFIRMED remains active.
The next execution prerequisite is a separately reviewed halt-resolution
procedure; cache reconciliation does not authorize orders or imply profitability.
Daily starting-balance tracking, Markets usability and hosted AI verification
remain pending. No paid service, quota bypass or VPS purchase occurred.
