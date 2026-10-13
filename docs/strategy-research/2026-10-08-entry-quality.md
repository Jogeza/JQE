# Entry-quality research — 2026-10-08

Recommendation: **needs more data; adopt no strategy change**. No improvement established. The canonical baseline has negative simulated expectancy at illustrative costs on all seven active eligible symbols. FX Vol 20 has no trades. Verified Weltrade account-currency expectancy is unavailable. This mission has not established institutional-level entry quality or a deployable edge.

## Frozen protocol and scope

Only `D:\JQE\venv\Scripts\python.exe -m backtesting.backtest --entry-quality-audit reports/entry-quality-20261008/baseline-gap-disclosed` performed replays. All decisions use `strategy.pipeline.generate_trading_signal`, the existing indicators/regime translation and BacktestEngine/RiskEngine. No live path, strategy, risk, execution file, environment file, dataset, terminal or operator safety state was changed.

Universe: every existing M5 bundle (17 native Weltrade symbols). M1 was excluded before examining returns. Hash-verified manifests identify the provider, exact symbol, retrieval time, UTC window and source. Terminal catalogue availability was not rechecked because terminal access is prohibited. No aliases or replacement prices were used. Active operator databases and untracked historical backups were not used.

Nine bundles fail closed-bar provenance: their last candle closes after manifest retrieval. Eight remaining bundles each have one 15-minute timestamp interval (two missing M5 bars), after index 303. Gaps stay unfilled. The gap is in training, not the test window; indicator state still incorporates discontinuous training history. Hash validity does not prove correct UTC provenance. Initial provenance-only pass rejected gaps; before any replay, protocol was revised to allow disclosed gaps. That first pass ran zero backtests. Its evidence is retained separately.

Chronological split: indices [0,350) train, [350,500) test. Indices [0,200) warm indicators only; training diagnostics evaluate [200,350). Test starts flat, uses only prior closed observed bars, and enters at the next observed bar open. Train trades close at its boundary; no position or pending order crosses into test. Each test partition is evaluated once per prespecified cost scenario. No tuning was performed. These previously existing research bundles are not certified untouched external holdouts; this is a chronological diagnostic holdout, not proof of an unseen deployment sample.

One baseline strategy configuration; **zero candidate configurations**, zero parameter searches. Eight eligible symbols × two partitions × three cost assumptions = 48 canonical runs. No candidate was formulated from the now-exposed test outcomes. Reusing this holdout to tune a future candidate is prohibited.

## Baseline assumptions

Initial simulated cash 50 per symbol/run; 1% risk, minimum confidence 70 in backtest RiskEngine (canonical strategy independently enforces 75), minimum ATR 1, maximum spread 30. Default stop 1.5 ATR, target 3 ATR, timeout 19 observed bars. Single position per symbol. Conservative stop-first ordering on same-bar collision; gap fills at trigger price, not adverse gap-open price. Daily live limits are not enforced in research.

Costs are **assumptions, not measured Weltrade costs**: existing default = zero; illustrative = 0.10 ATR spread + 0.05 ATR adverse entry slippage + 0.01 simulation-cash fee per trade; stress = 0.20 ATR spread + unchanged 0.05 ATR slippage + 0.02 fee. Spread and slippage shift entry price, with stops/targets anchored to that fill; the fee is deducted at exit. There is no exit-slippage or funding model. Therefore stress is an internal sensitivity experiment, not verification that a broker edge survives doubled real costs. Simulation units use linear price P&L, never verified MT5 lots.

## Exact data and provenance


| Symbol | Full UTC window | Retrieval UTC | SHA-256 manifest content hash | Disposition |
| --- | --- | --- | --- | --- |
| FX Vol 20 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:33.258564+00:00 | sha256:ad800dc14b4a5b7187e5484e14e251c438e8129298a4f18dbc29b632be148605 | Replay; two missing bars disclosed |
| FX Vol 40 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:35.131484+00:00 | sha256:c8132ab19f90be9b559783c3e3052eafe6baab6f5116caebf27038499e6d3cda | Replay; two missing bars disclosed |
| FX Vol 60 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:37.086863+00:00 | sha256:4a34e06f489c3cf8e78b8f0bc41de1668cfc9d605e97836feae80358f46c1ec4 | Replay; two missing bars disclosed |
| FX Vol 80 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:39.031826+00:00 | sha256:441890a25153268f530dbe9fda18a66917b3d7316ef23e123e1de753437a9b51 | Replay; two missing bars disclosed |
| FX Vol 99 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:40.955015+00:00 | sha256:efca741b7c895e23fd4c266f89178f3ed776572fcc31552908eb62fc0f41536c | Replay; two missing bars disclosed |
| MAX PainX 1000 | 2026-09-26 04:50:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:44.277982+00:00 | sha256:4f97e59cc69512f16ce74166a020fef42198ba9c9065b4df08a1618d02fc4d8b | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| MAX PainX 2000 | 2026-09-26 04:50:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:45.177361+00:00 | sha256:0ff6e3bda2054cdf70150ddeeafa74882394e971fad0165023019f7cbc9feb81 | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| PainX 1200 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:43.405109+00:00 | sha256:23c490343861516faa008b2ad9d4913036e1f3c902a28a08068337f2e42cc3fe | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| PainX 400 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:39.902955+00:00 | sha256:a4c01ec388263fb46c174b1fa1ef5d533a544b753fae9afa77d908419fc5bc3e | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| PainX 600 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:40.780963+00:00 | sha256:5b5e723bc1854133b66c5466f73da9ea7bd24698676fa33d2370fc57a580065a | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| PainX 800 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:41.706365+00:00 | sha256:ca662cf8c638b9cf31eb319a5b63ace2d5d80d8d08722661c4fb62d7af811478 | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| PainX 999 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:42.562294+00:00 | sha256:834210846e39366da9efd995ef9b4843530d94121233f9e27390940193228d11 | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| SFX Vol 20 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:42.898297+00:00 | sha256:42a1a50e7c0493c991b865e25d46180a0e065a82697b0bc91f45b25037902613 | Replay; two missing bars disclosed |
| SFX Vol 40 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:44.752403+00:00 | sha256:edc3a68c2c2f3877fa8c420775db8185e6a627643d6b231decd83b94c4be38db | Replay; two missing bars disclosed |
| SFX Vol 60 | 2026-09-26 02:30:00+00:00 — 2026-09-27 20:15:00+00:00 | 2026-09-27 21:53:46.667919+00:00 | sha256:3cd743661e5d8236c392cf083774f9c6c2a383e936a2560425f2d363de6e74bc | Replay; two missing bars disclosed |
| SFX Vol 80 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:38.083255+00:00 | sha256:64839cfac002b2f9088de93bf2720810bf28e91353ba6ee745d22a8ed56edbef | Bar closes after manifest retrieval time; closed-bar provenance unverified |
| SFX Vol 99 | 2026-09-26 04:40:00+00:00 — 2026-09-27 22:25:00+00:00 | 2026-09-27 19:48:38.994257+00:00 | sha256:627a4dae5b30a286db543744299a16d5e193a70ab7bca5145d90f8b205bdc187 | Bar closes after manifest retrieval time; closed-bar provenance unverified |


All eligible windows: train diagnostics **2026-09-26 19:10–2026-09-27 07:45 UTC**; test **2026-09-27 07:50–20:15 UTC**. Each test covers 150 closed bars (12.5 hours including last bar duration); 500 bars in each complete manifest. Per-run indices and timestamps are recorded in baseline.json.


| Symbol | Train first/last signal UTC | Test first/last signal UTC |
| --- | --- | --- |
| FX Vol 20 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| FX Vol 40 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| FX Vol 60 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| FX Vol 80 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| FX Vol 99 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| SFX Vol 20 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| SFX Vol 40 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |
| SFX Vol 60 | 2026-09-26 19:10:00+00:00 / 2026-09-27 07:45:00+00:00 | 2026-09-27 07:50:00+00:00 / 2026-09-27 20:15:00+00:00 |


## Out-of-sample baseline metrics

All cash figures below are **simulation cash**, with account-currency expectancy **N/A for every row**. R = net simulated P&L / (initial price-stop distance × simulation quantity). Drawdown is realized balance only, not marked-to-market equity. Sharpe is mean/std(ddof=1) of per-trade balance returns; Sortino uses sqrt(mean(min(return,0)^2)); both unannualized, zero hurdle, and not calendar-time portfolio ratios. Exposure is occupied observed bars / 150; all trades are within the contiguous test interval. No portfolio aggregation of overlapping symbol exposure is implied.


| Symbol | N | E cash | E R | PF | Win % | Avg win cash | Avg loss cash | Max DD cash | Max DD % | Sharpe | Sortino | Exposure % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FX Vol 20 | 0.0000 | N/A | N/A | N/A | N/A | N/A | N/A | 0.0000 | 0.0000 | N/A | N/A | 0.0000 |
| FX Vol 40 | 8.0000 | -0.1482 | -0.2941 | 0.5292 | 37.5000 | 0.4443 | -0.5037 | 1.5589 | 3.1178 | -0.2620 | -0.3646 | 36.0000 |
| FX Vol 60 | 4.0000 | -0.0447 | -0.0849 | 0.8239 | 50.0000 | 0.4181 | -0.5074 | 1.0149 | 2.0298 | -0.0769 | -0.1177 | 37.3333 |
| FX Vol 80 | 4.0000 | -0.1385 | -0.2699 | 0.6411 | 25.0000 | 0.9900 | -0.5147 | 1.5442 | 3.0283 | -0.1799 | -0.3056 | 18.6667 |
| FX Vol 99 | 6.0000 | -0.0149 | -0.0199 | 0.9565 | 33.3333 | 0.9845 | -0.5146 | 1.0337 | 2.0291 | -0.0129 | -0.0239 | 31.3333 |
| SFX Vol 20 | 3.0000 | -0.5049 | -1.0202 | 0.0000 | 0.0000 | N/A | -0.5049 | 1.5148 | 3.0295 | -4924.1010 | -1.0000 | 11.3333 |
| SFX Vol 40 | 3.0000 | -0.5049 | -1.0202 | 0.0000 | 0.0000 | N/A | -0.5049 | 1.5148 | 3.0295 | -4924.1017 | -1.0000 | 6.0000 |
| SFX Vol 60 | 5.0000 | -0.2118 | -0.4201 | 0.4806 | 20.0000 | 0.9798 | -0.5097 | 1.5287 | 3.0289 | -0.3131 | -0.4604 | 22.0000 |


Pooled descriptive results: **33 trades**, mean **-0.1847 simulation cash/trade**, **-0.3670 R/trade**, win rate **27.27%**, profit factor **0.5005**. This pools independent simulated accounts and is not a portfolio backtest.


Exploratory 95% symbol-cluster bootstrap interval for pooled mean R: **[-0.6601, -0.1730]**, 10,000 draws, seed 20261008, sampling eight symbol blocks with replacement and retaining all their chronological trades. This preserves within-symbol order/dependence but cannot capture shared shocks across symbols or longer-term regime uncertainty. Only one test day is available; a credible time-block uncertainty interval and rolling walk-forward validation are unavailable. The interval is not institutional validation.


## Entry quality and cost sensitivity

MAE/MFE use all high/low extrema from entry through the entire exit bar, divided by initial stop distance. These are **OHLC upper bounds**, not exact pre-exit excursions, because intrabar ordering is unknown. Time distributions include timeout and forced end-of-data exits. Median bars × 5 gives median minutes; N/A means no trades.


| Symbol | MAE R p10/p50/p90 | MFE R p10/p50/p90 | Holding bars p10/p50/p90 |
| --- | --- | --- | --- |
| FX Vol 20 | N/A | N/A | N/A |
| FX Vol 40 | 0.3237/1.0184/1.2648 | 0.1430/0.3286/1.7332 | 3.4000/5.5000/10.6000 |
| FX Vol 60 | 0.1978/0.8271/1.2773 | 0.6185/0.9393/1.5038 | 9.8000/14.5000/17.8000 |
| FX Vol 80 | 0.9078/1.1738/1.3459 | 0.0225/0.0964/2.0174 | 2.3000/4.0000/14.1000 |
| FX Vol 99 | 0.4811/1.0174/1.2222 | 0.1221/1.0277/2.0552 | 2.5000/5.5000/15.5000 |
| SFX Vol 20 | 1.5145/1.8800/1.9330 | 0.0412/0.1866/0.8666 | 2.0000/6.0000/9.2000 |
| SFX Vol 40 | 1.0923/1.2252/1.6473 | 0.1010/0.5049/0.6148 | 1.4000/3.0000/4.6000 |
| SFX Vol 60 | 0.9986/1.3817/2.2582 | 0.1196/0.1806/1.4023 | 2.4000/3.0000/13.4000 |

| Symbol | Default N / E R | Illustrative N / E R | Double spread+fee N / E R |
| --- | --- | --- | --- |
| FX Vol 20 | 0 / N/A | 0 / N/A | 0 / N/A |
| FX Vol 40 | 7 / 0.2057 | 8 / -0.2941 | 8 / -0.3312 |
| FX Vol 60 | 4 / -0.0147 | 4 / -0.0849 | 4 / -0.1385 |
| FX Vol 80 | 3 / 0.0000 | 4 / -0.2699 | 4 / -0.2897 |
| FX Vol 99 | 6 / 0.0000 | 6 / -0.0199 | 4 / -0.0267 |
| SFX Vol 20 | 3 / -1.0000 | 3 / -1.0202 | 3 / -1.0404 |
| SFX Vol 40 | 3 / -1.0000 | 3 / -1.0202 | 3 / -1.0404 |
| SFX Vol 60 | 5 / -0.4000 | 5 / -0.4201 | 5 / -0.4401 |


Costs change fills, exits, subsequent eligibility and sometimes trade count; these are full canonical replays, not fee subtraction from the same trade list. No positive edge survives the stated illustrative/stress assumptions. Zero-cost FX Vol 40 has positive simulated mean R on only seven trades; this disappears with assumed costs. Near-zero FX Vol 80/99 default means are floating-point noise.


## Diagnosis before any strategy change

Training diagnostics at illustrative costs contain 30 trades. The following clusters are descriptive, not tuned selection thresholds. Two ATR is a diagnostic display bucket only; no candidate filter was run.


### Training diagnostics


| Signal regime | Direction | Distance from EMA50 | N | Losses | Mean R | Median entry gap ATR | Exit reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TREND_UP | BUY | >=2ATR | 20.0000 | 14.0000 | -0.3241 | 0.1505 | {'TIMEOUT': 2, 'STOP_LOSS': 14, 'END_OF_DATA': 1, 'TAKE_PROFIT': 3} |
| TREND_UP | BUY | <2ATR | 10.0000 | 4.0000 | 0.5705 | 0.1461 | {'STOP_LOSS': 4, 'TAKE_PROFIT': 4, 'END_OF_DATA': 1, 'TIMEOUT': 1} |

### Test diagnostics (now exposed; cannot tune on these)


| Signal regime | Direction | Distance from EMA50 | N | Losses | Mean R | Median entry gap ATR | Exit reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TREND_UP | BUY | >=2ATR | 21.0000 | 17.0000 | -0.6021 | 0.1489 | {'STOP_LOSS': 17, 'END_OF_DATA': 2, 'TAKE_PROFIT': 2} |
| TREND_UP | BUY | <2ATR | 12.0000 | 7.0000 | 0.0443 | 0.1451 | {'STOP_LOSS': 7, 'TAKE_PROFIT': 3, 'TIMEOUT': 2} |


The baseline enters only TREND_UP/BUY setups here. In code, FeatureEngine marks momentum STRONG only above RSI 60; `core.regime` re-exports the legacy detector, whose TREND_DOWN requires RSI below 50. SignalEngine requires STRONG momentum for SELL. These conditions cannot coincide, making canonical SELL entries unreachable. No alternative signal path was introduced to compensate.

StrategyEngine records the six-factor ConfidenceModel total as `institutional_confidence`, but the operative confidence is the FeatureEngine score. Strong momentum scores 30, trend 30, normal volatility 10 = 70 (below the canonical 75 threshold); high volatility scores 20, giving 80. Entries consequently favor elevated relative ATR. The legacy regime bridge does not emit HIGH_VOLATILITY, so the SignalEngine's high-volatility regime protection is not activated by that bridge. These are design observations; neither directional symmetry nor switching confidence scores has proven positive expectancy.

The OHLC bundles have no historical spread column. StrategyEngine therefore uses its existing constant spread fallback of 1.0 for liquidity/confidence context, while RiskEngine uses its existing fallback of 0 for its spread gate. Changing execution-cost assumptions does not inject observed spreads into those signal/risk features. This mismatch further prevents interpreting the audit as a broker-cost-aware execution proof.

Extended training entries lose more often in aggregate, but that is insufficient for a universal filter: sample sizes are small, correlated and contain boundary exits. Stops are anchored to next-open simulated fills, not the signal's TradePlan; an ATR stop is not structural invalidation. Gap-to-entry ATR and excursion bounds are retained trade by trade in the evidence. Cost-induced entry/stop shifts and timeout exits can lose edge independently of signal classification. Their individual causal contribution is not identified by this sample.

## Hypotheses and trial log

1. Baseline audit, configuration B0: unchanged canonical strategy, exact windows above. Three prespecified execution-cost assumptions, no strategy parameter trials. Result: negative simulated test expectancy on all seven active symbols at illustrative costs; one inactive symbol. Failed to establish an edge.
2. Candidate work: **not started**. A late-entry exclusion or direction-aware momentum hypothesis would require a sufficiently long training campaign and a new untouched test dataset with corrected provenance and measured economics. No claim that either improves expectancy is made. Tuning now would reuse exposed test outcomes. No failed candidates were hidden; none were run.

The first provenance-only command targeted `reports/entry-quality-20261008/baseline` and ran zero replays. The revised command targeted `baseline-gap-disclosed`; both protocol files and exclusion inventories remain. [Baseline evidence](2026-10-08-evidence/baseline.json) retains all 48 runs, exact indices, per-trade outcomes, decision-state counts and manifest hashes. [Frozen protocol](2026-10-08-evidence/protocol.json) retains all costs and trial counts; [initial inventory](2026-10-08-evidence/provenance-only-inventory.json) and [initial protocol](2026-10-08-evidence/provenance-only-protocol.json) preserve the pre-replay provenance pass. Canonical fingerprints currently omit evaluation indices, so train/test can share a fingerprint; use manifest hash + partition + explicit start/end indices + cost, not fingerprint alone, for this audit. No identity-schema migration was attempted.

## Final recommendation

**Needs more data; adopt nothing.** The desired institutional evidence is not met. No strategy improvement was found or claimed. Preserve the negative baseline and stop candidate selection on these test windows. A follow-on campaign requires immutable historical-service exports into new files, verified UTC/closed bars, actual terminal tick economics, historical spread/commission evidence, a prespecified train/validation/final holdout protocol, multiple chronological folds, and enough independent trades/time periods to quantify uncertainty. Acquisition was not attempted because it would access the prohibited terminal. Current operator history was not used as a substitute for frozen provenance.

## NOT proven

- Positive expectancy in Weltrade account currency, verified lots, broker costs, or executable returns.
- Improved entry quality versus baseline: no candidate was tested or adopted.
- A general edge across symbols, jump families, short trades, regimes or market periods.
- Rolling walk-forward robustness or a genuinely untouched final holdout.
- Exact MAE/MFE before intrabar exit, marked-to-market maximum drawdown, calendar-time Sharpe/Sortino, or a portfolio exposure estimate.
- Realistic adverse gap exits, exit slippage, funding, terminal sizing constraints, live/backtest execution equivalence, or forward-demo evidence.
- Institutional certification, readiness for deployment, or any claim of profitability.

## Validation

- Relevant metric/provenance tests: **3 passed** using `D:\JQE\venv\Scripts\python.exe -m pytest -p tests.offline_research_guard tests/test_entry_quality_audit.py -q`.
- Full backend: **2,577 passed, 4 skipped**, 131.47 seconds; `D:\JQE\venv\Scripts\python.exe -m pytest -p tests.offline_research_guard -q --junitxml=reports/entry-quality-20261008/backend-final.xml`. Zero external network attempts. The four existing opt-in skips are one live MT5 diagnostic and three archived forensic tests requiring immutable external fixtures. No safety assertion was removed, weakened or newly skipped.
- Initial full backend attempt: **1 failed, 2,575 passed, 4 skipped**. The audit isolation plugin initially overrode the environment for a repository-default experiment path, causing `test_default_research_experiment_catalog_is_repository_relative` to fail. The wrapper was corrected to isolate the imported settings object as the documented backend checker does; the assertion remained intact. The final full rerun above passed.
- Frontend `npm test -- --run`: **40 files, 238 tests passed**. `npm run build`: **passed**; existing JavaScript chunk-size warning (852.67 kB bundle) remains.
- `git diff --check`: passed (Windows LF/CRLF normalization notice only).

[Validation summary](2026-10-08-evidence/validation.json) preserves command outcomes. Detailed local logs/JUnit evidence remain under `reports/entry-quality-20261008/`; that directory is Git-ignored. The portable baseline/protocol inventories alongside this report are deliberately retained outside it. Source changes are limited to the offline backtest audit CLI/module, its opt-in test-isolation plugin/tests, and this research documentation/evidence. No candidate or live behavior changed.

## 2026-10-08 canonical v2 follow-up

The original v1 evidence above remains unchanged. The separate [canonical v2
training baseline](2026-10-08-v2-training-baseline.md) completed 30 preregistered
conditional-cost replays across ten native Weltrade symbols. Only SFX Vol 99
traded, with negative training expectancy in every cost case. No candidate or
untouched out-of-sample evaluation was performed; no improvement is established.
See that report for all counts, costs, sizing rejections, loss clusters, validation
and explicit limitations. Next work is fee/financing reconciliation and model
review before candidate or holdout work.

## Corrected accounting baseline

The [completed accounting comparison](2026-10-08-accounting-correction.md) replaces
flawed-model values as the current conditional v2 training reference. It preserves
the original artifacts. All 30 replays completed; SFX Vol 99 only has 266 / 164 /
69 trades and mean net R -0.01318 / -0.20808 / -0.46119 for zero / assumed / doubled
costs. Nine symbols remain no-trade; no candidate or OOS result is established.
See the [fee reconciliation](2026-10-08-fee-financing-reconciliation.md) for observed
cashflow evidence, corroborated current swap magnitudes and unresolved historical
terms. Next work requested: preregistered ML feasibility without holdout reuse.

## ML feasibility follow-up

The [ML entry-quality research perspective](2026-10-08-ml-entry-quality.md) reviews
primary sources through September 2026 and records the current blocked readiness,
causal-label requirements, proposed one-model experiment and security controls.
Zero ML models were fitted or performance trials evaluated. Next work: canonical
opportunity-label recording and additional immutable qualified history; existing
holdouts and all negative baseline outcomes remain preserved.
