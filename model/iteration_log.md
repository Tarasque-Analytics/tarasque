# Tarasque — Model Iteration Log
_Tracks every model version, what changed, what improved, and what failed._
_Last updated: 2026-04-28_

---

## Summary Arc

```
v1  →  v2  →  v3  →  v4  →  v4 full corpus  →  v5  →  v6  →  v6 full corpus  →  v7  →  v8 (current)
                              (94 tickers)        BUG     split  (97 tickers)     Elastic  Optuna+
RMSE   QLIKE  Beta   ETF    Production-scale     FIX     fix    two passes        Net      P15 floor
fixed  fixed  drift  mom    calibration          ETF    AMZN   audit overlay     VIF      93-ticker
       -90%   closed added  100% EW-calibrated  reload  fixed  benchmark         back     signal lift
```

---

## v1 — Baseline (2026-04-03)

**What it was:** First real backtest after pipeline was fixed. BA and PG only. 39 features. Data from 2014 (no 2011 seed). No T5YIFR, no ETF momentum.

**Key metrics:**

| Ticker | H  | RMSE  | MZ beta | R²    | QLIKE  |
|--------|----|-------|---------|-------|--------|
| BA     | 21 | 0.167 | 0.483   | 0.322 | 0.0496 |
| BA     | 63 | 0.133 | 0.848   | 0.241 | 0.0580 |
| BA     | 126| 0.120 | 0.667   | 0.285 | 0.0468 |
| PG     | 21 | 0.060 | 0.800   | 0.270 | 0.0375 |
| PG     | 63 | 0.056 | 1.084   | 0.191 | 0.0388 |
| PG     | 126| 0.049 | 1.274   | 0.230 | 0.0308 |

**Key finding:** BA's MZ beta of 0.483 at H=21 means the model severely overpredicts — calling for twice the realized vol. QLIKE is high across all horizons. PG looks better at H=21 but H=126 beta is already drifting above 1.

**Verdict:** Promising direction but not usable. QLIKE values are too high; beta drift is severe for distressed names.

**Archived to:** `results/v1_no_t5yifr/`

---

## v2 — T5YIFR + QLIKE Fix (2026-04-04)

**What changed:**
- Added T5YIFR (5yr/5yr forward inflation swap rate) from FRED — structural inflation regime signal
- Fixed `macro_inflation_fwd_*` feature chain (T5YIFR level + chg_21d + abs_chg_21d)
- Expanded to 7-ticker run: BA, PG, AAPL, XOM, JPM, JNJ, NVDA

**Why T5YIFR matters:** Standard breakeven (T5YIE) picks up near-term inflation noise. T5YIFR isolates years 5-10 — the structural regime signal. 2022's sustained elevation at 2.8% for 18 months was exactly the regime that broke beta calibration; T5YIFR captured it where T5YIE could not.

**Key metrics (selected):**

| Ticker | H  | beta v1→v2     | R² v1→v2      | QLIKE v1→v2     |
|--------|----|----------------|---------------|-----------------|
| BA     | 21 | 0.483 → 0.916  | 0.322 → 0.384 | 0.0496 → 0.0112 |
| BA     | 126| 0.667 → 0.902  | 0.285 → 0.368 | 0.0468 → 0.0067 |
| PG     | 21 | 0.800 → 1.130  | 0.270 → 0.346 | 0.0375 → 0.0018 |
| AAPL   | 63 | —   → 1.544   | —   → 0.400  | —   → 0.0018   |
| JPM    | 63 | —   → 1.719   | —   → 0.489  | —   → 0.0022   |
| XOM    | 21 | —   → 0.877   | —   → 0.555  | —   → 0.0030   |
| NVDA   | 21 | —   → 0.863   | —   → 0.375  | —   → 0.0052   |

**Key finding:** QLIKE dropped 80–96% universally — model is now rarely severely underforecasting. BA beta fixed dramatically. But two systematic clusters emerged:
- **Underforecast cluster** (beta < 1): XOM, NVDA, BA — model calls for less vol than realized
- **Overforecast cluster** (beta > 1): AAPL, JPM, JNJ, PG — model calls for more vol than realized
- H=21 portfolio-level beta = 1.007 (near-perfect average masking opposite errors)

**Verdict:** Major quality leap. QLIKE problem solved. Beta calibration at portfolio level good, but individual ticker drift is the next problem.

**Archived to:** `results/v2_t5yifr/`

---

## v3 — Inflation Zscore (Beta Drift Fix Attempt) (2026-04-04)

**What changed:**
- 3 new inflation features targeting overforecast cluster:
  - `macro_inflation_fwd_abs_chg_21d` — bilateral shock magnitude
  - `macro_inflation_fwd_chg_63d` — slow structural drift window
  - `macro_inflation_fwd_zscore` — (T5YIFR - 252d mean) / std: the key fix — tells model "this level is priced in, stop treating it as a shock"
- Ran same 5-ticker AAPL/XOM/JPM/JNJ/NVDA set

**Hypothesis:** The overforecast cluster (AAPL/JPM) treats elevated T5YIFR as perpetual risk-off signal. The zscore returns toward 0 once a regime has stabilized for 252 days — this should dampen the persistent overforecast.

**Results:**

| Ticker | H   | beta v2→v3     | R² v2→v3       | Verdict     |
|--------|-----|----------------|----------------|-------------|
| JPM    | 21  | 1.057 → 0.848  | +0.009         | Confirmed   |
| JPM    | 63  | 1.719 → 1.387  | -0.076         | Partial     |
| JPM    | 126 | 1.736 → 1.584  | -0.015         | Partial     |
| AAPL   | 21  | 1.204 → 0.982  | -0.068         | Confirmed   |
| AAPL   | 63  | 1.544 → 1.376  | -0.013         | Confirmed   |
| XOM    | 21  | 0.877 → 0.821  | 0.555 → 0.415  | R2 REGRESSION |
| NVDA   | 21  | 0.863 → 0.746  | -0.082         | Overcorrected |

H=21 avg beta: 1.007 → 0.888. H=21 avg R²: 0.333 → 0.271.

**Finding:** Hypothesis partially confirmed — JPM/AAPL beta drift closes as predicted. But features are blunt: XOM and NVDA (already well-calibrated) lose R² because the inflation dampening applies globally rather than only to macro-sensitive names. LassoCV *should* downweight these features for XOM/NVDA but training windows may be too short to learn the distinction cleanly.

**Verdict:** Right direction, wrong tool. Features were over-engineering a calibration correction that's better handled by MZ post-hoc overlay or exponential weighting, not additional input features.

**Archived to:** `results/v3_inflation_zscore/`

---

## v4 — ETF Momentum + 2011 Data Start + 5950X (2026-04-05/06)

**What changed:**
- Added 6 ETF 21d log-momentum features: `mom21_SPY/VIXY/HYG/USO/TLT/UUP`
- Rationale: a one-day VIXY spike looks identical to a sustained grind-up in returns-only feature space. Momentum distinguishes them — "is TLT in a sustained grind down or just a noise day?"
- Expanded data window to **2011-01-01** (adds 3 years; 2011-2013 rows seed rolling windows, first predictions ~late 2016 after 5yr burn-in on 49 features)
- Now 49 total features
- Ran 16-ticker cross-sector sweep: BA, PG, AAPL, XOM, JPM, GS, C, CVX, AMZN, GOOGL, MRK, NEE, WMT, CAT, MS, LIN

**Key results (selected):**

| Ticker | H  | beta   | R²    | vs v3 note                         |
|--------|----|--------|-------|------------------------------------|
| BA     | 21 | 0.834  | 0.451 | best BA R² ever                    |
| BA     | 63 | 1.007  | 0.424 | beta essentially 1.0               |
| CVX    | 21 | 0.991  | 0.476 | near-perfect calibration           |
| XOM    | 21 | 0.827  | 0.495 | R² recovered from v3 regression    |
| JPM    | 21 | 1.022  | 0.286 | well-calibrated                    |
| AAPL   | 21 | 1.108  | 0.322 | beta still slightly elevated       |
| AMZN   | 21 | 0.638  | 0.336 | overforecast cluster confirmed     |
| AMZN   | 63 | 0.204  | 0.125 | severe overforecast mid-horizon    |
| GOOGL  | 21 | 0.526  | 0.180 | overforecast — class split 2014    |
| NEE    | 21 | 0.657  | 0.256 | overforecast — regulated cash flows |
| LIN    | 21 | 1.014  | 0.961 | highest R² seen (merger creates     |
|        |    |        |       | clean structural pair)             |

H=21 portfolio avg beta=0.901, R²=0.346 — strong recovery from v3 dip (0.271).

**Three confirmed beta clusters:**
1. **Well-calibrated [0.85–1.10]:** XOM, CVX, JPM, GS, C, BA, PG, CAT, MRK, WMT — macro signals transmit proportionally
2. **Overforecast [beta < 0.65]:** AMZN, GOOGL, NEE — mega-cap liquidity buffers or regulated cash flows dampen macro transmission
3. **Mild underforecast [beta 1.1–1.5]:** AAPL, C H=126, PG H=126 — model anchors too low on these names

**Engineering also in v4:** Caleb Solomon's parallel pipeline (ProcessPoolExecutor, 4 tickers simultaneous, ~4x throughput), XGBoost CUDA auto-fallback, predict_curve_batch() vectorized. Speed: ~14.7 min effective throughput/ticker.

**Bug fixed:** `exp_weight_lambda` tested (0.0006/day) on JPM — H=126 beta worsened (1.333→1.431). Reverted to 0.0. Infrastructure kept in ModelConfig, disabled.

**Verdict:** Best generalization yet. ETF momentum hypothesis validated on energy/macro names. The overforecast cluster (AMZN/GOOGL/NEE) is a genuine structural phenomenon, not a bug — these names fundamentally don't transmit macro risk the same way.

---

## v4 Full Corpus — 94 Tickers (2026-04-07/08)

**What changed:** Same model as v4. Ran across all 89 qualified tickers (CRSP × OptionMetrics universe), plus 5 previously run (AAPL, XOM, etc.). Two overnight batch runs completed the full corpus.

**Final corpus:**
- 94 tickers total (90 clean, 4 flagged for corporate action: GE breakup, META late ticker, RTX merger, GOOGL class split)
- 282 prediction files (94 × 3 horizons)
- ~2,676 prediction rows per ticker-horizon (2011-2026 walk-forward)

**Full portfolio summary (90 clean tickers):**

| Horizon | Mean beta | Median beta | Well-calibrated [0.85–1.15] | Mean R² |
|---------|-----------|-------------|----------------------------|---------|
| H=21    | **0.995** | 0.990       | **70/90 (78%)**            | 0.349   |
| H=63    | 1.114     | 1.111       | 51/90 (57%)                | 0.334   |
| H=126   | 1.192     | 1.191       | 36/90 (40%)                | 0.452   |

**Exp-weighted diagnostic (half-life ~1yr — recent regime only):**

| Horizon | EW Mean beta | EW Calibrated |
|---------|-------------|---------------|
| H=21    | 0.984       | **90/90 (100%)** |
| H=63    | 0.974       | **89/90 (99%)**  |
| H=126   | 0.976       | **89/90 (99%)**  |

**Critical insight:** The full-history H=126 drift (beta=1.19) is entirely a COVID/2022-era artifact. Once you weight recent observations more heavily (EW diagnostic), the model is essentially perfectly calibrated at all horizons. This means the model is not structurally broken for long horizons — it just has 2020–2022 overforecast events in the training tail that dilute the current-regime reading.

**Sector calibration at H=21 (clean tickers):**

| Sector        | N   | Mean beta | Well-calibrated |
|---------------|-----|-----------|-----------------|
| Comm          | 5   | 1.005     | 5/5 (100%)      |
| Consumer Disc | 6   | 0.919     | 5/6 (83%)       |
| Energy        | 6   | 0.984     | 5/6 (83%)       |
| Financials    | 10  | 1.016     | 6/10 (60%)      |
| Health Care   | 12  | 0.935     | 7/12 (58%)      |
| Industrials   | 9   | 1.005     | 7/9 (78%)       |
| Materials     | 5   | 1.023     | 4/5 (80%)       |
| REIT          | 5   | 0.942     | 5/5 (100%)      |
| Staples       | 10  | 0.998     | 7/10 (70%)      |
| Tech          | 14  | 1.049     | 12/14 (86%)     |
| Utilities     | 5   | 1.036     | 4/5 (80%)       |

**Notable outliers:** LIN R²=0.961 (highest in corpus — merger pair creates extreme structural regularity), GE R²=0.293 H=126 (corporate breakup creates training noise), AMZN H=63 R²=0.125 (known overforecast cluster).

**Beta-delta signal (90-ticker basis):**
- Market-average rolling beta delta z-score fires before 56% of 3-sigma SPY events (30-day lead window)
- ROC curve clearly above diagonal — usable as pre-event signal
- 71% false alarm rate — not a trading signal alone, but strong contextual indicator

**Verdict:** Model passes production-grade muster. H=21 is the gold standard horizon. The long-horizon drift is a solved calibration problem (MZ post-hoc correction or exp-weighted overlay). Signal detection capability confirmed at portfolio scale.

---

---

## v5 — Critical Feature Bug Fix (2026-04-09)

**What changed:**
- **Bug 1 (data_loader.py:604):** `store.load("ohlcv", tickers=config.tickers)` excluded ETFs — silently dropped all 12 `ret_*/mom21_*` features AND broke `beta_spy`/sector coupling (no SPY in closes). Fix: load `config.tickers + config.all_factor_etfs`.
- **Bug 2 (features.py:122):** `"mom21_"` missing from `include_prefixes` in `get_predictor_columns()` — momentum features were computed but never passed to models. The entire v4 rationale (ETF momentum) was never actually used.
- Net: entire 94-ticker v4 corpus ran with ~34 effective features instead of 46. All v4 results are invalid.
- Also dropped `tech_ATR` (Spearman=0.949 with rv_21d — pure redundancy).
- VIF exclusions added: rv_5d, rv_10d, rv_63d, iv_atm_30d, vol_trend, put_call_abs_skew_30d. Feature count: 46. min_train raised to 920.

**6-ticker validation (AAPL/JPM/XOM/NVDA/IBM/PEP):**

| Ticker | H   | beta v4→v5     | R² note                      |
|--------|-----|----------------|------------------------------|
| JPM    | 21  | 1.082 → 0.992  | best result — beta near 1.0  |
| JPM    | 126 | 1.431 → 1.253  | H126 drift closed             |
| XOM    | 21  | 0.892 → 0.879  | canary held                  |
| NVDA   | 21  | 0.935 → 0.776  | regressed — min_train effect  |

**Verdict:** Pipeline bugs invalidated the full v4 corpus. 6-ticker validation confirms bug fix works; XOM canary held; JPM best result ever. Full 94-ticker re-run required. Config reset to full universe.

---

## v6 — Stock Split Fix + GARCH Feature + Full Corpus (2026-04-10 / 2026-04-11–16)

**What changed:**
1. **Split-adjusted prices:** `_pivot_ohlcv()` now reconstructs `adj_closes` from CRSP `ret` column (cumulative product). Prior approach used `log(prc/prc.shift(1))` which injected phantom vol spikes on split dates — AMZN June 2022 20:1 split injected ewma_vol=1425%. GK RV still uses raw H/L/O/C (intraday ratios are split-safe).
2. **`garch_cond_vol` as predictor:** GARCH(1,1)-skewt conditional vol fit once per ticker on adj_returns. Added as 43rd predictor. Weakly selected by Lasso/ElasticNet (rank 28/43 at H=63, collinear with ewma_vol at H=21).
3. **rv_21d re-added:** Was VIF-excluded (VIF=10.6) but is the strongest H=21 predictor. LassoCV/ElasticNet handle collinearity. Feature count 44.
4. **Lasso + XGB tracking:** `lasso_tracking_{TICKER}.csv` and `xgb_importance_{TICKER}.csv` written per ticker.

**6-ticker validation results:**

| Ticker | H   | beta v5→v6     | R² note                              |
|--------|-----|----------------|--------------------------------------|
| AMZN   | 63  | 0.204 → 0.942  | SPLIT FIX CONFIRMED — biggest fix    |
| BA     | 21  | 0.834 → 1.018  | improved                             |
| XOM    | 21  | —    → 0.898   | canary: R²=0.512                     |
| AAPL   | 21  | —    → 1.125   | stable                               |
| C      | 126 | —    → 1.316   | R²=0.584 best H=126 in run           |
| CVX    | 21  | —    → 0.991   | near-perfect calibration             |

**Full 97-ticker corpus (two overnight passes via batch_backtest.py):**
- First pass: 48 tickers, 17.8 hours. Second pass: 49 remaining, 13.6 hours.
- 291 prediction files (97 tickers × 3 horizons). 756,249 rows in all_predictions.csv.
- H=21 R²=0.374, H=63=0.319, H=126=0.458 corpus mean.
- EW MZ betas 0.97-0.98 in current regime (COVID dominates flat OLS, making it look 24% calibrated — EW is the correct lens).
- Tail asymmetry: -0.12 systematic underprediction of severe events (structural rolling-window lag — not worth patching separately).
- Term structure inversion: 64.8% pre-overlay (calibration drift artifact, not real inversions).

**Post-hoc additions (2026-04-11–16):**
- **audit.py** — 9-test validity suite: DM test (97/97 beat persistence at H63/H126), MZ regression, tail coverage, IC, term structure compliance.
- **mz_overlay.py** — EW MZ calibration (lambda=0.003) + soft isotonic term structure enforcement (tol=5%). Beta cap at 2.0 (VZ H126 raw=2.619). TS inversions reduced 64.8%→55.6%. Secondary violation bug identified (not yet fixed).
- **benchmark_models.py** — HAR-RV + GARCH(1,1) walk-forward comparison. Ensemble lift over HAR: +0.135/+0.200/+0.432 mean ΔR² at H21/63/126. GARCH negative R² at all horizons (multi-step GARCH collapses to unconditional mean).

**Verdict:** Definitive corpus. Split fix was the most impactful single change (AMZN H=63 R² 0.125→0.441). Full-history audit confirms robustness. MZ overlay makes H=126 deployment-ready.

---

## v7 — ElasticNet + Sector Coupling + Quantile Model (2026-04-23/24)

**What changed:**
1. **ElasticNet replaces LassoCV:** `ElasticNetCV(l1_ratio=[0.5,0.7,0.9])` cross-validates sparsity vs group-shrinkage per fold. L2 term prevents arbitrary zeroing of correlated feature groups. `mean_l1_ratio` tracked per fold in lasso_tracking CSVs.
2. **6 VIF-excluded features restored:** `rv_5d, rv_10d, rv_63d, corr_sector_21d, corr_sector_252d, sector_wedge`. VIF=26-30 but carry real incremental signal (JPM H63 R² dropped 0.17 after removal). ElasticNet handles collinearity proportionally. Feature count 41→50.
3. **min_train fixed to 756 flat** (was `max(252, 20×n_features)=1000` with 50 features — the 20× rule is Lasso-specific instability guard; ElasticNet's L2 is stable with shorter windows).
4. **QuantileVolModel added:** Parallel XGBoost at tau=0.85 with `objective="reg:quantileerror"`. Outputs `y_pred_q85`. coverage_q85 = 0.27–0.36 vs target 0.15 → tau=0.85 behaves like ~P68 in practice.
5. **Optuna search launched overnight:** hyperparam_search.py (JPM 120 trials + AAPL 80 trials, QLIKE + 0.3×|beta-1|² objective, step_days=63 for speed).

**20-ticker cross-sector validation results (key highlights):**

| Ticker | H   | beta v6→v7     | R² note                              |
|--------|-----|----------------|--------------------------------------|
| AMZN   | 21  | 0.666 → 0.846  | overforecast cluster improved        |
| GOOGL  | 21  | 0.526 → 1.007  | dramatic improvement                 |
| D      | 21  | 0.924 → 0.769  | sector coupling overcorrecting       |
| LIN    | —   | —    → R²=0.94 | leakage artifact, exclude            |
| META   | —   | —    → 314 rows| IPO recency — too short              |

H21 mean R²=0.370, H63=0.350, H126=0.460.

**Verdict:** ElasticNet + sector features are clearly better for financial names (JPM, GS). GOOGL overforecast cluster resolved. Sector coupling somewhat overcorrects at H21 for utilities (D). Quantile right-tail calibration is intractable — confirmed mismatch in model distribution, not a tau problem.

---

## v8 — Optuna Params + Left-Tail Floor + 93-Ticker Production Run (2026-04-28)

**What changed:**
1. **Optuna hyperparameters applied to config.py:** JPM/AAPL agreed on: depth 4→3, n_estimators 100→225, reg_alpha 0.01→0.15, reg_lambda 1.0→0.27, gamma 0.1→0.20, subsample 1.0→0.75, colsample 0.8→0.70. Compromises: learning_rate=0.05, min_child_weight=4, colsample_bytree=0.70. Smoke test: H126 beta improved (AAPL 1.372→1.230, JPM 1.356→1.303) at modest R² tradeoff. Systematic beta>1.0 is structural (expanding-window training), not hyperparameter-fixable.

2. **tau=0.92 investigation → pivot to left tail (tau=0.15):** coverage_q92=0.19–0.39 vs target 0.08. Linear extrapolation implied tau>1.0 needed for true P85 — right tail is structurally intractable (unobserved shocks dominate). **Left tail (tau=0.15) is tractable:** low-vol regimes driven by observable persistent factors (GARCH, HYG, VIXY, RV windows). Errs conservatively (overwarn) — preferred under asymmetric loss. `quantile_alphas=[0.15]`. Outputs `y_pred_q15` = P15 vol floor estimate.

3. **signal_strength.py built** (`analysis/`):
   - Non-linear risk weight: flat <P60, convex above (P70→0.15, P80→0.30, P90→0.55, P95→0.75, P99→0.95)
   - Expanding-window CDF per ticker (no lookahead bias) to track output percentiles
   - Conditional tail precision: P(rv elevated | signal ≥ P80) vs baseline lift
   - **3-ticker results:** XOM 24.7×, AAPL 7.2×, JPM 3.3× pooled 5.4× lift at P80+
   - **2×2 regime taxonomy:** ensemble-only elevated = 6.1× (sharpest), both elevated = 5.4×, floor-only = 0.69× (contrarian), neither = 1.0×

4. **vrp_return_conditional.py built** (`analysis/`): bins prior 5d/21d returns into quintiles, computes VRP wedge distribution per bucket. Hi-return + lo-VRP = momentum regime; hi-return + hi-VRP = mean reversion setup. JSON output for frontend.

5. **MemoryError fix in parallel backtest:** `_slice_raw()` inside `_run_parallel()` — slices raw_data dict to only target ticker's vsurfd + shared ETF ohlcv + fred/meta before submitting to worker. Reduces per-worker pickle size ~90×.

6. **93-ticker production universe:** Excluded LIN (R²=0.94 leakage artifact), OXY (RMSE explosion), VZ (beta outlier — Frontier Communications acquisition), META (IPO recency / user-flagged). step_days=63.

**Status:** 85/93 tickers complete at session end. Final workers finishing.

**Pending full-corpus analytics:**
- `signal_strength.py` on all 93 tickers — expect 4–6× pooled lift at P80+
- `vrp_return_conditional.py` — full VRP conditional distribution by return quintile

---

## What's Next

**Immediate (once v8 corpus completes):**
1. Run signal_strength.py and vrp_return_conditional.py on full 93-ticker predictions
2. Fix TS monotonicity bug in mz_overlay.py (second H21-H63 pass after H63-H126 enforcement)
3. OI differential pull from WRDS (25δ put/call OI — TIME SENSITIVE, access expiring)

**Deferred:**
- IC demeaned cross-sectional signal (IC=0.836 dominated by structural component)
- SHAP cross-ticker analysis — feature importance heatmap by sector
- Exponential sample weighting — lambda=0.0006 worsened JPM H=126, revisit
- SVI interpolated IV surface, Markov regime switching — long-term
- Supabase write layer, backend API, frontend — SWEs handling
