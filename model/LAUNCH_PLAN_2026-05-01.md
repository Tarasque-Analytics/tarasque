# Full-Corpus Production Run — Launch Plan

_Created 2026-05-01, updated 2026-05-01 (evening). Two staged launches:_

**Phase A — 91-ticker corpus** (this is what we run NEXT, single-host, ~14h):
data already on disk for these tickers. v10 + tech-event-gravity spec. Validates
v9 calibration claim at corpus scale, produces full risk-payload package, gives
the web app real data to render against.

**Phase B — 500-ticker expansion** (later, ~4 days × 4 machines):
requires WRDS pulls for ~400 net-new tickers, time-sensitive (mid-June expiry).
Plan below applies, but Phase A should ship first as the beta launch.

---

## CONFIRMED 2026-05-01 (evening session)

The v9 canary data on the sneakernet SSD (`H:\volarbmodel\model\pipeline\results\`,
36 per-horizon files dated 4/29) was stacked into `v9_canary_predictions.csv`
and analyzed.

**v9 calibration confirmed dramatically better than v8:**

| Horizon | v9 OLS β (12 tk) | v9 std | v9 in [0.7,1.3] | v8 same 6tk subset |
|---|---|---|---|---|
| H=21 | 0.972 | 0.079 | **12/12** | mean 0.678, std 0.324 |
| H=63 | 1.006 | 0.126 | 11/12 | mean 0.511, std 0.353 |
| H=126 | 1.034 | 0.106 | **12/12** | mean 0.761, std 0.151 |

**Spec is worthy of 91-ticker corpus run.** No loss-function intervention
needed. The β residual is the regime signal (per beta_regime + regime_trail
viz), not a defect to train away. MZ overlay handles dynamic regime drift
post-hoc; raw β_mz is what the 2×2 / trail / risk-tier UI reads.

---

## 1. Locked Model Spec (commit before launch — no changes mid-run)

| Component | Setting | Notes |
|---|---|---|
| Architecture | v9 ensemble (XGB + RF + ElasticNetCV) | 36/36 canary improved; do not change |
| XGB hyperparameters | Optuna v8 (depth=3, n_est=225, alpha=0.15, lambda=0.27, gamma=0.20, subsample=0.75, colsample=0.70) | Already in config.py |
| RF hyperparameters | n_est=150, min_samples_leaf=12 | Already in config.py |
| ElasticNet | l1_ratio=[0.5,0.7,0.9], alphas=20 | Already in config.py |
| Loss | MSE in log-vol space | NO weighted-MSE / QLIKE objective changes (research-stage) |
| Quantile model | XGB pinball, τ=0.15 | Left-tail floor only |
| Walk-forward | step_days=20, min_train=756 | Validated today on AAPL |
| Features | v10 (55) + **event_tech_gravity (NEW, 56 total)** | CES/SXSW/GTC/Google IO/WWDC/iPhone |
| Bias correction | MZ overlay applied **after** corpus run (Phase 1 of deployment) | Includes isotonic TS enforcement + q15 coverage offsets |

**What is intentionally NOT in this run:**
- Per-ticker hyperparameters (overfit risk)
- Per-ticker step_days (not validated)
- Right-tail pinball (intractable per audit)
- Weighted-MSE loss (no canary yet)

---

## 2. Pre-Launch Data Gaps

These MUST close before the launch is data-coherent. Most are time-sensitive
because WRDS access expires ~mid-June 2026.

### 2A. WRDS pulls for net-new tickers (~400 names)

The 4-day run targets ~500 tickers but the cache currently has data for ~118
(93 model tickers + 25 factor ETFs). The remaining ~400 need:

```
ohlcv      via fetch_crsp_daily       — ~1 hour at WRDS bandwidth
vsurfd     via fetch_vsurfd           — ~6-8 hours (year tables, 2014-2025)
oi_25delta via fetch_oi_25delta       — ~2-3 hours (opprcd tables)
compustat_meta via fetch_compustat_meta — minutes (GICS sector codes)
earnings, dividends                   — quick
```

**Plan**: dedicate Machine #1 to a one-shot `--mode refresh_data --force-refresh`
with the expanded `dc.tickers` list. Run overnight before the canary. Verify
each cache's `max_date` after, and `ticker_count`.

### 2B. Cache integrity check (post-pull)

Today's runbook surfaced a 461-day OHLCV gap on 71 tickers (2024-12-31 →
2026-04-06). After fresh WRDS pull, run a diagnostic:

```
python -c "
from model.pipeline.data_loader import ParquetStore
from model.pipeline.config import load_config
import pandas as pd
dc, _, _ = load_config()
s = ParquetStore(dc.base_dir)
ohlcv = s.load('ohlcv')
ohlcv['date'] = pd.to_datetime(ohlcv['date'], format='mixed')
gaps = []
for tk, g in ohlcv.groupby('ticker', observed=True):
    if (g.sort_values('date')['date'].diff().dt.days > 30).any():
        gaps.append(tk)
print('Tickers with date gaps > 30 days:', gaps)
"
```

**Target**: empty list. If non-empty, run the Alpaca backfill block from today's
session (see `data_loader.py:append_recent_data` after my fix).

### 2C. New-universe tickers list

Define `dc.tickers` for the launch. Suggest:
- All 500 S&P 500 components (snapshot today via Wikipedia or paid data)
- Existing 25 factor ETFs (unchanged)
- Excluded: 4 documented exclusions from v8 (LIN, OXY, VZ + post-mortem-pending names)

Save the list explicitly to `model/pipeline/configs/launch_2026_universe.py`
so it's reproducible.

---

## 3. Canary Validation (~5 hours, before full launch)

### 3A. Sector-diverse 6-ticker canary

Validate `event_tech_gravity` doesn't damage non-tech tickers. Use:

| Ticker | Sector | Why |
|---|---|---|
| AAPL | Tech | Tech baseline; expect lift |
| JPM | Financials | Macro-sensitive; expect ≈ no change |
| XOM | Energy | Sector decoupled from tech; expect ≈ no change |
| JNJ | Healthcare | Defensive; expect ≈ no change |
| KO | Staples | Lowest market beta in corpus; expect ≈ no change |
| BA | Industrials | Single-name event-risk; expect ≈ no change |

```
python -m model.pipeline --mode backtest --tickers AAPL JPM XOM JNJ KO BA
```

### 3B. Pass criteria

Compare canary results to v9 12-ticker baseline (claude_context.md L549–558):
- AAPL R²/RMSE: ≥ v9 (allow +/- 0.02 R²) — feature should help, not hurt
- Other 5 tickers R²/RMSE: within +/- 0.03 R² of v9 baseline (no degradation)
- All 6: MZ_beta direction unchanged (no flips across 1.0)

If ANY non-tech ticker shows R² regression > 0.03, **abort**: investigate the
feature's interaction (probably collinearity with event_fed_gravity).

---

## 4. Launch Orchestration (4 machines × ~125 tickers each)

### 4A. Ticker split

Distribute 500 tickers across 4 machines by alphabetical block, NOT by sector
(avoid sector-clustered failure modes):
- Machine 1: A–F (~125)
- Machine 2: G–M (~125)
- Machine 3: N–S (~125)
- Machine 4: T–Z + ETFs (~125 + factor universe)

Each machine runs:
```
python -m model.pipeline --mode backtest --tickers <its block>
```

`parallel_tickers` per machine: 4 (5950X home rig) or 8 (campus 64GB rig if
available). claude_context.md L91 documents the OOM ceiling at 4 on 32GB.

### 4B. Output collision risk

Each machine writes to its own `model/pipeline/results/` directory. After all
4 finish, **rsync results onto a single host** before the post-run pipeline.
Specifically the per-ticker files (`predictions_*.csv`, `lasso_detailed_*.csv`,
`xgb_importance_steps_*.csv`, `feature_decay_*.csv`) merge cleanly because
they're per-ticker. The aggregates (`backtest_results.csv`,
`all_predictions.csv`) need to be **rebuilt** from the per-ticker files on the
unified host (script: `_run_sector_sweep` rebuild logic in backtest.py:472).

---

## 5. Post-Run Pipeline (in order, on unified host)

```
# 5A. Rebuild aggregates from per-ticker files
python -m model.pipeline.scripts.rebuild_aggregates    # NEEDS TO BE WRITTEN

# 5B. MZ overlay (calibration + isotonic TS + coverage offset)
python -m model.pipeline.analysis.mz_overlay

# 5C. Coverage offsets (refresh on v9 predictions)
python -m model.pipeline.analysis.coverage_check

# 5D. Signal strength (corpus-level lift)
python -m model.pipeline.analysis.signal_strength

# 5E. VRP-return-conditional analysis
python -m model.pipeline.analysis.vrp_return_conditional

# 5F. Audit (9-test post-hoc validity)
python -m model.pipeline.analysis.audit

# 5G. Benchmark vs HAR-RV / GARCH
python -m model.pipeline.analysis.benchmark_models

# 5H. Per-ticker feature decay
python -m model.pipeline.analysis.feature_decay --all

# 5I. Regime 2×2
python -m model.pipeline.analysis.beta_regime

# 5J. Tail event logs (corpus + sector roll-up)
python -m model.pipeline.analysis.tail_log --all --sectors

# 5K. Correlation matrices (all 3 windows)
python -m model.pipeline.analysis.corr_matrix

# 5L. NEW: Risk JSON bundler — see §6 gap
python -m model.pipeline.scripts.bundle_risk_payloads  # NEEDS TO BE WRITTEN
```

Estimated post-run pipeline: ~1 hour total.

---

## 6. Web-App Data Contract

### 6A. Per-ticker risk JSON (NEW — gap)

Existing `{TICKER}_Payload.json` (output.py) has forecast + calibration + time
series. Missing: tail events, current tail state, regime quadrant, q15 floor
series.

**Spec for `{TICKER}_Risk.json` (to be built post-run):**

```json
{
  "ticker": "AAPL",
  "as_of": "2026-05-01",
  "forecast": {
    "h21": 0.189, "h63": 0.200, "h126": 0.218,
    "q15_floor": { "h21": 0.151, "h63": 0.169, "h126": 0.180 },
    "cycle_window_end": "2026-05-29"
  },
  "current_state": {
    "percentile_h21": 0.64,
    "regime": "normal",                         // normal / tail / extreme
    "days_in_state": 18,
    "last_tail_entry": "2025-02-10",
    "last_tail_exit": "2025-04-11"
  },
  "structural": {
    "beta_mkt_252d": 1.01,
    "beta_mz_h21": 1.18,
    "beta_mz_h63": 1.49,
    "beta_mz_h126": 1.23,
    "quadrant": "Q2-idiosync-plus-systematic"
  },
  "lifetime_stats": {
    "tail_entries": 28,
    "extreme_entries": 12,
    "median_tail_duration_days": 24,
    "pct_time_in_tail": 0.201
  },
  "history": {
    // sparse arrays for charts; date-aligned
    "dates":        ["2014-01-06", ...],
    "y_true":       [0.198, ...],
    "y_pred_h21":   [0.205, ...],
    "y_pred_q15":   [0.155, ...],
    "percentile":   [null, null, ..., 0.32, ...]    // null pre-warmup
  }
}
```

This bundles everything per-ticker so the backend can serve a single endpoint
(`GET /api/risk/{ticker}`) per stock-detail page without joining 4 CSVs.

### 6B. Aggregate JSONs

| File | Purpose | Source |
|---|---|---|
| `market_overview.json` | landing page summary | output.py — exists |
| `metrics_summary.json` | corpus metrics | output.py — exists |
| `regime_2x2.json` | NEW — quadrant-by-ticker for the 2×2 viz | bundler from regime_2x2.csv |
| `sector_overview.json` | NEW — per-sector tail counts + avg β_mz + avg vol forecast | bundler from sector_tail_summary.csv + backtest_results.csv |
| `corr_matrix_w{63,252,504}.json` | for portfolio aggregator | bundler from corr_matrix_w*.csv |

### 6C. Portfolio "my risk" endpoint (downstream — frontend/backend)

Backend takes `{ticker: weight}` from user, computes:
- portfolio_vol_h21 = sqrt(w' Σ w) where Σ_ij = corr_ij × σ_i × σ_j (σ from forecast)
- quadrant_concentration = % weight in Q1+Q2 (hidden risk pockets)
- top_contributors = marginal vol contribution per holding
- diversification_benefit = portfolio_vol vs sum(w_i × σ_i)
- floor_signal_exposure = % weight currently above own P85

All required model-side data is in `{TICKER}_Risk.json` + `corr_matrix_*.json`.
Endpoint logic is backend-side only — no model retraining needed per portfolio.

---

## 7. Verification Gates Post-Launch

| Gate | Check | Target |
|---|---|---|
| Per-ticker schema | Random sample 5 tickers; cols match v9 | Pass |
| Date range | `predictions_*.csv` `date.max()` ≈ `ohlcv.max() − 126 BDays` | Within 5 BDays |
| MZ betas | After overlay, EW MZ β across corpus | mean within [0.95, 1.05] |
| Coverage_q15 | After offsets, 91+/91 tickers at 0.85 ± 0.02 | ≥ 95% pass |
| TS inversions | After isotonic enforcement | < 1% (vs current 51%) |
| Forecast cycle | `forecast_*.csv` row count | == # tickers in run |
| Risk JSON | One per ticker, schema-valid | All present |
| Sector roll-up | 11 GICS sectors represented | All 11 |
| Corr matrix | Symmetric, diagonal == 1.0 ± 1e-6 | All pass |

---

## 8. Open Items Before "Go"

### Phase A (91-ticker corpus, ready now):

1. **Tech-event canary** — 6 tickers (AAPL/JPM/XOM/JNJ/KO/BA), ~5h, validate
   event_tech_gravity doesn't damage non-tech. **Required before corpus run.**
2. ✅ `scripts/rebuild_aggregates.py` — built, smoke-tested on 12-ticker v9 sample.
3. ✅ `scripts/bundle_risk_payloads.py` — built, smoke-tested. Schema matches
   §6A. Per-ticker single-document with all horizons inside.
4. **Run 91-ticker corpus** — `python -m model.pipeline --mode backtest`
   (existing 91-ticker config). ~14h on parallel_tickers=4. OI features will be
   NaN for all tickers except AAPL — ElasticNet zeros them, no harm.
5. **Run post-pipeline analysis** — full §5 sequence (mz_overlay → coverage →
   signal_strength → audit → benchmark → feature_decay → beta_regime →
   regime_trail → beta_over_time → corr_matrix → bundle_risk_payloads).
6. **Validation gates** — §7 checklist. Especially: 91-ticker corpus β
   distribution should match the 12-ticker v9 canary's tightness (mean β
   ~1.0, std ~0.10, ≥85% in [0.7, 1.3]).

### Phase B (500-ticker expansion, follows Phase A success):

1. **WRDS pulls for ~400 net-new tickers** — overnight on dedicated machine.
   Time-sensitive (mid-June expiry).
2. **`launch_2026_universe.py` config** — define the exact 500-ticker list.
3. **Per-machine launch script** — `launch_machine.sh` with hardcoded ticker
   block (4 machines × ~125 tickers).

### Dropped (no longer in scope):

- ~~Canary A (exp_weight_lambda)~~ — v9 already addresses the over-forecast cluster.
- ~~Canary B (vol_weight_alpha)~~ — static β is fine; dynamic drift handled by
  MZ overlay; raw β_mz is the regime signal we WANT to preserve.

---

## 9. Sanity Stop-Conditions During Run

If any of these fire on any machine, halt and investigate before proceeding:

- Single-ticker wall time > 90 minutes (vs 50min today on AAPL with 149 steps)
- More than 5 tickers per 100 fail at "feature build" stage
- backtest_results aggregate produces NaN MZ_beta on > 2% of (ticker, horizon) pairs
- `predictions_*.csv` file size < 100KB (likely empty backtest)

Halt response: stop the affected machine, post the log, decide whether to skip
the bad ticker(s) and continue or abort the run.
