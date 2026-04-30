# Tarasque / Volarbear — Claude Working Context
_Last updated: 2026-04-30 | Model: claude-opus-4-6_

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
