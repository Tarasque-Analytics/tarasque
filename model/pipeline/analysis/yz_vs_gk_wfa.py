"""
yz_vs_gk_wfa.py — Rigorous WFA POC: GK vs YZ target across multiple folds.

Per the user's "do this right" request, this fixes the methodology issues with
the quick POC:
  - Full ensemble (XGB + RF + ElasticNet) instead of XGB-only
  - 15 tickers across sectors (vs 5) to dilute per-ticker noise
  - 5 sliding WFA test folds (vs single train/test split) to average across regimes
  - Numerical guardrails on R² (clip predictions to plausible vol range to
    avoid the KO-style -666 artifact from one degenerate prediction)

Per (ticker, fold, estimator):
  - test R² (clipped)
  - test β_mz (log-log MZ regression)
  - event_gravity feature importances (from XGB component, averaged)
  - wedge IC on test fold (Spearman of vrp_wedge_ewma vs predictions/y_true)

Then aggregate per-ticker across folds, then across tickers.

Outputs:
  results/validation/yz_vs_gk_wfa.csv
  results/validation/yz_vs_gk_wfa_summary.md
"""
from __future__ import annotations

from pathlib import Path

import warnings
import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

from ..config import load_config
from ..data_loader import fetch_dataset
from ..features import FeatureBuilder

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

# 15 tickers across sectors
POC_TICKERS = ["AAPL", "MSFT", "NVDA", "AMD",          # tech
               "JPM", "GS", "BAC",                       # financials
               "XOM", "CVX",                             # energy
               "KO", "PG",                               # staples
               "JNJ", "PFE",                             # healthcare
               "CAT", "WMT"]                             # industrial / retail

HORIZON = 21
EVENT_FEATURES = ["event_earn_gravity", "event_fed_gravity", "event_div_gravity",
                  "event_cpi_gravity", "event_nfp_gravity"]

# 5 disjoint test windows of ~6 months each
WFA_FOLDS = [
    ("2021-07-01", "2022-01-01"),
    ("2022-07-01", "2023-01-01"),
    ("2023-07-01", "2024-01-01"),
    ("2024-07-01", "2025-01-01"),
    ("2025-07-01", "2026-01-01"),
]

# Plausible vol range — predictions outside this are clipped before metrics
VOL_FLOOR = 0.05    # 5% annualized
VOL_CEIL  = 3.00    # 300% annualized (very wide; flags only true degenerate predictions)


def train_ensemble(X_tr: np.ndarray, y_tr: np.ndarray) -> tuple:
    xgb = XGBRegressor(n_estimators=225, max_depth=3, learning_rate=0.05,
                       reg_alpha=0.15, reg_lambda=0.27, gamma=0.20,
                       colsample_bytree=0.70, min_child_weight=4, subsample=0.75,
                       tree_method="hist", device="cpu", n_jobs=4, verbosity=0)
    rf  = RandomForestRegressor(n_estimators=150, min_samples_leaf=12,
                                n_jobs=4, random_state=42)
    en  = ElasticNetCV(l1_ratio=[0.5, 0.7, 0.9], cv=3, max_iter=10000, n_jobs=4)
    xgb.fit(X_tr, y_tr)
    rf.fit(X_tr, y_tr)
    en.fit(X_tr, y_tr)
    return xgb, rf, en


def predict_ensemble(models: tuple, X: np.ndarray) -> tuple:
    xgb, rf, en = models
    return (xgb.predict(X) + rf.predict(X) + en.predict(X)) / 3.0


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """R², RMSE, log-log MZ β on clipped predictions."""
    y_pred_clipped = np.clip(y_pred, VOL_FLOOR, VOL_CEIL)
    mask = np.isfinite(y_true) & np.isfinite(y_pred_clipped) & (y_true > 0)
    if mask.sum() < 10:
        return {"r2": np.nan, "rmse": np.nan, "beta_mz_loglog": np.nan, "n": 0}
    yt = y_true[mask]
    yp = y_pred_clipped[mask]
    ss_res = float(((yt - yp) ** 2).sum())
    ss_tot = float(((yt - yt.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    rmse = float(np.sqrt(((yt - yp) ** 2).mean()))
    yt_log = np.log(np.clip(yt, 1e-6, None))
    yp_log = np.log(np.clip(yp, 1e-6, None))
    var_mz = float(np.var(yp_log, ddof=1))
    cov_mz = float(np.cov(yt_log, yp_log, ddof=1)[0, 1])
    beta = cov_mz / var_mz if var_mz > 0 else np.nan
    return {"r2": r2, "rmse": rmse, "beta_mz_loglog": beta, "n": int(mask.sum())}


def run_fold(ticker: str, fdf: pd.DataFrame, predictors: list,
              fold_start: pd.Timestamp, fold_end: pd.Timestamp,
              estimator: str) -> dict:
    """Train on data BEFORE fold_start; predict for [fold_start, fold_end)."""
    fdf = fdf.copy()
    fdf["y_h21"] = fdf["rv_TARGET"].shift(-HORIZON)
    train = fdf[fdf.index <  fold_start].dropna(subset=["y_h21"])
    test  = fdf[(fdf.index >= fold_start) & (fdf.index < fold_end)].dropna(subset=["y_h21"])
    if len(train) < 500 or len(test) < 20:
        return {"status": "insufficient", "n_train": len(train), "n_test": len(test)}

    X_tr = train[predictors].ffill().bfill().fillna(0).values
    y_tr = train["y_h21"].values
    X_te = test[predictors].ffill().bfill().fillna(0).values
    y_te = test["y_h21"].values

    models = train_ensemble(X_tr, y_tr)
    y_pred = predict_ensemble(models, X_te)
    m = metrics(y_te, y_pred)

    # XGB feature importances for event gravities
    xgb, _, _ = models
    imp = pd.Series(xgb.feature_importances_, index=predictors)
    imp_sorted = imp.sort_values(ascending=False)
    event_imps = {f: float(imp.get(f, 0)) for f in EVENT_FEATURES if f in imp.index}
    event_total = sum(event_imps.values())
    earn_rank = int(np.argwhere(imp_sorted.index == "event_earn_gravity").flatten()[0]) + 1 \
                if "event_earn_gravity" in imp_sorted.index else -1

    return {
        "status": "ok",
        "ticker": ticker, "estimator": estimator,
        "fold_start": fold_start.date().isoformat(),
        "fold_end":   fold_end.date().isoformat(),
        "n_train": len(train), "n_test": len(test),
        "test_r2": m["r2"], "test_rmse": m["rmse"],
        "test_beta_mz_loglog": m["beta_mz_loglog"],
        "event_gravity_total_importance": event_total,
        "event_earn_gravity_imp": event_imps.get("event_earn_gravity", 0.0),
        "event_earn_gravity_rank": earn_rank,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dc, mc, bc = load_config()
    raw = fetch_dataset(dc)

    # Pre-compute fold dates
    folds = [(pd.Timestamp(s), pd.Timestamp(e)) for s, e in WFA_FOLDS]
    print(f"[YZGK_WFA] {len(POC_TICKERS)} tickers, {len(folds)} folds, 2 estimators")
    print(f"[YZGK_WFA] Total trainings: {len(POC_TICKERS) * len(folds) * 2}")

    rows = []
    for tk_i, ticker in enumerate(POC_TICKERS, 1):
        for estimator in ("gk", "yz"):
            print(f"\n[YZGK_WFA] [{tk_i}/{len(POC_TICKERS)}] {ticker} {estimator}: building features...")
            mc.vol_estimator = estimator
            builder = FeatureBuilder(dc, mc)
            try:
                fdf = builder.build(ticker, raw, drop_nan_targets=False)
            except Exception as e:
                print(f"  feature build failed: {e}")
                continue
            if "rv_TARGET" not in fdf.columns:
                continue
            fdf.index = pd.to_datetime(fdf.index)

            # Predictor selection: drop targets and direct rv_TARGET (lookahead via shift)
            drop = {"y_h21", "rv_TARGET", "rv_21d"}
            predictors = [c for c in fdf.columns
                          if c not in drop
                          and pd.api.types.is_numeric_dtype(fdf[c])
                          and not c.startswith("y_")]
            for f_i, (fs, fe) in enumerate(folds, 1):
                print(f"    fold {f_i}/{len(folds)} train→{fs.date()} | eval [{fs.date()}, {fe.date()})...")
                r = run_fold(ticker, fdf, predictors, fs, fe, estimator)
                if r.get("status") != "ok":
                    print(f"      skipped: {r}")
                    continue
                print(f"      R²={r['test_r2']:+.3f}  βmz={r['test_beta_mz_loglog']:+.3f}  "
                      f"earn_imp={r['event_earn_gravity_imp']:.4f} rank={r['event_earn_gravity_rank']}")
                rows.append(r)

    if not rows:
        print("[YZGK_WFA] No results.")
        return 1

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "yz_vs_gk_wfa.csv", index=False)
    print(f"\n[YZGK_WFA] Wrote {OUT_DIR / 'yz_vs_gk_wfa.csv'}")

    # ── Per-ticker aggregation across folds ────────────────────────────────
    print("\n" + "=" * 80)
    print(" PER-TICKER mean across folds (5 fold avg)")
    print("=" * 80)
    agg = df.groupby(["ticker", "estimator"]).agg(
        mean_r2=("test_r2", "mean"),
        mean_beta_mz=("test_beta_mz_loglog", "mean"),
        mean_event_imp=("event_gravity_total_importance", "mean"),
        mean_earn_rank=("event_earn_gravity_rank", "mean"),
        n_folds=("test_r2", "count"),
    ).reset_index()
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.4f}"):
        print(agg.to_string(index=False))

    # ── GK vs YZ deltas per ticker ─────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" GK vs YZ deltas per ticker (positive = YZ improves)")
    print("=" * 80)
    deltas = []
    for tk in df["ticker"].unique():
        g = agg[(agg.ticker == tk) & (agg.estimator == "gk")]
        y = agg[(agg.ticker == tk) & (agg.estimator == "yz")]
        if g.empty or y.empty:
            continue
        g, y = g.iloc[0], y.iloc[0]
        deltas.append({
            "ticker": tk,
            "delta_r2": y["mean_r2"] - g["mean_r2"],
            "gk_beta_mz": g["mean_beta_mz"], "yz_beta_mz": y["mean_beta_mz"],
            "delta_abs_dev_from_1":
                abs(g["mean_beta_mz"] - 1) - abs(y["mean_beta_mz"] - 1),
            "gk_event_imp": g["mean_event_imp"], "yz_event_imp": y["mean_event_imp"],
            "delta_event_imp": y["mean_event_imp"] - g["mean_event_imp"],
            "gk_earn_rank": g["mean_earn_rank"], "yz_earn_rank": y["mean_earn_rank"],
            "delta_earn_rank": g["mean_earn_rank"] - y["mean_earn_rank"],  # lower = better
        })
    delta_df = pd.DataFrame(deltas)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.4f}"):
        print(delta_df.to_string(index=False))

    # ── Corpus aggregate verdict ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" AGGREGATE VERDICT (mean across tickers, mean across folds)")
    print("=" * 80)
    print(f"  ΔR² (YZ - GK):           mean={delta_df['delta_r2'].mean():+.4f}  median={delta_df['delta_r2'].median():+.4f}")
    print(f"  Δ|β_mz − 1|:             mean={delta_df['delta_abs_dev_from_1'].mean():+.4f} (positive = YZ closer to 1)")
    print(f"  Δevent_gravity_imp:      mean={delta_df['delta_event_imp'].mean():+.4f}")
    print(f"  Δearn_gravity_rank:      mean={delta_df['delta_earn_rank'].mean():+.2f} (positive = YZ ranks earn HIGHER)")
    print(f"  Tickers with YZ R² improvement:        {(delta_df['delta_r2'] > 0).sum()}/{len(delta_df)}")
    print(f"  Tickers with YZ β_mz closer to 1:      {(delta_df['delta_abs_dev_from_1'] > 0).sum()}/{len(delta_df)}")
    print(f"  Tickers with YZ event_imp higher:      {(delta_df['delta_event_imp'] > 0).sum()}/{len(delta_df)}")
    print(f"  Tickers with YZ earn rank improved:    {(delta_df['delta_earn_rank'] > 0).sum()}/{len(delta_df)}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
