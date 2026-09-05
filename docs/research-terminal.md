# JQE Research Terminal boundary

The research API consumes canonical candles from `CandleStore` in SQLite read-only
mode and runs the deterministic Python backtester. It never constructs a broker
gateway. Sessions are bounded, ephemeral, and identified by the existing SHA-256
hash of normalized candle content.

Replay responses are cursor-scoped. At cursor `N`, the API returns candles and
decisions through `N`, trades whose entries occurred through `N`, and realized
balance/drawdown through `N`. Exit fields and outcomes are absent until the exit
candle. Final metrics are absent until the final cursor. This makes the HTTP
boundary responsible for preventing accidental lookahead; browser filtering is a
second defensive layer.

`balance_curve` means realized, closed-trade balance. It is not mark-to-market
equity. Drawdown is the decline from the running peak of that same realized
balance, matching `BacktestResult.drawdown_basis = REALIZED_BALANCE`.

## Volume semantics

Canonical `Candle.volume` intentionally remains numeric-only. Dataset provenance
now persists its meaning independently in the versioned SQLite cache.

- Deriv public candles currently provide no volume (`UNAVAILABLE`).
- MT5 maps `tick_volume`, so its true meaning is `TICK_VOLUME`, but this metadata
  is lost when stored in the present canonical candle/cache schema.
- Simulation provides generated synthetic volume. It must not be represented as
  exchange volume.
- Existing cached non-null volume without provenance is reported as `UNKNOWN`;
  legacy rows are never reinterpreted during migration.

The canonical values are `REAL_VOLUME`, `TICK_VOLUME`, `BROKER_VOLUME`,
`SIMULATED_VOLUME`, `UNAVAILABLE`, and `UNKNOWN`.

## Fixed Range Volume Profile v1

FRVP is a research-only view. It cannot authorize or alter strategy signals,
risk, position sizing, execution policy, or broker submission. Python consumes an
immutable research session's canonical `CandleStore` dataset and provenance. The
browser receives and renders the resulting snapshot; it does not calculate bins,
POC, VAH, or VAL.

Eligibility fails closed. `REAL_VOLUME`, `TICK_VOLUME`, `BROKER_VOLUME`, and
`SIMULATED_VOLUME` are eligible and retain their explicit semantic label and
source. `UNAVAILABLE` and `UNKNOWN` are ineligible. Missing candle volume is also
ineligible; no value is fabricated or inferred.

Algorithm `frvp-contract-v1` uses `UNIFORM_RANGE_OVERLAP_V1`:

1. The profile range is the minimum low through maximum high of the inclusive
   selected candle-index range. Fixed-width bins begin at that minimum, are
   ordered low to high, contiguous, and half-open `[low, high)`. The final bin is
   closed at the profile maximum and may be shorter than the requested bin size.
2. Candle volume is allocated in proportion to the width of each bin overlap:
   `volume × overlap width / candle high-low`. OHLCV candles do not reveal exact
   intrabar volume distribution, so this volume-at-price result is an
   approximation. A zero-range candle assigns its full volume to its containing
   bin; an upper-boundary price belongs to the final bin.
3. Allocation conserves volume exactly under Python `Decimal`: the sum of bin
   volumes equals the sum of selected source-candle volume. Any division residual
   is assigned to the candle's final overlapped bin.
4. POC is the midpoint of the maximum-volume bin. Equal maxima choose the
   lowest-price bin.
5. Value area begins at POC and expands contiguously. At each step it includes the
   adjacent bin with greater volume; equal adjacent volumes choose the lower-price
   bin. Expansion stops when included volume reaches or exceeds the configured
   fraction of total volume. VAL and VAH are the lower and upper edges of this
   contiguous area, so `VAL <= POC <= VAH`.

Requests are bounded to 2,000 bins. Unsupported algorithms/allocation methods,
invalid ranges, non-finite values, invalid fractions, and excessive bin counts
fail closed. Identical inputs serialize deterministically. Snapshot identity
includes dataset hash, index/timestamp range, profile bounds, volume semantics and
source, bin configuration, value-area fraction, allocation method, algorithm
version, bins and levels, plus conservative gap metadata. Detected gaps are
reported and never interpolated or filled by FRVP.

The read-only endpoint is
`POST /api/v1/research/backtests/{session_id}/volume-profile`. It resolves candles
only from the immutable server-side session and accepts no paths, URLs, broker
credentials, or browser-provided candle arrays. When a replay cursor is supplied,
the server enforces `range_end_index <= cursor`; future candles cannot contribute
to bins, levels, total volume, or gap analysis.

Future strategy experiments should treat volume-profile relationships as features
under test and evaluate them with train/validation/test splits and out-of-sample
results. They are not strategy assumptions by default.

## FRVP experiment framework

FRVP experiments are deterministic offline counterfactuals over the unchanged
canonical backtest result. `POC_PROXIMITY_FILTER_V1` filters existing baseline
trades when `abs(entry price - POC) / ATR` is below a candidate threshold.
`VALUE_AREA_LOCATION_V1` classifies those same trades as `ABOVE_VAH`,
`INSIDE_VALUE_AREA`, or `BELOW_VAL`; it does not create signals.

Profiles use `ROLLING_FIXED_LOOKBACK`: for a decision at candle `N`, the inclusive
profile is `N-lookback+1 ... N`. No candle after `N`, future exit, future P&L, or
future indicator participates in feature construction. The dataset is split
chronologically 60% train, 20% validation, and 20% out of sample, without random
shuffle. Candidate thresholds are reported on validation and selected by
validation expectancy (then validation net P&L, then the lowest threshold for a
deterministic tie). Test metrics never select parameters and are reported once
for the selected configuration.

Every partition reports baseline and variant trade count, win rate, net P&L,
expectancy, profit factor, average and median result, and maximum realized-balance
drawdown, plus explicit deltas. A configurable minimum trade count defaults to 30;
smaller out-of-sample groups are `INSUFFICIENT_SAMPLE`, not evidence of
improvement. `UNAVAILABLE` and `UNKNOWN` volume return
`FRVP_EXPERIMENT_UNAVAILABLE`. `SIMULATED_VOLUME` fixtures validate mechanics only
and are not market evidence.

Requests are bounded to 2,000 session candles, 200 lookback candles, eight
threshold candidates, and 1,000 rolling profile calculations. A later
walk-forward engine can advance explicit train/validation/test windows while
preserving the same identities and per-dataset results.

An FRVP experiment result is evidence about a particular historical dataset and
configuration. It is not permission to change live strategy behavior.

## Dynamic Deriv research catalogue

The Research Terminal obtains instrument truth from the unauthenticated Deriv
`active_symbols: "full"` public request. The backend normalizes provider data into
immutable JQE `MarketInstrument` values; React never calls Deriv and never sends a
display label as a historical-data identifier. Provider symbol, canonical JQE
symbol, and display name remain separate.

The adapter is pinned by contract tests to the `deriv-api-schemas` master contract
inspected with release line `production_v20260804_0`. That contract names
`underlying_symbol`, `underlying_symbol_name`, `underlying_symbol_type`, `market`,
`subgroup`, `submarket`, `pip_size`, `exchange_is_open`, and
`is_trading_suspended`. A deliberate compatibility path normalizes the older
SmartCharts `symbol`/`display_name`/`symbol_type` form. Malformed entries are
discarded, unknown market strings are preserved, and deterministic ordering is by
market, submarket, display name, and provider symbol. Periodic schema audits and
clear adapter failures detect drift; schemas are not downloaded or executed at
runtime.

Catalogue discovery has a 15-minute bounded in-memory TTL. A refresh failure
returns the last validated catalogue as stale; without one it reports unavailable.
Local CandleStore datasets are enumerated independently, so public discovery
failure does not remove cached research. Cache identity remains provider +
canonical symbol + timeframe, with dataset-specific provenance and content hash.

Deriv `ticks_history` is public and uses the selected provider symbol with
`style: "candles"`. JQE exposes its supported subset of schema granularities:
M1, M5, M15, M30, H1, H4, and D1. Historical capability remains `UNKNOWN` until
bounded acquisition is attempted because `active_symbols` alone does not prove
candle availability. Acquisition is explicit, limited to 5,000 candles, and
flows through `HistoricalDataService` into CandleStore. `contracts_for` is not
used because execution-contract availability is not historical research
capability.

Changing market, instrument, or timeframe invalidates the old session, replay,
timer, candles, decisions, trades, indicators, FRVP snapshot, experiment result,
metrics, and scoped errors before new research is shown. This selector is never
an execution symbol selector.

Historical acquisition is an observable in-process job boundary.
`POST /api/v1/research/history/acquisitions` returns immediately with `QUEUED`,
`RUNNING`, `COMPLETED`, or `FAILED`; clients poll the returned identifier at the
matching GET endpoint. Identical active requests share one job. At most two jobs
contact the public provider concurrently, the registry holds at most 32 jobs,
and terminal records expire after one hour. The registry is deliberately
ephemeral across API restarts; CandleStore data and provenance remain durable.

Progress is factual rather than a fabricated percentage: requested range,
cached-before count, provider-received count when knowable, inserted and duplicate
counts, stored coverage, gap count, content hash, request count, and volume
semantics are reported. A fully cached range completes without contacting the
provider. Failures preserve valid partial cache writes and report incomplete
coverage; retrying creates a new safe job after the failed job becomes terminal.
Changing provider symbol, canonical symbol, or timeframe isolates the old job in
the browser so a late response cannot replace the newly selected market.

## Research-terminal UX reference decisions

The terminal shell was reviewed against Marketcalls projects as interaction
references only. No external source code or dependency was copied into JQE.

| Reference pattern | Decision | JQE treatment |
| --- | --- | --- |
| Compact research watchlist | ADAPT | UI-local favourites over the backend Deriv catalogue; no quote authority |
| Ctrl+K or `/` symbol switch | ADAPT | Focuses local catalogue search and uses the normal stale-state reset |
| Persistent layout preferences | ADAPT | Benign favourites, category, instrument, and timeframe only; revalidated against each catalogue |
| Toolbar indicator organization | ADAPT | Visibility controls for existing Python-authoritative EMA50, EMA200, RSI, and volume only |
| Explicit chart/pane lifecycle | ADOPT | Each `JQEChart` owns and removes its Lightweight Charts instance and series |
| Two-chart comparison | ADOPT | Optional pair of independently owned canonical research workspaces; single-chart remains the default |
| 4/6/8 chart grid | FUTURE | Not promised; first validate performance and interaction clarity with the bounded two-workspace design |
| Crosshair/time synchronization | FUTURE | UI-only and timestamp-based; never synchronize unrelated price scales |
| Yahoo/yfinance data authority | REJECT | Deriv public backend and CandleStore remain authoritative |
| Client-calculated canonical indicators or profile | REJECT | Python remains authoritative for indicators, FRVP, and experiments |
| Mixed-universe market breadth or copied trend score | REJECT | Semantics are invalid across the heterogeneous Deriv catalogue |
| Footprint, delta, CVD, DOM from OHLCV | REJECT | Unsupported without authoritative tick/order-book semantics |
| Chart order entry and position tools | REJECT | Research Terminal has no execution authority |

The resulting desktop layout uses a compact context bar, cached-status watchlist,
large primary chart, canonical-indicator display toolbar, focused replay controls,
and collapsible acquisition, FRVP, and experiment panels. Favourites and the last
valid selection are stored in `localStorage`; credentials, account identifiers,
broker configuration, and execution preferences are never persisted.

## Reusable chart workspace and comparison mode

`ResearchPage` owns the backend catalogue, favourites, category/search filters,
comparison enablement, and the explicit active-workspace identifier. Selection
actions from the toolbar and watchlist are routed only to that active workspace.
Single-chart mode is the default; comparison mode mounts exactly one additional
workspace and returns focus to the primary workspace when disabled.

`ResearchWorkspaceState` contains presentation and selection state only: stable
workspace identity, the selected catalogue instrument, timeframe, EMA overlay
visibility, and typed price/volume/RSI pane visibility. It contains no candles,
indicator values, signals, account state, or execution authority. Preferences may
persist comparison enablement and the second instrument/timeframe, but are
revalidated against the current backend catalogue. Storage failures remain
non-fatal.

Each `ResearchChartWorkspace` owns its canonical backtest session request, replay
view/cursor/timer, request generation guard, acquisition poll, FRVP result,
experiment result, and errors. Instrument or timeframe changes alter the
workspace selection identity and clear only that workspace's transient state.
The other workspace remains mounted and unchanged. Replay keyboard handling is
focus-local to its own toolbar, so a keystroke cannot advance both workspaces.
Autoplay timers are also instance-local.

Each workspace mounts one `JQEChart`. Chart handles, price/EMA/volume/RSI series,
fit state, markers, price lines, and FRVP primitive remain instance-local.
Lightweight Charts auto-sizing owns resize observation. The mount effect removes
the chart on unmount; request abort controllers, acquisition intervals, replay
timers, and keyboard handlers are cleaned up by their respective effects. Replay
and indicator visibility update existing series and do not recreate the chart.

Request behavior is intentionally bounded. Mounting or enabling a workspace does
not start a backtest or acquire history. A user-triggered cached backtest makes
one session request followed by one cursor-scoped replay read; advancing replay
makes one additional replay read. Instrument/timeframe changes and overlay/pane
visibility changes make no candle request. Stale replay reads are aborted, and
explicit session/acquisition requests are aborted or generation-rejected when a
workspace changes identity or unmounts. Acquisition polling exists only while an
explicit job is non-terminal and its interval is removed on cleanup.

Historical acquisition is a manual advanced action. Its trigger is inside the
collapsed acquisition disclosure—not beside ordinary chart controls—and the
expanded panel shows the provider symbol, canonical display context, timeframe,
and UTC range before the button. Expanding the panel, changing selection, or
enabling comparison never initiates acquisition. While a job is active the
button reports its running state and is disabled; React continues to call only
the canonical backend acquisition endpoint and never a provider directly.

Price is the required base pane, volume is an optional overlay pane, RSI is an
optional secondary pane, and EMA50/EMA200 remain optional price overlays. These
controls only hide or show values already returned by Python. React never derives
EMA, RSI, ATR, regimes, signals, FRVP bins, or experimental results.

On wide desktops two workspaces appear side by side; below 980px they stack so
charts remain readable. A future extension beyond two charts would require a
bounded workspace registry, explicit resource limits, and measured fetch/render
budgets. This checkpoint deliberately does not promise a general chart grid or
crosshair synchronization.

License audit at the time of review: `marketcalls/openalgo-charts` is Apache-2.0;
`marketcalls/yfinance-terminal` and `marketcalls/tradingview-yahoo-finance` are MIT;
`marketcalls/trading-terminal` had no repository license file, so only high-level
interaction concepts were considered. No Marketcalls source was copied.
