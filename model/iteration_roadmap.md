# Tarasque v4 — Model Iteration Roadmap
*Internal research & engineering context document. Last updated: 2026-04-08.*

---

## Current State (v4 Baseline)

### Architecture
Three-model ensemble trained via walk-forward analysis (WFA):
- **XGBoost** — non-linear interactions, handles vol clustering and regime transitions
- **Random Forest** — robust to noise, handles event-day spikes (earnings, FOMC)
- **LassoCV** — linear stabilizer, acts as sanity check and penalizes redundant features

Models are trained in **log-volatility space** (targets = `log(RV_h)`). Predictions are
exponentiated back to realized vol space, clipped to [-5, 5] before exp to prevent overflow
(vol range 0.7%–148%). Ensemble weighting is inverse-RMSE per model, minimum floor 0.10.

### WFA Configuration
- 7 steps, `step_days=25` (~1.15 months between retrains)
- Expanding window (all history used, not rolling)
- `parallel_tickers=4` on 5950X

### Forecast Horizons
- H=21d (primary, highest reliability)
- H=63d
- H=126d

### Feature Set (49 features across 12 groups)
| Group | Features | Notes |
|---|---|---|
| GK Realized Vol | rv_5d, rv_10d, rv_21d, rv_63d, rv_126d, rv_TARGET, ewma_vol | Core predictors |
| Returns | ret_TARGET | Log daily return |
| Technicals | tech_RSI, tech_ATR, tech_MACD_hist | Trend/momentum context |
| Factor ETF returns | ret_SPY/TLT/GLD/USO/XLF/VXX + mom21_ variants | 12 features |
| Vol Dynamics | vol_trend, vol_vel, vol_of_vol, vol_regime_zscore, vol_chg_21d | Regime context |
| Events | event_fed_gravity, event_earn_gravity, event_div_gravity | Inverse-distance to next event |
| Options/IV | iv_atm_30d, put_call_skew_30d, put_call_abs_skew_30d, term_structure_slope, vrp_wedge, iv_atm_z_score | From OptionMetrics surface |
| Macro | macro_yield_curve_slope, macro_hy_spread, macro_hy_spread_chg_5d, macro_breakeven_5y, macro_inflation_fwd_5y5y + derivatives, macro_dollar_ret | FRED via yfinance/fredapi fallback |
| Factor Decomp | beta_spy, res_vol, res_vol_vel | SPY beta, idiosyncratic vol |
| Price Regime | price_regime | Drawdown from 252d peak |
| Sector Coupling | corr_sector_21d, corr_sector_252d, sector_wedge | GICS-mapped ETF correlation |

### Loss Function
MSE in log-vol space — natural loss for log-normal volatility data. Symmetric.

### Data Sources
- OHLCV: WRDS/CRSP daily (via PostgreSQL)
- Options surface: OptionMetrics vsurfd (delta=-25/25/50, DTE=30/91)
- FRED macro: yfinance fallback (treasury rates) + fredapi (HY spread, breakevens, dollar)
- Events: Compustat earnings/dividends calendar

### Validation Metrics
- RMSE in linear vol space (primary)
- Mincer-Zarnowitz regression (α≈0, β≈1, R² high = well-calibrated)
- PIT (Probability Integral Transform) — uniformity of rank percentiles
- Coverage test — empirical vs. nominal prediction interval width
- Rolling MZ Beta (252d window) — persistent calibration over time

### Current Validation Summary (94 tickers, H=21)
- MZ Beta: majority 0.85–1.15 (calibrated), flagged outliers: META, RTX, GE, GOOGL
- PIT KS stats: range 0.06–0.57, bulk in 0.10–0.20 (fat-tail signature, expected for point-forecast vol model)
- Coverage deficit at P90: ~16pp market-wide (P90 nominal → 73.4% empirical) — model distributions too narrow by construction (MSE trains conditional mean, not tails)
- META KS=0.57: structural regime shift 2022–2023 explains outlier
- RTX KS=0.38: corp action distortion

---

## Iteration 1 — Feature Hygiene (IN PROGRESS)

### Goal
Confirm the 49-feature input space is providing clean, non-redundant signal to the models.
Correlated features split importance without adding information (especially relevant for
LassoCV and for the upcoming quantile models).

### Method
1. **VIF (Variance Inflation Factor)** — pooled across all tickers, all dates
   - VIF > 10: drop or consolidate
   - VIF 5–10: review for economic redundancy
2. **Pearson correlation matrix** — linear redundancy
3. **Spearman correlation matrix** — monotonic redundancy (catches nonlinear duplication)
4. **Known suspect pairs** (flagged before running):
   - `rv_5d` / `rv_10d` / `rv_21d` — mechanically correlated rolling windows
   - `rv_TARGET` == `rv_21d` — literal duplicate
   - `treasury_10y` baked into `macro_yield_curve_slope` — partial overlap
   - `vrp_wedge` = `iv_atm_30d - rv_TARGET` — linear combination of two other features
   - `vol_regime_zscore` derived from `rv_TARGET` rolling mean/std
   - `corr_sector_21d` / `corr_sector_252d` used to make `sector_wedge` — three correlated cols

### Output
- `feature_vif.csv` — VIF scores per feature
- `feature_corr_pearson.png` / `feature_corr_spearman.png` — heatmaps
- `feature_vif_bar.png` — ranked bar chart with VIF > 5/10 thresholds
- Recommendation table: keep / consolidate / drop per feature

### Impact on Models
Feature drops reduce dimensionality → LassoCV trains faster and penalizes less redundantly,
XGBoost importance plots become more interpretable, quantile models (next iteration) get
cleaner tail-specific signal.

---

## Iteration 2 — Quantile Regression Layer

### Goal
Extend the point-forecast ensemble with conditional quantile models trained via pinball loss.
Produces feature-conditional prediction intervals rather than static empirical bands.

### What We're Building
Three additional XGBoost models per ticker per horizon:
- `Q_0.10` — downside floor: 90% of realized vol lands *above* this
- `Q_0.50` — median forecast (cross-check on ensemble mean)
- `Q_0.90` — upside ceiling: 90% of realized vol lands *below* this

**Pinball loss** (check loss):
```
L_τ(y, ŷ) = τ · (y − ŷ)       if y ≥ ŷ   (underprediction)
           = (1−τ) · (ŷ − y)   if y < ŷ   (overprediction)
```
At τ=0.90: underforecasting a spike costs 9x more than overforecasting calm.
The Q_0.90 model *learns* to be conservative at the right tail. This is structurally
different from the existing MSE ensemble which learns the conditional mean.

XGBoost implementation: `objective='reg:quantileerror'`, `quantile_alpha=α`

### Architecture Change
```
Current:  features → [XGB, RF, Lasso] → ensemble → y_pred (mean)

Proposed: features → [XGB, RF, Lasso] → ensemble → y_pred_p50
          features → XGB_Q10          → y_pred_p10
          features → XGB_Q90          → y_pred_p90
```
Quantile models run alongside the ensemble — existing columns untouched, fully backwards compatible.
Runtime impact: ~+40% per ticker (3 additional fits vs. existing 3-model ensemble).

### New Prediction CSV Schema
Adds three columns: `y_pred_p10`, `y_pred_p50`, `y_pred_p90`

### Key Research Outputs

**1. Interval Width as a Signal**
`band_width = Q_0.90 - Q_0.10`
Wide = model uncertainty / event risk / regime ambiguity.
Narrow = low-dispersion, high-confidence environment.
*Independently tradeable*: wide bands before earnings = options cheap relative to uncertainty.

**2. Asymmetry Signal (new vol skew metric)**
`model_skew = (Q_0.90 - Q_0.50) / (Q_0.50 - Q_0.10)`
`skew > 1` = model sees upside vol risk (right tail wider).
`skew < 1` = model sees downside vol compression.
Complement to `vrp_wedge` and `put_call_skew_30d` — three independent skew lenses
(model-implied, market-implied via term structure, market-implied via chain skew).

**3. Feature Importance Divergence**
P50 and P90 models will learn different feature importances. Expected:
- `vrp_wedge`, `vol_regime_zscore`, `macro_vix`, `event_earn_gravity` → higher at P90
- `rv_5d`, `rv_10d` → higher at P50 (mean-tracking, not spike-predicting)
This is original research. Most practitioners use GARCH for vol intervals.
Feature-conditional quantile divergence maps which features drive tail risk specifically.

**4. Coverage as Live Risk Monitor**
Rolling 63-day empirical coverage. If 80% band captures <65% of realized moves:
model is in unseen regime → raise risk flags, widen position limits.
Automated regime-break detector built from model's own uncertainty.

**5. Cross-Quantile Consistency (Quantile Crossing)**
Q_0.10 < Q_0.50 < Q_0.90 must hold (monotonicity). Violations = internally contradictory
feature inputs, typically at structural breaks. Rare but highly predictive of realized vol spikes.

### Why This Is Better Than GARCH on Residuals
GARCH on residuals models *unconditional* error variance — it captures that errors cluster
over time but doesn't know *why* (which features drove the error). Quantile regression gives
*feature-conditional* intervals — the P90 model knows "when VRP wedge is high AND earnings
are imminent, the upside vol risk is X."

### Why This Supersedes Arbitrary Coverage Patches
The current 73.4% empirical coverage at P90 is a symptom of using MSE (trains conditional mean).
Quantile regression solves this at the source: the Q_0.90 model is explicitly trained to
capture the 90th percentile of realized vol, not approximate it post-hoc.

---

## Iteration 3 — SHAP Attribution Layer

### Goal
Explain what features are driving each forecast — at the prediction level (production) and
across time (research).

### Two Layers

**Snapshot SHAP (production):**
After each `predict_curve` call, compute SHAP values for the current observation only.
Output: `shap_snapshot.csv` — one row per ticker per horizon per date, 49 SHAP columns.
Powers the macro-market page: "Why is AAPL vol elevated? → vrp_wedge +0.4, earnings gravity +0.3"
Storage: trivial (~1MB/day).

**Research SHAP (offline):**
Run SHAP on the full holdout set for the terminal WFA fold only (last ~252 observations).
This gives a 252-point time series of feature attribution per ticker without full storage burden.
Full storage math: 94 × 3 × 3000 × 49 = 41M values (~165MB at float32) — feasible but
reserved for research runs, not daily inference.

### Key Research Outputs
- Beeswarm plot: feature × value × direction across all tickers (standard SHAP summary)
- P50 vs P90 SHAP comparison: which features matter more at the tail than at the mean
- Time-series SHAP for 2020 COVID window: shows feature attribution dynamics during crisis
- Feature importance stability: does the model agree with itself across regimes?

### Relationship to Quantile Models
P50 SHAP vs P90 SHAP comparison directly visualizes the quantile divergence analysis above.
Same feature, different quantile model → different SHAP value → that difference IS the
model's answer to "what makes this a tail event rather than an average one."

---

## Pending Infrastructure

### Supabase Write Layer (db.py)
psycopg2 connection + upsert into:
- `backtest_runs` — run metadata
- `backtest_predictions` — per-ticker per-date predictions (including quantile columns when ready)
- `backtest_metrics` — RMSE, R², MZ beta per ticker per horizon per WFA step
- `vol_regime_summary` — current regime percentiles (RV/forecast/IV lens) per ticker

`vol_regime_summary.csv` is already generated and Supabase-ready.
SWEs are currently blocked on this layer.

### Model Serialization for Daily Inference
Serialize trained models to disk after each WFA retrain.
Daily prediction = load + predict (estimated ~2 sec/ticker vs. full refit).
Required for production decoupling of retrain (25-day) from inference (daily).

### Trigger-Based Retrain on Regime Breaks (v2)
Retrain when vol regime crosses threshold (e.g., VIX > 30, RV percentile > P90).
Currently: calendar-based retrain every 25 trading days regardless of regime.

---

## Analysis Scripts Reference

| Script | Output | Status |
|---|---|---|
| `plot_vol_distributions.py` | Per-ticker/sector/market KDE distributions | Done |
| `plot_pit_test.py` | PIT calibration histograms + KS test | Done |
| `plot_coverage_test.py` | Coverage curves, sector breakdown, ticker heatmap | Done |
| `plot_vol_regime.py` | Regime heatmap, sector bars, IV vs RV scatter | Done |
| `plot_beta_full.py` | MZ beta rolling + terminal bar chart | Done |
| `plot_feature_vif.py` | VIF scores, correlation heatmaps, drop recommendations | In progress |
| `plot_quantile_analysis.py` | Band width, asymmetry signal, rolling coverage | Planned (post Iter 2) |
| `plot_shap_analysis.py` | Beeswarm, P50 vs P90 SHAP, time-series attribution | Planned (post Iter 3) |

---

## Notes on Model Philosophy

The coverage deficit (~16pp at P90) is not a model bug — it is expected behavior of any
point-forecast model trained on MSE. MSE minimizers learn E[Y|X], not quantiles.
The fat-tail signature in PIT histograms (doubling at tails) is consistent with the
vol-of-vol literature: realized vol is log-normal with heavy tails, and no historical
distribution fully captures the next crisis.

The quantile regression layer is not a correction to the existing model — it is an extension
that answers a different question. The ensemble answers "what will vol be?" The quantile models
answer "how uncertain are we, and in which direction?" These are complementary, not competing.

For risk management applications (position sizing, margin, options pricing): the quantile
bands are the actionable number. For signal generation (entry/exit, vol surface arbitrage):
the ensemble point forecast remains primary.
