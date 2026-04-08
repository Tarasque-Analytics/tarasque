# Tarasque / Volarbear — Claude Working Context
_Last updated: 2026-04-06 (end of session) | Model: claude-sonnet-4-6_

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

**Owner:** Leo DiPietro — econ/stats student, CS is not primary. Hand-hold on implementation details. Graduating soon, WRDS access expires in ~1.5 months.
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
      features.py           <- 39-feature FeatureBuilder (fully current)
      models.py             <- GarchForecaster + EnsembleVolModel
      backtest.py           <- Walk-forward BacktestEngine
      run.py                <- CLI orchestrator
      utils.py              <- FOMC calendar, Black-Scholes, Monte Carlo cone
      requirements.txt
      analysis/
        __init__.py
        vrp_analysis.py     <- VRP wedge bilateral uncertainty analysis
        residual_analysis.py<- Systematic residual diagnostic tool
      results/              <- Backtest CSVs (predictions_TICKER_Hh.csv, backtest_results.csv)
    claude_context.md       <- THIS FILE — always update this
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
| OptionMetrics | `optionm.vsurfd{YEAR}` (2014–2025) | OK — unified view missing, use year tables |
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

## Complete Feature Set (49 active as of 2026-04-04 v4)

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

### Options Surface (requires vsurfd)
- iv_atm_30d, put_call_skew_30d, `put_call_abs_skew_30d`, term_structure_slope, vrp_wedge, iv_atm_z_score
- `put_call_abs_skew_30d` — bilateral skew (U-shaped signal confirmed in VRP analysis)

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

### Sector Coupling
- corr_sector_21d, corr_sector_252d, sector_wedge

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

### v4 (+ ETF 21d momentum for 6 core ETFs + 2011 data start) — IN PROGRESS
16-ticker cross-sector sweep: BA, PG, AAPL, XOM, JPM, GS, C, CVX, AMZN, GOOGL, MRK, NEE, WMT, CAT, MS, LIN
49 features total. Data from 2011 (pre-2014 = context seed only). First predictions ~late 2016.
Archived to results/v4_etf_momentum/ when complete.

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

---

## Progress Checklist

```
[##########] Data pipeline (WRDS pull, Parquet cache)           100%  COMPLETE
[##########] Feature engineering (49 features v4)               100%  COMPLETE — ETF momentum added Apr 5
[##########] Walk-forward backtest engine                        100%  COMPLETE
[##########] Lookahead bias audit & fix                          100%  FIXED
[##########] IV staleness fix                                    100%  FIXED
[##########] VRP bilateral uncertainty analysis                  100%  COMPLETE
[##########] Residual systematic analysis                        100%  COMPLETE
[##########] 94-ticker full corpus backtest                      100%  COMPLETE — Apr 7/8 overnight runs
[##########] Full stat sheet (v4_stat_sheet_full.csv)           100%  COMPLETE — 279 rows, 93 tickers x 3H
[##########] Beta/calibration visualizations                     100%  COMPLETE — 3 chart sets
[##########] WRDS universe discovery (454 qualified)             100%  COMPLETE — wrds_qualified_universe.csv
[##########] Exp sample weighting infra                         100%  COMPLETE but DISABLED (lambda=0.0)
[----------] MZ post-hoc calibration overlay                     0%   Designed — rolling OOS alpha/beta correction
[----------] IC/quintile spread validation                        0%   Not yet — key monetization test
[----------] Pull 119 new WRDS tickers                           0%   Identified, not pulled
[----------] Supabase write layer (db.py)                        0%   SWEs blocked — highest external dependency
[----------] Backend API endpoints                               0%   SWEs handling
[----------] Frontend web app                                    0%   SWEs handling
```

---

## Next Actions (in priority order)

### 0. HARDWARE STATUS (2026-04-06)
5950X online. RF n_jobs=-1 restored. LassoCV alphas=20 (sklearn 1.7+ param, was n_alphas — deprecated/silently ignored).
Arctic Liquid Freezer III 280 confirmed good: 67°C at 100% sustained load (settled after first heat cycle).
2070 Super NOT YET installed — add CUDA when it arrives:
```python
xgb_params: "device": "cuda", "tree_method": "hist"
```
**True speed baseline (2011 data, full settings, alphas=20):** CAT run in progress at session end — check results for clean timing.
Target: -30% from 31 min baseline = under ~22 min/ticker.
If alphas=20 doesn't hit -30%, next lever is **parallel ticker processing** (multiprocessing in run.py, 4 tickers × 8 threads = ~4x throughput, zero model quality change).

### 1. COMPLETE — v4 remaining tickers
CAT run in progress at session end. Still needed: WMT, MS, LIN, MRK (full horizons).
Archive to results/v4_etf_momentum/ when all 16 done.
Config currently set to "CAT" — restore 16-ticker list when ready for full run.

### 2. IMPLEMENT — Exponential Sample Weighting
Addresses the COVID/2018/2025 regime bias. The ACF=0.96 finding means the model remembers recent errors — exponential weighting reinforces this appropriately by making recent regimes matter more.

```python
# In backtest.py, inside the WFA loop, before fitting:
# age = (train_end_date - train_dates).dt.days / 365.25
# sample_weight = np.exp(-0.15 * age)  # half-life ~4.6 years
# Pass to XGBoost: model.fit(X, y, sample_weight=sw)
# Pass to RF: model.fit(X, y, sample_weight=sw)
# LassoCV does NOT support sample_weight — leave as is
```
lambda=0.15 gives: current year weight=1.0, 5yr ago=0.47, 10yr ago=0.22. 2014 data ~22% weight of 2024 — present but not dominant.

### 2. DESIGN — v5 inflation feature pruning
Drop `macro_inflation_fwd_chg_21d` and `macro_inflation_fwd_chg_63d` (redundant with zscore).
Keep 3 orthogonal features: level, zscore, abs_chg_21d.
Hypothesis: reduces overforecast on AMZN/GOOGL/NEE by removing correlated inflation signals competing for tree splits.
Run same 16-ticker set, diff against v4.

### 3. FINISH + COMPARE — v2 BA/PG A/B test (T5YIFR)
BA/PG v2 run was interrupted. Results so far in results/ (BA H21+H63 only). v1 archived in results/v1_no_t5yifr/.

**To finish:** re-run `python -m model.pipeline --mode backtest` (config is already set to BA, PG).

**To compare after:** run this to diff v1 vs v2 metrics side by side:
```python
import pandas as pd
v1 = pd.read_csv('model/pipeline/results/v1_no_t5yifr/backtest_results.csv')
v2 = pd.read_csv('model/pipeline/results/backtest_results.csv')
comp = v1.merge(v2, on=['ticker','horizon'], suffixes=('_v1','_v2'))
comp['r2_delta'] = comp['mz_r2_v2'] - comp['mz_r2_v1']
comp['rmse_delta'] = comp['rmse_v2'] - comp['rmse_v1']
print(comp[['ticker','horizon','mz_r2_v1','mz_r2_v2','r2_delta','rmse_delta']].to_string())
```
Key thing to check: does T5YIFR improve BA 2022 specifically (H=126 R²=0.008 in v1 — structural inflation year, exactly what T5YIFR targets)?

### 3. RESTORE + RUN — Full 30-ticker prod backtest
- Set config.py tickers to full 30-ticker universe
- Wipe results/ directory (stale files from test runs)
- Run on new 5950X (~2.5hr estimate)
- After run: execute both analysis scripts

### 3. BUILD — Supabase write layer (pipeline/db.py)
SWEs are blocked. Tables needed:
- `backtest_runs` — run metadata (timestamp, n_tickers, horizons, config)
- `backtest_predictions` — per-ticker/horizon/date predictions (y_true, y_pred, vrp_wedge, skew)
- `backtest_metrics` — summary stats (RMSE, MZ_alpha/beta/R2, QLIKE, event_capture)

Write after each ticker completes (not all at end). Use psycopg2 with upsert (ON CONFLICT DO UPDATE).

### 4. DEFERRED — v0.3+
- SVI interpolated IV surface (replace raw iv_atm_30d with smile-interpolated)
- Markov regime switching overlay
- Dynamic sector betas
- IC / quintile spread calculation
- Point-in-time dynamic universe (volume threshold)

---

## Hardware Note

Leo upgrading to **Ryzen 9 5950X** (16c/32t, Zen 3). Estimated full 30-ticker runtime: ~2.5hrs vs ~14hrs on current i7-7700.

When installed: add to config.py xgb_params for GTX 1070 acceleration (~15% additional gain):
```python
"device": "cuda",
"tree_method": "hist",
```

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
| 2026-04-06 (Leo) | New PC online (5950X + Arctic Liquid Freezer III 280). RF restored to n_jobs=-1. Speed benchmarking: true baseline with 2011 data = 31 min/ticker. n_alphas deprecated in sklearn 1.7 — fixed to alphas=20 (correct param). CPU temps settled to 67C after first heat cycle. **CAT completed (first clean alphas=20 + parallel pipeline benchmark):** H=21 alpha=0.023 beta=0.941 R²=0.393 QLIKE=0.0255; H=63 alpha=0.015 beta=1.008 R²=0.302 QLIKE=0.0263 — best-calibrated ticker yet (H=63 beta essentially 1.0). LassoCV only 7% of runtime after Caleb parallel impl; alphas=20 optimization largely irrelevant now. Speed with parallel pipeline: ~73min wall/3 tickers vs old ~60 min/ticker on i7. Remaining v4 tickers: WMT, MS, LIN, MRK, CAT(H126), NEE(H63/H126). |
| 2026-04-06 (Caleb, claude-opus-4-6) | **Major pipeline overhaul — parallelism, GPU, output standardization.** New dev (Caleb Solomon). Changes: (1) LassoCV n_jobs=-1; (2) Ticker-level multiprocessing via ProcessPoolExecutor with parallel_tickers=4; (3) XGBoost CUDA device with auto-fallback to CPU; (4) predict_curve_batch() vectorized; (5) New output.py: {TICKER}_Payload.json, market_overview.json, metrics_summary.json; (6) .env relative path fix; (7) .gitignore cleanup. 3-ticker validation (JPM/AAPL/XOM): H=21 avg beta=1.054, R²=0.338. Timing: ~73min wall for 3 tickers parallel (XGB 56%, RF 37%, LassoCV 7%). |
| 2026-04-07/08 (Leo, claude-sonnet-4-6) | **WRDS universe discovery + 48-ticker run + 30-ticker overnight = 94-ticker full corpus.** (1) Resolved claude_context.md merge conflict keeping both entries. (2) Completed 48-ticker batch run overnight; ~14.7 min effective throughput/ticker via parallel_tickers=4. (3) Discovered WRDS universe: 454 qualified tickers (CRSP shrcd 10/11, avg_dv>=100M, OptionMetrics vsurfd 200+ days), 89 in local DB, 119 new pullable. Saved wrds_qualified_universe.csv. (4) Built 64-ticker stat sheet; generated 3 rounds of beta visualizations (beta_over_time.png, beta_events.png, beta_signal_detection.png). (5) **Key finding**: exp-weighted MZ diagnostic (lambda=0.003, half-life ~1yr) shows 100%/99%/99% calibration at H=21/63/126 in current regime — full-history H=126 beta drift of 1.19 is COVID/2022-era artifact in training tail, not a structural flaw. (6) **Beta-delta signal**: market-avg beta-delta z-score fires before 56% of 3-sigma SPY events (30-day lead window); ROC curve clearly above diagonal. (7) Tested exp sample weighting (lambda=0.0006): JPM H=126 beta worsened. Reverted to lambda=0.0. Infrastructure kept in ModelConfig + models.py but disabled. (8) Completed 30-ticker overnight run (ADBE/AEP/AMAT/AMD/AMGN/AMT/BLK/CCI/CL/CRM/CSCO/CVS/D/DOW/DUK/EQIX/F/GM/LOW/MO/MU/NOC/ORCL/SO/SPG/TGT/TMO/UPS/USB/VZ). (9) Final full corpus: 94 tickers, 282 prediction files. Full stat sheet: H=21 mean beta=0.995 R²=0.349 (78% calibrated); EW-beta 100% calibrated across all horizons. Beta-delta signal updated to 90-ticker basis: 56% sensitivity unchanged. |
