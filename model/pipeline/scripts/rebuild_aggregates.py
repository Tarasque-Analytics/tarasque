"""
rebuild_aggregates.py — Merge per-ticker outputs from a multi-machine corpus run
into the single-host aggregate files the analysis pipeline expects.

Usage scenarios:
  1. Single-machine corpus run produced one aggregate already — re-run is a no-op
     but verifies integrity.
  2. 4-machine corpus run produced N per-ticker CSVs in `model/pipeline/results/`
     after rsync — this script rebuilds:
       - all_predictions.csv     (concat of predictions_*.csv)
       - backtest_results.csv    (recompute metrics per ticker × horizon)

Produces no new schema; just stitches per-ticker files into the corpus aggregates
that mz_overlay / signal_strength / audit / etc. read from.

Run:
    python -m model.pipeline.scripts.rebuild_aggregates
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"


def compute_metrics(df: pd.DataFrame) -> dict:
    """Standard metrics (RMSE, MZ_beta, MZ_R2, QLIKE) per ticker × horizon."""
    df = df.dropna(subset=["y_true", "y_pred"])
    df = df[(df["y_true"] > 0) & (df["y_pred"] > 0)]
    if len(df) < 30:
        return {"rmse": np.nan, "mz_beta": np.nan, "mz_r2": np.nan,
                "qlike": np.nan, "n": len(df)}
    y, p = df["y_true"].values, df["y_pred"].values
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    yl, pl = np.log(y), np.log(p)
    var = np.var(pl, ddof=1)
    mz_beta = float(np.cov(yl, pl, ddof=1)[0, 1] / var) if var > 0 else np.nan
    mz_r2 = float(np.corrcoef(yl, pl)[0, 1] ** 2)
    # QLIKE: mean( y/p - log(y/p) - 1 ) -- variance-form, scale-free
    ratio = (y ** 2) / (p ** 2)
    qlike = float(np.mean(ratio - np.log(ratio) - 1))
    return {"rmse": rmse, "mz_beta": mz_beta, "mz_r2": mz_r2,
            "qlike": qlike, "n": int(len(df))}


def main():
    pred_files = sorted(RESULTS_DIR.glob("predictions_*.csv"))
    if not pred_files:
        print("[REBUILD] No predictions_*.csv files found — nothing to rebuild.")
        return

    print(f"[REBUILD] Stitching {len(pred_files)} per-ticker prediction files...")
    frames = []
    metrics_rows = []
    for f in pred_files:
        try:
            df = pd.read_csv(f, parse_dates=["date"])
        except Exception as e:
            print(f"[REBUILD] {f.name}: failed to read ({e}); skipping")
            continue
        if "ticker" not in df.columns or "horizon" not in df.columns:
            print(f"[REBUILD] {f.name}: missing required cols; skipping")
            continue
        frames.append(df)
        for (tk, h), g in df.groupby(["ticker", "horizon"], observed=True):
            row = {"ticker": tk, "horizon": int(h), **compute_metrics(g)}
            metrics_rows.append(row)

    if not frames:
        print("[REBUILD] No usable per-ticker frames; abort.")
        return

    all_preds = pd.concat(frames, ignore_index=True)
    all_preds = all_preds.sort_values(["ticker", "horizon", "date"])
    all_preds = round_for_output(all_preds, DECIMAL_PRECISION)
    out_pred = RESULTS_DIR / "all_predictions.csv"
    all_preds.to_csv(out_pred, index=False)
    print(f"[REBUILD] Wrote {out_pred.name}: {len(all_preds):,} rows, "
          f"{all_preds['ticker'].nunique()} tickers")

    metrics = pd.DataFrame(metrics_rows).sort_values(["ticker", "horizon"])
    metrics = round_for_output(metrics, DECIMAL_PRECISION)
    out_m = RESULTS_DIR / "backtest_results.csv"
    metrics.to_csv(out_m, index=False)
    print(f"[REBUILD] Wrote {out_m.name}: {len(metrics)} (ticker × horizon) rows")

    # Quick summary: how does the corpus look at a glance?
    print()
    print("=== Corpus calibration summary ===")
    for h in sorted(metrics["horizon"].unique()):
        sub = metrics[metrics["horizon"] == h].dropna(subset=["mz_beta"])
        b = sub["mz_beta"]
        in_band = ((b >= 0.7) & (b <= 1.3)).sum()
        print(f"  H={int(h):3d}: mean beta={b.mean():.3f} std={b.std():.3f}  "
              f"R2={sub['mz_r2'].mean():.3f}  in [0.7,1.3]: {in_band}/{len(sub)}")


if __name__ == "__main__":
    main()
