# Tarasque / Volarbear — Claude Working Context
_Last updated: 2026-05-27 | Model: claude-opus-4-7_

---

## INSTRUCTIONS FOR FUTURE CLAUDE INSTANCES

**Read this file first, every session.** It is your primary context. Update it at the end of every session or after any significant change. Follow this protocol:

1. **Start of session**: Read this file. Verify any file paths or function names before acting (use Glob/Grep — memory can be stale).
2. **During session**: Track progress on the checklist. Mark items complete as you go.
3. **End of session**: Rewrite this file with updated progress, new bugs, findings, decisions, and next actions. Keep the format consistent.
4. **What to record**: Work done, bugs fixed, analysis findings, decisions made, and **why**. The "why" is critical — future instances won't remember the reasoning.
5. **What NOT to record**: Code patterns derivable from reading the files, git history, ephemeral task details.

Leo's instruction: *"you should be adding information to this file to give context for next iterations of yourself: work plans, implementation stages, checklist, progress percentages, next actions — always update this same document and tell the next iteration of yourself to do this"*

---

## 🔥 PICK UP HERE (state as of 2026-05-27)

**v1 backend is LIVE on Supabase with overnight weekly_extend complete.** 284K rows of step_days=20-cadence predictions pushed last night (was 270K under single-retrain extension). Pipeline ran cleanly 23:11 → 00:56. All 93 tickers extended through today's date with proper WFA cadence.

**Live Supabase row counts (verified 2026-05-27 morning):**
```
volatility_history  : 283,796   (+13,206 vs yesterday — step_20 cadence retrains)
prices_history      : 283,797
securities          :      94   (93 prod + 1 leftover test row)
event_history       :   6,948
macro_calendar      :  10,124
model_runs          :       4   (id=4 created last night, current canonical)
```

**Live Supabase URL:** `https://kynrztmoshssqduxhdsb.supabase.co`

### 🚨 2026-05-27 foundational finding: the wedge isn't what we thought

Four discriminating tests showed our +0.40 IC "VRP signal" is **NOT** what the project
framing assumed. Honest reframe:

| Test | Finding | Implication |
|---|---|---|
| A: variance decomposition | 98.6% idiosyncratic but per-ticker idio median IC = -0.05 | Signal lives in cross-sectional structure, not time-series wiggle |
| B: macro correlation | Agg wedge: +0.59 dollar, +0.56 breakeven, -0.49 yield slope, +0.17 SPY vol | Tracks macro liquidity cycle, NOT equity fear |
| C: regime-conditional IC | Calm +0.42, normal +0.44, **stress +0.36** | True VRP should strengthen in stress; ours weakens |
| D: event-orthogonal | Raw IC +0.40 → residual +0.14 after calendar-week demean | 65% of predictive power is earnings-season clustering |

**The signal is real (+0.40 IC, validated across 11 years × 267k obs) but it's a
combination of cross-sectional structural ranking + earnings-season patterns + macro-
liquidity-cycle correlations — NOT per-stock real-time fear premium.** Product framing
must change accordingly. See [RESEARCH_TODO §12](model/RESEARCH_TODO.md) for full
test write-up.

**The β_mz aggregate signal IS the genuine market-fear early warning** (separately
validated 2026-05-27: caught 7 of 8 major US vol shocks 2015-2026, +1.13× lift on
down→up sign-change events at H=21d). This belongs on the Macro page as "Universe
Calibration Drift" — frame it product-side as the early-warning indicator, NOT
the per-stock wedge.

**Test E + F closure (2026-05-27)**: doubly-residualized wedge (strip calendar-week
+ cross-sectional mean) has SLIGHTLY NEGATIVE IC (-0.10), confirming there is NO
hidden per-stock fear-premium signal to recover. Path-length target gives identical
IC to vol-std target (+0.003 delta), so target choice isn't a hidden lever. Final
verdict: the +0.40 IC lives entirely in the 30%-of-variance seasonality + macro
component. Question closed. See [RESEARCH_TODO §12](model/RESEARCH_TODO.md) for
the complete decomposition.

**YZ migration tested and rejected (2026-05-27)**: rigorous WFA POC (15 tickers ×
5 folds × full ensemble × 2 estimators = 150 trainings) showed YZ degrades
R² (mean Δ = −0.64) despite marginally increasing event-gravity importance.
**Economic reason**: earnings overnight gaps are largely surprises — model can
know the date but not the magnitude. YZ adds unpredictable variance to the
target. GK was actually a defensible choice all along by implicitly defining a
more learnable forecasting problem. **Decision: don't do full corpus YZ retrain.**
The wedge framing IS what it is regardless of target; YZ doesn't rescue per-stock
fear-premium isolation. See [RESEARCH_TODO §12 YZ closure](model/RESEARCH_TODO.md).

**The reframe from earlier in this session is now empirically LOCKED IN.** Every
plausible architectural change we tested (forward IV-prediction, YZ migration,
residual-after-seasonality, path-length targets, ticker-relative thresholds,
trail dynamics) failed to reveal a hidden per-stock fear-premium signal. The
wedge is structural + seasonal + macro patterns. The project's strongest
single signal is the β_mz Universe Calibration Drift indicator (the macro-level
early warning).

**β_mz Universe Calibration Drift Signal — VALIDATED AS DEFENSIVE OVERLAY (2026-05-27)**

The β_mz aggregate signal passed every test we ran. Receipts:

- **Monte Carlo hypothesis test (N=1000)**: p < 0.001 on Sharpe; p = 0.012 on max DD;
  p = 0.021 on total return. Real strategy beats every single random-shuffle null.
- **Multi-index generalization**: 7/8 ETFs see Sharpe improvement; **8/8 see max
  DD reduction** (SPY, QQQ, IWM, XLF, XLE, XLK, XLV, XLI all tested).
- **Cost-modeled backtest (5 bps/flip)**: $300,680 ending value vs $230,992 BH on
  $100k starting; Sharpe 0.92 vs 0.43; max DD -17.7% vs -36.1%.
- **Subperiod robustness**: works in calm/COVID/inflation regimes separately;
  COVID most dramatic (BH -36% DD → overlay -11% DD same year).
- **Slope IC against forward drawdown**: -0.146 (strongest single-signal DD
  predictor we have).
- **Caught 7 of 8 major US vol shocks 2015-2026** (qualitative receipts).
- **Cumulative finding**: HY spread alone is a stronger SINGLE signal (2.70× lift),
  but β_mz adds value as part of a multi-signal framework. Smart combination
  (logistic regression composite) is the path to a meaningfully better signal
  than HY alone.

**Why this signal exists** (best explanation per session discussion):
1. It's a **second-order signal** (about how vol models systematically fail
   before regime transitions), not first-order market state
2. **Academic VRP literature is biased toward alpha generation**, not drawdown
   prediction — defensive signals don't get published as much
3. **Infrastructure prerequisite is unusual** — needs per-stock vol forecasting
   at scale + WFA calibration tracking + cross-stock aggregation + defensive
   reframe, all at once. Signal lives in the gap between research domains.

**Productionization**: SWE-ready spec at
[model/DASHBOARD_SPEC_MACRO_REGIME.md](model/DASHBOARD_SPEC_MACRO_REGIME.md)
with data shapes, component layouts, copy, tooltips, and what-to-claim-vs-not.
This is the new HEADLINE FEATURE of the platform. The per-stock VRP wedge
panel is now supporting infrastructure; the Macro β_mz panel is the centerpiece.

### 🔬 Additional findings from extended session (2026-05-27 late)

**Signal direction asymmetry (statistical significance)**: UP→DOWN (calm-coming)
direction is meaningfully more reliable than DOWN→UP (stress-coming).
- SPY 21d hit rate: UP→DOWN 79% (vs 67% baseline), DOWN→UP 56% (vs 33% baseline)
- Cross-direction t-test on SPY 21d returns: spread +4.66pp, **p = 0.033** (significant)
- Same significant pattern on IWM (p=0.036), marginal on QQQ (p=0.078)
- Economic logic: vol mean reversion is empirically more predictable than vol
  spikes. Bullish calm-coming signals have persistence; bearish stress signals
  predict unforecastable shocks.
- **Implication**: when sizing positions, trust UP→DOWN MORE than DOWN→UP.
  Asymmetric overlay variants (lean long on cooling, only mildly defensive on
  heating) outperform symmetric ones.

**VIXY trading variants (Test 19 in signal_context/README.md catalog)**:
- DOWN→UP buy VIXY (21d): 56% hit rate, mean +17.5% (COVID was +244%, drives
  the mean — winsorized to +6.2%). Tail-event protection trade.
- **UP→DOWN short VIXY (21d): 89% hit rate** — highest precision signal in
  the project. Mean +7.9% per signal; winsorized +8.6% (signal is ROBUST,
  not COVID-dependent). Combination of high signal precision + structural
  VIXY contango decay = consistent short-side win.
- Caveats: VIXY vol ~60-80% annualized → position sizing must be small.
  Short squeeze risk catastrophic (Volmageddon liquidated XIV).

**25% tilt strategy on SPY (the headline deployment)**: Variant A wins on
EVERY metric vs BH SPY (2015-2026, $100k starting, 5 bps/flip + 50 bps borrow):
| Strategy | Ending Value | Sharpe | Max DD |
|---|---|---|---|
| BH SPY | $365,637 | 0.68 | -34.1% |
| **25% TILT leveraged** | **$464,303** | **0.94** | **-21.0%** |
| 25% short only (no lev) | $347,173 | 0.89 | -19.0% |

Variant A: heating → 75% long + 25% short = 50% net; cooling → 125% long
(uses leverage). The leverage during high-confidence COOLING captures
bull-market upside while shorts during HEATING protect downside.
Chart: `signal_context/charts/beta_mz_25pct_tilt_strategy.png`.

**Per-index optimal overlay variant (multi-index test)**:
- SPY: CASH or 50/50 wins on Sharpe
- QQQ: 70/30 L/S wins (light shorting works; full cash gives up too much
  growth-market upside)
- IWM: AGGRESSIVE shorting (30/70 or FULL_FLIP) wins on both Sharpe AND
  total return ($496k vs $242k BH using FULL_FLIP)
- XLK (tech): defensive overlay is suboptimal (concentrated tech rallies
  cost too much during cooling periods)

**Winsorization revealed signal-component asymmetry (Test 20)**:
- UP→DOWN long is ROBUST — raw mean ≈ trimmed mean (SPY: +2.48% → +2.29%).
  Reliable mean-reversion alpha, NOT COVID-dependent.
- DOWN→UP short is COVID-dependent — raw mean drops 50%+ when winsorized
  (SPY: +2.18% → +0.82%; VIXY long: +17.5% → +6.2%).
- **Honest reframe**: signal has two components doing different jobs.
  - UP→DOWN = "reliable income" (mean-reversion harvest)
  - DOWN→UP = "tail-event insurance" (COVID-magnified, modest in normal times)

**Friday-cadence + witching + Monday-lag analysis (Test 22)**:
- All signal dates fall on Friday (W-FRI snapshot frequency in aggregator)
- Signal computable POST-Friday-close; earliest tradeable Monday open
- β_mz AND 12-week slope BOTH computed weekly (daily β_mz never tested → Open Test G)
- Witching Friday rate 8.1% vs baseline 7.7% → NOT over-represented
- **Monday-lag costs ~0.34% per signal = ~14% of average PNL**
- **Implication for honest claims**: backtest assumes Friday-close execution
  (institutional). Retail Monday-open execution → adjusted Sharpe ~0.27
  improvement (not +0.34). Adjusted max DD reduction ~10pp (not 13pp).
- **Open Test H**: clean re-backtest using Monday-open execution

**HY spread is a stronger SINGLE-signal early warning than β_mz** (humbling but
important finding):
- HY spread Z > 1: 2.70× lift on forward DD > 10% in 42 BD
- β_mz level low (Q1): 1.11× lift
- Naive combinations (AND/OR) don't help — β_mz adds noise to HY
- **Open Test A**: train logistic regression composite of β_mz + HY + yield curve
  + breakeven. Likely path to a signal meaningfully better than HY alone.

### 📂 signal_context/ — the canonical archive

[`model/signal_context/`](model/signal_context/) is a self-contained archive of all β_mz signal work:
- `README.md` — orientation + complete 22-test catalog with question, method, result, data file per test
- `analysis_scripts/` — 8 reproducible Python scripts
- `validation_data/` — 19 CSV outputs including `beta_mz_full_event_table_with_vixy.csv` (every signal event with SPY/QQQ/XLF/VIXY 21d PNL scaled by direction)
- `charts/` — the 25% tilt equity curve chart
- `specs/` — `DASHBOARD_SPEC_MACRO_REGIME.md`

If you're picking up this signal work in a future session, start at
`signal_context/README.md`.

Full validation history + research extensions in [RESEARCH_TODO §14](model/RESEARCH_TODO.md).

---

### Original headline (now reframed): vrp_ewma at +0.40 IC is forward-vol predictive

Comprehensive 8-predictor × 4-target × 3-horizon IC suite on 267k (ticker, date) observations
([model/pipeline/analysis/vrp_ic.py](model/pipeline/analysis/vrp_ic.py), full results
in [results/validation/vrp_ic_summary.md](model/pipeline/results/validation/vrp_ic_summary.md)).

| Predictor | Pooled IC vs fwd vol h=21 | Per-ticker median IC | % tickers \|IC\|>0.10 |
|---|---|---|---|
| **vrp_ewma** | **+0.396** | +0.179 | 69% |
| **vrp_raw** | +0.332 | **+0.227** | **99%** |
| vrp_ewma_slope5 | +0.149 | +0.155 | 85% |
| vrp_pct_own | +0.148 | +0.167 | 87% |
| vrp_zscore_own | +0.146 | +0.164 | 83% |
| vrp_sign | +0.057 | +0.011 | 14% (noise) |

**Quintile-lift on forward 21d vol**: top quintile of vrp_ewma → 38.5% realized fwd vol; bottom quintile → 20.9%. **Spread = +17.6 vol-points.** This is the project's actionable read — `get_distribution()` RPC + a dedicated VRP panel on the equity page should surface this.

**Key implications:**
1. VRP isn't a supporting feature — it's the centerpiece. ~50% stronger than the regime classifier (+0.27 IC) and stronger than the forecast itself.
2. EWMA smoothing extracts more signal than raw (+0.40 vs +0.33 pooled at H=21).
3. **Sign is useless** — magnitude is what matters. Don't engineer sign-based features.
4. **Pct/zscore underperform raw** at the pooled level (see "bounded-ordinal principle" below).

### 🎯 The bounded-ordinal principle (new mental model from this session)

The ticker-relative percentile framing (Leo's VRP-percentile intuition) is **not universal**. Across two IC tests on the regime classifier and 8 IC tests on VRP variants, the pattern is clear:

| Signal type | Apply ticker-relative percentile? | Examples |
|---|---|---|
| **Unitless ratios already cross-ticker comparable** | NO — keep absolute | β_mkt, β_mz, IC, percentile-of-percentile, Sharpe |
| **Magnitude depends on ticker baseline** | YES — but test first | VRP_wedge (turns out NO at pooled level; ticker-relative still helps per-ticker), raw residuals (untested) |

`β_mz = 1.5` means "model under-predicts by 50%" regardless of ticker — normalizing destroys cross-ticker info. Same for any unitless slope/ratio. VRP is a borderline case — pct_own modestly helps per-ticker median but loses at pooled level. **When in doubt, test absolute vs relative.**

### 🧪 Resolved research questions (don't re-litigate)

1. **Step_days cadence (Phase 2 cadence experiments)**: 4-config test on 10-ticker preview (step_10, step_20, dynamic single-trigger, multi-trigger). Pooled R² deltas across all configs were within ±0.02 of each other. **step_days=20 is fine for production.** Faster retraining doesn't materially help; dynamic triggers (2σ residual shock) don't fire enough; multi-trigger (bias + RMSE + ceiling) targets correct tickers but doesn't fix structural model failures on ORCL/MU/COST. **The real bottleneck is features, not cadence.** See [model/RESEARCH_TODO.md §4-8](model/RESEARCH_TODO.md) for parked research directions (residual auto-corrector, EMV/EPU features, per-ticker news sentiment).

2. **Trail dynamics IC test** ([analysis/trail_dynamics_ic.py](model/pipeline/analysis/trail_dynamics_ic.py)): tested whether trail velocity / drift_mz_6mo / drift_mkt_6mo / direction_angle add IC over the static quadrant_rank. **They don't.** Static quadrant has +0.26 to +0.29 IC vs forward vol; dynamics features either zero or wrong-sign. Specifically, `drift_mz_6mo` has WRONG sign (rising β_mz = past shocks already hit the 252-BD window → forward vol mean-reverts down). **The slug trail is good viz, not good feature.** Don't engineer drift-as-feature.

3. **Relative quadrant thresholds** ([analysis/relative_quadrant_ic.py](model/pipeline/analysis/relative_quadrant_ic.py)): tested per-ticker median-based thresholds for β_mkt × β_mz quadrant classifier vs absolute β=1.0 cutoffs. **Absolute wins decisively**: rel_full and rel_exp either kill the IC (0.23 → 0.02 at H=21) or flip its sign (H=63/126). Both schemes give nearly identical numbers, so lookahead leak isn't doing the work — the relative framing genuinely fails for this signal type (β_mz is already a unitless ratio).

### 🐛 Pipeline bug fixes shipped this session

1. **[analysis/mz_overlay.py](model/pipeline/analysis/mz_overlay.py):195-197** — Split mask into `fit_mask` (requires y_true) and `apply_mask` (just needs valid y_pred). Was setting y_cal=NaN on every row without observable y_true → forecast y_cal stopped ~h BD before today for every horizon. Now extends through forecast horizon.
2. **[export_for_webapp.py:133](model/pipeline/export_for_webapp.py)** — Changed `dropna(subset=['y_true_21'])` to `dropna(subset=['y_pred_21'])`. Was dropping recent forecast rows because their y_true_21 hadn't materialized yet (cutoff ~21 BD before today). Now forward forecasts make it into per-ticker CSVs.
3. **[scripts/weekly_extend.bat](scripts/weekly_extend.bat)** — Rewired to use `cadence_experiment --step-days 20` instead of single-retrain `extend_predictions`. 6-step pipeline: refresh → cadence → merge → rebuild → overlay → push. Validated by overnight 00:56 completion.
4. **[scripts/merge_cadence_to_canonical.py](model/pipeline/scripts/merge_cadence_to_canonical.py)** (new) — Splices `cadence_experiment/step_N/predictions_<TICKER>.csv` into the canonical per-ticker files, preserving pre-extension backtest rows.
5. **[scripts/daily_refresh.bat](scripts/daily_refresh.bat)** — Now 6 steps (added rebuild_aggregates + mz_overlay between daily_forecast and export). Push uses `--append-only` for cheap idempotent incremental.
6. **[model/sql/migrations/005_get_distribution_rpc.sql](model/sql/migrations/005_get_distribution_rpc.sql) + 006** — `get_distribution()` RPC implemented (was stub). 30-bin × 3-scope histogram + current_value + current_percentile. 006 dropped a stale 4-arg overload that PostgREST couldn't disambiguate. Live and verified via [scripts/test_get_distribution.py](model/pipeline/scripts/test_get_distribution.py).

### 🎨 UI design proposal: VRP Signal panel (HTML mockup in [results/webapp_export/mockups/equity_with_vrp_panel.html](model/pipeline/results/webapp_export/mockups/equity_with_vrp_panel.html))

Given VRP's +0.40 IC, current equity page treatment (small subgraph under price chart + buried as one toggle in distribution panel) is insufficient. Mockup shows "Option C" — a full main-content panel between Forward Vol Forecast and Contracts/Skew with:
- Gauge needle pointing into quintile arc (P82 of own 1Y for XOM example)
- 1Y sparkline of VRP_ewma with σ bands + sector rank + slope direction
- Quintile-lift table showing "you are here at Q5 → 38.5% expected fwd vol vs Q1 baseline 20.9%"

Frontend SWE handoff item. User reviewed and is gravitating toward this. Amber/gold visual identity reserved for VRP-related elements throughout the page.

### What's left

| Priority | Task | Status |
|---|---|---|
| 🔝 | User runs `scripts\register_daily_task.ps1` as Admin → daily + weekly automation goes live | Pending — pipeline tested, just needs admin elevation |
| 🔝 | Frontend builds **Macro page β_mz panel** (the new headline feature) | Spec ready: `DASHBOARD_SPEC_MACRO_REGIME.md`; add nightly compute job |
| ⭐ | Frontend builds VRP Signal panel (reframed as structural/seasonal/macro context, NOT fear gauge) | Mockup at `results/webapp_export/mockups/equity_with_vrp_panel.html` |
| ⭐ | Frontend wires get_distribution() RPC into Historical Distribution panel | RPC live, frontend integration pending |
| research | β_mz Open Tests A-H — see signal_context/README.md "Tests we DIDN'T run". Top priority: Test A (logistic regression multi-signal composite β_mz + HY spread) | Parked |
| research | See [RESEARCH_TODO.md](model/RESEARCH_TODO.md) §4 (half-residual corrector), §7 (EMV/EPU), §10 (dual-head loss), §11 (IV-prediction) | Parked w/ priorities |
| optional | Re-map sequential security_ids 1000-1091 to real SEC CIKs | Cosmetic; v1 works fine |

### Specific gotchas to remember (cumulative)

- **`security_id` convention is MIXED**: AAPL=320193 (SEC CIK), other 92 tickers = sequential ids 1000-1091. Frontend should map by ticker, not assume id pattern.
- **`prices_history.volume` is `bigint` in Postgres but CSV has float** — `fetch_ohlcv` in `export_for_webapp.py` coerces to nullable Int64. Don't remove.
- **`pd.NaT` is its own type** — `isinstance(v, pd.Timestamp)` doesn't catch it. `db.py._df_to_records` has explicit type-name check. Don't remove.
- **`event_history` (singular, lead-dev redesign)** — security-keyed via FK. FOMC events go in `macro_calendar` ONLY (Option A).
- **`upsert_event_history` does within-batch dedupe** — Compustat duplicates. Don't remove.
- **`features.build(..., drop_nan_targets=False)`** — pass False for prediction-time use. Default True for backtest training.
- **SHAP is concurrent-only** — backtest predictions have `shap_h*_top10 = NULL`. Daily forecast writes parallel `forecasts/<TICKER>_shap.csv`.
- **XGB SHAP via `booster.predict(pred_contribs=True)` + force `device='cpu'`** — CUDA boosters hang on `pred_contribs` for single-sample inputs.
- **Forward premium math uses 252/365 ratio** to convert IV calendar-day anchors to trading-day axis.
- **`days_to_dividend` (no 's')** — migration 003 fixed original typo.
- **`mz_overlay` mask split** (NEW 2026-05-26) — fit_mask uses y_true; apply_mask doesn't. Don't merge them back.
- **Export pivot uses `dropna(y_pred_21)`** (NEW 2026-05-26) — not y_true_21. Don't switch back.
- **`weekly_extend.bat` swaps `extend_predictions` for `cadence_experiment --step-days 20`** (NEW 2026-05-26) — Phase 2 validated cadence; don't revert to single-retrain.

### To pick up next session

1. Verify Supabase still live: `python -m model.pipeline.db` (should print "schema verified")
2. Confirm `scripts\register_daily_task.ps1` was run as admin (check `Get-ScheduledTask Tarasque*`)
3. **Read `signal_context/README.md`** — the β_mz Universe Calibration Drift signal is the
   project's strongest validated result and is the new headline product feature. The README
   has the complete 22-test catalog with all numbers + 8 reproducible scripts + the open-test queue.
4. Pick a direction:
   - **Productionize**: hand the Macro β_mz panel spec to the SWE; build nightly compute job
   - **Research**: β_mz Open Test A (logistic-regression multi-signal composite), or Test B
     (true out-of-sample 2015-20 train / 2021-26 test), or Test G (daily-cadence β_mz)
   - **Honesty pass**: β_mz Open Test H (re-backtest with Monday-open execution to lock in
     the ~14%-lower realistic claim)

### The big-picture arc of the 2026-05-27 session (so the story isn't lost)

The project began the day trying to **isolate VRP for the equity page**. Through rigorous
self-questioning we discovered:
1. The per-stock VRP wedge is NOT a fear-premium isolator — it's 30% earnings seasonality +
   macro liquidity cycle + cross-sectional structural ranking. The +0.40 IC is real but
   misframed. (Tests A-F, locked in.)
2. Every architectural rescue attempt failed: IV-prediction reframe (mixed), YZ migration
   (degrades R²), residual-after-seasonality (slight negative IC), ticker-relative thresholds
   (absolute wins), trail dynamics (no IC), path-length target (identical IC).
3. **The genuine win that emerged**: the β_mz Universe Calibration Drift signal — a
   corpus-level second-order signal (about how the 93-model ensemble systematically
   miscalibrates before regime shifts). Validated as a defensive overlay: Monte Carlo
   p<0.001, 8/8 ETF DD reduction, 25%-tilt strategy beats SPY BH on every metric
   ($464k vs $366k, Sharpe 0.94 vs 0.68, max DD -21% vs -34%).
4. **Product repositioning**: Macro β_mz panel is the new headline feature; per-stock VRP
   wedge is supporting "context engine" infrastructure (structural + seasonal + macro,
   not fear gauge). Honest claims documented. The reframe is a STRONGER product story
   because it's defensible and survives scrutiny.

---

## Project Summary

Quantitative volatility forecasting engine. Core objective: isolate the **Volatility Risk Premium (VRP)** wedge (IV - RV) as a fear/uncertainty signal, use it as a dynamic defensive equity overlay. Predicts **Garman-Klass Realized Volatility** using XGBoost/RF/LassoCV ensemble stabilized by GARCH(1,1).

**Owner:** Leo DiPietro — econ/stats student, CS is not primary. Hand-hold on implementation details. Graduating soon, WRDS access expires in ~1.5 months wants to learn while we work, teach concepts, explain why we do things, and never lie or appease him, he wants to know when he is wrong or out of touch.
**Stack:** Python pipeline → Supabase (PostgreSQL) → FastAPI/Uvicorn → React frontend (SWEs handling backend/frontend).

---

## Repository Layout

```
volarbmodel/
  model/
    pipeline/
      __init__.py
      __main__.py
      config.py             <- DataConfig, ModelConfig, BacktestConfig dataclasses
      data_loader.py        <- WRDS + Alpaca/yfinance acquisition
      features.py           <- FeatureBuilder (features trimmed post-v6 full run — see below)
      models.py             <- GarchForecaster + EnsembleVolModel
      backtest.py           <- Walk-forward BacktestEngine
      batch_backtest.py     <- Overnight batch runner (25 batches x 4 tickers)
      run.py                <- CLI orchestrator
      utils.py              <- FOMC/CPI/NFP calendars, Black-Scholes, Monte Carlo cone
      requirements.txt
      analysis/
        __init__.py
        vrp_analysis.py       <- VRP wedge bilateral uncertainty analysis
        residual_analysis.py  <- Systematic residual diagnostic tool
        audit.py              <- 9-test post-hoc validity audit (NEW 2026-04-11)
        mz_overlay.py         <- EW MZ calibration overlay + term structure enforcement (NEW)
        benchmark_models.py   <- HAR-RV + GARCH(1,1) benchmark comparison (NEW)
      results/
        predictions_TICKER_Hh.csv     <- 97 tickers x 3 horizons = 291 files
        backtest_results.csv          <- rebuilt from individual files (batch runner overwrites)
        all_predictions.csv           <- raw ensemble predictions (756,249 rows)
        all_predictions_cal.csv       <- MZ-calibrated + TS-enforced predictions
        mz_calibration.csv            <- EW alpha/beta per (ticker, horizon)
        benchmark_comparison.csv      <- Ensemble vs HAR-RV vs GARCH R2/RMSE/QLIKE
        audit/                        <- 9 audit CSVs (mz_regression, diebold_mariano, etc.)
        archive_pre_v6/               <- Pre-v6 predictions preserved for comparison
        payloads/                     <- 97 TICKER_Payload.json + market_overview.json (calibrated)
    claude_context.md       <- THIS FILE — always update this
  logs/
    v6_full_corpus.log      <- First pass (48/97 tickers, 17.8 hours)
    v6_second_pass.log      <- Second pass (49 missing tickers, 13.6 hours)
  supabase/config.toml
  backend/requirements.txt
```

**Data cache:** `D:/Tarasque_DB/` (Parquet, partitioned by ticker)
**Run from:** `C:/Users/Leo DiPietro/Desktop/volarbmodel/`

---

## Environment & Credentials

| Item | Value |
|---|---|
| TARASQUE_BASE_DIR | `D:/Tarasque_DB` (set in model/.env) |
| WRDS_USERNAME | `ldip9` (set in model/.env — no pgpass.conf on this PC) |
| WRDS_PASSWORD | `GabeNorbert1108!` (set in model/.env) |
| FRED_API_KEY | `3733cf9cba7d39c8c6d07537d4a4b441` (set in model/.env) |
| Alpaca keys | Paper trading account — in model/.env |

**Run data pull:**
```bash
python -m model.pipeline --mode refresh_data
```

**Run backtest:**
```bash
python -m model.pipeline --mode backtest
```

**Run analysis after backtest:**
```bash
python -m model.pipeline.analysis.vrp_analysis --horizon 21
python -m model.pipeline.analysis.residual_analysis --horizon 21 --top-n 20
```

---

## WRDS Data Access

| Source | Table | Status |
|---|---|---|
| CRSP OHLCV | `crsp.dsf` + `crsp.msenames` | OK — 2014–2024 |
| CRSP index | `crsp.dsi` | OK |
| OptionMetrics IV | `optionm.vsurfd{YEAR}` (2014–2025) | OK — unified view missing, use year tables |
| OptionMetrics OI | `optionm.opprcd{YEAR}` (2011–2025) | OK — 25-delta OI aggregated per (secid, date, cp_flag). vsurfd does NOT have open_interest. |
| Compustat GICS | `comp.company` JOIN `comp.funda` | OK |
| Compustat earnings | `comp.fundq` | OK |
| Compustat dividends | `comp.funda` (dvpsx_f) | OK |
| FRED direct | `fred.data` | NOT AVAILABLE in student subscription |
| FRED via yfinance + fredapi | `^TNX`, `^IRX` + 4 fredapi series | OK — all 6 macro series active |

---

## Parquet Cache State (as of 2026-04-04)

| Dataset | Rows | Date Range | Notes |
|---|---|---|---|
| ohlcv | 164,876 | 2014-01-02 – 2026-04-02 | CRSP + Alpaca continuation |
| vsurfd | 1,808,080 | 2014-01-02 – 2025-08-29 | 30 tickers, year tables |
| fred | 3,241 | 2014-01-01 – 2026-04-03 | **6 series including T5YIFR** — rebuilt 2026-04-04 |
| crsp_index | 2,768 | 2014-01-01 – 2024-12-31 | |
| earnings | 1,470 | | |
| dividends | 289 | | |
| compustat_meta | 30 | | GICS sector codes |

| oi_25delta | 7,068 (AAPL only) | 2011-01-10 – 2025-08-29 | 25-delta OI from opprcd, per (date, cp_flag). **Only AAPL pulled so far — full 91-ticker pull needed before WRDS expires.** |

**FRED cache was rebuilt 2026-04-04** (prior was wiped accidentally during T5YIFR addition). All 6 series confirmed present: treasury_10y, treasury_3mo, hy_spread, breakeven_5y, dollar_index, inflation_forward_5y5y.

---

## Ticker Universe (config.py)

**CURRENT STATE: 100-ticker S&P large-cap universe (v4 prod config)**
**Start date: 2011-01-01** (2011-2013 rows seed rolling windows only; IV features NaN pre-2014, first predictions ~late 2016 after 5yr burn-in at 49 features)

Tech: AAPL, MSFT, NVDA, AMD, ORCL, INTC, QCOM, AVGO, TXN, IBM, CRM, ADBE, AMAT, MU, CSCO
Comm: GOOGL, META, NFLX, DIS, CMCSA, T, VZ
ConsDisc: AMZN, TSLA, HD, MCD, NKE, SBUX, TGT, LOW, BKNG, GM, F
ConsStap: PG, KO, PEP, WMT, COST, PM, MO, CL
Fin: JPM, BAC, WFC, GS, MS, C, BLK, AXP, SCHW, USB
Health: JNJ, LLY, ABBV, MRK, PFE, UNH, TMO, ABT, BMY, AMGN, GILD, CVS
Indust: CAT, HON, BA, UPS, RTX, DE, MMM, GE, LMT, NOC, FDX
Energy: XOM, CVX, COP, EOG, SLB, MPC, PSX, OXY
Materials: LIN, APD, NEM, FCX, DOW
Utilities: NEE, DUK, SO, D, AEP
RealEstate: AMT, PLD, CCI, EQIX, SPG

**To restore:** In config.py, comment out the current single-ticker block, uncomment the full universe.

**IMPORTANT before full run:** Wipe stale results/ CSVs first — old per-ticker files contaminate `all_predictions.csv` assembly:
```bash
rm model/pipeline/results/predictions_*.csv model/pipeline/results/all_predictions.csv model/pipeline/results/backtest_results.csv
```

---

## Complete Feature Set (55 active as of 2026-04-30 v10 — ElasticNet)

### Price / Vol
- GK RV: rv_5d, rv_10d, rv_21d, rv_63d, rv_126d
- EWMA vol, ret_TARGET

### Technicals
- tech_RSI, tech_ATR, tech_MACD_hist

### Factor ETF Returns + Momentum (v4)
- ret_SPY, ret_VIXY, ret_HYG, ret_USO, ret_TLT, ret_UUP
- mom21_SPY, mom21_VIXY, mom21_HYG, mom21_USO, mom21_TLT, mom21_UUP — 21d log momentum. Tells the model whether an ETF is in a sustained trend vs a one-day spike. "Is TLT in a grind down or just noise?"

### Vol Dynamics (expanded Apr 3–4)
- vol_trend, vol_vel, vol_of_vol
- `vol_regime_zscore` — (rv_21d - 252d mean) / 252d std. Addresses ACF=0.96 persistent regime errors.
- `vol_chg_21d` — signed 21d change in rv_21d. Captures slow regime drift.

### Events
- event_fed_gravity, event_earn_gravity, event_div_gravity
- `event_cpi_gravity` — 1/(days_to_next_CPI+1), BLS CPI release calendar (NEW v10)
- `event_nfp_gravity` — 1/(days_to_next_NFP+1), BLS Employment Situation first-Friday calendar (NEW v10)
- CPI/NFP dates generated programmatically in utils.py (156 dates each, 2014-2026). CPI ~13th of month (nearest weekday), NFP first Friday.

### Options Surface (requires vsurfd)
- iv_atm_30d, put_call_skew_30d, `put_call_abs_skew_30d`, term_structure_slope, vrp_wedge, iv_atm_z_score
- `put_call_abs_skew_30d` — bilateral skew (U-shaped signal confirmed in VRP analysis)

### Open Interest (25-delta, NEW v10 — requires opprcd data pull)
- `oi_put_call_ratio_25d` — put/call OI ratio at 25-delta, 20-40 DTE
- `fear_intensity_25d` — IV skew x log(OI_put/OI_call) multiplicative interaction. Requires BOTH price asymmetry (skew) AND quantity asymmetry (OI ratio) to fire.
- `oi_hedge_pressure_chg_5d` — 5d change in put/call OI ratio (positioning momentum)
- Data source: `opprcd{YEAR}` tables with |delta| 0.20-0.30, DTE 20-40, open_interest > 0
- **IMPORTANT**: vsurfd does NOT have open_interest. OI comes from opprcd (option price data).
- fetch_oi_25delta() in data_loader.py aggregates: SUM(open_interest), OI-weighted IV per (secid, date, cp_flag)

### Macro (6 series, all active)
- macro_yield_curve_slope (10y-3mo fallback)
- macro_hy_spread, macro_hy_spread_chg_5d
- macro_breakeven_5y (T5YIE)
- macro_dollar_ret
- `macro_inflation_fwd_5y5y` (T5YIFR — added 2026-04-04)
- `macro_inflation_fwd_chg_21d` — 21d momentum of forward inflation expectations
- `macro_inflation_fwd_abs_chg_21d` — bilateral shock magnitude (NEW v3): rising OR falling fast = regime transition uncertainty
- `macro_inflation_fwd_chg_63d` — slower 63d drift (NEW v3): structural regime shifts without 21d noise
- `macro_inflation_fwd_zscore` — (T5YIFR - 252d mean) / 252d std (NEW v3): "living with inflation" signal — dampens level signal once market has repriced around a stable regime

### Factor Decomp
- beta_spy, res_vol, res_vol_vel

### Regime
- price_regime (252d drawdown)

### Sector Coupling (restored v7 — were VIF-excluded in v5/v6, caused JPM H63/H126 R² drop of 0.17)
- corr_sector_21d, corr_sector_252d, sector_wedge
- **Why restored**: High VIF does not mean zero incremental signal — it means collinearity.
  LassoCV arbitrarily zeroes one feature from a correlated group. ElasticNet (L1+L2) shrinks them
  proportionally. JPM H63 beta improved 1.343→1.052 after restoration + ElasticNet swap.

### Model change: ElasticNet replaces LassoCV (v7)
- `ElasticNetCV(l1_ratio=[0.5, 0.7, 0.9])` cross-validates sparsity vs group-shrinkage per step.
- `mean_l1_ratio` now tracked in lasso_tracking CSVs — expect financials (JPM/GS) to show lower
  l1_ratio (more grouped) vs tech names.
- `min_train` fixed to 756 flat (was `max(252, 20×n_features)` = 1000 days with 50 features —
  the 20× rule was designed for Lasso instability, ElasticNet's L2 is stable with shorter windows).

### Quantile model: QuantileVolModel (tau=0.15, v8 — LEFT TAIL FLOOR)
- Parallel XGBoost with `objective="reg:quantileerror"` trained per horizon.
- **Design pivot (2026-04-28)**: Shifted from right-tail P85/P92 to left-tail P15 vol floor.
- **Why left tail**: Right tail is structurally unforecastable from lagged features — unobserved shocks (earnings surprises, macro events) dominate. Left tail is tractable — low-vol regimes are driven by observable, persistent factors (GARCH, HYG, VIXY, RV windows). Errs conservatively (overwarn), which is the preferred direction under asymmetric loss.
- tau=0.92 investigation confirmed distribution mismatch: coverage_q92 = 0.19–0.39 vs target 0.08 — moving tau proportionally did not move coverage proportionally. This is a model distribution issue, not a tau calibration problem. Linear extrapolation implied tau > 1.0 for true P85, confirming right tail is off-limits.
- Outputs `y_pred_q15` column in prediction CSVs (floor estimate = 1st quartile vol lower bound).
- Signal use: when ensemble forecast is ABOVE its own historical P15 floor by a large margin, vol regime is firmly elevated. When ensemble hovers near the floor, low-vol regime confirmed.

### Signal strength framework (signal_strength.py — new 2026-04-28)
- **Key insight**: Signal value is ordinal, not cardinal. Model's output percentile within its own history is the actionable signal. When ensemble is at P90+ of its own historical distribution, bad outcomes are 5-6× more likely.
- Non-linear risk weight mapping: flat below P60, convex acceleration: P70→0.15, P80→0.30, P90→0.55, P95→0.75, P99→0.95.
- Expanding-window CDF per ticker (no lookahead) to compute output percentiles.
- **3-ticker lift results**: pooled precision lift 5.4×; XOM 24.7×, AAPL 7.2×, JPM 3.3× (when signal ≥ P80, forward realized vol elevated 1.5× median with 5× base rate lift).
- **2×2 regime taxonomy** (ensemble signal × floor signal):
  - Ensemble-only elevated (spike from quiet): 6.1× lift — SHARPEST signal
  - Both elevated (persistent high-vol): 5.4× lift
  - Floor-only elevated (vol compressing): 0.69× — contrarian, vol declining
  - Neither elevated: baseline 1.0×
- **Important**: two signals identify different regimes — do NOT combine into single score.
- Type II error asymmetry: false negatives (missing real risk) >> false positives. Even 5× lift at P80 is actionable. "Economists predicted 4 of last 9 recessions" — imperfect signal still valuable under asymmetric loss.

---

## Design Decisions & Rationale

### Why T5YIFR (5yr/5yr forward inflation) not just T5YIE (5yr breakeven)
T5YIE measures expected inflation over the next 5 years — it picks up near-term noise (oil shocks, supply chain). T5YIFR measures what the bond market expects inflation to be in years 5-10, stripping near-term noise entirely. It's a structural regime signal that cleanly separates:
- **2008/2020 deflationary shock**: T5YIFR collapsed, TLT rallied — risk-off
- **2022 structural inflation**: T5YIFR peaked ~2.8% and stayed there for 18 months — the regime that broke most models

Also added `macro_inflation_fwd_chg_21d` — whether long-run inflation expectations are shifting. A rising 5y5y forward while yields are also rising = stagflationary regime signal. This is genuinely orthogonal to HY spread (credit stress) and yield curve (rate expectations), making it a low-multicollinearity addition even for LassoCV.

### v3 Inflation Feature Expansion Rationale (2026-04-04)
Leo's observation: T5YIFR as a level signal has a directional bias problem — markets *adapt* to persistent inflation regimes. After 18 months at 2.8%, the level stops being news. The model keeps treating it as risk-off when the market has already repriced. This explains the systematic beta>1.0 cluster on AAPL/JPM/JNJ in v2.

Three new features added to address this:
- **abs_chg_21d**: bilateral — both rising AND falling fast = uncertainty = vol. Fixes directionality.
- **chg_63d**: slower window captures structural shifts without reacting to weekly noise.
- **zscore**: the key fix. Once T5YIFR stays stable for 252 days, zscore returns toward 0 even at a high level — tells the model "this is priced in, stop treating it as a shock."

**Hypothesis for v3**: if the beta drift on JPM (most macro-sensitive drifter) closes toward 1.0, Leo's hypothesis is validated. If it doesn't close, cause is training window composition (calm 2017-2019 dominates early folds) and the fix is exponential weighting instead.

**Note on dollar/inflation interaction**: tariff regimes (2025) create strong dollar + rising inflation simultaneously — the opposite of the normal FX/inflation relationship. A `macro_dollar_inflation_interaction = macro_dollar_ret * macro_inflation_fwd_chg_21d` term could capture this, deferred to v4 pending v3 results.

### Why NOT expand data back to 2008
OptionMetrics vsurfd only has year tables from vsurfd2014 onward. Going pre-2014 means 6 years of training data with IV features entirely absent (iv_atm_30d, vrp_wedge, put_call_skew, term_structure_slope all NaN). The model would learn a fundamentally different feature space for 2008-2013 vs 2014+. That's not regime diversity — it's a structural break in input representation.

**Better path**: Exponential sample weighting (downweight old data within 2014+ window). Will capture the 2020 COVID regime without pre-2014 representation mismatch.

### Why NOT orthogonalize inflation on TLT
For tree-based models (XGBoost/RF), pure multicollinearity doesn't destabilize the way it does in OLS. Trees split on one variable at a time. The information-richest split wins. LassoCV is the one model where it matters, and L1 regularization handles it. The orthogonalized residual is econometrically purer but introduces a new estimation step (TLT relationship must be updated each fold). More complexity, marginal gain — revisit if T5YIFR alone doesn't improve regime separation.

---

## Stress Test Results (2026-04-04)

### NVDA Stress Test
- Overall H=21: RMSE=0.101, MZ_beta=0.817, R²=0.341, event_capture=0.916
- **2024 complete OOS failure**: H=63 R²=0.005, H=126 R²=0.004 — AI boom regime broke the model for a full year. Recovering by 2025 as expanding window ingests the new regime.
- **VRP wedge flat for NVDA** (Q1→Q5 lift only 2% vs 55% for XOM) — confirms negative VRP: options chronically overprice NVDA vol.
- **>80% vol bucket**: mean |error|=0.44 — tree ensembles can't extrapolate beyond training distribution. Structural limitation.

### BA Stress Test
- Overall H=21: RMSE=0.167, MZ_beta=0.483, R²=0.322, event_capture=0.820
- **2019: beta=-0.771** (737 MAX grounding — model inverted, predicted lower vol as BA collapsed)
- **2023-24: R²~0.001-0.006** — chronic distress regime, model flat-lines
- **>80% vol bucket**: mean |error|=1.045 — worst extrapolation failure across all tests
- High alpha (+0.161) compensates somewhat — model adds a constant upward bias for BA which is correct on average

### PG Softball Test
- Overall H=21: RMSE=0.060, MZ_beta=0.800, R²=0.270
- **Underperformed expectations** — R² should be higher for a low-vol staple. 2023-24 R² weak (0.067, 0.080).
- Likely cause: options surface coverage thins post-2023 in vsurfd, IV features go NaN, model falls back to price-only features.
- **>60% vol bucket**: only 17 observations (COVID) but error=0.508 — COVID spike unavoidable

### Cross-test patterns
1. H=21 is the only reliable horizon consistently. H=63/126 degrade badly for idiosyncratic names.
2. All extreme vol (>60-80%) is structurally under-predicted — tree ensemble limitation, not a bug.
3. 2023-24 is consistently weak across all tickers — expanding window will improve as it matures.
4. BA-type chronic distress is genuinely out of scope — recommend the overlay strategy exclude or discount such names.
5. VRP wedge signal strength is ticker-specific: XOM R²=0.275, JNJ 0.10, NVDA/AMD negative.

---

## All Bugs Fixed (cumulative)

| # | Session | File | Bug | Fix |
|---|---|---|---|---|
| 27 | Apr 29 | vrp_return_conditional.py | Unicode arrow char crashed cp1252 Windows terminal | Replaced with ASCII -> |
| 28 | Apr 29 | mz_overlay.py | Sequential TS enforcement (H21-H63 then H63-H126) creates new H21>H63 inversions | Added second H21-H63 pass after H63-H126 enforcement |
| 29 | May 1  | data_loader.py:752 | append_recent_data crashed on mixed string/Timestamp dates after concat (cached parquet vs Alpaca fresh pull) — pd.to_datetime inferred "%Y-%m-%d" then failed at first Timestamp.toString row | Truncate to YYYY-MM-DD via .astype(str).str[:10] (mirrors line 747's pattern) |
| 30 | May 1  | data_cache/ohlcv | Pre-existing 461-day gap (2024-12-31 → 2026-04-06) on 71/118 tickers; Alpaca rows had ret=NaN which would have flattened _pivot_ohlcv's cumulative return scaling | Backfilled 23,643 Alpaca rows for affected tickers + computed ret from prc.pct_change for all 39,295 Alpaca-pulled rows |
| 1 | Apr 2 | utils.py | FOMC dates only from 2025 | Added full 2014–2026 FOMC history |
| 2 | Apr 2 | data_loader.py | WRDS connection always prompted interactively | Read from pgpass.conf, fall back to env vars |
| 3 | Apr 2 | data_loader.py | Unicode crashed Windows cp1252 terminal | Replaced with ASCII |
| 4 | Apr 2 | data_loader.py | optionm.vsurfd unified view missing | Loop over year tables vsurfd2014–vsurfd2025 |
| 5 | Apr 2 | data_loader.py | comp.funda.gsector missing | JOIN comp.company to comp.funda |
| 6 | Apr 2 | data_loader.py | fetch_compustat_meta crash killed pipeline | try/except wrapper |
| 7 | Apr 2 | data_loader.py | fred.data not available — 630 errors | Fast-fail before chunked loop |
| 8 | Apr 2 | features.py | CRSP msenames join → duplicate rows → pivot crash | drop_duplicates before pivot |
| 9 | Apr 2 | features.py | dropna only checked y_21 | dropna(subset=all target cols) |
| 10 | Apr 2 | backtest.py | y_tr_dict only passed current horizon | Pass all horizons |
| 11 | Apr 2 | backtest.py | FRED all-NaN → LassoCV crash | Pre-filter all-NaN cols; impute inside window |
| 12 | Apr 2 | models.py | NaN targets → mean_squared_error crash | notna() mask before fitting |
| 13 | Apr 2 | models.py | H=126 RMSE overflow from unclamped np.exp() | Clip log predictions to [-5,5] |
| 14 | Apr 2 | data_loader.py | FRED not in WRDS | fetch_fred_yfinance() via yfinance + fredapi |
| 15 | Apr 2 | features.py | macro_yield_curve_slope required treasury_2y | Fall back to 10y-3mo spread |
| 16 | Apr 3 | data_loader.py | .dt.date → Python date objects → ValueError after Parquet round-trip | .dt.normalize() |
| 17 | Apr 3 | data_loader.py | Fred date parsing crash | .astype(str).str[:10] before pd.to_datetime() |
| 18 | Apr 3 | data_loader.py | ParquetStore.save() appends partition files → accumulation | shutil.rmtree() before write |
| 19 | Apr 3 | features.py | Target rolling overlap → inflated R² | rv_{h}d.shift(-h) — zero sample overlap |
| 20 | Apr 3 | features.py | IV ffill unlimited → stale values for months | ffill(limit=5) on all IV series |
| 21 | Apr 3 | analysis/*.py | Unicode chars crashed cp1252 terminal | Replaced all with ASCII |
| 22 | Apr 3 | results/ | "copy" filename broke horizon int parse | Deleted the file |
| 23 | Apr 3 | config.py | rv_windows missing 126 — no rv_126d for H=126 target | Added 126 to rv_windows |
| 24 | Apr 4 | D:/Tarasque_DB/fred | Cache wiped during T5YIFR addition (rmtree before failed write) | Rebuilt from scratch — all 6 series |
| 25 | Apr 5 | data_loader.py | tz-naive (CRSP) vs tz-aware (Alpaca) timestamp comparison crash on pandas 2.x | pd.to_datetime(utc=True).dt.tz_localize(None) |
| 26 | Apr 5 | models.py / config.py | OOM kill (exit 137) — RF n_jobs=-1 spawned 8 workers each holding full 2011-2026 matrix | RF n_jobs=4, LassoCV n_jobs=1 (restore -1 on 5950X) |

---

## Iteration Results Log

### v1 (BA/PG only, no T5YIFR) — archived in results/v1_no_t5yifr/
| Ticker | H | RMSE | MZ_beta | R² | QLIKE |
|---|---|---|---|---|---|
| BA | 21 | 0.167 | 0.483 | 0.322 | 0.0496 |
| BA | 63 | 0.133 | 0.848 | 0.241 | 0.0580 |
| BA | 126 | 0.120 | 0.667 | 0.285 | 0.0468 |
| PG | 21 | 0.060 | 0.800 | 0.270 | 0.0375 |
| PG | 63 | 0.056 | 1.084 | 0.191 | 0.0388 |
| PG | 126 | 0.049 | 1.274 | 0.230 | 0.0308 |

### v2 (T5YIFR + vol features, BA/PG/AAPL/XOM/JPM/JNJ/NVDA) — archived in results/v2_t5yifr/
| Ticker | H | RMSE | MZ_beta | R² | QLIKE | Notes |
|---|---|---|---|---|---|---|
| BA | 21 | 0.130 | 0.916 | 0.384 | 0.0112 | beta fixed (was 0.483) |
| BA | 63 | 0.138 | 0.766 | 0.196 | 0.0114 | slight R2 regression |
| BA | 126 | 0.109 | 0.902 | 0.368 | 0.0067 | R2 +0.083, T5YIFR working |
| PG | 21 | 0.057 | 1.130 | 0.346 | 0.0018 | beta drifted above 1 |
| PG | 63 | 0.056 | 1.148 | 0.204 | 0.0017 | |
| PG | 126 | 0.047 | 1.327 | 0.311 | 0.0011 | |
| AAPL | 21 | 0.068 | 1.204 | 0.361 | 0.0025 | beta drift cluster |
| AAPL | 63 | 0.058 | 1.544 | 0.400 | 0.0018 | |
| AAPL | 126 | 0.044 | 1.312 | 0.472 | 0.0010 | best R2 in run |
| XOM | 21 | 0.073 | 0.877 | 0.555 | 0.0030 | best R2 overall |
| XOM | 63 | 0.082 | 0.932 | 0.325 | 0.0038 | |
| XOM | 126 | 0.070 | 0.906 | 0.370 | 0.0027 | |
| JPM | 21 | 0.082 | 1.057 | 0.204 | 0.0039 | |
| JPM | 63 | 0.063 | 1.719 | 0.489 | 0.0022 | worst beta drift |
| JPM | 126 | 0.059 | 1.736 | 0.393 | 0.0018 | |
| JNJ | 21 | 0.054 | 1.033 | 0.170 | 0.0016 | |
| JNJ | 63 | 0.045 | 0.927 | 0.167 | 0.0011 | |
| JNJ | 126 | 0.035 | 1.217 | 0.267 | 0.0006 | |
| NVDA | 21 | 0.099 | 0.863 | 0.375 | 0.0052 | massive improvement vs stress test |
| NVDA | 63 | 0.090 | 0.857 | 0.275 | 0.0042 | |
| NVDA | 126 | 0.063 | 0.956 | 0.386 | 0.0020 | |

**v2 key finding**: Two systematic clusters — underforecast (XOM, NVDA, BA: beta <1) vs overforecast (AAPL, JPM, JNJ, PG: beta >1). H=21 average beta=1.007 (near-perfect at portfolio level). QLIKE improved ~80-96% vs v1 universally.

### v4 (+ ETF 21d momentum for 6 core ETFs + 2011 data start) — COMPLETE (94 tickers)
Full corpus: 94 tickers (90 clean, 4 flagged: GE breakup, META late, RTX merger, GOOGL class split).
H=21 portfolio avg beta=0.995, median=0.990, 70/90 (78%) well-calibrated [0.85-1.15].
EW-weighted (recent regime): 90/90 (100%) calibrated — COVID/2022 tail artifacts explain full-history drift.
**CRITICAL BUG FOUND POST-FACTO:** AMZN H=63 beta=0.204 was attributed to "mega-cap liquidity buffers" but was actually stock split contamination — see v6.

### v6 (split fix + GARCH feature + lasso/XGB tracking) — VALIDATED 2026-04-10
6-ticker sample: AAPL, AMZN, JPM, XOM, BA, D

**Three changes:**
1. Split-adjusted prices: `_pivot_ohlcv()` reconstructs adj_closes from CRSP `ret` column. Eliminates phantom vol spikes on split dates.
2. `garch_cond_vol` as predictor: GARCH(1,1)-skewt conditional vol fit once per ticker on adj_returns, fed as feature. Lasso selects it mostly at H=63/126 (collinear with ewma_vol at H=21).
3. Lasso tracking + XGB importance CSVs written per ticker.

**Key validation results (v6 vs v4):**
| Ticker | H=21 beta v4 | H=21 beta v6 | Change |
|--------|-------------|-------------|--------|
| AMZN H=63 | 0.204 (contaminated) | 0.942 | FIXED — split contamination confirmed |
| BA | 0.834 | 1.018 | Improved |
| D | — | 1.024 | Clean |
| JPM | 1.022 | 1.084 | Stable |
| XOM | 0.827 | 0.898 | Improved |
| AAPL | 1.108 | 1.125 | Stable |

**R² are strong:** H=21 0.27-0.51, H=63 0.25-0.49, H=126 0.38-0.57. AMZN H=63 R²=0.441 (was 0.125 in v4).

**Feature rankings (Lasso, 6-ticker avg):**
- H=21: ewma_vol (0.744) > iv_atm_z_score (0.701) > macro_hy_spread (0.454)
- H=63: iv_atm_z_score (0.492) > price_regime (0.469) > mom21_USO (0.386)
- H=126: macro_yield_curve_slope (0.511) > beta_spy (0.411) > price_regime (0.384)
- Raw ETF returns (ret_*) almost never selected. Momentum versions are far more useful.
- garch_cond_vol: rank 28/43 at H=63, near-zero at H=21. Not hurting, not leading.

**rv_21d:** Re-added at end of session. Was dropped via VIF=10.6 but is the strongest H=21 predictor. Lasso handles collinearity. Now 44 features total.

**XGB importance tracking:** Added `_write_xgb_importance()` to backtest.py. Will write `xgb_importance_{TICKER}.csv` on next run.

**Hypothesis**: ETF 21d momentum gives the model trend context it was missing. A one-day VIXY spike looks identical to a sustained grind in returns-only. Momentum distinguishes them.

**Pass/fail criteria vs v3:**
| Metric | v3 baseline | Pass |
|---|---|---|
| JPM H=63 beta | 1.387 | < 1.3 (continued improvement) |
| AAPL H=21 beta | 0.982 | 0.90-1.10 (hold near 1) |
| XOM H=21 R2 | 0.415 | > 0.45 (recover v2 regression) |
| H=21 avg R2 | 0.271 | > 0.30 (recover from v3 dip) |
| NVDA H=21 beta | 0.746 | > 0.80 (v3 pushed too low) |

**New tickers — no v3 baseline, watch for:**
- GS/C/MS: should behave like JPM — macro-sensitive financials, beta drift expected pre-v4
- GOOGL/AMZN: growth names, expect similar AAPL pattern
- NEE: pure rate duration — TLT momentum should be highly predictive here
- LIN/CAT: global cycle names, USO+HYG momentum most relevant

**Results — PARTIAL (OOM killed at MRK, resumed, NEE H21 confirmed). Remaining: MRK H63/H126, WMT, CAT, MS, LIN still running.**
| Ticker | H | RMSE | MZ_beta | R² | Notes |
|---|---|---|---|---|---|
| AAPL | 21 | 0.067 | 1.108 | 0.322 | beta slightly up from v3 |
| AAPL | 63 | 0.052 | 1.461 | 0.473 | |
| AAPL | 126 | 0.042 | 1.361 | 0.498 | |
| AMZN | 21 | 0.080 | 0.638 | 0.336 | overforecast cluster |
| AMZN | 63 | 0.128 | 0.204 | 0.125 | severe overforecast |
| AMZN | 126 | 0.048 | 1.128 | 0.493 | corrects at H=126 |
| BA | 21 | 0.119 | 0.834 | 0.451 | |
| BA | 63 | 0.111 | 1.007 | 0.424 | best BA calibration ever |
| BA | 126 | 0.101 | 1.008 | 0.450 | |
| C | 21 | 0.082 | 1.054 | 0.361 | |
| C | 63 | 0.071 | 1.229 | 0.394 | |
| C | 126 | 0.053 | 1.316 | 0.584 | best H=126 R2 in run |
| CVX | 21 | 0.070 | 0.991 | 0.476 | near-perfect calibration |
| CVX | 63 | 0.074 | 1.034 | 0.311 | |
| CVX | 126 | 0.068 | 1.114 | 0.298 | |
| GOOGL | 21 | 0.070 | 0.526 | 0.180 | overforecast cluster |
| GOOGL | 63 | 0.064 | 0.401 | 0.108 | |
| GOOGL | 126 | 0.043 | 0.795 | 0.270 | |
| GS | 21 | 0.069 | 0.884 | 0.301 | |
| GS | 63 | 0.062 | 1.024 | 0.262 | |
| GS | 126 | 0.045 | 1.190 | 0.504 | |
| JPM | 21 | 0.076 | 1.022 | 0.286 | |
| JPM | 63 | 0.060 | 1.343 | 0.420 | |
| JPM | 126 | 0.051 | 1.330 | 0.422 | |
| NEE | 21 | 0.079 | 0.657 | 0.256 | overforecast — regulated cash flows dampen macro transmission |
| PG | 21 | 0.052 | 1.061 | 0.368 | |
| PG | 63 | 0.048 | 1.106 | 0.313 | |
| PG | 126 | 0.041 | 1.325 | 0.399 | |
| XOM | 21 | 0.073 | 0.827 | 0.495 | R2 recovered from v3 regression |
| XOM | 63 | 0.075 | 0.985 | 0.377 | |
| XOM | 126 | 0.065 | 0.993 | 0.430 | |

**H=21 portfolio avg (11 tickers): beta=0.901, R2=0.346** — strong recovery from v3 (0.271).

**Three confirmed beta clusters:**
- Well-calibrated (beta 0.85-1.10): XOM, CVX, JPM, GS, C, BA, PG, MRK — macro signals transmit proportionally
- Overforecast (beta < 0.65): AMZN, GOOGL, NEE — mega-cap liquidity buffers or regulated cash flows dampen macro transmission
- Mild underforecast (beta 1.1-1.5): AAPL, C H126, PG H126 — model anchors low on these names

### v3 (+ 3 inflation features: abs_chg_21d, chg_63d, zscore) — IN PROGRESS
Same 5-ticker set: AAPL, XOM, JPM, JNJ, NVDA. 43 features total. Archived to results/v3_inflation_zscore/ when complete.

**Bug fixed before v3 launch**: early training windows (< 252 days) produced all-NaN `macro_inflation_fwd_zscore` column. `train_medians` for that column was also NaN so `fillna(train_medians)` was a no-op, passing NaN to LassoCV. Fix: added `.fillna(0)` as final fallback in backtest.py imputation chain.

**Key test — hypothesis validation criteria:**
| Metric | v2 baseline | Pass threshold | Fail = |
|---|---|---|---|
| JPM H=63 beta | 1.719 | < 1.4 | training window issue, not inflation feature |
| JPM H=126 beta | 1.736 | < 1.4 | same |
| AAPL H=63 beta | 1.544 | < 1.3 | same |
| XOM H=21 R2 | 0.555 | >= 0.50 (should hold) | regression = overfit |
| NVDA H=21 beta | 0.863 | 0.85-1.05 range | too wide = unstable |

**Results — COMPLETE. Archived to results/v3_inflation_zscore/.**
| Ticker | H | beta v2→v3 | R² v2→v3 | Verdict |
|---|---|---|---|---|
| JPM | 21 | 1.057→0.848 | +0.009 | confirmed — zscore working |
| JPM | 63 | 1.719→1.387 | -0.076 | confirmed, partial |
| JPM | 126 | 1.736→1.584 | -0.015 | confirmed, partial |
| AAPL | 21 | 1.204→0.982 | -0.068 | confirmed |
| AAPL | 63 | 1.544→1.376 | -0.013 | confirmed |
| AAPL | 126 | 1.312→1.302 | -0.022 | minimal |
| JNJ | 126 | 1.217→1.489 | +0.090 | beta regression, R2 improved |
| XOM | 21 | 0.877→0.821 | 0.555→0.415 | R2 regression — was clean |
| XOM | 63 | 0.932→0.804 | -0.071 | over-corrected |
| NVDA | 21 | 0.863→0.746 | -0.082 | pushed too far under |

**H=21 avg beta**: 1.007→0.888. **H=21 avg R2**: 0.333→0.271.

**Finding**: hypothesis partially confirmed — JPM/AAPL beta drift closes as predicted. But features are too aggressive: XOM/NVDA (already well-calibrated) lose R2 as inflation dampening pulls their betas too low. Features are blunt — dampening inflation sensitivity globally instead of only on macro-sensitive names. LassoCV *should* naturally downweight these for XOM/NVDA but training windows may be too short to learn that cleanly. Exponential weighting (longer effective memory of energy/vol regimes) may help XOM more than adding features.

### v9 canary — Step A decomposition (step_days=25 vs v8 step_days=63) — VALIDATED 2026-04-29
6-ticker canary: AAPL, JPM, XOM, BA, AMZN, NVDA. Same Optuna XGB params, ElasticNet, tau=0.15 as v8.
**Only change: step_days 63 back to 25.**

| Ticker | H | R2_v8 | R2_new | dR2 | beta_v8 | beta_new | RMSE_v8 | RMSE_new |
|--------|---|-------|--------|-----|---------|----------|---------|----------|
| AAPL | 21 | 0.263 | 0.343 | +0.080 | 1.213 | 1.216 | 0.067 | 0.064 |
| AAPL | 63 | 0.224 | 0.415 | +0.191 | 1.122 | 1.438 | 0.058 | 0.052 |
| AAPL | 126 | 0.286 | 0.446 | +0.160 | 0.953 | 1.181 | 0.047 | 0.042 |
| AMZN | 21 | 0.292 | 0.420 | +0.128 | 0.589 | 0.832 | 0.081 | 0.069 |
| AMZN | 63 | 0.309 | 0.472 | +0.164 | 0.878 | 1.005 | 0.064 | 0.056 |
| AMZN | 126 | 0.208 | 0.477 | +0.269 | 0.775 | 1.119 | 0.059 | 0.048 |
| BA | 21 | 0.268 | 0.300 | +0.032 | 0.775 | 0.903 | 0.141 | 0.137 |
| BA | 63 | 0.266 | 0.364 | +0.098 | 0.837 | 0.961 | 0.131 | 0.121 |
| BA | 126 | 0.306 | 0.462 | +0.156 | 0.854 | 1.047 | 0.119 | 0.104 |
| JPM | 21 | 0.156 | 0.322 | +0.166 | 0.915 | 1.113 | 0.081 | 0.073 |
| JPM | 63 | 0.165 | 0.273 | +0.108 | 0.901 | 1.100 | 0.069 | 0.065 |
| JPM | 126 | 0.131 | 0.316 | +0.186 | 0.859 | 1.312 | 0.060 | 0.054 |
| NVDA | 21 | 0.350 | 0.446 | +0.096 | 0.875 | 0.931 | 0.100 | 0.092 |
| NVDA | 63 | 0.363 | 0.507 | +0.144 | 0.906 | 1.011 | 0.086 | 0.075 |
| NVDA | 126 | 0.493 | 0.628 | +0.135 | 0.924 | 1.010 | 0.067 | 0.057 |
| XOM | 21 | 0.347 | 0.517 | +0.170 | 0.814 | 0.973 | 0.082 | 0.070 |
| XOM | 63 | 0.233 | 0.406 | +0.173 | 0.717 | 1.012 | 0.084 | 0.073 |
| XOM | 126 | 0.343 | 0.475 | +0.132 | 0.935 | 1.099 | 0.070 | 0.063 |

**H=21 mean: R2 0.279->0.391 (+0.112), beta 0.863->0.995 (near-perfect), RMSE 0.092->0.084**
**H=63 mean: R2 0.260->0.406 (+0.146), beta 0.893->1.088, RMSE 0.082->0.074**
**H=126 mean: R2 0.295->0.467 (+0.173), beta 0.883->1.128, RMSE 0.070->0.061**

**All 18/18 ticker-horizon combinations improved.** R2 exceeded v6 levels (v6 H=21 was 0.374).
step_days=63 was the entire cause of v8's regression. Optuna params are fine. v9 = v8 + step_days=25.

Only soft spot: JPM H=126 beta=1.312 (structural long-horizon over-forecasting for macro-sensitive financials).

### v9 canary batch 2 — confirmation run (PG, GOOGL, CVX, C, NFLX, NEE) — VALIDATED 2026-04-29
Same config as batch 1, different sector mix. **All 18/18 improved again (36/36 total across both batches).**

| Horizon | R2 (v8) | R2 (new) | Delta | Beta (v8) | Beta (new) |
|---------|---------|----------|-------|-----------|------------|
| H=21 | 0.299 | **0.385** | +0.086 | 0.981 | 1.043 |
| H=63 | 0.211 | **0.315** | +0.104 | 0.882 | 1.057 |
| H=126 | 0.228 | **0.388** | +0.161 | 0.866 | 1.116 |

Standouts: NFLX H=126 R2 +0.258 (biggest single gain, beta 0.549->0.931). GOOGL H=126 beta 0.619->0.857 (still under 1 but large improvement). PG H=126 beta went to 1.367 (over-forecasting at long horizon).

**Combined 12-ticker v9 vs v8:**
- H=21:  R2 0.289 -> 0.388 (+0.099)  |  beta 0.922 -> 1.019
- H=63:  R2 0.236 -> 0.361 (+0.125)  |  beta 0.887 -> 1.073
- H=126: R2 0.261 -> 0.428 (+0.167)  |  beta 0.875 -> 1.122

---

### Tier 0 Audit Results (2026-04-29)

**A. Signal Strength — full 91-ticker corpus**
Pooled lift: 3.45x at P80+ (248,426 obs, 91 tickers). Replaces the 3-ticker "5.4x" claim.
Dashboard messaging should use ~3.5x, not 5.4x. Still above the 2x pass threshold.
Top signal tickers (lift >10x): AMGN (60x), BA (31x), BMY (25x), SLB (15x), XOM (14x), BLK (12x), T (10x).
Weak/negative signal: NFLX (0.39x), SCHW (0.83x), AMAT (0.70x), PEP (0.94x).
Output: results/signal_strength/signal_strength.json + signal_strength.png

**B. VRP Return Conditional — full corpus**
Confirmed at scale. High return + high VRP = +6.8% higher forward vol (5d window), +7.6% (21d window).
VRP asymmetric by return quintile: Q1 (worst 20% returns) median VRP=0.062 vs Q5 (best 20%)=0.035.
Output: results/vrp_conditional/vrp_return_conditional.json + .png

**C. Coverage q15 Calibration**
91/91 tickers calibrated to 0.85 at all horizons. Average delta ~0.01 (1% annualized vol shift).
Outliers: TSLA (delta=0.050 H126), NFLX (0.041), CRM, AMD — high-vol names, floor was most conservative.
Script: analysis/coverage_check.py. Output: results/q15_coverage_offsets.csv

**D. Term Structure Inversion Fix**
Second H21-H63 pass added to mz_overlay.py. Inversions: 70.4% -> 51.1%.
Still above <10% target — sequential pairwise approach has structural limits.
Root cause: three independently-trained horizon models with no joint constraint.
May need isotonic regression or joint training to truly fix.

### v10 canary — AAPL only (OI features + CPI/NFP gravity) — 2026-04-30

**v10 = v9 + 5 new features** (oi_put_call_ratio_25d, fear_intensity_25d, oi_hedge_pressure_chg_5d, event_cpi_gravity, event_nfp_gravity). 55 total predictors.

| Ticker | H | R2_v9 | R2_v10 | dR2 | RMSE_v9 | RMSE_v10 | IC_v9 | IC_v10 |
|--------|---|-------|--------|-----|---------|----------|-------|--------|
| AAPL | 21 | 0.3132 | 0.3175 | +0.004 | 0.0636 | 0.0634 | 0.5854 | 0.5897 |
| AAPL | 63 | 0.3523 | 0.3544 | +0.002 | 0.0520 | 0.0520 | 0.6445 | 0.6469 |
| AAPL | 126 | 0.4026 | 0.3947 | -0.008 | 0.0420 | 0.0422 | 0.6676 | 0.6593 |

**Assessment:** Neutral on AAPL. Small gains H21/H63, tiny regression H126. Expected — AAPL's options market is extremely liquid and efficient, so OI ratio adds little signal beyond what IV skew already captures. CPI/NFP gravity is a macro feature that has less impact on tech. ElasticNet correctly shrinks the new features near zero when they don't help. "First, do no harm" check passed — no overfitting damage.

**v10 is NOT validated for production.** Only 1 ticker tested; OI data only pulled for AAPL. The validated deployable version is **v9** (12-ticker canary, 36/36 improved). v10 features go into the next validation cycle after full OI pull + broader canary.

**Decision: v9 is the deployment model. v10 features are research-stage.**

---

## Deployment Plan (as of 2026-04-30)

**Goal: ship v9 as a credible beta / POC.** The model math is solid (beats HAR-RV/GARCH, 0.31-0.47 R2 OOS). The things that would embarrass are presentation-layer: inverted term structures, systematically low forecasts, vol floor too aggressive. All fixable without retraining.

### Phase 1: Fix Post-Processing (code work, ~2 hours)
| Task | File | What |
|------|------|------|
| A. Isotonic TS enforcement | mz_overlay.py | Replace pairwise blend with true isotonic: h63=max(h21,h63), h126=max(h63,h126). Guarantees 0% inversions vs current 51%. |
| B. Coverage offset integration | mz_overlay.py | After MZ cal + TS enforcement, read q15_coverage_offsets.csv, apply y_pred_q15 -= delta per (ticker, horizon). Offsets already computed. |
| C. Validate payload schema | payloads/ | Confirm JSON matches web app expectations (forecast_rv, vol_forecast_series, calibration block). |

### Phase 2: Full v9 Corpus Run (~31 hours compute)
Config already correct (step_days=25, 91 tickers). Run BacktestEngine.run_sector_sweep(). Produces 273 prediction files + all_predictions.csv + backtest_results.csv. Kick off overnight.

### Phase 3: Apply Post-Processing (5 min)
Run `python -m model.pipeline.analysis.mz_overlay` on fresh v9 predictions. Applies MZ calibration + isotonic TS + coverage offsets in one pass. Outputs calibrated all_predictions_cal.csv and updates all JSON payloads.

### Phase 4: Validate Before Deploy
- MZ betas near 1.0 (overlay corrects raw bias)
- TS inversion rate ~0% (isotonic guarantees monotonicity)
- Coverage_q15 near 0.85 (offsets close the gap)
- Spot-check 3-4 payloads visually

### NOT launch-blocking (future work):
- v10 features (OI, CPI/NFP) need full corpus validation
- step_days=21 experiment
- Tier 3 diagnostics from audit plan
- OI pull for remaining 90 tickers (TIME SENSITIVE — WRDS expires ~mid-June)

---

## Progress Checklist

```
[##########] Data pipeline (WRDS pull, Parquet cache)           100%  COMPLETE
[##########] Feature engineering (features trimmed post-v6)     100%  COMPLETE
[##########] Walk-forward backtest engine                        100%  COMPLETE
[##########] Lookahead bias audit & fix                          100%  FIXED
[##########] IV staleness fix                                    100%  FIXED
[##########] VRP bilateral uncertainty analysis                  100%  COMPLETE
[##########] Residual systematic analysis                        100%  COMPLETE
[##########] Stock split contamination fix                       100%  FIXED in v6
[##########] Lasso + XGB tracking export                        100%  COMPLETE — 97 tickers
[##########] Full 97-ticker corpus run (v6)                     100%  COMPLETE — two passes
[##########] Post-hoc validity audit (9 tests)                  100%  COMPLETE — audit.py
[##########] MZ calibration overlay                             100%  COMPLETE — mz_overlay.py
[##########] Term structure enforcement                          100%  COMPLETE — in mz_overlay.py
[##########] HAR-RV + GARCH benchmark comparison                100%  COMPLETE — benchmark_models.py
[##########] Hyperparameter search (Optuna)                     100%  COMPLETE — params applied to config.py (v7)
[##########] Quantile model pivot (tau=0.15 left tail floor)    100%  COMPLETE — right tail intractable, left tail tractable
[##########] Signal strength framework (signal_strength.py)     100%  COMPLETE — 3-ticker lift 5.4x pooled, 2x2 regime taxonomy
[##########] VRP return conditional (vrp_return_conditional.py) 100%  COMPLETE — full 91-ticker corpus run done 2026-04-29
[##########] MemoryError fix in parallel backtest               100%  FIXED — _slice_raw() in _run_parallel() reduces per-worker pickle ~90x
[##########] Full 91-ticker corpus run (v8: Optuna+tau0.15)    100%  COMPLETE — 91 tickers, step_days=63 (caused R2 regression)
[##########] signal_strength.py on full 91-ticker predictions  100%  COMPLETE — 3.45x pooled lift at P80+, replaces 3-ticker 5.4x claim
[##########] vrp_return_conditional.py on full 91-ticker data  100%  COMPLETE — +6.8%/+7.6% fwd vol for hi-ret+hi-VRP at 5d/21d
[##########] TS monotonicity bug fix in mz_overlay.py          100%  FIXED — second H21-H63 pass added, 70.4%->51.1% (still needs isotonic)
[##########] Coverage q15 per-ticker scalar offset             100%  COMPLETE — 91/91 tickers hit 0.85 target, coverage_check.py
[##########] Step A decomposition test (step_days=25)          100%  VALIDATED — R2 +0.11/+0.15/+0.17 at H21/63/126, all 18/18 improved
[##########] v9 canary smoke tests (step_days=25)              100%  COMPLETE — 12/12 tickers, 36/36 improved, R2 +0.10/+0.13/+0.17
[##########] v10 feature build (OI + CPI/NFP gravity)           100%  COMPLETE — 5 new features, 55 total predictors
[##########] OI data pull from WRDS (AAPL test)                100%  COMPLETE — fetch_oi_25delta() in data_loader.py, opprcd tables
[##########] v10 AAPL canary smoke test                        100%  COMPLETE — neutral result (do no harm), v9 remains deployment model
[-----50%--] OI data pull for all 91 tickers                    50%  AAPL done, 90 remaining — TIME SENSITIVE (WRDS expires ~mid-June)
[----------] Full 91-ticker corpus run (v9: step_days=25)        0%  NEXT — ~31 hours, config already correct
[----------] Post-processing fixes (isotonic TS + coverage)      0%  Phase 1 of deployment plan
[----------] IC demeaned cross-sectional signal                   0%  Deferred
[----------] SHAP cross-ticker analysis                           0%  Deferred
[----------] Supabase write layer (db.py)                        0%  SWEs blocked
[----------] Backend API endpoints                               0%  SWEs handling
[----------] Frontend web app                                    0%  SWEs handling
```

---

## Next Actions (in priority order, as of 2026-04-30)

### 0. [IMMEDIATE] Post-processing fixes for deployment (Phase 1)
Two edits to mz_overlay.py, no retraining needed:
**A. Isotonic TS enforcement** — replace pairwise blend in enforce_term_structure() with:
```python
h63 = np.maximum(h21, h63)
h126 = np.maximum(h63, h126)
```
Guarantees 0% inversions (vs current 51%). Simple, correct, no tolerance tuning.
**B. Coverage offset integration** — after MZ cal + TS enforcement, read q15_coverage_offsets.csv, apply `y_pred_q15 -= delta` per (ticker, horizon). The offsets are already computed in results/.

### 1. [IMMEDIATE] Full 91-ticker v9 corpus run (Phase 2)
Config already correct (step_days=25). Run:
```bash
python -m model.pipeline --mode backtest
```
~31 hours at parallel_tickers=4. After completion:
```bash
python -m model.pipeline.analysis.mz_overlay    # applies MZ cal + TS + coverage
python -m model.pipeline.analysis.coverage_check # recompute offsets on v9 predictions
python -m model.pipeline.analysis.signal_strength
```

### 2. [TIME SENSITIVE] OI data pull for remaining 90 tickers (~35 days until WRDS expires)
fetch_oi_25delta() is built and tested (AAPL pulled successfully, 7k rows). Need to run for all 91 tickers.
**Even if not modeled immediately, the parquet on disk is irrecoverable after WRDS access ends.**
OI is in `optionm.opprcd{YEAR}` tables — NOT in vsurfd (audit plan was wrong about this).
Run:
```python
from model.pipeline.config import load_config
from model.pipeline.data_loader import WRDSLoader, ParquetStore
dc, mc, bc = load_config()
loader = WRDSLoader(dc)
df = loader.fetch_oi_25delta()  # all 91 tickers
ParquetStore(dc.base_dir).save(df, 'oi_25delta', partition_cols=['ticker'])
loader.close()
```

### 3. Validate and deploy (Phase 3-4)
After corpus run + post-processing:
- Check MZ betas near 1.0, TS inversions ~0%, coverage_q15 near 0.85
- Spot-check payloads visually
- Push to web app

### 4. Tier 3 diagnostics (alongside, non-blocking)
- GOOGL diagnosis reconciliation
- LIN/VZ/OXY post-mortems in iteration_log.md
- H=126 calibration drift root cause
- garch_cond_vol drop-or-justify ablation
- MSFT/MU undocumented absence from v8 corpus
- DOW H126/EQIX H21/GILD H21 data artifact rows
- RTX exclusion candidate (2020 UTX-Raytheon merger)

### Deferred
- v10 full corpus validation (after OI pull for all 91 tickers)
- step_days=21 experiment
- IC demeaned cross-sectional signal
- SHAP cross-ticker analysis
- Overlay backtest POC (Tier 2-F/G in AUDIT_PLAN)
- Supabase write layer, backend API, frontend -- SWEs handling

---

## Session Log

| Date | Work Done |
|---|---|
| 2026-04-02 | Fixed 15 bugs. First WRDS pull (10 tickers, 2021-2024). First backtest run. FRED yfinance fallback added. |
| 2026-04-03 (session 1) | New PC setup. Expanded to 30 tickers + 2014 start. Fixed 3 pipeline bugs. Cleaned doubled cache. Created vrp_analysis.py and residual_analysis.py. |
| 2026-04-03 (session 2) | Fixed lookahead bias (target overlap). Fixed IV ffill staleness. Ran mini backtest (AAPL/JNJ/XOM). Both analysis scripts run. VRP bilateral confirmed R²=0.147. ACF=0.96 found. Three new vol features added. |
| 2026-04-04 (session 1) | NVDA stress test (AI boom OOS failure 2024). BA stress test (737 MAX inversion, chronic distress). PG softball. T5YIFR (5yr/5yr forward inflation) added to FRED fetch + macro features. FRED cache rebuilt after accidental wipe. Exponential weighting designed (not yet implemented). Archived pre-T5YIFR BA/PG results to results/v1_no_t5yifr/. Kicked off v2 BA/PG run. |
| 2026-04-04 (session 2) | v2 completed. BA beta fixed (0.483->0.916 at H=21), QLIKE down ~80-96% universally. Ran 5-ticker expansion (AAPL/XOM/JPM/JNJ/NVDA). Identified two systematic beta clusters: underforecast (XOM/NVDA/BA) vs overforecast (AAPL/JPM/JNJ/PG). H=21 portfolio-level beta=1.007. NVDA massively improved vs prior stress test. Added 3 new inflation features (abs_chg_21d, chg_63d, zscore) to address beta drift hypothesis. Archived v2 to results/v2_t5yifr/. v3 run complete — hypothesis partially confirmed (JPM/AAPL beta drift closed) but features over-corrected on XOM/NVDA (R2 regression). Features are blunt — dampening inflation globally rather than selectively. Archived v3 to results/v3_inflation_zscore/. |
| 2026-04-05 | v4 launched: 49 features (added mom21_ for 6 ETFs), data from 2011, 16-ticker cross-sector run. OOM killed mid-run (RF n_jobs=-1 spawning 8 workers x full matrix). Fix: RF n_jobs=4, LassoCV n_jobs=1. Resumed remaining 6 tickers. 11 tickers complete at session end. Key findings: XOM R2 recovered (0.415->0.495), BA H=63/126 best calibration ever, new overforecast cluster confirmed (AMZN/GOOGL/NEE beta 0.526-0.657). H=21 portfolio avg beta=0.901, R2=0.346 (strong recovery from v3 dip). Leo building new PC (5950X + 2070 Super) — restore n_jobs=-1, add CUDA device on new machine. |
| 2026-04-06 (Leo) | New PC online (5950X + Arctic Liquid Freezer III 280). RF restored to n_jobs=-1. Speed benchmarking: true baseline with 2011 data = 31 min/ticker (not 13 min — that was old 2014-start cache). n_alphas parameter deprecated in sklearn 1.7, silently ignored — fixed to alphas=20 (correct param). alphas=20 benchmark in progress at session end, clean isolated run needed for final timing. CPU temps 80-81C at 100% load — healthy, install confirmed good. LassoCV n_jobs=1 and alphas=20 in place. Next: complete alphas=20 isolated benchmark, then implement parallel ticker processing if -30% target not met. |
| 2026-04-09 (Leo, claude-sonnet-4-6) | **v5: Two critical feature bugs found + fixed. Full corpus invalid. 6-ticker validation.** Bug 1 (data_loader.py:604): store.load("ohlcv", tickers=config.tickers) didn't include ETFs — silently dropped all 12 ETF ret_*/mom21_* features + broke beta_spy/sector coupling (no SPY in closes). Fix: config.tickers + config.all_factor_etfs. Bug 2 (features.py:122): "mom21_" missing from include_prefixes in get_predictor_columns() — momentum features computed but never passed to models. Net: entire 94-ticker corpus ran with ~34 effective features instead of 46. ETF momentum (v4's entire rationale) was never used. Also dropped tech_ATR (Spearman=0.949 with rv_21d). Leo's laptop session added VIF exclusions to get_predictor_columns(): rv_5d, rv_10d, rv_63d, iv_atm_30d, vol_trend, put_call_abs_skew_30d. Feature count now 46, min_train=920. Also: IC analysis showed IC=0.836 but flagged as structural (characteristic vol ordering, not dynamic). Demeaned IC still needed. 6-ticker v5 validation (AAPL/JPM/XOM/NVDA/IBM/PEP): JPM best result (H=126 beta 1.431→1.253, H=21 1.082→0.992). XOM canary held (0.892→0.879). NVDA H=21 regressed (0.935→0.776, likely min_train effect). IBM/PEP results stale — not re-run. **CORPUS IS INVALID. Full 94-ticker re-run required before any further analytics.** Reset config.py tickers to full universe. |
| 2026-04-06 (Caleb, claude-opus-4-6) | **Major pipeline overhaul — parallelism, GPU, output standardization.** New dev (Caleb Solomon) on WSL machine with NVIDIA GPU. Changes: (1) LassoCV n_jobs=1→-1 (parallelize CV folds); (2) Ticker-level multiprocessing via ProcessPoolExecutor in backtest.py with configurable parallel_tickers=4 in BacktestConfig; (3) XGBoost GPU acceleration — device="cuda", tree_method="hist" with auto-fallback to CPU if no GPU; (4) Vectorized prediction loop — predict_curve_batch() replaces row-by-row predict_curve(); (5) New output.py module producing frontend-aligned JSON: per-ticker {TICKER}_Payload.json (meta, vol_forecast_series, calibration), market_overview.json (regime, sector risk, treemap, GARCH calibration, sector history), metrics_summary.json; (6) Fixed .env to use relative path (data_cache) for cross-platform compat; (7) Fixed .gitignore merge conflicts, added model/.env and data_cache/ to gitignore; (8) Fixed NaN crash in output.py (iv_atm_30d NaN at end of sample). Data rebuilt from WRDS with all 6 FRED series. **3-ticker validation run (JPM/AAPL/XOM, 36 features, 120 WF steps):** H=21 portfolio avg beta=1.054, R²=0.338. XOM best (R²=0.437, beta=0.892). Timing: ~73min wall for 3 tickers parallel (XGB 56%, RF 37%, LassoCV 7%). GPU working but small dataset limits gains. Created batch_backtest.py for overnight runs of untested tickers. |
| 2026-04-10 (Leo, claude-sonnet-4-6) | **v6: Stock split fix + GARCH feature + diagnostics.** (1) Split fix: _pivot_ohlcv() reconstructs adj_closes from CRSP ret column. log(prc/prc.shift(1)) was contaminated — AMZN June 2022 20:1 split injected ewma_vol=1425%. Now uses adj_closes for ewma_vol, RSI, MACD, ret_TARGET, factor returns. GK RV still uses raw H/L/O/C (intraday ratios, split-safe). (2) garch_cond_vol as feature: GARCH(1,1)-skewt conditional vol fit once per ticker on adj_returns. cond_vol_series() added to GarchForecaster. Fed as 43rd predictor. (3) Lasso tracking: lasso_tracking_{TICKER}.csv per ticker. (4) XGB importance tracking: xgb_importance_{TICKER}.csv per ticker (added end of session). (5) rv_21d re-added: was excluded via VIF=10.6 but is the strongest H=21 predictor — Lasso handles collinearity. 44 features now. (6) Date format fix: pd.to_datetime(format="mixed") to handle mixed string/timestamp[ns] parquet files. Data cache fix: JPM/XOM were missing from data_cache/ohlcv/ (env uses data_cache not D:/Tarasque_DB) — copied from D: drive. **v6 sample results (6 tickers):** Split fix validated — AMZN H=63 beta 0.204→0.942. BA H=21 beta 0.834→1.018. All canaries held. R² strong: XOM H=21=0.512, AMZN H=126=0.566. garch_cond_vol weakly selected by Lasso (rank 28/43 at H=63, near-zero at H=21, collinear with ewma_vol). Feature hierarchy: H=21 dominated by vol/IV features; H=126 dominated by macro (yield curve slope #1). All v6 code changes uncommitted. config.py still on 6-ticker sample — reset before full run. |
| 2026-04-28 (Leo, claude-sonnet-4-6) | **v8: Optuna params applied, tau pivot to left tail (P15 floor), signal strength framework, 93-ticker production run.** (1) **Optuna results reviewed**: JPM/AAPL agreed on core params — depth 4→3, n_est 100→225, reg_alpha 0.01→0.15, reg_lambda 1.0→0.27, gamma 0.1→0.20, subsample 1.0→0.75, colsample 0.8→0.70. Conflicting params (learning_rate, min_child_weight, colsample) resolved via compromise. Smoke test (JPM/AAPL/XOM) showed H126 beta improved (AAPL 1.372→1.230, JPM 1.356→1.303) at modest R² tradeoff. Systematic beta>1.0 is structural, not hyperparameter-fixable. (2) **Tau investigation + pivot**: tau=0.92 tested — coverage_q92=0.19-0.39 vs target 0.08. Moving tau didn't proportionally move coverage, confirmed model distribution mismatch on right tail (not a tau problem). Right tail dominated by unobserved shocks (earnings, macro surprises) — no lagged feature can capture it. **Pivoted to left tail (tau=0.15)**: low-vol regimes are observable and persistent (GARCH, HYG, VIXY, RV windows). Errs conservatively (overwarn) — preferred direction under asymmetric loss. Outputs y_pred_q15 (vol floor). (3) **signal_strength.py built** (analysis/): non-linear risk weight mapping (flat <P60, convex above), expanding-window CDF per ticker, conditional tail precision. 3-ticker: XOM 24.7×, AAPL 7.2×, JPM 3.3× lift at P80+. 2×2 regime taxonomy: ensemble-only elevated = 6.1× (sharpest), both elevated = 5.4×, floor-only = 0.69× (contrarian). Key design principle: use ordinal output percentile as risk signal, not cardinal vol number. (4) **vrp_return_conditional.py built** (analysis/): bins prior 5d/21d returns into quintiles, shows VRP distribution per bucket. High returns + low VRP = momentum regime; high returns + high VRP = mean reversion setup. (5) **MemoryError fix**: ProcessPoolExecutor was pickling full 93-ticker raw_data to every worker. Fixed via _slice_raw() in _run_parallel() — keeps only target ticker vsurfd + shared ETF ohlcv + fred/meta per worker. Reduces pickle size ~90×. (6) **93-ticker production run launched**: LIN excluded (R²=0.94 leakage), OXY excluded (RMSE explosion), VZ excluded (beta outlier), META excluded (user-flagged). Config: step_days=63, quantile_alphas=[0.15]. Run 85/93 complete at session end, final workers finishing. (7) **Config update**: tickers list trimmed to 93 production universe with comments explaining each exclusion. quantile_alphas comment block updated with full rationale for left-tail focus. |
| 2026-04-23 to 2026-04-24 (Leo, claude-sonnet-4-6) | **v7: ElasticNet + sector coupling restored + quantile model + hyperparam search launched.** (1) **ElasticNet replaces LassoCV**: ElasticNetCV(l1_ratio=[0.5,0.7,0.9]) — cross-validates sparsity vs group-shrinkage. L2 term prevents arbitrary zeroing of correlated feature groups. l1_ratio_ tracked per fold in lasso_tracking CSVs via new mean_l1_ratio column. (2) **6 VIF-excluded features restored**: rv_5d, rv_10d, rv_63d, corr_sector_21d, corr_sector_252d, sector_wedge — VIF=26-30 but carry real incremental signal (JPM H63 R² dropped 0.17 after removal). ElasticNet handles collinearity proportionally. Feature count 41→50. (3) **min_train fixed to 756 flat** (was max(252,20×n_features)=1000 with 50 features — 20× rule was Lasso-specific instability guard). (4) **QuantileVolModel added** (models.py): parallel XGBoost at tau=0.85 with objective="reg:quantileerror". Outputs y_pred_q85 per prediction. coverage_q85 computed in metrics: mean(y_true>y_pred_q85), target=0.15. (5) **20-ticker cross-sector validation run** completed overnight. Key results: AMZN overforecast cluster fixed (H21 beta 0.666→0.846, R² +0.087); GOOGL betas improved dramatically (0.526→1.007 at H21); H21 mean R²=0.370, H63=0.350, H126=0.460. coverage_q85=0.27-0.36 confirms tau=0.85 behaves like P68, not P85 → tau recalibration needed. D H21/63 betas worsened (sector coupling overcorrecting at short horizons for utilities). LIN data artifact (R²=0.94, coverage=0.0). META only 314 predictions (IPO recency). (6) **Optuna hyperparameter search** designed and launched overnight: hyperparam_search.py (single ticker, 13-param search space, objective=QLIKE+0.3×|MZ_beta-1|²) + overnight_runner.py (JPM 120 trials then AAPL 80 trials, step_days=63 for speed, ~5.7h wall time). (7) **VRP conditional return signal concept**: given recent 5d/21d returns in the Nth percentile bucket, show historical distribution of VRP wedge — if VRP still low after big run = momentum regime; if VRP high = mean reversion setup. Documented in analysis plan (vrp_return_conditional.py to be built). |
| 2026-04-29 (Leo, claude-opus-4-6) | **Tier 0 audit sweep + Step A decomposition -- step_days=63 confirmed as sole cause of v8 R2 regression.** (1) **TS inversion fix (bug #28)**: added second H21-H63 pass in mz_overlay.py enforce_term_structure() after H63-H126 enforcement. Inversions 70.4%->51.1%, still above <10% target -- needs isotonic regression replacement. (2) **Coverage q15 calibration (coverage_check.py)**: per-ticker scalar offset to bring coverage to 0.85. All 91/91 tickers hit target. Average delta ~0.01 (1% ann vol). Outliers: TSLA/NFLX/AMD/CRM. Output: q15_coverage_offsets.csv. (3) **Signal strength full 91-ticker corpus**: pooled lift 3.45x at P80+ (248k obs). Replaces 3-ticker "5.4x" claim. Top: AMGN 60x, BA 31x, BMY 25x, SLB 15x, XOM 14x. Weak: NFLX 0.39x, SCHW 0.83x. (4) **VRP return conditional full corpus**: confirmed at scale. Hi-ret + hi-VRP = +6.8%/+7.6% fwd vol (5d/21d). Q1 median VRP=0.062 vs Q5=0.035. (5) **Unicode fix (bug #27)**: arrow chars in vrp_return_conditional.py crashed cp1252. (6) **MZ overlay re-run** with TS fix. (7) **Step A decomposition -- DEFINITIVE**: 6-ticker canary (AAPL/JPM/XOM/BA/AMZN/NVDA) with step_days=25 (current config) vs v8 step_days=63. **All 18/18 ticker-horizon combinations improved.** H=21 R2 0.279->0.391 (+0.112), beta 0.863->0.995 (near-perfect). H=63 R2 0.260->0.406, H=126 0.295->0.467. R2 exceeded v6 levels. Ensemble weights were NOT hardcoded (audit doc was wrong -- 0.33 was payload placeholder, actual predictions use inverse-RMSE from train_wfa()). step_days=25 already in config.py. **v9 = v8 + step_days=25, no architecture changes needed.** (8) Second 6-ticker smoke test (PG/GOOGL/CVX/C/NFLX/NEE) launched overnight. |
| 2026-04-30 (Leo, claude-opus-4-6) | **v10 feature build + AAPL canary + deployment planning.** (1) **OI data pipeline built**: fetch_oi_25delta() in data_loader.py queries opprcd{YEAR} tables (NOT vsurfd -- audit plan was wrong about vsurfd having open_interest). SQL aggregates SUM(open_interest) and OI-weighted IV per (secid, date, cp_flag) with filters |delta| 0.20-0.30, DTE 20-40. Fixed SECID duplication bug in merge (drop_duplicates on secid before merge). AAPL test pull: 7,068 rows, 2011-2025. Saved to oi_25delta parquet. (2) **CPI/NFP calendar added to utils.py**: CPI_DATES (156 dates, ~13th of month, nearest weekday) and NFP_DATES (156 dates, first Friday). days_to_next_cpi() and days_to_next_nfp() functions. Programmatically generated 2014-2026, +/-2 day accuracy is negligible for 1/(days+1) gravity. (3) **5 new features in features.py**: event_cpi_gravity, event_nfp_gravity (in _add_event_features), oi_put_call_ratio_25d, fear_intensity_25d (skew x log(OI ratio)), oi_hedge_pressure_chg_5d (in new _add_oi_features method). get_predictor_columns updated with "oi_" and "fear_" prefixes. build() updated with step 9b for OI features. 50->55 total predictors. (4) **AAPL v10 canary**: neutral result -- H21 R2 +0.004, H63 +0.002, H126 -0.008. Expected for liquid mega-cap where IV skew already captures most OI signal. ElasticNet correctly shrinks new features near zero when unhelpful. No overfitting damage. (5) **Deployment plan formalized**: v9 is the deployment model (12-ticker validated). v10 is research-stage. Four-phase plan: (Phase 1) fix TS enforcement to isotonic + wire coverage offsets in mz_overlay.py, (Phase 2) full v9 91-ticker corpus run, (Phase 3) apply mz_overlay post-processing, (Phase 4) validate and deploy. Key insight: things that would embarrass are presentation-layer (inverted TS, systematic underprediction, aggressive vol floor), not model math. All fixable without retraining. |
| 2026-04-11 to 2026-04-16 (Leo, claude-sonnet-4-6) | **v6 full corpus run, post-hoc audit, MZ overlay, benchmark comparison, OI/pinball discussion.** (1) **Full 97-ticker corpus run**: two-pass overnight via batch_backtest.py. First pass: 48 tickers, 17.8 hours (AAPL→WMT). Second pass: 49 remaining tickers, 13.6 hours. Both passes via ProcessPoolExecutor parallel_tickers=4. 291 prediction files generated (97 tickers × 3 horizons). (2) **Post-hoc validity audit (audit.py)**: 9-test suite run on full corpus. Key findings: 97/97 tickers beat naive persistence at H63/H126 (DM test); H21 R²=0.374, H63=0.319, H126=0.458 corpus mean; EW MZ betas 0.97-0.98 in current regime (COVID dominates flat OLS making it look 24% calibrated — EW correct); tail asymmetry -0.12 systematic underprediction of severe events (structural rolling-window lag, not worth patching separately); 64.8% term structure inversion rate pre-overlay (calibration drift artifact not real inversions). (3) **backtest_results.csv rebuild**: batch runner overwrites on each run — only had WMT. Rebuilt from 291 individual prediction files using rsplit('_H', 1) to correctly parse HD/HON names. 291 rows, all metrics recomputed. (4) **MZ overlay (mz_overlay.py)**: EW MZ calibration (lambda=0.003) + soft isotonic term structure enforcement (tol=5%). Beta cap at 2.0 prevents extreme corrections (VZ H126 raw=2.619, capped to 2.0). Write-back used merge-based approach to fix numpy.datetime64 vs pd.Timestamp dict-key mismatch bug. TS inversions reduced from 64.8% to 55.6%. Secondary violation bug identified (sequential H21-H63 then H63-H126 can create new H21>H63 inversions) — not yet fixed. (5) **Benchmark comparison (benchmark_models.py)**: HAR-RV (Corsi 2009) + GARCH(1,1) walk-forward vs ensemble. Ensemble lift over HAR: +0.135/+0.200/+0.432 mean ΔR² at H21/63/126. GARCH negative R² at all horizons (mean -0.33 to -1.20) — multi-step GARCH converges to unconditional mean from high-vol history, poor beyond daily. HAR gets 60% of ensemble signal at H21, collapses at longer horizons; ensemble IV/macro/event features provide the gap. (6) **OI differential discussion**: 25δ put vs call open interest as positioning signal (quantity vs price of protection). Mechanism: large put OI = market makers short gamma = vol amplification. vsurfd has no OI column — needs separate WRDS OptionMetrics pull before access expires. (7) **Pinball loss discussion**: tau=0.85/0.90 quantile regression to structurally address -0.12 tail underprediction. XGBoost supports `objective="reg:quantileerror"`. Would serve as "risk upper bound" signal alongside point forecast. (8) **VZ data quality**: H126 EW beta=2.619, calibrated vol 124% annualized — likely Frontier Communications 2024 acquisition artifact. Added EW_BETA_CAP=2.0 guard but needs investigation before production inclusion. |
| 2026-05-26 (Leo, claude-opus-4-7) | **DB cutover day — first live push of full 93-ticker corpus to Supabase.** All four end-to-end stages green. (1) **Live integration test PASSED on AAPL** — `test_daily_append.py --live --ticker AAPL --cleanup` ran all 6 steps clean: schema verified, security_id resolved (320193 = AAPL's SEC CIK — lead dev seeded with CIK convention), full upload (2,973 rows each into prices_history + volatility_history), simulated next-day append (+1 row), idempotent re-run (0 new rows), cleanup removed all test rows. (2) **Two upsert bugs squashed mid-test**: (a) `prices_history.volume` is bigint but CSV had "14820614.0" — fixed `fetch_ohlcv` in `export_for_webapp.py` to coerce `volume.round().astype('Int64')` so CSV writes whole numbers; (b) `pd.NaT` from missing `next_dividend_date` / `next_earnings_date` wasn't caught by the Timestamp/datetime64 isinstance check in `db.py._df_to_records` — added explicit `v is pd.NaT or type(v).__name__ == 'NaTType'` check + defensive catch-all using pd.isna with try/except for non-scalar safety. (3) **Lead dev's schema redesign — `events_history` → `event_history`**: now security-keyed via FK to securities (was generic scope_value string). Severity + scope_value + symbol columns dropped. Restructured writer `write_event_history()` accepts `ticker_to_security_id` dict, drops FOMC events (market-wide events live in `macro_calendar` only — Option A), uses `(security_id, event_date, event_type)` natural-key UNIQUE from migration 004 for idempotent upserts. Updated `db.py` EXPECTED_COLUMNS, TABLE_CONFLICT_COLUMNS, and renamed `upsert_events_history` → `upsert_event_history` (with backward-compat alias). (4) **`ai_overview` EXPECTED_COLUMNS updated** to match lead dev's simpler schema (dropped `date`, `risk_tier`, `input_hash`, `input_tokens`, `output_tokens`, `flagged_reason` from our expectation — they're not in the live table and we don't write to ai_overview anyway). (5) **Migrations 003 + 004 applied by user**: 003 fixed `days_to_dividend` typo, added macro_calendar.event_date, added 3 SHAP JSONB cols to volatility_history, added events_history natural-key UNIQUE. 004 added event_history natural-key UNIQUE after the lead dev's rename. (6) **Migration 002 (forward premium scalars)** applied — 5 `fwd_premium_*` cols on volatility_history. Frontend splines the 7 anchors client-side via d3.curveMonotoneX. (7) **Full corpus push to live Supabase**: 270,590 rows in volatility_history + 270,591 in prices_history = ~93 tickers × ~2,973 days × 2 tables. Took ~60 min wall. (8) **securities table seed**: AAPL pre-existed at security_id=320193 (CIK). Seeded remaining 92 tickers with sequential security_ids starting at 1000 (sequential placeholder — user plans to manually re-map to CIKs later). (9) **`get_distribution()` RPC body** still pending — user flagged this as top frontend priority but architecture work has consumed the session. ~50 lines of PL/pgSQL. (10) **Task Scheduler scripts** ready (`scripts/daily_refresh.bat`, `scripts/weekly_extend.bat`, `scripts/register_daily_task.ps1`) but NOT yet registered. Need: enable `--push-to-supabase --append-only` flag in daily_refresh.bat (currently CSV-only), then user runs PowerShell-as-admin to register. (11) **The 2026-05-25 file lists Path B chain ran end-to-end this morning** (refresh_data → fetch_alpaca_vsurfd → daily_forecast --all → predictions through today 2026-05-26 for all 93 tickers + SHAP per ticker). Predictions table is now the canonical "single source of truth" with rows from 2014-01-06 → 2026-05-26 per ticker. (12) **Open after this session**: register Task Scheduler, write `get_distribution()` RPC, optionally re-map sequential security_ids to CIKs (or accept the mixed scheme as v1). Web dev can start building against live data NOW. |
| 2026-05-25 (Leo, claude-opus-4-7) | **HUGE session: full S&P 500 sneakernet from laptop, root-cause `ret` bug fix, Phases 2/3/4 all landed, SHAP working, predictions extended to today.** Backend integration now wired end-to-end. (1) **Sneakernet executed** — laptop's `H:\Tarasque_DB` (622MB, full SP500 WRDS pull from laptop's earlier run) copied to rig's `data_cache/`. Final corpus state: **ohlcv 528 tickers through 2026-05-20**, **vsurfd 503 tickers** (WRDS data ends 2025-08-29 — OptionMetrics publication lag, confirmed empty post-Aug), **oi_25delta 495 tickers**, **earnings 29,433 rows / dividends 5,576 rows** (Compustat, `(tic, datadate, rdq)` schema). 93 prod tickers fully covered (`C` and `GOOGL` missing from OI only — reclassified secids). `cp -r` left duplicate parquet files in each partition (UUID-named, coexist instead of overwriting) — one-shot dedupe removed 96.6M duplicate vsurfd rows. **Memory worth keeping**: future sneakernets should `rm -rf` target dir first. (2) **Root-cause fix for `ret = NA` bug** — `features._pivot_ohlcv` uses `(1+ret).cumprod()` for adj_close. When Alpaca-appended rows have NA ret, `fillna(0)` was flattening cum and warping the close[-1]/cum[-1] anchor scale across the whole series. Three-part fix: (a) `data_loader.append_recent_data` now backfills `ret` from `abs(prc).pct_change()` per ticker at append time (root cause); (b) `features._pivot_ohlcv` does the same defensive fill (belt-and-suspenders); (c) one-shot backfill on existing parquet filled 182,321 NA-`ret` rows (131K in 2025, 50K in 2026 — all from Alpaca splices). **Impact on v10+ results**: minimal because log-return-based features (ret_TARGET, ewma_vol, factor returns) are scale-invariant, and RSI/MACD pass through StandardScaler. v10+ headline R² stays valid. Bug only would have biased recent-edge forecasts. (3) **Phase 2 complete — real data flowing through `export_for_webapp.py`**: yfinance→CRSP parquet swap (matches training-data methodology), `iv_atm_30/60/91/182d` from vsurfd via `merge_asof` with 120-day tolerance to bridge the WRDS→Alpaca dead zone, `ewma_vol` + `vrp_wedge_ewma_21d` computed inline, `next_earnings_date` from Compustat `rdq` with per-ticker median-lag forward projection (AAPL projects 2026-07-28 vs mockup's 2026-07-29 — within 1 day), `events_history.csv` populated from earnings+dividends+FOMC (181 rows for AAPL), `macro_calendar.csv` from utils.py FOMC/CPI/NFP calendars (9,818 rows per export, 3,651 BDays × 3 event types), `model_runs` seed + FK wiring. `next_dividend_date` remains NULL pending Alpaca corporate-actions integration. (4) **Phase 3 — forward premium scalars (5 new columns + migration 002)**: `model/pipeline/premium_curve.py` implements PCHIP-on-total-variance interpolation. Model anchors at trading days [21, 63, 126], market anchors at calendar days [30, 60, 91, 182] converted to trading days via 252/365 ratio so all math happens on one axis. Five scalars added to volatility_history: `fwd_premium_21d`, `fwd_premium_63d`, `fwd_premium_126d`, `fwd_premium_21_to_63d`, `fwd_premium_63_to_126d`. Sign convention: `IV − Model` (positive = market premium, matches mockup "Wedge +6.6pp" framing). Frontend splines the 7 anchor points directly via d3.curveMonotoneX — no JSONB needed. AAPL corpus-wide mean premiums: +6.8/+6.0/+5.6pp (cumulative), +5.6/+5.2pp (isolated forward windows) — consistent with VRP literature. `model/sql/migrations/002_forward_premium_columns.sql` drafted, additive + idempotent. (5) **Phase 4 — SHAP wired (concurrent-only, NOT backtest)**: `model/pipeline/shap_explainer.py` computes ensemble SHAP via weighted combination of XGB (via XGBoost's native `booster.predict(pred_contribs=True)`, with `device='cpu'` forced — CUDA boosters hang on pred_contribs for single-sample inputs), RF (via `shap.TreeExplainer`, with array-aware `expected_value` handling for newer shap versions), ElasticNet (exact via `coef · (x − μ)`). Combined: `ensemble_shap = Σ_m w_m · shap_m`. Top-10 features by `|shap|`, JSON blob matches SUPABASE_SCHEMA.md §2. **`FEATURE_DISPLAY_NAMES` dict** maps all 55 internal names → user-facing labels per mockup vocabulary: `inflation_forward_5y5y → "Inflation (5y5y fwd)"`, `treasury_10y → "10Y Treasury yield"`, `hy_spread → "HY credit spread"`, etc. (6) **Daily forecast architecture (Pattern A from design discussion)**: `model/pipeline/daily_forecast.py` — per-ticker: load latest joblib → build features → predict → append row to `predictions_<TICKER>.csv` (y_true=NaN) → compute SHAP → append to `forecasts/<TICKER>_shap.csv` (parallel file) → backfill y_true on stale rows where horizon elapsed. **Predictions CSV is single source of truth for predictions**, SHAP lives in parallel file (concurrent-only architecture). `export_for_webapp.py` updated to NULL `shap_h*_top10` on backtest rows and merge in SHAP from `forecasts/<TICKER>_shap.csv` via `load_shap_blob_file()` + pivot. (7) **`extend_predictions.py` — closes Oct 29 → today gap**: backtest's `dropna(subset=target_cols)` truncates feature_df at `data_max − 126 BDays`, leaving predictions stale 6 months. New script trains ONE ensemble per ticker on data through last-existing-prediction-date (clean OOS for the gap), predicts every date in the gap, backfills y_true where horizon elapsed, saves joblib for daily_forecast. **Critical fix in `features.build()`**: added `drop_nan_targets=False` parameter — backtest still uses True (default), but `extend_predictions` and `daily_forecast` use False so they get features for all dates including recent ones. AAPL canary: 378 new prediction rows (126 dates × 3 horizons), now extends to 2026-05-20, joblib `AAPL_model_2026-05-25.joblib` saved. (8) **WRDS access expired** — confirmed via the laptop's pull failing on vsurfd2026 (doesn't exist as a WRDS table) and vsurfd2025 having no rows past 2025-08-29. **Alpaca options splice path established** via `model/pipeline/scripts/fetch_alpaca_vsurfd.py` (`OptionChainRequest` → 4×5 grid extraction → vsurfd append). Adds 1 day of grid per ticker per call. Useful for daily forward signal but doesn't backfill the WRDS-Alpaca dead zone (Sep 2025 → May 2026). (9) **Supabase migrations drafted, not yet applied**: `001_supabase_schema_fixes.sql` (existing — adds `excluded_reason`, creates `model_runs` + `macro_calendar`, adds 11 cols to `volatility_history`, fixes `shap_snapshot` PK, etc.) + `002_forward_premium_columns.sql` (new — adds 5 fwd_premium cols). Both additive-only, idempotent. **User to apply via Supabase SQL editor + provide real creds in model/.env before live test.** (10) **`model/pipeline/results/shap_waterfall_AAPL.png`** generated — 3-panel waterfall (H=21/63/126) showing top-10 SHAP contributions for synthetic AAPL feature row. Validates SHAP output is well-formed. AAPL H=21 dominant feature: rv_21d (-0.057), then ewma_vol (+0.016). H=126 dominated by rv_126d (+0.021) — short-horizon model anchored to short RV, long-horizon to long RV. Sensibility check passed. (11) **Full extend_predictions running on all 93 tickers in background** — ETA ~3-4 hours. After: run `export_for_webapp --all` to produce fresh bundle with wedge series through 2026-05-20 + scalar premiums + null SHAP (filled by next daily_forecast). (12) **Task Scheduler scripts pending** — user wants daily refresh automated post-extend, will set up in next session. Proposed: nightly 5:30 PM ET for daily_forecast + export_for_webapp (push to Supabase once creds land); weekly Sunday 2 AM for extend_predictions (incremental WFA cadence refresh). |
| 2026-05-05 (Leo, claude-opus-4-7) | **Batch 4 (29 tickers) → corpus at 55/91, then quick-validation sanity-checks confirm headline R² is real skill, not horizon mechanics.** (1) **Batch 4**: ABBV/ABT/ADBE/AEP/AMGN/APD/AXP/BAC/BKNG/BLK/BMY/COST/CSCO/CVS/DE/EQIX/FCX/GILD/INTC/LOW/MO/MRK/MS/NKE/ORCL/QCOM/RTX/SO/TXN/UPS — 29 names across financials/industrials/materials/REITs/consumer/utilities/healthcare/semis. Total v10+ corpus now 55 tickers (60% of 91-ticker target). Final aggregate: H=21 mean β=0.980 std=0.094 (54/55 in [0.7,1.3], 98%), R²=0.460. H=63 β=1.066 (54/55, 98%), R²=0.451. H=126 β=1.117 (50/55, 91%), R²=0.555. Cross-horizon mean R²≈0.489. Lone outlier UPS H=21 β=0.52 (logistics name, structural feature gap). v8→v10+ R² lifts: WFC +0.573, UPS +0.559, XOM +0.547, GE +0.521, INTC +0.516. (2) **`scripts/rebuild_aggregates.py` re-run** to merge per-ticker outputs after batch 4. all_predictions.csv had been stale at 29 tickers (not auto-rebuilt by `_run_sector_sweep`). Now 476,667 rows × 55 tickers, dates 2014-01-06 → 2025-10-29. (3) **Quick validation infra built**: `analysis/quick_validation.py` runs 3 sanity tests on the in-sample WFA prediction set. Outputs to `results/validation/quick_validation_summary.md` + 4 CSVs. (4) **Test 1 — naive long-window baseline (lagged 252d rolling mean of y_true)**: model beats naive by ΔR²=+0.240/+0.309/+0.476 at H=21/63/126. Pooled model R²=0.528/0.560/0.672 (pooled across all ticker×date pairs, naturally higher than mean per-ticker R² which is 0.460/0.451/0.555). **Resolves prior concern that H=126 R²=0.55 was "long horizons are easy" — naive baseline scores 0.196 at H=126, model is doing real work.** (5) **Test 2 — period-stratified R²**: pre-2020 vs 2020-2021 vs post-2021. H=21 R² 0.666 / 0.260 / 0.631. H=63 R² 0.678 / 0.232 / 0.719. H=126 R² 0.654 / 0.538 / 0.822. **Counterintuitive finding: post-2021 R² ≥ pre-2020 R² across all horizons** — model is improving with data, not staling. 2020-2021 drag is the COVID regime break (no model handles regime shifts well at the moment of the shift); model recovered fully and now exceeds pre-COVID accuracy. (6) **Test 4 — calm/normal/stress regime stratification (SPY 21d RV terciles, cutoffs 9.3% / 14.7%)**: H=21 R² 0.634 / 0.513 / 0.437 (typical pattern: calmer = more accurate). **At H=63 and H=126 the pattern INVERTS**: H=63 stress R²=0.608 > calm R²=0.528. H=126 stress R²=0.768 > calm R²=0.661. Model is most accurate at long horizons exactly when accuracy matters most. Mechanism hypothesis: stress regimes mean-revert to ~25% vol on a 6-month horizon predictably; calm periods have more idiosyncratic 6-month noise. Model bias consistently negative across regimes (-0.7pp to -1.8pp) — slight underforecasting, not regime-conditional. (7) **What these 3 tests can NOT diagnose**: in-sample WFA leakage. The held-out OOS slice (Test 3) and feature-group ablation (Test 5) are documented in the new "Deferred Validation Tests" section below. Tests 3 and 5 are launch-ready follow-ups, not blockers. (8) **38 tickers remain to hit 100% corpus coverage** — finishing in 1-2 more batches still planned but pending user go-ahead. |
| 2026-05-02 to 05-04 (Leo, claude-opus-4-7) | **v10+ launch validation campaign: 26-ticker stress canary across 12 sectors + meeting-ready aggregation + wedge research finding.** (1) **Reverted event_tech_gravity** from features.py after AAPL+XOM canary showed near-zero net effect on AAPL (its intended target) with -0.015 R² regression at H=63. TECH_EVENT_DATES + days_to_next_tech_event remain in utils.py as research artifacts for v11+ event-window analysis. Predictor count back to 55 (or 52 for tickers without OI data). (2) **Stress canary 1 (4 tickers, 2026-05-02)**: MSFT/LLY/KO/CAT — chosen because v8 had them catastrophically broken at H=63 (LLY β=-0.138 R²=0.010, KO R²=0.005, CAT R²=0.024) and MSFT was untested. v10+ results: H=21 4/4 in [0.7, 1.3] (MSFT 1.04, LLY 0.96, KO 1.06, CAT 0.96), R² gains 0.16-0.45 vs v8. LLY H=63 went R²=0.010→0.455 (45× lift). DUK-style confirmation that v9 step_days fix generalizes to corpus tail names. (3) **Stress canary 2 / batch 2 (8 tickers, 2026-05-02)**: JNJ/GS/TSLA/HON/DUK/AMT/MO/AMD across 8 sectors. v10+ results: H=21 8/8 in band, mean β=0.940 std=0.095, mean R²=0.297. H=63 8/8 in band. H=126 6/8 in band. Standout: DUK H=126 R² went from 0.003 (totally broken) to 0.406 (135× lift). TSLA H=126 R²=0.477 vs v8 R²=0.011 (43× lift). (4) **Batch 3 (12 tickers, 2026-05-03 to 05-04)**: PFE/UNH/AVGO/CRM/WMT/HD/MCD/SLB/GE/WFC/PLD/DIS — wider sector coverage including healthcare insurance, semis, software, retail, restaurants, oilfield services, industrial conglomerate, REIT, media. H=21 12/12 in band, mean β=0.985 std=0.091, mean R²=0.368. H=63 10/12 in band. H=126 8/12 in band. WMT H=63 went from R²=0.000 (broken) to 0.264. WFC R²=0.008→0.467 (58× lift), GE 0.008→0.502 (63× lift), PLD 0.005→0.375 (75× lift). (5) **Aggregate v10+ across 26 tickers (post-batch 3 + AAPL/XOM from May 1)**: H=21 26/26 in [0.7, 1.3] (100%, mean β=0.991 std=0.057, mean R²=0.471), H=63 25/26 in band (96%, mean β=1.058, R²=0.460), H=126 24/26 in band (92%, mean β=1.099, R²=0.551). v10+ launch spec is bulletproof at 28% of corpus coverage — no name catastrophically miscalibrated. (6) **New analysis infra**: `analysis/aggregate_canaries.py` — combines local v10+ predictions + SSD v9 canary into unified MZ table + side-by-side v8 comparison + meeting-ready markdown brief (`v10_canary_summary.md`). `analysis/wedge_price_panel.py` — 3-panel viz per ticker showing price + EWMA(VRP_wedge, 21/63/126d) + z-score. Outputs to `wedge_panels/`. `analysis/beta_regime.py` extended with `--mz-source` and `--beta-col` args to support alternate MZ inputs. (7) **VRP wedge research finding**: when EWMA-21d wedge is in top decile of own history, forward 21d return on growth names runs +5-12% above bottom decile. TSLA: +12.6% top vs +5.5% bottom (7.2pt spread). NVDA: +8.7% vs +3.6% (5.2pt). KO: +1.9% vs +0.7% (1.2pt). AAPL: ~flat. The signal works on momentum names where high VRP correlates with vol-seller premium harvest opportunity, less on staples/mega-caps. **Caveats**: in-sample, period-specific (2020-2021 dominates), needs OOS validation. Real enough to be a "vol seller setup" tile in the web app. (8) **Decision: launch spec locked as v10+ with no further model changes.** event_tech_gravity dropped, weighted-MSE/exp-weighting interventions dropped (v9 already addresses over-forecast cluster). Loss-function research deferred to post-launch v11+ exploration. (9) **Regime 2×2 + slug trail outputs refreshed for the 26-ticker v10+ set** (`regime_2x2_v10canary_h21/63/126.png`, `regime_trail/{TICKER}_trail.png` x 26). Quadrant breakdown at H=21: 11 Q3 genuinely-calm, 7 Q1 stealth event-risk (DUK/KO/AMT/HD/SLB/PFE/MSFT-edge), 5 Q4 mega-cap-buffer (AMD/AVGO/TSLA/CAT/GS), 3 Q2 idiosync+systematic (AAPL/GE/WFC). **Externals vs internals retail framing crystallized** (β_mz>1=externals-driven, β_mz<1=internals-driven; β_mkt>1=systematic, β_mkt<1=decoupled). Decision-actionable hedging guidance: external-dominated names need single-stock options, internal-dominated need broad market hedges. |
| 2026-05-01 evening (Leo, claude-opus-4-7) | **v9 canary data found on sneakernet (H:\); confirms launch readiness; bundler infra built.** (1) **Sneakernet investigation**: sneakernet SSD at H:\volarbmodel\model\pipeline\results\ has 36 v9 per-ticker per-horizon prediction CSVs (predictions_TICKER_Hh.csv, dated 2026-04-29) covering the 12 v9 canary tickers (AAPL/AMZN/BA/JPM/NVDA/XOM/C/CVX/GOOGL/NEE/NFLX/PG). Stacked via new `analysis/stack_v9_canary.py` into `v9_canary_predictions.csv` (99,165 rows) + `v9_canary_mz_calibration.csv` (raw OLS + EW betas at lambda=0.003). (2) **v9 calibration verified at corpus scale**: 12-ticker OLS β: H=21 mean=0.972 std=0.079 (12/12 in [0.7,1.3]), H=63 mean=1.006 std=0.126 (11/12), H=126 mean=1.034 std=0.106 (12/12). EW β slightly biased low (mean 0.85/0.81/0.99) reflecting recent over-forecast regime drift — not a model defect, MZ overlay corrects post-hoc. (3) **Rolling β-over-time on v9 reveals dynamic story**: most v9 tickers' rolling 252d β at most recent date is BELOW 0.7 (over-forecasting) even though full-history aggregate is in band. Example: JPM static OLS β=0.94 H=21, but rolling-window current β=0.57. The model is anchored to longer-term vol levels; 2024-2025 has been calmer than training-era for most names. **This validates the regime-as-signal framing — the residual β IS the regime classifier, not a calibration defect to train away.** (4) **Decision: NO loss-function intervention before launch.** Static training is fine; dynamic regime drift is the regime signal; MZ overlay handles dynamic correction. Both Canary A (exp_weight_lambda) and Canary B (vol_weight_alpha) dropped from the launch plan. (5) **Two-stage launch architecture**: Phase A = 91-ticker corpus on existing data (gated by tech-event-gravity 6-ticker canary first), ships as beta. Phase B = 500-ticker expansion requiring fresh WRDS pull for ~400 net-new tickers (time-sensitive, mid-June expiry). (6) **Bundler infra built**: `scripts/rebuild_aggregates.py` (merges per-ticker outputs from multi-machine corpus run into all_predictions.csv + backtest_results.csv with corpus-level β stats), `scripts/bundle_risk_payloads.py` (per-ticker `{TICKER}_Risk.json` matching launch plan §6A: forecast + current_state + structural + lifetime_stats + history; one-ticker-per-document storage convention matching supabase target). Smoke-tested on v9 canary stacked to per-ticker form — 12 Risk.json files written, schema verified end-to-end. (7) **gitignore overhaul**: model/pipeline/results/ derived outputs (predictions_*, forecasts/, payloads/, regime_trail/, beta_over_time/, etc.) all gitignored going forward. Existing committed history preserved; future corpus runs won't pollute git. logs/ also gitignored. |
| 2026-05-01 (Leo, claude-opus-4-7) | **20-day cadence cutover on AAPL + analytics infra build.** (1) **AAPL runbook executed end-to-end**: refresh_data → backtest → feature_decay → forecast --retrain. Today's AAPL results (step_days=20, post-cutover, v9-class spec): H21 RMSE=0.0645 β=1.179 R²=0.346, H63 0.0525/1.489/0.427, H126 0.0404/1.232/0.489. Predictions through 2025-10-29. Forecast for cycle 2026-05-01→2026-05-29: H21=0.189, H63=0.200, H126=0.218. (2) **Bug #29 — date-parse crash in append_recent_data** (data_loader.py:752): mixed string/Timestamp date columns from concat of cached parquet + Alpaca pull caused pd.to_datetime to infer "%Y-%m-%d" then fail at row 52,328 on a Timestamp.toString form. Fix: truncate to YYYY-MM-DD via .astype(str).str[:10] (mirrors line 747 pattern). (3) **Pre-existing data integrity issue surfaced**: 461-day OHLCV gap (2024-12-31 → 2026-04-06) on 71/118 tickers. Backfilled via Alpaca for affected list (23,643 rows). Filled `ret` column from prc.pct_change for all 39,295 Alpaca-pulled rows to prevent _pivot_ohlcv's cum from going flat through 2025-2026 (would have contaminated adj_closes). (4) **Diagnostic infra built**: beta_regime.py (static 2×2: β_mkt × β_mz), regime_trail.py (slug-trail trajectory through 2×2, 24 monthly snapshots, viridis gradient), regime_returns.py (validates quadrants are economically meaningful — Q2 has 64% neg-return rate at H=21 with -9.5% mean; Q3 highest mean +0.55%; quadrants carry real signal), tail_log.py (per-ticker tail-event journal — separate concept from trail), corr_matrix.py (3 windows: 63/252/504d for portfolio aggregation), beta_over_time.py (rolling-window MZ β time series per ticker, monthly grid). (5) **event_tech_gravity feature added** (utils.py + features.py): single gravity feature for CES/SXSW/GTC/Google IO/WWDC/iPhone keynote dates, programmatically generated 2014-2027. AAPL's 2025-03-07 P97 extreme entry was 7 days from SXSW. ElasticNet shrinks for non-tech tickers (defensible across 400 names). Predictor count 55→56. (6) **Loss-function knobs wired** (models.py + config.py): vol_weight_alpha (upweights high-vol observations, default 0); ElasticNet now accepts sample_weight in addition to XGB+RF (existing gap). Both knobs default off, preserving existing behavior. (7) **CRITICAL FRAMING CORRECTION**: prior loss-function diagnosis was based on v8 corpus (step_days=63) which we know caused R² regression. v8 corpus shows wide MZ spread: H=63 mean β=0.496, only 29% in [0.7,1.3] band. **v9 same 6 tickers (AAPL/JPM/XOM/BA/AMZN/NVDA) shows dramatic improvement: H=21 mean β 0.678→0.995, std 0.324→0.143, in-band 3/6→6/6. H=63 mean 0.511→1.088, in-band 2/6→5/6.** v9 step_days=25 already largely fixes the over-forecast cluster I diagnosed as a structural problem. Loss-function intervention plan revised: Canary A (exp_weight_lambda) was targeting a v8 artifact and is no longer needed. Canary B (vol_weight_alpha for AAPL underforecast) remains potentially useful but is secondary. (8) **AAPL rolling-β-over-time analysis**: today's data shows H=21 β stayed mostly in [0.7,1.3] band 2015-2024 (currently β=1.01 — dead-on). H=63/H=126 had major spikes during regime breaks (2018, 2020, 2024) but currently trending DOWN toward calibration (H63 from 2.5+ in 2024 → 1.28 now; H126 from 2+ → 1.31). The model is auto-calibrating as it ingests recent data. The whole-history aggregate β=1.49 at H=63 is dragging in old miscalibrated windows; recent rolling β is much better. (9) **Launch plan written**: `model/LAUNCH_PLAN_2026-05-01.md`. Locked spec: v10 features + event_tech_gravity (#56), v9 ensemble architecture, step_days=20, τ=0.15 floor, MSE loss. Pre-launch gaps: WRDS pulls for ~400 net-new tickers (time-sensitive, mid-June expiry), 6-ticker tech-event canary, missing scripts (rebuild_aggregates, bundle_risk_payloads). Post-run pipeline order documented. Web-app data contract specified: per-ticker {TICKER}_Risk.json with all horizons (forecast + tail state + structural betas + history) plus aggregate JSONs (regime_2x2, sector_overview, corr_matrix). Storage convention: one ticker per document, all horizons inside (matches supabase target). |

---

## 20-Day Cadence Cutover (in-flight, runs Fri 2026-05-01)

**Status:** code edits done Thu 2026-04-30. Data refresh + backtest + forecast scheduled for Fri 2026-05-01.

**Why:** the pipeline used `step_days=25` for backtests and had no live-forecast persistence layer. Production needs a 4-week (20-BDay) retrain with daily inference between cycles. Database team also needs a clean per-ticker CSV with all horizons stacked + cleaned float precision (source data resolves to ~6 decimals; predictions were emitting 16-decimal repr with FP-subtraction artifacts on `put_call_skew_30d`).

### What was changed Thu 2026-04-30 — code only

All edits in `model/pipeline/`. Verified by `python3 -m model.pipeline --help`, feature_decay CLI parsing, save/load round-trip, and rounding helper smoke tests.

| File | Change |
|---|---|
| `config.py` | `BacktestConfig.step_days` 25 → 20 |
| `utils.py` | new `DECIMAL_PRECISION` dict (~105 keys), `round_for_output(df, schema=)`, `round_scalar`, `round_json_dict(payload, schema=)` |
| `models.py` | `EnsembleVolModel.save(path)` / `.load(path)` (joblib); same on `QuantileVolModel`. Persists models, weights, predictors, final_scaler, config |
| `run.py` | new `--mode forecast` + `--retrain` flag. Forecast mode calls `append_recent_data`, builds features, retrains-or-loads, writes `pipeline/results/forecasts/forecast_{run_date}.csv` (cols: ticker, cycle_start_date, window_end_date, forecast_h21/63/126). Aligns predictor columns to loaded model when retraining is skipped. Uses pandas BDay(20) for window_end_date |
| `backtest.py` | per-ticker `predictions_{TICKER}.csv` long-form (all horizons stacked) replaces per-horizon files. New `lasso_detailed_{ticker}.csv` (raw per-step coefs) and `xgb_importance_steps_{ticker}.csv` (per-step XGB feature importance). Rounding applied at every CSV write. `_run_sector_sweep` and `_generate_json_output` updated to read per-ticker files |
| `output.py` | `round_json_dict` applied to ticker payloads, market overview, metrics summary |
| `analysis/feature_decay.py` | NEW (~330 LOC). Inputs: `lasso_detailed_*.csv`, `xgb_importance_steps_*.csv`. Outputs: `feature_decay_{ticker}.csv` + `feature_decay_summary.csv`. Metrics: rolling_inclusion_freq (8-step window), inclusion_drop_from_peak, sign_flip_rate, importance_slope (OLS) + p-value, decay_score [0,1] heuristic. CLI: `--ticker TICKER` or `--all` |
| `analysis/audit.py` | loader `_load_all_predictions` rewritten to read `all_predictions.csv` (preferred) or per-ticker `predictions_*.csv` (fallback). Test 7 (vrp_nan_rate) loader updated to filter horizon in-memory. Rounding applied to 11 writes |
| `analysis/mz_overlay.py` | loader rewritten for per-ticker schema. Rounding applied to 2 writes |
| `analysis/benchmark_models.py` | loader rewritten. `STEP_DAYS` constant updated to 20. Rounding applied |
| `analysis/{coverage_check,residual_analysis,vrp_analysis,hyperparam_search,signal_strength,vrp_return_conditional,overnight_runner}.py` | imports + rounding at writes; fallback loaders updated where they globbed `predictions_*_H*.csv` |

**Schema for `predictions_{TICKER}.csv`** (database team handoff target, preferred col order):
`date, y_true, y_pred, y_pred_q15, vrp_wedge, put_call_skew_30d, ticker, horizon`. Sorted by (horizon, date).

**Aggregate `all_predictions.csv` is preserved** — still emitted by `_run_sector_sweep`, used by analysis scripts for cross-ticker work.

### Runbook for Fri 2026-05-01

In order. Do not skip steps.

```
python -m model.pipeline --mode refresh_data
python -m model.pipeline --mode backtest --tickers AAPL
python -m model.pipeline.analysis.feature_decay --ticker AAPL
python -m model.pipeline --mode forecast --retrain --tickers AAPL
```

**Pre-checks before running:**
- WRDS creds (`~/.pgpass` on Unix, `%APPDATA%/postgresql/pgpass.conf` on Windows). Falls back to FRED+yfinance+Alpaca if absent.
- `.env` has `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `FRED_API_KEY`.
- Cache last seen at 2026-04-07 (24 days stale at run time).

**Verification after each step:**

1. **refresh_data:** `df['date'].max()` should print `2026-05-01`. Check via:
   ```
   python3 -c "from model.pipeline.data_loader import fetch_dataset; from model.pipeline.config import DataConfig; d = fetch_dataset(DataConfig()); print(d['ohlcv']['date'].max())"
   ```

2. **backtest:** `pipeline/results/predictions_AAPL.csv` exists, contains all 3 horizons stacked. `lasso_detailed_AAPL.csv` and `xgb_importance_steps_AAPL.csv` exist. Last `date` within 20 BDays of 2026-05-01. **Precision check** — all numeric columns should max 6 decimals (4 for bounded stats). No 16-decimal repr.

3. **feature_decay:** `feature_decay_AAPL.csv` exists with per-(horizon × feature) decay metrics.

4. **forecast --retrain:** `forecasts/AAPL_model_2026-05-01.joblib` exists. `forecasts/forecast_2026-05-01.csv` has `forecast_h21 > 0`, `cycle_start_date = 2026-05-01`, `window_end_date ≈ 2026-05-29`.

**Daily refresh path (Mon 5/4 onward, no --retrain):**
```
python -m model.pipeline --mode forecast --tickers AAPL
```
Loads existing joblib, sub-minute runtime per ticker. Writes a fresh `forecast_{date}.csv`.

### Pitfalls / things to remember

- **Stale per-horizon files in `pipeline/results/`** — old `predictions_{TICKER}_H{h}.csv` from previous runs are still on disk. New code does not write them and does not read them; analysis scripts now read `all_predictions.csv` or `predictions_{TICKER}.csv`. Optional cleanup before tomorrow's run for tidiness; pipeline does not require it.
- **Per-step XGB importance** is captured only on the first outer-horizon pass (`h == _first_h`) since `train_wfa()` fits all horizons internally — capturing on every outer pass would triple-count.
- **`_run_forecast` predictor alignment** — when loading a persisted model, missing predictors are filled with 0 and a warning printed; column order is reordered to match `model.predictors`. If the warning prints for many features at daily refresh time, the feature pipeline diverged and a `--retrain` is warranted.
- **Full 91-ticker corpus is NOT cleared to run yet.** Plan: AAPL handoff first, then scale up only after database team confirms schema acceptance. Full corpus wall-time ~14-16h on parallel_tickers=8.
- **Automation is out of scope.** The two single-command entry points are scriptable; user invokes them by hand for the first cycle. Cron / GHA / Task Scheduler comes after one cycle runs cleanly.
- **WRDS access expires mid-June 2026.** Out of scope for this initiative but worth flagging.

### Sanity-check commands kept handy

```bash
# Confirm step_days
python3 -c "from model.pipeline.config import BacktestConfig; print(BacktestConfig().step_days)"

# Inspect prediction precision
python3 -c "import pandas as pd; df = pd.read_csv('model/pipeline/results/predictions_AAPL.csv'); print(df.head()); [print(f'{c}: max {df[c].astype(str).str.split(chr(46)).str[1].fillna(chr(48)).str.len().max()} dec') for c in ['y_true','y_pred','y_pred_q15','vrp_wedge','put_call_skew_30d']]"

# Round-trip model save/load (quick verify)
python3 -c "from model.pipeline.models import EnsembleVolModel; print(hasattr(EnsembleVolModel, 'save'), hasattr(EnsembleVolModel, 'load'))"
```

---

## Deferred Validation Tests (added 2026-05-05)

Quick validation (Tests 1, 2, 4) is done — see `results/validation/quick_validation_summary.md` and the 2026-05-05 session log entry. The two tests below are NOT done. They are the validation work that separates "in-sample WFA model" from "production-defensible model." Neither blocks the Phase A 91-ticker launch but both should run before any external claim of generalization.

### Test 3 — Held-out OOS slice (the real one)

**Why:** all current R² numbers are in-sample walk-forward. WFA is not a held-out test — there's no chunk of data that the model never saw via its CV process. A clean OOS slice answers: "if you train this model with data that ends 2024-01-01 and score it on 2024-2025, does R² survive?"

**How:**
1. Pick a small canary set first (suggest the 6-ticker set already trusted: AAPL/JPM/XOM/BA/AMZN/NVDA).
2. Modify `BacktestConfig` to set `train_end_date = "2024-01-01"` (or similar config knob — may need a small code addition to honour it; current backtest engine walks forward through full history).
3. Run `python -m model.pipeline --mode forecast --retrain --tickers <canary>` to fit on pre-2024 data only and persist joblib.
4. Score the persisted model against actual 2024-2025 y_true. Compare R² to the WFA R² for the same (ticker, horizon, date range).
5. **Pass criterion:** OOS R² within ±0.05 of WFA R² → real generalization. If OOS R² craters by >0.10, WFA was leaking.

**Cost:** ~2 hours compute on the 6-ticker canary. Multi-day if scaled to full 55. Code change is small (a `train_end_date` filter in `BacktestEngine.run_sector_sweep`).

### Test 5 — Feature-group ablation

**Why:** ElasticNet shrinks marginal features near zero, but "shrunk near zero" ≠ "earned its slot." A leave-one-group-out study tells you which feature families are actually paying rent. This is the answer reviewers ask when they say "if you had to remove 10 features, which 10?"

**How:**
1. Define 7 feature groups: `rv_ladder` (rv_*), `options_surface` (iv_*, *_skew_*, term_structure_slope, vrp_wedge), `oi_features` (oi_*, fear_*), `garch_feature` (garch_cond_vol), `macro` (treasury_*, hy_spread, breakeven_*, dollar_index, inflation_forward_5y5y), `events` (event_*_gravity), `factor_etfs` (ret_*, mom21_*).
2. For each group, set `get_predictor_columns()` to exclude that group's prefix and retrain on a 3-ticker canary (AAPL/JPM/XOM) at all 3 horizons. Log R²_full vs R²_dropped per group.
3. ΔR² per group = the marginal value of that family. Report sorted descending.

**Cost:** 7 ablations × ~50min/ticker × 3 tickers = ~17 hours single-threaded. Parallelize across 4 workers → ~4-5 hours. Not launch-blocking but informative for the deck (and for Phase B when WRDS access expires and you're deciding which feature pulls to prioritize).

**Note for both:** results land in `results/validation/`. Update `quick_validation_summary.md` with a "Test 3" and "Test 5" section once run, or split into separate files if cleaner.
