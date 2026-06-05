"""
yz_vs_gk_poc.py — POC: train per-ticker XGB with vol_estimator in {gk, yz}
                   and compare key metrics.

Designed to answer: does switching the target from GK to YZ make event_gravity
features structurally meaningful? Does β_mz move closer to 1.0? Does the model
forecast its own target better?

Each ticker gets two trainings:
  - GK target: features built with GK rv_*, target = GK rv_TARGET shifted +21
  - YZ target: features built with YZ rv_*, target = YZ rv_TARGET shifted +21

XGB only (no full ensemble) for speed. Per-ticker train: 2-5 seconds.
5 tickers × 2 estimators = ~30 sec total.

Outputs:
  results/validation/yz_vs_gk_poc.csv
  prints comparison tables
"""
from __future__ import annotations

from pathlib import Path

import warnings
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

from ..config import load_config
from ..data_loader import fetch_dataset
from ..features import FeatureBuilder

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

POC_TICKERS = ["AAPL", "JPM", "XOM", "NVDA", "KO"]
EVAL_CUTOFF = pd.Timestamp("2025-05-27")
HORIZON = 21

# Features we particularly care about — should rise under YZ if hypothesis holds
EVENT_FEATURES = ["event_earn_gravity", "event_fed_gravity", "event_div_gravity",
                  "event_cpi_gravity", "event_nfp_gravity"]


def build_train_pred(ticker: str, dc, mc, bc, raw_data, estimator: str) -> dict:
    """Build features with given estimator, train XGB, evaluate on last year."""
    # Temporarily set estimator on a copy of mc-like config
    mc.vol_estimator = estimator
    builder = FeatureBuilder(dc, mc)
    try:
        fdf = builder.build(ticker, raw_data, drop_nan_targets=False)
    except Exception as e:
        return {"status": "feat_fail", "error": str(e)}

    target_col = "rv_TARGET"
    if target_col not in fdf.columns:
        return {"status": "no_target", "error": "rv_TARGET missing"}

    # Forward H=21 target: shift rv_TARGET by -h
    fdf["y_h21"] = fdf[target_col].shift(-HORIZON)
    fdf.index = pd.to_datetime(fdf.index)

    # Predictor selection: drop target cols and obviously leaky cols
    drop = {"y_h21", "rv_TARGET", "rv_21d"}  # rv_21d == rv_TARGET; lookahead via shift
    predictors = [c for c in fdf.columns
                  if c not in drop
                  and pd.api.types.is_numeric_dtype(fdf[c])
                  and not c.startswith("y_")]

    train = fdf[fdf.index <  EVAL_CUTOFF].dropna(subset=["y_h21"])
    test  = fdf[fdf.index >= EVAL_CUTOFF].dropna(subset=["y_h21"])
    if len(train) < 500 or len(test) < 20:
        return {"status": "insufficient", "n_train": len(train), "n_test": len(test)}

    X_tr = train[predictors].ffill().bfill().fillna(0).values
    y_tr = train["y_h21"].values
    X_te = test[predictors].ffill().bfill().fillna(0).values
    y_te = test["y_h21"].values

    model = XGBRegressor(n_estimators=300, max_depth=5, learning_rate=0.05,
                         tree_method="hist", device="cpu", n_jobs=4,
                         verbosity=0)
    model.fit(X_tr, y_tr)
    y_pred = model.predict(X_te)

    # Metrics
    ss_res = float(((y_te - y_pred) ** 2).sum())
    ss_tot = float(((y_te - y_te.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    rmse = float(np.sqrt(((y_te - y_pred) ** 2).mean()))

    # β_mz: log-log MZ regression on test predictions
    yt_log = np.log(np.clip(y_te, 1e-6, None))
    yp_log = np.log(np.clip(y_pred, 1e-6, None))
    cov_mz = float(np.cov(yt_log, yp_log, ddof=1)[0, 1])
    var_mz = float(np.var(yp_log, ddof=1))
    beta_mz = cov_mz / var_mz if var_mz > 0 else np.nan

    # Feature importance
    imp = pd.Series(model.feature_importances_, index=predictors)
    imp_sorted = imp.sort_values(ascending=False)
    event_imps = {f: float(imp.get(f, 0)) for f in EVENT_FEATURES if f in imp.index}
    event_total = sum(event_imps.values())
    event_rank_top10 = {f: int(np.argwhere(imp_sorted.index == f).flatten()[0]) + 1
                        for f in EVENT_FEATURES if f in imp_sorted.index}

    return {
        "status": "ok",
        "estimator": estimator,
        "ticker": ticker,
        "n_train": len(train),
        "n_test": len(test),
        "test_r2": r2,
        "test_rmse": rmse,
        "test_beta_mz_loglog": beta_mz,
        "event_gravity_total_importance": event_total,
        "event_earn_gravity_imp": event_imps.get("event_earn_gravity", 0.0),
        "event_earn_gravity_rank": event_rank_top10.get("event_earn_gravity", -1),
        "event_fed_gravity_imp": event_imps.get("event_fed_gravity", 0.0),
        "event_fed_gravity_rank": event_rank_top10.get("event_fed_gravity", -1),
        "top10_features": list(imp_sorted.head(10).index),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dc, mc, bc = load_config()
    raw = fetch_dataset(dc)

    rows = []
    for ticker in POC_TICKERS:
        print(f"\n[YZGK_POC] === {ticker} ===")
        for estimator in ("gk", "yz"):
            r = build_train_pred(ticker, dc, mc, bc, raw, estimator)
            if r.get("status") != "ok":
                print(f"  [{estimator}] {r}")
                continue
            print(f"  [{estimator}] R2={r['test_r2']:+.3f}  beta_mz={r['test_beta_mz_loglog']:+.3f}  "
                  f"earn_grav_imp={r['event_earn_gravity_imp']:.4f} "
                  f"rank={r['event_earn_gravity_rank']}")
            rows.append(r)

    if not rows:
        print("[YZGK_POC] No results.")
        return 1

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "yz_vs_gk_poc.csv", index=False)

    print("\n" + "=" * 80)
    print(" SUMMARY: GK vs YZ target — per ticker test metrics")
    print("=" * 80)
    cmp_cols = ["ticker", "estimator", "test_r2", "test_beta_mz_loglog",
                "event_gravity_total_importance", "event_earn_gravity_imp",
                "event_earn_gravity_rank"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.4f}"):
        print(df[cmp_cols].to_string(index=False))

    # Per-ticker side-by-side deltas
    print("\n" + "=" * 80)
    print(" PER-TICKER: GK vs YZ deltas (positive = YZ improves)")
    print("=" * 80)
    deltas = []
    for tk in df["ticker"].unique():
        gk_row = df[(df.ticker == tk) & (df.estimator == "gk")]
        yz_row = df[(df.ticker == tk) & (df.estimator == "yz")]
        if gk_row.empty or yz_row.empty:
            continue
        g, y = gk_row.iloc[0], yz_row.iloc[0]
        deltas.append({
            "ticker": tk,
            "delta_r2": y["test_r2"] - g["test_r2"],
            "gk_beta_mz": g["test_beta_mz_loglog"],
            "yz_beta_mz": y["test_beta_mz_loglog"],
            "delta_beta_mz_toward_1": abs(g["test_beta_mz_loglog"] - 1) - abs(y["test_beta_mz_loglog"] - 1),
            "gk_event_imp": g["event_gravity_total_importance"],
            "yz_event_imp": y["event_gravity_total_importance"],
            "delta_event_imp": y["event_gravity_total_importance"] - g["event_gravity_total_importance"],
            "gk_earn_rank": int(g["event_earn_gravity_rank"]),
            "yz_earn_rank": int(y["event_earn_gravity_rank"]),
        })
    delta_df = pd.DataFrame(deltas)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.4f}"):
        print(delta_df.to_string(index=False))

    # Aggregate verdict
    print("\n" + "=" * 80)
    print(" AGGREGATE VERDICT (5-ticker mean)")
    print("=" * 80)
    print(f"  mean ΔR² (YZ − GK):                    {delta_df['delta_r2'].mean():+.4f}")
    print(f"  mean β_mz absolute deviation from 1:")
    print(f"    GK: {(delta_df['gk_beta_mz'] - 1).abs().mean():+.4f}")
    print(f"    YZ: {(delta_df['yz_beta_mz'] - 1).abs().mean():+.4f}")
    print(f"    improvement: {delta_df['delta_beta_mz_toward_1'].mean():+.4f}")
    print(f"  mean Δevent_gravity_total_importance:  {delta_df['delta_event_imp'].mean():+.4f}")
    print(f"  mean Δearn_gravity_rank (YZ better=lower):")
    print(f"    GK avg rank: {delta_df['gk_earn_rank'].mean():.1f}")
    print(f"    YZ avg rank: {delta_df['yz_earn_rank'].mean():.1f}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
