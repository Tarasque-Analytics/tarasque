"""
vrp_long_horizon_r2_recompute.py -- Recompute R^2 honestly.

The prior long-horizon test reported POOLED R^2 across all (ticker, date), which
inflates by absorbing between-stock variance (high-vol stocks are trivially
predicted high). The honest forecasting R^2 is the WITHIN-TICKER R^2 -- how much
of each stock's time-series variation in forward vol the model explains.

Reports four R^2 variants per (model, horizon):
  - POOLED         (1 - sum(y-p)^2 / sum(y - global_mean(y))^2) -- inflated
  - DEMEANED       within-stock pooled (both y, p demeaned by their ticker mean)
  - PER-TICKER MED median of per-stock OOS R^2
  - PER-TICKER MEAN
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import RESULTS_DIR
from .vrp_har_baseline_compare import daily_gk_rv, har_walk_forward
from .vrp_long_horizon_test import build_panel_h, load_iv_term, HORIZON_TO_IV_DAYS

OUT_DIR = RESULTS_DIR / "validation"
HORIZONS = [21, 63, 126]


def r2_pooled(y: np.ndarray, p: np.ndarray) -> float:
    m = np.isfinite(y) & np.isfinite(p)
    y, p = y[m], p[m]
    if len(y) < 30: return np.nan
    sst = float(np.sum((y - y.mean()) ** 2))
    sse = float(np.sum((y - p) ** 2))
    return 1.0 - sse / sst if sst > 0 else np.nan


def r2_demeaned_pooled(df: pd.DataFrame, ycol: str, pcol: str) -> float:
    """Within-stock pooled R^2: both y and p demeaned by per-ticker mean of y."""
    d = df.dropna(subset=[ycol, pcol]).copy()
    if len(d) < 30: return np.nan
    mu = d.groupby("ticker")[ycol].transform("mean")
    y_dm = (d[ycol] - mu).to_numpy(float)
    p_dm = (d[pcol] - mu).to_numpy(float)
    sst = float(np.sum(y_dm ** 2))
    sse = float(np.sum((y_dm - p_dm) ** 2))
    return 1.0 - sse / sst if sst > 0 else np.nan


def r2_per_ticker(df: pd.DataFrame, ycol: str, pcol: str, min_n: int = 60) -> pd.Series:
    def _r2(g):
        y = g[ycol].to_numpy(float); p = g[pcol].to_numpy(float)
        m = np.isfinite(y) & np.isfinite(p)
        y, p = y[m], p[m]
        if len(y) < min_n: return np.nan
        sst = float(np.sum((y - y.mean()) ** 2))
        sse = float(np.sum((y - p) ** 2))
        return 1.0 - sse / sst if sst > 0 else np.nan
    return df.groupby("ticker").apply(_r2, include_groups=False).dropna()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    iv_term = load_iv_term()
    print("[VRP_R2] Computing daily GK RV per ticker (HAR features)...")
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    rv_panel = {tk: daily_gk_rv(
                    g.sort_values("date").set_index("date")[["askhi","bidlo","prc","openprc"]])
                for tk, g in oh.drop_duplicates(["date","ticker"]).groupby("ticker", observed=True)}

    rows = []
    for h in HORIZONS:
        print(f"\n[VRP_R2] === HORIZON h={h} BD ===")
        panel = build_panel_h(h).dropna(subset=["y_true", "y_pred"])
        # HAR walk-forward
        har = []
        for tk, sub in panel.groupby("ticker"):
            if tk not in rv_panel: continue
            preds = har_walk_forward(rv_panel[tk], sub.set_index("date")["y_true"].sort_index(),
                                      retrain_step=21, min_train=252, purge=h)
            for d, v in preds.dropna().items():
                har.append({"ticker": tk, "date": d, "y_pred_har": float(v)})
        har_df = pd.DataFrame(har)
        iv_col = f"iv_{HORIZON_TO_IV_DAYS[h]}d"
        pp = panel.merge(iv_term[["ticker","date", iv_col]].rename(columns={iv_col: "iv"}),
                         on=["ticker","date"], how="inner") \
                  .merge(har_df, on=["ticker","date"], how="inner") \
                  .dropna(subset=["iv","y_true","y_pred","y_pred_har"])
        print(f"  n_obs={len(pp):,}  n_tickers={pp['ticker'].nunique()}")

        for model_name, pcol in [("ENSEMBLE", "y_pred"), ("HAR     ", "y_pred_har")]:
            r2_pool = r2_pooled(pp["y_true"].to_numpy(), pp[pcol].to_numpy())
            r2_dm = r2_demeaned_pooled(pp, "y_true", pcol)
            ptr = r2_per_ticker(pp, "y_true", pcol)
            print(f"\n  {model_name} R^2 variants at h={h}:")
            print(f"    POOLED (inflated)          : {r2_pool:+.3f}")
            print(f"    DEMEANED pooled (within)   : {r2_dm:+.3f}     <- HONEST FORECASTING R^2")
            print(f"    PER-TICKER median          : {ptr.median():+.3f}")
            print(f"    PER-TICKER mean            : {ptr.mean():+.3f}")
            print(f"    per-ticker dist: p25 {ptr.quantile(.25):+.3f}  p75 {ptr.quantile(.75):+.3f}  "
                  f"% positive {(ptr>0).mean():.0%}")
            rows.append({"horizon": h, "model": model_name.strip(),
                         "pooled": r2_pool, "demeaned": r2_dm,
                         "perticker_median": float(ptr.median()),
                         "perticker_mean": float(ptr.mean()),
                         "perticker_p25": float(ptr.quantile(.25)),
                         "perticker_p75": float(ptr.quantile(.75)),
                         "pct_positive": float((ptr > 0).mean()),
                         "n_tickers": int(len(ptr))})

    sm = pd.DataFrame(rows)
    print("\n" + "=" * 90)
    print(" SUMMARY -- proper within-ticker R^2 by horizon")
    print("=" * 90)
    print(sm.pivot_table(index="horizon", columns="model",
                         values=["pooled", "demeaned", "perticker_median"]).to_string())
    sm.to_csv(OUT_DIR / "vrp_long_horizon_r2_recompute.csv", index=False)
    print("\n[VRP_R2] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
