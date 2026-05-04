"""
stack_v9_canary.py — Stack the 12-ticker v9 canary predictions from SSD
(per-horizon old format) into a single long-form CSV matching v10+ schema.

Reads from H:\volarbmodel\model\pipeline\results\predictions_{TICKER}_H{h}.csv
(36 files, dated 2026-04-29 — the v9 canary on step_days=25), reshapes to
the long-form schema (date, y_true, y_pred, y_pred_q15, vrp_wedge,
put_call_skew_30d, ticker, horizon), and writes:

  model/pipeline/results/v9_canary_predictions.csv

Plus computes a v9 mz_calibration from these (raw OLS, since EW-weighted
mz_overlay.py would need to be run separately for true comparison):

  model/pipeline/results/v9_canary_mz_calibration.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
SSD = Path("H:/volarbmodel/model/pipeline/results")
TICKERS = ["AAPL", "AMZN", "BA", "C", "CVX", "GOOGL", "JPM",
           "NEE", "NFLX", "NVDA", "PG", "XOM"]
HORIZONS = (21, 63, 126)


def main():
    frames = []
    for tk in TICKERS:
        for h in HORIZONS:
            f = SSD / f"predictions_{tk}_H{h}.csv"
            if not f.exists():
                print(f"[STACK] missing {f.name}, skipping")
                continue
            df = pd.read_csv(f, parse_dates=["date"])
            df["ticker"] = tk
            df["horizon"] = h
            frames.append(df)
    if not frames:
        print("[STACK] no files found, abort.")
        return
    full = pd.concat(frames, ignore_index=True)
    # Reorder columns to match v10+ long-form schema where possible
    cols_pref = ["date", "y_true", "y_pred", "y_pred_q15", "vrp_wedge",
                 "put_call_skew_30d", "ticker", "horizon"]
    cols = [c for c in cols_pref if c in full.columns] + \
           [c for c in full.columns if c not in cols_pref]
    full = full[cols].sort_values(["ticker", "horizon", "date"]).reset_index(drop=True)
    full = round_for_output(full, DECIMAL_PRECISION)

    out = RESULTS_DIR / "v9_canary_predictions.csv"
    full.to_csv(out, index=False)
    print(f"[STACK] Wrote {out.name}: {len(full):,} rows, "
          f"{full['ticker'].nunique()} tickers")

    # Raw OLS MZ per (ticker, horizon)
    mz_rows = []
    for (tk, h), g in full.groupby(["ticker", "horizon"], observed=True):
        g = g.dropna(subset=["y_true", "y_pred"])
        g = g[(g["y_true"] > 0) & (g["y_pred"] > 0)]
        if len(g) < 30:
            continue
        yt = np.log(g["y_true"])
        yp = np.log(g["y_pred"])
        cov = np.cov(yt, yp, ddof=1)[0, 1]
        var = yp.var(ddof=1)
        if var <= 0:
            continue
        beta = cov / var
        alpha = yt.mean() - beta * yp.mean()
        r2 = float(np.corrcoef(yt, yp)[0, 1] ** 2)
        # Also compute exp-weighted MZ for parity with mz_overlay (lambda=0.003)
        n = len(g)
        w = np.exp(0.003 * np.arange(n))
        w = w / w.mean()
        wm_yp = (w * yp).sum() / w.sum()
        wm_yt = (w * yt).sum() / w.sum()
        ew_var = (w * (yp - wm_yp) ** 2).sum() / w.sum()
        ew_cov = (w * (yp - wm_yp) * (yt - wm_yt)).sum() / w.sum()
        ew_beta = ew_cov / ew_var if ew_var > 0 else float("nan")
        ew_alpha = wm_yt - ew_beta * wm_yp
        mz_rows.append({
            "ticker": tk,
            "horizon": int(h),
            "ols_alpha": float(alpha),
            "ols_beta": float(beta),
            "ols_r2": r2,
            "ew_alpha": float(ew_alpha),
            "ew_beta": float(ew_beta),
            "n": n,
        })
    mz_df = pd.DataFrame(mz_rows)
    mz_df = round_for_output(mz_df, DECIMAL_PRECISION)
    mz_path = RESULTS_DIR / "v9_canary_mz_calibration.csv"
    mz_df.to_csv(mz_path, index=False)
    print(f"[STACK] Wrote {mz_path.name}: {len(mz_df)} (ticker × horizon) rows")

    # Summary
    print()
    print("=== v9 canary MZ summary (12 tickers × 3 horizons = 36 rows) ===")
    for h in HORIZONS:
        sub = mz_df[mz_df["horizon"] == h]
        b_ols = sub["ols_beta"]
        b_ew = sub["ew_beta"]
        print(f"H={h:3d}: OLS mean={b_ols.mean():.3f} std={b_ols.std():.3f}  "
              f"EW mean={b_ew.mean():.3f} std={b_ew.std():.3f}  "
              f"in [0.7,1.3]: OLS {((b_ols>=0.7)&(b_ols<=1.3)).sum()}/{len(sub)}, "
              f"EW {((b_ew>=0.7)&(b_ew<=1.3)).sum()}/{len(sub)}")


if __name__ == "__main__":
    main()
