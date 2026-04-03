# Tarasque / Volarbear — Claude Working Context
_Last updated: 2026-04-02 | Model: claude-sonnet-4-6_

---

## Project Summary

Quantitative volatility forecasting engine. Core objective: isolate the **Volatility Risk Premium (VRP)** wedge (Interpolated Market IV minus Model RV) as a fear/uncertainty signal, then use it as a dynamic defensive equity overlay. The pipeline predicts **Garman-Klass Realized Volatility** using an XGBoost/RF/LassoCV ensemble stabilized by GARCH(1,1).

**Owner:** Economics & statistics student (econ/stats background, CS is not primary — hand-hold on implementation details).  
**Timeline:** ~1.5 months until WRDS access expires (graduating). Need to lock in historical data before then.  
**Stack:** Python model pipeline → Supabase (PostgreSQL) → FastAPI/Uvicorn backend → React frontend (SWEs handling).

---

## Repository Layout

```
volarbmodel/
  model/
    pipeline/               ← Main model package (this is what we work on)
      __init__.py
      __main__.py
      config.py             ← DataConfig, ModelConfig, BacktestConfig dataclasses
      data_loader.py        ← WRDS + Alpaca/yfinance data acquisition
      features.py           ← ~34-feature FeatureBuilder
      models.py             ← GarchForecaster + EnsembleVolModel
      backtest.py           ← Walk-forward BacktestEngine
      run.py                ← CLI orchestrator (backtest / refresh_data / live)
      utils.py              ← FOMC calendar, Black-Scholes, Monte Carlo cone
      requirements.txt      ← Model pipeline dependencies
    volarbmodel_backtest.py ← OLD Alpaca-based script (reference only, abandoned)
    strat_outline_mar25.md  ← Strategy specification
    claude_context.md       ← THIS FILE
  supabase/
    config.toml             ← Local Supabase dev config (port 54321/54322/54323)
  backend/
    requirements.txt        ← FastAPI + Uvicorn (psycopg2 commented out — TODO)
```

**Data cache:** `C:/Users/Owner/Tarasque_local/Tarasque_DB/` (Parquet, partitioned by ticker)  
**Python venv:** `C:/Users/Owner/Tarasque_local/venv/`  
**Working dir for runs:** `C:/Users/Owner/Tarasque_local/volarbmodel/`

---

## Environment & Credentials

| Item | Detail |
|---|---|
| WRDS credentials | Saved in `%APPDATA%\postgresql\pgpass.conf` (host: wrds-pgdata.wharton.upenn.edu:9737, user: ldip9) |
| Alpaca keys | Paper trading account — `model/.env` |
| `.env` location | `C:/Users/Owner/Tarasque_local/volarbmodel/model/.env` |
| `TARASQUE_BASE_DIR` | Not yet set in `.env` — must pass `--base-dir C:/Users/Owner/Tarasque_local/Tarasque_DB` on every run |

**TODO:** Add `TARASQUE_BASE_DIR=C:/Users/Owner/Tarasque_local/Tarasque_DB` to `model/.env` to avoid passing `--base-dir` every time.

**Run command:**
```bash
cd C:/Users/Owner/Tarasque_local/volarbmodel
python -m model.pipeline --mode backtest --base-dir "C:/Users/Owner/Tarasque_local/Tarasque_DB"
```

---

## WRDS Data Access

| Source | Table | Status | Notes |
|---|---|---|---|
| CRSP | `crsp.dsf` + `crsp.msenames` | **OK** | 29,937 rows, 2021–2024 (2025+ has ~1yr lag for students) |
| CRSP index | `crsp.dsi` | **OK** | 1,005 rows |
| OptionMetrics | `optionm.vsurfd` (unified view) | **MISSING** | Does not exist |
| OptionMetrics | `optionm.vsurfd{YEAR}` | **OK** | Year-partitioned tables work (vsurfd2021–vsurfd2025) — 277,420 rows cached |
| Compustat GICS | `comp.funda.gsector` | **MISSING** | Column not in comp.funda for this subscription |
| Compustat GICS | `comp.company.gsector` joined to `comp.funda` | **OK** | Fixed — 10 rows cached |
| Compustat earnings | `comp.fundq` | **OK** | 210 rows |
| Compustat dividends | `comp.funda` (dvpsx_f) | **OK** | 39 rows |
| FRED macro | `fred.data` | **NOT AVAILABLE** | Not in student subscription — fast-fail added, macro features absent this run |

---

## Feature Set (34 active after FRED drop)

Features that will be **absent/NaN** (FRED not available):
- `macro_yield_curve_slope`, `macro_hy_spread`, `macro_hy_spread_chg_5d`, `macro_breakeven_5y`, `macro_dollar_ret`

These 5 are auto-dropped at runtime by the all-NaN column filter in `backtest.py`. The remaining ~29 features cover:
- Multi-scale GK RV (5d, 10d, 21d, 63d), EWMA vol
- Returns, RSI, ATR, MACD histogram, price regime (drawdown)
- Factor ETF returns (SPY, VIXY, HYG, USO, TLT, UUP)
- Vol dynamics (trend, velocity, vol-of-vol)
- Event gravity (FOMC, earnings, dividends)
- Options surface: iv_atm_30d, put_call_skew_30d, term_structure_slope, vrp_wedge, iv_atm_z_score
- Factor decomp: beta_spy, res_vol, res_vol_vel
- Sector coupling: corr_sector_21d, corr_sector_252d, sector_wedge

---

## Bugs Fixed This Session

| # | File | Bug | Fix |
|---|---|---|---|
| 1 | `utils.py` | FOMC dates only started 2025-12-17 — `event_fed_gravity` was constant for all 2021–2025 data | Added full historical FOMC dates 2021–2026 |
| 2 | `data_loader.py` | WRDS `wrds.Connection()` with empty username/password always prompted interactively | Read credentials from pgpass.conf and pass explicitly as `wrds_username`/`wrds_password` |
| 3 | `data_loader.py` | Unicode `→` in print statement crashed on Windows cp1252 terminal | Replaced with `->` |
| 4 | `data_loader.py` | `optionm.vsurfd` unified view doesn't exist in this subscription | Rewrote `fetch_vsurfd` to loop over year tables (`vsurfd2021`...`vsurfd2025`) |
| 5 | `data_loader.py` | `comp.funda.gsector` column doesn't exist | Rewrote `fetch_compustat_meta` to join `comp.company` (has gsector) with `comp.funda` (has tic) |
| 6 | `data_loader.py` | `fetch_compustat_meta` was unprotected — crash killed pipeline | Added try/except, also added try/except wrapper in `fetch_dataset` |
| 7 | `data_loader.py` | `fred.data` not available — 630 error messages per run | Added fast-fail check before the chunked loop |
| 8 | `features.py` | CRSP `msenames` join produces duplicate `(date, ticker)` rows → `pivot()` crash | Added `drop_duplicates(subset=["date","ticker"], keep="last")` before pivot |
| 9 | `features.py` | `dropna` only checked `y_21` — `y_63` and `y_126` still had NaN tail rows | Changed to `dropna(subset=all target cols)` |
| 10 | `backtest.py` | `y_tr_dict = {h: train[target_col]}` only passed current horizon — `train_wfa` expected all 3 | Fixed to pass all horizons: `{hh: train[f"y_{hh}"] for hh in self.mc.horizons}` |
| 11 | `backtest.py` | FRED macro features were all-NaN → LassoCV crash | Pre-filter all-NaN columns before walk-forward loop; ffill/bfill/median imputation inside each window |
| 12 | `models.py` | NaN targets in fold test set → `mean_squared_error` crash | Added `y_tr.notna()` / `y_te.notna()` mask before fitting each fold |
| 13 | `models.py` | H=126 RMSE overflow — `np.exp()` of unclamped log-vol predictions → 1e18+ RMSE | Clip log predictions to `[-5, 5]` before `np.exp()` in `train_wfa` fold loop and `predict_curve` (range = vol 0.7%–148% annualised) |
| 14 | `data_loader.py` | FRED macro unavailable in WRDS student subscription → 5 features absent | Added `fetch_fred_yfinance()`: recovers `treasury_10y`/`treasury_3mo` via yfinance (`^TNX`,`^IRX`); recovers `hy_spread`/`breakeven_5y`/`dollar_index` via `fredapi` when `FRED_API_KEY` is set in `.env` |
| 15 | `features.py` | `macro_yield_curve_slope` required `treasury_2y` which WRDS FRED lacks | Falls back to `treasury_10y - treasury_3mo` (10y-3mo is actually the preferred recession-indicator spread) |

---

## Known Issues / Next Actions

### CRITICAL — Fix Before Next Run
- [x] **H=126 RMSE explosion** — FIXED 2026-04-02: `np.clip(log_pred, -5, 5)` before `np.exp()` in `models.py`

### HIGH — Before Research Analysis
- [ ] **TARASQUE_BASE_DIR in .env**: Add to `model/.env` so `--base-dir` flag isn't needed on every run
- [x] **FRED macro via yfinance fallback** — FIXED 2026-04-02: `fetch_fred_yfinance()` added; recovers yield curve slope immediately; HY spread / breakeven need free `FRED_API_KEY` (see below)
- [ ] **FRED_API_KEY**: Get free key at https://fred.stlouisfed.org/docs/api/api_key.html, add to `model/.env`. Then `pip install fredapi`. Recovers 3 more features: `macro_hy_spread`, `macro_breakeven_5y`, `macro_dollar_ret`.
- [ ] **Re-run backtest** now that clipping fix and FRED fallback are in place. Cache is warm — will be fast. Force-refresh fred data: the previous cache is empty, so it will auto-pull. Compare H=63/H=126 RMSE to v0.1 results.
- [ ] **Verify backtest_results.csv** after clean run: read and review results for metric improvements vs v0.1.

### MEDIUM — v0.1 Polish
- [ ] **Supabase write layer**: Add `pipeline/db.py` with psycopg2 connection + upsert functions. Tables needed: `backtest_runs`, `backtest_predictions`, `backtest_metrics`. Write after each ticker completes. SWEs are blocked without this.
- [ ] **Exponential sample weighting stub**: Add `sample_weight` parameter to `train_wfa` (not yet wired — defer to v0.2 but add the parameter hook now)
- [ ] **3σ event capture**: Currently 2σ — confirmed to keep at 2σ (3σ events too rare for 4yr dataset to be statistically meaningful)

### DEFERRED — v0.2+
- [ ] SVI interpolated IV surface (replace raw grid-point `iv_atm_30d`)
- [ ] Markov regime switching
- [ ] Dynamic sector betas (beyond SPY-only)
- [ ] Structural market break logging
- [ ] IC / quintile spread calculation
- [ ] Point-in-time dynamic universe (volume threshold crossing)

---

## Progress

```
[##########] Data pipeline (WRDS pull, Parquet cache)     100%  COMPLETE
[#######---] Feature engineering (34 features, FRED=0)    70%   FRED missing; all others working
[########--] Walk-forward backtest engine                  80%   Running; H=126 overflow bug open
[----------] Supabase write layer                          0%    Not started
[----------] FRED yfinance fallback                        0%    Not started
[----------] Backend API endpoints                         0%    SWEs handling
[----------] Frontend web app                              0%    SWEs handling
```

---

## First Backtest Results — v0.1 (2026-04-02)

Run ID: `bec8z4ih3` | Status: **COMPLETED** ✓  
Results CSV: `model/pipeline/results/backtest_results.csv`  
Data coverage: 2021–2024 (CRSP lag), 34 features (5 FRED macro absent)  
Walk-forward steps: 8–12 per ticker per horizon | min_train: 680 rows

### Full Results Table

| Ticker | H | RMSE | MZ_beta | MZ_R2 | QLIKE | Event Capture | N |
|---|---|---|---|---|---|---|---|
| AAPL | 21 | **0.0186** | **1.052** | **0.574** | 0.0061 | 0.813 | 180 |
| AAPL | 63 | 0.0326 | 0.514 | 0.124 | 0.0150 | 0.750 | 180 |
| AAPL | 126 | 0.0305 | -0.033 | 0.001 | 0.0123 | — | 180 |
| MSFT | 21 | **0.0133** | 0.532 | **0.576** | 0.0030 | **1.000** | 180 |
| MSFT | 63 | 0.0179 | -0.033 | 0.003 | 0.0050 | 0.667 | 180 |
| MSFT | 126 | 0.0221 | -0.112 | 0.065 | 0.0066 | — | 180 |
| AMZN | 21 | 0.0186 | 0.616 | 0.486 | 0.0036 | **1.000** | 240 |
| AMZN | 63 | 0.0305 | 0.041 | 0.003 | 0.0083 | 0.545 | 240 |
| AMZN | 126 | 0.0303 | 0.042 | 0.005 | 0.0074 | — | 240 |
| META | 21 | 0.0348 | 0.688 | 0.574 | 0.0068 | — | 57 |
| META | 63 | 0.0251 | -0.458 | 0.434 | 0.0039 | — | 57 |
| META | 126 | 0.0120 | 0.515 | 0.367 | 0.0010 | **1.000** | 57 |
| GOOGL | 21 | 0.0169 | 0.351 | 0.178 | 0.0033 | — | 180 |
| GOOGL | 63 | 0.0173 | -0.271 | 0.132 | 0.0035 | 0.250 | 180 |
| GOOGL | 126 | 0.0182 | -0.100 | 0.046 | 0.0033 | **1.000** | 180 |
| MS | 21 | 0.0288 | 0.446 | 0.209 | 0.0094 | **1.000** | 180 |
| MS | 63 | 0.0279 | -0.392 | 0.374 | 0.0080 | **1.000** | 180 |
| MS | 126 | 0.0242 | -0.038 | 0.026 | 0.0056 | — | 180 |
| XOM | 21 | **0.0146** | **0.797** | 0.422 | 0.0035 | **1.000** | 180 |
| XOM | 63 | 0.0123 | 0.194 | 0.060 | 0.0023 | **1.000** | 180 |
| XOM | 126 | 0.0244 | -0.039 | 0.024 | 0.0067 | — | 180 |
| CVX | 21 | **0.0118** | 0.489 | 0.421 | 0.0021 | — | 180 |
| CVX | 63 | 0.0265 | -0.026 | 0.006 | 0.0089 | 0.294 | 180 |
| CVX | 126 | 0.0349 | 0.051 | 0.101 | 0.0135 | — | 180 |
| JNJ | 21 | **0.0090** | 0.535 | **0.511** | 0.0019 | **1.000** | 180 |
| JNJ | 63 | 0.0114 | 0.448 | 0.285 | 0.0029 | — | 180 |
| JNJ | 126 | 0.0111 | 0.306 | 0.220 | 0.0027 | — | 180 |
| CAT | 21 | 0.0134 | **0.920** | 0.418 | 0.0022 | **1.000** | 240 |
| CAT | 63 | 0.0225 | -0.047 | 0.003 | 0.0051 | 0.087 | 240 |
| CAT | 126 | 0.0221 | -0.235 | 0.058 | 0.0047 | — | 240 |

### Interpretation

**H=21 (21-day) — Strongest results, model is valid at this horizon:**
- MZ_beta: AAPL 1.05 (near-ideal), CAT 0.92, XOM 0.80 — good calibration
- MZ_R2: AAPL/MSFT/META all at 0.574 — meaningful explanatory power
- QLIKE: All < 0.010 — low asymmetric loss
- Event capture: 7/10 tickers at 1.0 (perfect) — model spikes before 2σ vol events

**H=63 (63-day) — Mixed, model loses edge:**
- Several negative MZ_beta (META -0.46, MS -0.39, GOOGL -0.27) — model inverting at this horizon on some tickers
- R2 collapses on most tickers — 63-day forecast needs more data and/or regime features
- XOM/JNJ hold up best (positive beta, reasonable R2)

**H=126 (126-day) — Uninformative:**
- With only 4 years of data and min_train=680 rows, only 8 walk-forward steps exist — statistically meaningless
- Expected — the 126-day forecaster will improve dramatically with a longer historical window
- MZ_R2 near 0 for most — model cannot reliably forecast 6-month vol on 4 years of data

**META note:** Only 57 predictions (vs 180–240 for others) — fewer walk-forward steps, likely due to data availability gaps for META in the 2021 CRSP data.

**Overflow note:** H=126 intermediate training RMSE had numerical explosions (1e18+) in some windows (model predicted extreme log-vol values → `np.exp()` overflow). The floor weighting (0.09 minimum) contained the damage to final predictions, but this should be fixed by clipping predictions before exponentiation.

---

## Known Issues / Next Actions

### CRITICAL — Fix Before Next Run
- [ ] **H=126 RMSE explosion in training**: Clip log-vol predictions to `[-5, 5]` before `np.exp()` in `models.py` `train_wfa` (lines ~154-156) and `predict_curve`. Range [-5,5] = vol 0.7%–148% annualized — no equity ever leaves this band. The floor weighting (0.09) suppressed this in final predictions but intermediate RMSE is still garbage.

### HIGH — Before Research Analysis
- [ ] **FRED macro via yfinance**: Add yfinance-based FRED fallback in `fetch_fred` or a separate `fetch_fred_yfinance` method for when `fred.data` is absent. Need: `^TNX` (10y), `^IRX` (3m/2y proxy), `BAMLH0A0HYM2` (HY spread). This recovers 5 features (yield curve slope, HY spread, HY momentum, breakeven, dollar). Already partially done in `AlpacaContinuation.fetch_recent_fred`.
- [ ] **TARASQUE_BASE_DIR in .env**: Add `TARASQUE_BASE_DIR=C:/Users/Owner/Tarasque_local/Tarasque_DB` to `model/.env`.
- [ ] **Residual analysis**: Identify which specific dates and tickers drove the worst predictions (the automated residual isolation requested in strat_outline_mar25.md). Focus on H=63 negative-beta tickers first.

### MEDIUM — v0.1 Polish
- [ ] **Supabase write layer** (`pipeline/db.py`): psycopg2 connection + upsert into `backtest_predictions`, `backtest_metrics`, `backtest_runs`. SWEs are blocked without this.
- [ ] **Exponential sample weighting stub**: Add `sample_weight` parameter to `train_wfa` — not yet wired, defer to v0.2 but add the hook now.

### DEFERRED — v0.2+
- SVI interpolated IV (replace raw `iv_atm_30d`)
- Markov regime switching
- Dynamic sector betas
- IC / quintile spread
- Point-in-time dynamic universe

---

## Progress

```
[##########] Data pipeline (WRDS pull, Parquet cache)       100%  COMPLETE
[########--] Feature engineering (34 features, FRED=0/5)    80%   FRED pending yfinance fallback
[#########-] Walk-forward backtest engine                    90%   Complete; H=126 clip fix pending
[----------] Supabase write layer                            0%    Not started — SWEs blocked
[----------] FRED yfinance fallback                          0%    Not started
[----------] Backend API endpoints                           0%    SWEs handling
[----------] Frontend web app                                0%    SWEs handling
```

---

## Session Log

| Date | Work Done |
|---|---|
| 2026-04-02 | Full schema review; pipeline assessment vs spec; installed all deps; fixed 12 bugs (see table above); first successful WRDS data pull (29,937 OHLCV rows, 277,420 vsurfd rows, GICS, earnings, dividends); **first complete backtest run — all 10 tickers, 3 horizons, results saved to CSV**; H=21 results valid (MZ_beta near 1, R2 0.4–0.58 on best tickers); H=126 overflow bug identified |
