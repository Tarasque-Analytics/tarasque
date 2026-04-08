# Tarasque — Model Iteration Log
_Tracks every model version, what changed, what improved, and what failed._
_Last updated: 2026-04-08_

---

## Summary Arc

```
v1  →  v2  →  v3  →  v4  →  v4 full corpus
                              (94 tickers)
RMSE   QLIKE  Beta   ETF    Production-scale
fixed  fixed  drift  mom    calibration confirmed
       -90%   closed added  100% EW-calibrated
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

## What's Next

**Immediate priorities:**
1. **MZ calibration overlay** — rolling OOS alpha+beta correction per ticker per horizon, applied as post-processing. Eliminates H=126 drift cleanly without touching the model.
2. **IC/quintile spread** — rank 90 stocks by predicted vol daily, test whether top quintile realizes more vol. Converts "diagnostically good" to "monetizably validated."
3. **Pull 119 new WRDS tickers** — identified but not yet in local DB. Expands universe toward the 400-ticker production target.
4. **SHAP cross-ticker analysis** — feature importance heatmap by sector, SHAP on named event dates, rolling importance over time.

**Deferred:**
- Vol surface term structure slope as feature (IV_30d - IV_91d already in DB)
- Residual autocorrelation correction (rho * residual_{t-1} term)
- SVI interpolated IV surface
- Markov regime switching overlay
- Supabase write layer (Caleb)
