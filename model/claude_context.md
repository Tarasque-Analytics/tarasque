# Tarasque / Volarbear — Claude Working Context
_Last updated: 2026-04-03 | Model: claude-sonnet-4-6_

---

## INSTRUCTIONS FOR FUTURE CLAUDE INSTANCES

**Read this file first, every session.** It is your primary context. Update it at the end of every session or after any significant change. Follow this protocol:

1. **Start of session**: Read this file. Verify any file paths or function names mentioned before acting on them (use Glob/Grep — memory can be stale).
2. **During session**: Track progress on the checklist below. Mark items complete as you go.
3. **End of session** (or when context is getting long): Rewrite this file with updated progress, new bugs found/fixed, new findings, and updated next actions. Keep the format consistent.
4. **What to record**: Work done, bugs fixed, analysis findings, decisions made, and why. The "why" is critical — future instances won't remember the reasoning.
5. **What NOT to record**: Code patterns derivable from reading the files, git history, ephemeral task details that won't matter next session.

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
      config.py             ← DataConfig, ModelConfig, BacktestConfig dataclasses
      data_loader.py        ← WRDS + Alpaca/yfinance acquisition
      features.py           ← ~37-feature FeatureBuilder (3 new features planned)
      models.py             ← GarchForecaster + EnsembleVolModel
      backtest.py           ← Walk-forward BacktestEngine
      run.py                ← CLI orchestrator
      utils.py              ← FOMC calendar, Black-Scholes, Monte Carlo cone
      requirements.txt
      analysis/
        __init__.py
        vrp_analysis.py     ← VRP wedge bilateral uncertainty analysis
        residual_analysis.py← Systematic residual diagnostic tool
      results/              ← Backtest CSVs (predictions_TICKER_Hh.csv, backtest_results.csv)
    claude_context.md       ← THIS FILE — always update this
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

**Run backtest (no flags needed):**
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
| Compustat GICS | `comp.company` JOIN `comp.funda` | OK — gsector not in comp.funda directly |
| Compustat earnings | `comp.fundq` | OK |
| Compustat dividends | `comp.funda` (dvpsx_f) | OK |
| FRED direct | `fred.data` | NOT AVAILABLE in student subscription |
| FRED via yfinance | `^TNX`, `^IRX` + fredapi | OK — all 5 macro series recovered |

---

## Parquet Cache State (as of 2026-04-03)

| Dataset | Rows | Date Range |
|---|---|---|
| ohlcv | 164,876 | 2014-01-02 – 2026-04-02 |
| vsurfd | 1,808,080 | 2014-01-02 – 2025-08-29 |
| fred | 3,240 | 2014-01-01 – 2026-04-02 |
| crsp_index | 2,768 | 2014-01-01 – 2024-12-31 |
| earnings | 1,470 | |
| dividends | 289 | |
| compustat_meta | 30 | |

---

## Ticker Universe (config.py)

**CURRENT STATE: Mini-run (3 tickers) — AAPL, JNJ, XOM**
The tickers list is currently set to 3 for validation. Before the full prod run, restore all 30.

**Full 30-ticker list (restore when ready):**
Tech: AAPL, MSFT, NVDA, AMD, ORCL | Comm: GOOGL, META, NFLX | ConsDisc: AMZN, TSLA, HD, MCD | ConsStap: PG, KO | Fin: MS, JPM, GS, BAC | Health: JNJ, LLY, ABBV | Indust: CAT, HON, BA | Energy: XOM, CVX, COP | Materials: LIN | Utilities: NEE | RealEstate: AMT

**To restore:** Edit config.py, comment out the mini-run block, uncomment the full 30-ticker list.

---

## Feature Set (current: ~34 active, 3 planned additions)

**Active features:**
- GK RV multi-scale: rv_5d, rv_10d, rv_21d, rv_63d, rv_126d (added for H=126 target)
- EWMA vol, returns, RSI, ATR, MACD histogram
- Factor ETF returns: SPY, VIXY, HYG, USO, TLT, UUP
- Vol dynamics: trend, velocity, vol-of-vol
- Event gravity: FOMC, earnings, dividends
- Options: iv_atm_30d, put_call_skew_30d, term_structure_slope, vrp_wedge, iv_atm_z_score
- Factor decomp: beta_spy, res_vol, res_vol_vel
- Price regime (252d drawdown)
- Sector coupling: corr_sector_21d, corr_sector_252d, sector_wedge
- Macro: yield_curve_slope, hy_spread, hy_spread_chg_5d, breakeven_5y, dollar_ret

**Planned additions (from residual/VRP analysis findings):**
- `vol_regime_zscore` — VIX level or SPY RV rolling z-score. Addresses the 0.96 lag-1 ACF (model stays wrong for months once in a vol regime). This is the highest-priority addition.
- `abs_put_call_skew` — |put_call_skew_30d|. VRP analysis Section F showed a U-shape: both tails of skew predict elevated RV. Bilateral skew signal independent of direction.
- `rv_regime_ar1` — lagged signed residual or AR(1) vol shock. Directly addresses the persistent autocorrelation in residuals (ACF lag-1=0.96 means model is making the same error for weeks).

---

## All Bugs Fixed (cumulative)

| # | Session | File | Bug | Fix |
|---|---|---|---|---|
| 1 | Apr 2 | utils.py | FOMC dates only from 2025 | Added full 2014–2026 FOMC history |
| 2 | Apr 2 | data_loader.py | WRDS connection always prompted interactively | Read from pgpass.conf, fall back to env vars |
| 3 | Apr 2 | data_loader.py | Unicode `→` crashed Windows cp1252 terminal | Replaced with `->` |
| 4 | Apr 2 | data_loader.py | `optionm.vsurfd` unified view missing | Loop over year tables vsurfd2014–vsurfd2025 |
| 5 | Apr 2 | data_loader.py | `comp.funda.gsector` missing | JOIN comp.company (has gsector) to comp.funda |
| 6 | Apr 2 | data_loader.py | fetch_compustat_meta crash killed pipeline | Added try/except wrapper |
| 7 | Apr 2 | data_loader.py | fred.data not available — 630 errors per run | Fast-fail check before chunked loop |
| 8 | Apr 2 | features.py | CRSP msenames join → duplicate rows → pivot() crash | drop_duplicates before pivot |
| 9 | Apr 2 | features.py | dropna only checked y_21 — y_63/y_126 had NaN tail | dropna(subset=all target cols) |
| 10 | Apr 2 | backtest.py | y_tr_dict only passed current horizon | Pass all horizons: {hh: train[f"y_{hh}"] ...} |
| 11 | Apr 2 | backtest.py | FRED all-NaN → LassoCV crash | Pre-filter all-NaN columns; impute inside window |
| 12 | Apr 2 | models.py | NaN targets → mean_squared_error crash | notna() mask before fitting |
| 13 | Apr 2 | models.py | H=126 RMSE overflow from unclamped np.exp() | Clip log predictions to [-5,5] |
| 14 | Apr 2 | data_loader.py | FRED not in WRDS | fetch_fred_yfinance(): ^TNX/^IRX + fredapi |
| 15 | Apr 2 | features.py | macro_yield_curve_slope required treasury_2y | Fall back to 10y-3mo spread |
| 16 | Apr 3 | data_loader.py | .dt.date → Python date objects → ValueError after Parquet round-trip | .dt.normalize() keeps datetime64 |
| 17 | Apr 3 | data_loader.py | Same crash on fred date parsing | .astype(str).str[:10] before pd.to_datetime() |
| 18 | Apr 3 | data_loader.py | ParquetStore.save() appends partition files → data accumulation | shutil.rmtree() before partitioned write |
| 19 | Apr 3 | features.py | Target used rolling(h).mean().shift(-h) → 20/21 day overlap with primary feature → inflated R² | Changed to rv_{h}d.shift(-h) — zero sample overlap |
| 20 | Apr 3 | features.py | iv_atm_30d ffill() carried stale IV values forever after vsurfd ends | ffill(limit=5) on all IV series |
| 21 | Apr 3 | analysis/*.py | Unicode chars (≥ → ± Δ) crashed cp1252 terminal | Replaced all with ASCII equivalents |
| 22 | Apr 3 | results/ | predictions_XOM_H21 copy.csv broke loader's horizon int parse | Deleted the file |
| 23 | Apr 3 | config.py | rv_windows missing 126 — no rv_126d column for H=126 target | Added 126 to rv_windows list |

---

## Analysis Results — v0.2 Mini-Run (AAPL, JNJ, XOM — 2017–2025)

### Backtest Metrics (post-lookahead fix — honest numbers)

| Ticker | H | RMSE | MZ_beta | MZ_R2 | QLIKE |
|---|---|---|---|---|---|
| AAPL | 21 | 0.0666 | 1.196 | 0.389 | 0.035 |
| AAPL | 63 | 0.0554 | 1.483 | 0.456 | 0.026 |
| AAPL | 126 | 0.0429 | 1.241 | 0.491 | 0.017 |
| JNJ | 21 | 0.0532 | 1.080 | 0.202 | 0.037 |
| JNJ | 63 | 0.0442 | 1.008 | 0.213 | 0.028 |
| JNJ | 126 | 0.0342 | 1.075 | 0.297 | 0.018 |
| XOM | 21 | 0.0742 | 0.930 | 0.539 | 0.038 |
| XOM | 63 | 0.0804 | 0.987 | 0.367 | 0.047 |
| XOM | 126 | 0.0673 | 0.971 | 0.445 | 0.036 |

Note: RMSE jumped from v0.1 ~0.02 → ~0.05–0.08 after the target fix. The old numbers were artificially inflated by the rolling overlap. These are real.

XOM is best-calibrated — MZ_beta hugging 1.0 at all three horizons. AAPL MZ_beta >1.2 means it systematically under-estimates vol.

### VRP Analysis Findings (vrp_analysis.py)

- **|wedge| is a real predictor**: OLS R²=0.147, t=50.87, p≈0. Q1 mean RV=0.220 vs Q5=0.342 (+55% lift). Monotonically increasing.
- **Bilateral hypothesis confirmed**: |wedge| R²=0.147 vs signed wedge R²=0.042. +0.105 R² lift proves size matters more than direction.
- **XOM strongest** (R²=0.275, slope=1.32) — energy vol almost entirely uncertainty-driven.
- **AMD and NVDA negative slopes** — classic negative VRP: options *overprice* vol for high-beta growth stocks, so high IV doesn't predict high RV.
- **Put-call skew U-shaped**: Q1 (most negative skew) RV=0.296, Q3 (neutral) RV=0.207, Q5 (most positive) RV=0.336. Both tails signal elevated vol — justifies `abs(put_call_skew)` as a feature.

### Residual Analysis Findings (residual_analysis.py)

- **Systematic failure regimes identified**:
  - Feb–Mar 2020 (COVID): All 7 tickers miss simultaneously. Mean |resid|=0.137 in 2020Q1 vs normal ~0.020.
  - Jan 2018 + Oct–Dec 2018: VIX spike / Q4 selloff. 4-ticker clusters.
  - Mar–Apr 2025: Tariff uncertainty. 6-ticker clusters.
- **ACF lag-1 = 0.96 (all lags significant to lag 10)**: Model makes the same directional error for weeks/months. Classic missing regime indicator. This is the most actionable finding.
- **Sector effect is significant** (Kruskal-Wallis p=0.000): Energy worst (0.039), Tech mid (0.033), Health best (0.027).
- **All tickers show under-prediction bias** (mean_signed > 0 for all). Model systematically predicts too-low vol.
- **2025Q1 error = 0.065** (2.5x normal) — tariff regime not yet seen in training data.

---

## Progress Checklist

```
[##########] Data pipeline (WRDS pull, Parquet cache)           100%  COMPLETE
[##########] Feature engineering (34 features, all FRED active) 100%  COMPLETE (3 new features planned)
[##########] Walk-forward backtest engine                        100%  COMPLETE
[##########] Lookahead bias audit & fix                          100%  FIXED — target now uses rv_{h}d.shift(-h)
[##########] IV staleness fix                                    100%  FIXED — ffill(limit=5)
[##########] VRP bilateral uncertainty analysis                  100%  COMPLETE — bilateral confirmed, R²=0.147
[##########] Residual systematic analysis                        100%  COMPLETE — COVID/2018/2025 regimes identified
[####------] Feature v2 (3 new features from analysis)          40%   Identified, not yet implemented
[----------] v0.2 full 30-ticker prod backtest                    0%   Waiting on new CPU (5900X or 5950X)
[----------] Supabase write layer (db.py)                        0%   SWEs blocked — highest external dependency
[----------] Backend API endpoints                               0%   SWEs handling
[----------] Frontend web app                                    0%   SWEs handling
```

---

## Next Actions (in priority order)

### 1. IMPLEMENT — 3 New Features (features.py)
From the residual and VRP analysis. These should be added before the full 30-ticker run.

**a) `vol_regime_zscore`** — addresses ACF=0.96 (model stays wrong for months)
```python
# In _add_vol_dynamics or new _add_regime_features method
# SPY RV rolling z-score relative to its trailing 252d distribution
spy_rv = df["rv_21d"]  # or use SPY-specific RV if available
df["vol_regime_zscore"] = (spy_rv - spy_rv.rolling(252).mean()) / (spy_rv.rolling(252).std() + 1e-9)
```

**b) `abs_put_call_skew`** — addresses U-shaped skew signal
```python
# In _add_options_features, after put_call_skew_30d is computed
df["abs_put_call_skew"] = df["put_call_skew_30d"].abs()
```
Also ensure `abs_put_call_skew` prefix `abs_` gets picked up by `get_predictor_columns` — add `"abs_"` to `include_prefixes`.

**c) `vol_shock_lag1`** — AR(1) feature to capture residual persistence
```python
# In _add_vol_dynamics
# 5-day absolute change in rv_21d (already have vol_vel — this is different)
df["vol_shock_lag1"] = (df["rv_21d"] - df["rv_21d"].shift(21)).abs()
```

### 2. RESTORE — Full 30-ticker list in config.py
Comment out mini-run block, uncomment full universe. Run on new CPU.

### 3. BUILD — Supabase write layer (pipeline/db.py)
SWEs are blocked. Tables needed: `backtest_runs`, `backtest_predictions`, `backtest_metrics`.
Write after each ticker completes (not all at end).

### 4. DEFERRED — v0.2+
- SVI interpolated IV surface
- Markov regime switching
- Dynamic sector betas
- IC / quintile spread
- Point-in-time dynamic universe

---

## Hardware Note

Leo is upgrading CPU. Options: 5900X (12c/24t, ~3.5hr runtime) or 5950X (16c/32t, ~2.5hr runtime). Either is a ~4x improvement over current i7-7700. GTX 1070 can accelerate XGBoost via `device: 'cuda'` for a marginal additional gain (~15-20% on total runtime). Add to config.py xgb_params when upgrade is complete.

---

## Session Log

| Date | Work Done |
|---|---|
| 2026-04-02 | Fixed 15 bugs. First WRDS pull (10 tickers, 2021–2024). First backtest run. H=21 valid, H=126 overflow identified. FRED yfinance fallback added. |
| 2026-04-03 (session 1) | New PC setup. Expanded to 30 tickers + 2014 start. Fixed 3 data pipeline bugs. Cleaned doubled Parquet cache. Created analysis/vrp_analysis.py and analysis/residual_analysis.py. |
| 2026-04-03 (session 2) | Identified and fixed lookahead bias in target construction (rolling overlap). Fixed IV ffill staleness (limit=5). Fixed Unicode crash in analysis scripts. Ran mini backtest (AAPL, JNJ, XOM). Ran both analysis scripts. VRP bilateral hypothesis confirmed (R²=0.147). Residual ACF=0.96 identified — missing regime feature. Three new features designed. |
