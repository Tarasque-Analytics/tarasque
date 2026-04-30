# Tarasque — Volatility Forecasting Engine
## Project Writeup & Results Summary
_April 2026 | Leo DiPietro_

---

## Overview

Tarasque is a machine learning ensemble for forecasting **realized equity volatility** across S&P 500 large-cap stocks. The core product is a daily prediction of Garman-Klass Realized Volatility (annualized) at three forward horizons — 21, 63, and 126 trading days — combined with an **options-market fear signal** (the VRP wedge: implied minus realized vol) to produce an actionable defensive overlay.

The forecasting model outperforms every published academic benchmark tested. At the 6-month horizon, the ensemble achieves a mean R² lift of **+0.432** over the gold-standard HAR-RV model (Corsi 2009). The traditional GARCH(1,1) model produces *negative* R² at all forecasting horizons.

The pipeline runs on 91 S&P large-cap tickers, training on daily data from 2011 to present, and produces prediction files, calibrated outputs, and frontend-ready JSON payloads.

---

## Motivation: The Volatility Risk Premium

Equity options consistently overprice volatility relative to what subsequently realizes. This gap — the **Volatility Risk Premium (VRP)** — is the market's price for uncertainty. It spikes in fear regimes (2008, 2020, 2022), compresses in momentum regimes, and reverts to a long-run average otherwise.

The commercial thesis: if you can forecast *realized* vol with low bias and model the *implied* vol surface independently (from OptionMetrics data), you can isolate the VRP wedge as a real-time fear signal and use it as a dynamic risk overlay on an equity portfolio. Low VRP after a big rally = momentum regime, stay long. Elevated VRP after a big rally = mean-reversion setup, reduce exposure.

---

## Data Infrastructure

### Sources
| Source | What it provides | Coverage |
|--------|-----------------|----------|
| CRSP (`dsf` + `msenames`) | OHLCV with dividend/split-adjusted returns | 2011–2026 |
| OptionMetrics (`vsurfd{YEAR}`) | Implied vol surface: 5 deltas × 4 maturities per ticker per day | 2014–2025 |
| Compustat (`company` + `funda` + `fundq`) | GICS sector codes, earnings dates, dividend schedules | 2011–2025 |
| FRED (via fredapi + yfinance) | 6 macro series: yield curve, HY spread, breakeven inflation, dollar index, 5y5y forward inflation | 2011–2026 |
| Alpaca (paper account) | OHLCV continuation past CRSP cutoff | 2024–2026 |

Data is stored in partitioned Parquet files in a local cache (`D:/Tarasque_DB`). Total cache: ~170k OHLCV rows, 1.8M volatility surface rows, 3.2k macro observations. All data is fetched from WRDS (Wharton Research Data Services) and rebuilt into a queryable Parquet store.

### Stock Split Handling (v6 Critical Fix)
Raw CRSP price data contains split-adjusted prices but the adjustment is *implicit* — the unadjusted price field `prc` jumps discontinuously on split dates. Using `log(prc_t / prc_{t-1})` to compute returns injects enormous phantom volatility spikes. AMZN's June 2022 20:1 split, for example, caused the rolling EWMA volatility to spike to **1,425% annualized** and contaminated 18 months of predictions (H=63 beta collapsed to 0.204 — the model systematically predicted twice the vol that realized).

The fix: reconstruct adjusted close prices using the CRSP `ret` column (which is correctly adjusted for splits and dividends) via cumulative product from the earliest observation. This is the correct CRSP methodology and produced the most impactful single result improvement in the project — AMZN H=63 R² jumped from 0.125 to 0.441 after this fix alone.

---

## Feature Engineering

50 active features across 9 categories:

### Realized Volatility History (Garman-Klass)
`rv_5d, rv_10d, rv_21d, rv_63d, rv_126d` — Garman-Klass estimator at multiple windows. Uses high/low/open/close intraday ratios (split-safe, since ratios cancel the level). These are the strongest predictors at H=21 because vol is autocorrelated (ACF at lag 1 ≈ 0.96). The model needs multiple windows to distinguish between short-term spikes and structural regime changes.

### Rolling Volatility Dynamics
`ewma_vol` (exponentially weighted), `vol_vel` (second derivative — rate of change of vol), `vol_of_vol` (realized variance of realized variance — captures regime uncertainty), `vol_regime_zscore` (how many standard deviations current rv_21d is from its 252-day mean — critical for suppressing spurious macro signals during stable regimes), `vol_chg_21d` (slow signed drift in vol, distinct from the spike measure).

### Options Surface (OptionMetrics)
`iv_atm_30d` (at-the-money 30-day implied vol), `iv_atm_z_score` (IV normalized to its own 252-day history — the top-ranked H=21 predictor by ElasticNet inclusion frequency, 0.798 across 91 tickers), `vrp_wedge` (IV minus forward RV — the fear signal), `put_call_skew_30d` (25-delta put IV minus call IV — downside fear premium), `term_structure_slope` (30-day vs 91-day IV — whether the curve is in contango or backwardation).

### Factor ETF Returns + Momentum
6 ETF returns (`ret_SPY/VIXY/HYG/USO/TLT/UUP`) plus their 21-day log-momentum versions (`mom21_*`). The momentum versions were the v4 insight: a one-day VIXY spike is indistinguishable from a sustained grind-up in the returns-only signal space. Momentum distinguishes "VIXY up for 3 weeks straight = vol regime shift" from "VIXY up today = noise."

### Macro (6 Series)
`macro_yield_curve_slope` (10y-3mo spread — the top-ranked H=126 predictor at 0.473 inclusion frequency), `macro_hy_spread` + `macro_hy_spread_chg_5d` (credit stress), `macro_breakeven_5y` (5-year inflation expectations), `macro_dollar_ret` (DXY direction), and critically **`macro_inflation_fwd_5y5y`** (5yr/5yr forward inflation swap rate from FRED T5YIFR).

The 5y5y forward rate is structurally more informative than the standard breakeven (T5YIE) because it measures what the bond market expects inflation to be in *years 5-10*, stripping out near-term oil/supply noise entirely. It cleanly separates the 2008/2020 deflationary shock (T5YIFR collapsed) from the 2022 structural inflation regime (T5YIFR hit 2.8% and held for 18 months — exactly the environment that broke most vol models). Three derived features: `abs_chg_21d` (bilateral shock — rising OR falling fast signals uncertainty), `chg_63d` (slow structural drift), and `zscore` (the key fix: once a level has been stable for 252 days, zscore returns to zero so the model stops treating "normal 2.8%" as a perpetual risk-off signal).

### Factor Decomposition + Sector Coupling
`beta_spy` (rolling 63-day market beta), `res_vol` (idiosyncratic residual volatility, orthogonal to market), `corr_sector_21d` / `corr_sector_252d` / `sector_wedge` (correlation to GICS sector ETF at short and long horizons, plus the divergence between them). These were VIF-excluded in early versions (VIF=26-30), but restoring them via ElasticNet (which handles correlated groups proportionally rather than zeroing one arbitrarily) improved JPM H=63 R² by 0.17.

### Events
`event_fed_gravity` (proximity to FOMC dates — based on full 2014-2026 FOMC calendar), `event_earn_gravity` (proximity to earnings announcements from Compustat), `event_div_gravity` (dividend ex-dates).

### GARCH Conditional Vol
`garch_cond_vol` — GARCH(1,1) with skewed-t innovations, fit once per ticker on the full adjusted return history, conditional vol series extracted and fed as a predictor. Primarily useful at H=63/126 where it's orthogonal to the more responsive EWMA.

### Technicals
`tech_RSI` (momentum oscillator), `tech_MACD_hist` (trend signal). `tech_ATR` was dropped after a Spearman rank-correlation check showed 0.949 correlation with rv_21d — pure redundancy.

---

## Model Architecture

### Ensemble of Four Models
Every prediction is a dynamically-weighted blend of:

1. **XGBoost** (gradient-boosted trees, GPU-accelerated via CUDA): tuned via Optuna — depth=3, n_estimators=225, reg_alpha=0.15, reg_lambda=0.27, gamma=0.20, subsample=0.75. Handles non-linear interactions between macro regime features and vol dynamics.

2. **Random Forest**: n_estimators=150, min_samples_leaf=12. Provides variance reduction through bagging; more stable than XGB in extreme regimes because averaging smooths the sharp predictions trees make in sparse regions.

3. **ElasticNet** (replaces LassoCV in v7): `ElasticNetCV(l1_ratio=[0.5, 0.7, 0.9])` cross-validates the tradeoff between L1 sparsity and L2 group-shrinkage per walk-forward fold. For highly correlated feature groups (sector coupling, multi-window RV), ElasticNet shrinks proportionally rather than zeroing one arbitrarily. `mean_l1_ratio` tracked per fold — financials (JPM, GS) tend toward lower l1_ratio (more grouped) vs tech names.

4. **GARCH(1,1)-skewt** (term structure anchor): provides a long-run unconditional vol baseline. Ensemble uses GARCH forecasts to anchor extreme predictions that trees can't make (trees can't extrapolate beyond training distribution). Used as a term-structure consistency constraint, not for standalone prediction.

### Ensemble Weighting
Weights are determined by rolling OOS RMSE of each component on the preceding fold. A minimum weight floor (0.10) prevents any single model from being fully zeroed. Typical weights at H=21: XGB ~36%, RF ~34%, ElasticNet ~30%. GARCH enters primarily through the term structure anchor rather than direct weight competition.

### Quantile Floor Model (v8)
A parallel XGBoost trained with `objective="reg:quantileerror"` at tau=0.15 produces a P15 vol floor estimate (`y_pred_q15`). This structurally addresses the risk management use case: the floor is set conservatively (errs by over-warning rather than under-warning), exploiting the fact that the left tail of volatility is determined by observable persistent factors (GARCH, HY spread, VIXY momentum) that the model captures well — unlike the right tail, which is dominated by unobserved shocks.

---

## Walk-Forward Validation

### Why Walk-Forward Matters
A standard train/test split would use 2015-2020 for training and 2021-2025 for testing. This is wrong for vol forecasting because: (1) the model would have seen COVID in training, trivializing the test; (2) real deployment retrains daily — a static test doesn't measure that; (3) lookahead bias from features that use future data is invisible in static splits.

The walk-forward design:
- **Expanding window**: start date fixed at 2011-01-01, end date advances by `step_days` at each fold
- **Minimum training**: 756 days (~3 years) before any prediction is made
- **No lookahead**: targets defined as `rv_{h}d.shift(-h)` with zero sample overlap between adjacent horizons (a common bug — fixed in v3)
- **IV ffill cap**: implied vol forward-filled 5 days maximum to prevent stale options data from contaminating features (another real bug: unlimited ffill caused June 2020 IV from before expiry to persist for months)

The expanding window means early folds are trained on 2011-2016 data and predict 2016 vol. Later folds are trained on 2011-2025 and predict 2025-2026 vol. No future information ever enters any prediction.

### Universe and Parallelism
91 S&P large-cap tickers (after excluding confirmed data artifacts: LIN leakage R²=0.94, OXY RMSE explosion, VZ Frontier Communications acquisition artifact, META IPO recency). Each ticker runs independently. ProcessPoolExecutor with 4 parallel workers on an AMD Ryzen 9 5950X; XGBoost uses CUDA GPU acceleration (GTX 1070). Per-ticker throughput: ~30 minutes on this hardware for the full 47-step expanding walk-forward with 50 features.

---

## Version History and Results

### The Progression

**v1 (April 3)** — BA and PG only, 39 features, 2014 start. First real result: BA H=21 MZ beta=0.483 (model predicted twice the vol that realized). QLIKE=0.050.

**v2 (April 4)** — Added T5YIFR (5y/5y forward inflation swap), 7 tickers. BA beta improved to 0.916. QLIKE dropped 80-96% universally. NVDA massively improved. Two systematic clusters emerged: overforecast (AAPL, JPM: beta>1) and underforecast (XOM, BA: beta<1). H=21 portfolio beta = 1.007 — essentially unbiased at portfolio level.

**v3 (April 4)** — 3 new inflation features to address overforecast cluster. JPM beta closed from 1.719→1.387 at H=63. But features were too blunt — XOM and NVDA (already calibrated) lost R²  because inflation dampening applied globally rather than selectively.

**v4 (April 5-6)** — Added ETF 21-day momentum features. Data start pushed to 2011. 16-ticker cross-sector run. XOM R² recovered, BA H=63 beta essentially 1.007 (best result for a distressed name). New overforecast cluster identified: AMZN/GOOGL/NEE (mega-cap liquidity buffers and regulated cash flows dampen macro transmission). H=21 portfolio beta=0.901, R²=0.346.

**v5 (April 9)** — Two critical silent bugs found that invalidated the entire v4 corpus:
1. `data_loader.py`: ETF tickers weren't included in the OHLCV load — silently dropped all 12 ETF ret_*/mom21_* features and broke beta_spy/sector coupling (no SPY in the price matrix)
2. `features.py`: "mom21_" was missing from include_prefixes in `get_predictor_columns()` — momentum features were computed but never passed to the model

Net: the entire 94-ticker corpus had run with ~34 effective features instead of 46. ETF momentum — v4's entire theoretical rationale — was never actually used. All prior results were invalid. 6-ticker validation after fix: JPM H=21 beta 1.082→0.992.

**v6 (April 10-16)** — Stock split fix (adj_close from CRSP ret column), GARCH as predictor, rv_21d re-added, lasso/XGB tracking. AMZN split contamination confirmed and fixed. Full 97-ticker corpus run (two overnight passes, 31+ hours total). **This is the benchmark corpus.**

| Metric | v6 Corpus (97 tickers) |
|--------|----------------------|
| H=21 mean R² | **0.374** |
| H=63 mean R² | **0.319** |
| H=126 mean R² | **0.458** |
| EW MZ beta (current regime) | 0.97–0.98 |
| Tickers beating naive (H=21 DM) | 97/97 |
| COVID mean bias | -0.082 (structural underprediction) |

**v7 (April 23-24)** — ElasticNet replaces LassoCV, 6 VIF-excluded sector coupling features restored, QuantileVolModel added (tau=0.85, later revised), min_train reduced to 756, Optuna hyperparameter search launched. 20-ticker cross-sector validation: H=21 R²=0.370, GOOGL overforecast fully resolved (0.526→1.007 beta), AMZN improved. Optuna confirmed: depth 4→3, n_estimators 100→225, more regularization.

**v8 (April 28)** — Optuna params applied, tau pivoted to left-tail floor (0.15), 93-ticker production run. *Note: step_days changed to 63 for run speed — this dominates the metric comparison to v6 (step_days=25) and makes R² figures incomparable. The proper production rerun with step_days=25 is the next task.*

---

## Benchmark Comparison

### vs HAR-RV (Corsi 2009)

The Heterogeneous Autoregression of Realized Volatility is the gold standard academic benchmark. It uses realized vol measured over 1-day, 5-day, and 22-day windows to forecast future RV, exploiting the well-known multi-scale persistence of volatility (HAR stands for Heterogeneous AR — different market participants react on different time scales).

**Ensemble vs HAR-RV — mean ΔR² across all tickers:**

| Horizon | Ensemble R² | HAR-RV R² | **ΔR² (ensemble advantage)** |
|---------|-------------|-----------|------------------------------|
| H=21 | 0.374 | 0.239 | **+0.135** |
| H=63 | 0.319 | 0.119 | **+0.200** |
| H=126 | 0.458 | 0.026 | **+0.432** |

HAR-RV captures roughly 60% of the ensemble's signal at H=21 — the RV persistence feature (lags of rv_21d) that HAR uses is also the ensemble's second-strongest predictor. HAR collapses at longer horizons because it has no macro, no IV surface, and no event information. The ensemble's IV features, yield curve slope, and sector coupling provide the gap.

### vs GARCH(1,1)

GARCH produces **negative R²** at all forecasting horizons (mean -0.33 at H=21, -0.82 at H=63, -1.20 at H=126). This is not a failure of GARCH as a daily vol model — it is an excellent daily forecaster. The problem is that multi-step GARCH forecasts decay toward the unconditional mean from whatever the current conditional variance is. After a high-vol period (COVID, 2022 rate shock), GARCH keeps forecasting elevated vol for months as the half-life is very long. It systematically overpredicts in post-spike regimes, producing predictions worse than simply guessing the historical mean.

### vs Naive Persistence

Naive persistence = "tomorrow's vol equals today's vol" (lag-H of realized vol). Given vol's high autocorrelation (ACF lag-1 ≈ 0.96), this is a genuinely competitive baseline.

**Diebold-Mariano test (squared error loss) vs naive:**
- H=21: **80/91 tickers** beat naive at p<0.05
- H=63: **89/91 tickers** beat naive at p<0.05
- H=126: **90/91 tickers** beat naive at p<0.05

The two tickers that naive beats at H=21 and H=126 respectively are SPG (REIT, low macro sensitivity) and DOW (known data quality issue — 14.8% NaN rate on the VRP feature). The model is dominant at longer horizons where simple persistence degrades.

---

## Post-Hoc Analytics Suite

After the full corpus run, six analytical tools were built and run:

### 1. MZ Calibration Overlay (`mz_overlay.py`)
Mincer-Zarnowitz regression (`y_true = α + β·y_pred + ε`) per ticker per horizon, estimated with exponential weighting (λ=0.003, half-life ~231 days) to emphasize the recent regime. Ideal: α=0, β=1. The walk-forward ensemble systematically over-forecasts at long horizons in the full history (β<1 on flat OLS) because COVID-era overpredictions dominate the historical average. EW-weighting corrects this — in the current regime (2023-2026), the model is nearly perfectly calibrated.

Post-overlay predictions are stored in `all_predictions_cal.csv`. Term structure enforcement (H21 < H63 < H126 with 5% tolerance) is applied as a soft isotonic correction — blending inversions toward a monotone surface.

Known limitation: the sequential enforcement (H21-H63, then H63-H126) can create secondary inversions — fixing H63-H126 can pull H63 down below H21. A full isotonic regression pass would fix this cleanly.

### 2. Validity Audit (`audit.py`) — 9 Tests
- **MZ Regression**: At the full-history level, 27% of (ticker, horizon) pairs fall in β=0.8-1.2. In the current regime with EW weighting: 100% of tickers well-calibrated at all horizons (v6 result).
- **Diebold-Mariano**: 88-99% of tickers beat naive persistence depending on horizon.
- **Tail Asymmetry**: Top-10% realized vol bucket has 5.4× worse RMSE than the middle-80%. Consistent -0.12 bias (systematic underprediction of severe events). Structural — rolling window models always lag on regime shifts. Not a fixable bug.
- **Macro Regime Bias**: Near-zero bias in normal regime and post-normalization regime. COVID bias: -0.082 (structural, model under-predicts once-per-decade spikes). Rate shock bias: -0.023.
- **VRP Quintile RMSE**: RMSE monotonically increases from low-VRP to high-VRP quintiles — when options are extremely mispriced, the model struggles. Confirms that the VRP wedge is itself a signal about forecast uncertainty.
- **Feature Stability (ElasticNet/Lasso)**: Avg pairwise Spearman rank correlation 0.505-0.531 — moderately stable cross-ticker feature ranking. iv_atm_z_score is by far the most consistently selected predictor at H=21 (0.798 inclusion frequency). macro_yield_curve_slope dominates at H=126 (0.473). macro_inflation_fwd_zscore appears in H=126 top-3 — the hypothesis (stable high inflation eventually gets priced in) is being captured.
- **Seam Analysis**: H=21 jump ratio 1.05 at model refit boundaries. Extremely clean — no visible discontinuities in the prediction time series at refit dates.

### 3. Signal Strength Framework (`signal_strength.py`)
The core signal insight: **calibration coverage is the wrong metric for risk management**. The right metric is: when the ensemble prediction is at the P80+ of its own historical distribution (expanding window, no lookahead), how much more likely is it that realized vol will be elevated?

**Pooled results (91 tickers, H=21):**
- Lift at P80+ signal threshold: **3.45×** (when the model is in the top 20% of its own history, adverse events are 3.45× more likely)
- Top individual tickers: AMGN (60×), BA (31×), BMY (25×), SLB (15×), XOM (14×), T (10×)
- Energy, healthcare, and telecom names show the strongest ordinal signal. Growth/tech names (NFLX 0.39×, AMAT 0.70×) show weak or contrarian signals — vol compression in these names often follows high model output.

**Non-linear risk weight mapping:**
The model's output percentile maps to a risk weight through a convex curve: flat below P60, then P70→0.15, P80→0.30, P90→0.55, P95→0.75, P99→0.95. This reflects the asymmetric loss function: false negatives (missing real risk) are far more costly than false positives (false alarms). A 3.45× lift at P80 is actionable even if it's wrong most of the time — avoiding one real event is worth many false alarms.

**2×2 Regime Classification (ensemble signal × floor signal):**
| Ensemble | Floor | Interpretation | Lift |
|----------|-------|----------------|------|
| High | Low | Spike forming from quiet base | **6.1×** — sharpest signal |
| High | High | Persistent high-vol regime | 5.4× |
| Low | High | Vol compressing | 0.69× — contrarian |
| Low | Low | Quiet regime | 1.0× baseline |

The two signals identify different economic regimes and should NOT be combined into a single score — they have orthogonal information.

### 4. VRP Conditional Return Distribution (`vrp_return_conditional.py`)
Given that the last 5d or 21d returns fall in quintile Q (from worst=Q1 to best=Q5), what is the distribution of the VRP wedge, and what forward vol does each combination predict?

Key findings across 91 tickers:
- **VRP gradient**: Bottom-quintile return stocks (Q1) carry median VRP=0.062; top-quintile winners (Q5) carry only 0.035. Winners have suppressed implied uncertainty relative to losers.
- **Mean reversion signal**: High return (Q5) + High VRP → forward realized vol **6.8-7.6% higher** than High return + Low VRP.
  - High returns + low VRP = momentum regime (market isn't pricing additional risk into the rally) → vol stays low
  - High returns + high VRP = mean reversion setup (options market sees risk not reflected in price) → vol rises

This gives the frontend a regime classification: for each stock, show the current return quintile and current VRP level, and flag the combination as either "momentum confirm" or "caution/mean-revert signal."

### 5. Benchmark Comparison (`benchmark_models.py`)
Rigorous walk-forward implementation of HAR-RV and GARCH(1,1) on the same tickers and periods as the ensemble, for a direct apples-to-apples comparison. Results summarized in the HAR/GARCH section above.

---

## Engineering Highlights

### Stock Split Contamination (Critical Bug, v6)
The most impactful engineering fix in the project. Using log price ratios for returns contaminates vol estimates on split dates. The fix — cumulative product of the CRSP `ret` series — is the correct institutional methodology for adjusted prices. Impact: AMZN H=63 R² 0.125 → 0.441 (a result that had been attributed to "mega-cap liquidity buffers" for two prior versions).

### MemoryError in Parallel Backtest (v8)
ProcessPoolExecutor pickles the full raw_data dictionary to every worker on submission. With 93 tickers of vsurfd + ohlcv data, each worker received the full ~3GB dataset. Fix: `_slice_raw()` function extracts only the target ticker's vsurfd plus the shared ETF ohlcv and macro series before submission — reduces per-worker pickle size ~90×.

### Feature Bug That Invalidated 94 Tickers (v5)
Two silent bugs ran the entire v4 corpus with ~34 features instead of 46:
1. ETF data wasn't loaded alongside stock data — all ETF features and sector coupling silently dropped
2. "mom21_" prefix was missing from the feature selector — all momentum features computed but discarded before model training

The ETF momentum rationale (distinguishing trends from spikes) — v4's entire theoretical contribution — was never actually tested until these were fixed.

### Lookahead Bias Fix (v3)
Original target construction used `rv_21d` at date t to predict `rv_21d` at date t — the target overlapped with itself in adjacent rows. Fix: `rv_{h}d.shift(-h)` with zero sample overlap between adjacent horizons. Easy to miss, catastrophic if present.

### Hyperparameter Optimization (Optuna)
13-parameter search space (XGBoost + RF), objective = `QLIKE + 0.3 × |MZ_beta - 1|²`. 120 trials on JPM + 80 on AAPL, overnight. Key improvements: max_depth 4→3 (less overfitting), n_estimators 100→225 (more trees at lower depth), reg_alpha 0.01→0.15 (stronger L1), reg_lambda 1.0→0.27 (less L2), gamma 0.1→0.20 (higher split penalty). H=126 beta improved notably (AAPL: 1.372→1.230, JPM: 1.356→1.303).

### GPU Acceleration
XGBoost configured with `device="cuda"`, `tree_method="hist"` with automatic CPU fallback. On a GTX 1070, this provides meaningful speedup for the ensemble's most expensive component. Total 97-ticker corpus run time: ~31 hours on a Ryzen 9 5950X + GTX 1070 with 4 parallel workers.

---

## Data Quality Flags and Exclusions

| Ticker | Issue | Status |
|--------|-------|--------|
| LIN | R²=0.94 across all horizons — leakage artifact from Linde-Praxair merger | Excluded from v8+ |
| OXY | RMSE explosion in several folds | Excluded |
| VZ | H=126 beta=2.619 (capped), calibrated vol 124% annualized — Frontier Communications 2024 acquisition artifact | Excluded |
| META | Only 314 predictions — IPO recency, insufficient history | Excluded |
| DOW | H=126 RMSE=7.29 (naive=0.11), 14.8% VRP NaN rate | Flag for investigation |
| EQIX | MZ beta≈0 at H=21 — model predicts a near-constant | Flag for investigation |
| RTX | Beta=0.21-0.26 at H=21/63 — Raytheon-UTC merger data discontinuity | Flag for investigation |

---

## Structural Limitations

**Tail vol underprediction is permanent.** The top-10% realized vol bucket has 5.4× higher RMSE than the middle-80%. The model systematically under-predicts by ~0.12 annualized vol in severe events. This is not a solvable bug — it's a consequence of using lagged features to predict forward vol: at the onset of a genuine regime shift (COVID crash, 2022 rate shock), no rolling-window feature has yet captured the new regime. The expanding window will eventually incorporate the event into training, but predictions during the event itself will always lag.

**Right-tail quantile calibration is intractable.** The quantile model for P85/P92/P99 coverage cannot be calibrated by adjusting tau — the prediction distribution is too narrow relative to realized vol extremes. This is why the quantile model was repositioned to the left tail (P15 floor) where the problem is tractable.

**COVID regime dominates flat-OLS MZ statistics.** Full-history MZ beta statistics look poorly calibrated (27% within 0.8-1.2 band) because COVID-era predictions dominate the regression. Using exponential-weighted MZ (emphasizing recent 1 year), the model is essentially perfectly calibrated in the current regime.

---

## Current Production State

- **91 tickers**, S&P 500 large-cap, covering all 11 GICS sectors
- **3 horizons**: 21, 63, 126 trading days (~1 month, 1 quarter, 6 months)
- **50 features** across price/vol, options surface, macro, events, sector coupling
- **Per-ticker JSON payloads** (`{TICKER}_Payload.json`) with calibrated forecasts, term structure, and VRP signal
- **Market overview JSON** (`market_overview.json`) with sector risk treemap, regime indicator, GARCH calibration
- **Signal strength JSON** with ordinal risk percentile per ticker, 2×2 regime classification
- **VRP conditional JSON** with return-quintile conditional vol distribution per ticker

---

## Remaining Roadmap

1. **Proper v8 validation (step_days=25)**: The v8 run used step_days=63 for speed — can't compare to v6. Need 5-ticker smoke test at step_days=25 to isolate the impact of Optuna params + ElasticNet + sector coupling.

2. **OI differential feature (time-sensitive)**: 25-delta put vs call open interest from OptionMetrics (`optionm.vsurfd`). Captures the *quantity* of hedging demand, not just its price. When put OI >> call OI at 25-delta, market makers are net-short gamma → they must delta-hedge by selling rallies and buying dips → mechanical vol amplification. WRDS access expires in ~1 month.

3. **Term structure monotonicity fix**: The sequential H21-H63, then H63-H126 enforcement in `mz_overlay.py` can create secondary inversions. Replace with full isotonic regression.

4. **DOW/EQIX/RTX investigation**: Three tickers flagged in the v8 audit with pathological behavior. Exclude or fix before production deployment.

5. **SHAP cross-ticker analysis**: Feature importance heatmap by sector. Which macro features matter for energy vs tech vs financials? How does importance shift through 2022-2025?

6. **Supabase write layer / backend API / frontend**: Engineering team handling.
