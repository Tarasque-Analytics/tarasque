"""
assemble_results.py -- Rebuild all_predictions.csv and backtest_results.csv
from existing per-ticker prediction files.

Use after a partial run (e.g., 91/93 tickers complete) to build the
aggregate files without re-running the backtest.

Usage (from project root):
    python -m model.pipeline.assemble_results
    python -m model.pipeline.assemble_results --tickers AAPL JPM XOM
    python -m model.pipeline.assemble_results --exclude MSFT MU
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

RESULTS_DIR = Path("model/pipeline/results")

# Default: 91-ticker v8 production universe (93 minus MSFT and MU which hung)
DEFAULT_TICKERS = [
    "AAPL", "ABBV", "ABT",  "ADBE", "AEP",  "AMAT", "AMD",  "AMGN",
    "AMT",  "AMZN", "APD",  "AVGO", "AXP",  "BA",   "BAC",  "BKNG",
    "BLK",  "BMY",  "C",    "CAT",  "CCI",  "CL",   "CMCSA","COP",
    "COST", "CRM",  "CSCO", "CVS",  "CVX",  "D",    "DE",   "DIS",
    "DOW",  "DUK",  "EOG",  "EQIX", "F",    "FCX",  "FDX",  "GE",
    "GILD", "GM",   "GOOGL","GS",   "HD",   "HON",  "IBM",  "INTC",
    "JNJ",  "JPM",  "KO",   "LLY",  "LMT",  "LOW",  "MCD",
    "MMM",  "MO",   "MPC",  "MRK",  "MS",   "NEE",  "NEM",
    "NFLX", "NKE",  "NOC",  "NVDA", "ORCL", "PEP",  "PFE",
    "PG",   "PLD",  "PM",   "PSX",  "QCOM", "RTX",  "SBUX",
    "SCHW", "SLB",  "SO",   "SPG",  "T",    "TGT",  "TMO",
    "TSLA", "TXN",  "UNH",  "UPS",  "USB",  "WFC",  "WMT",  "XOM",
]
HORIZONS = [21, 63, 126]


def _compute_metrics(pred_df: pd.DataFrame, horizon: int) -> dict:
    y_true = np.clip(pred_df["y_true"].values.astype(float), 1e-6, None)
    y_pred = np.clip(pred_df["y_pred"].values.astype(float), 1e-6, None)

    lr = LinearRegression()
    lr.fit(y_pred.reshape(-1, 1), y_true)

    ratio = y_true / y_pred
    qlike = float(np.mean(ratio - np.log(ratio) - 1))

    # Event capture: fraction of >=2sigma events where model predicted above-mean
    mean_true = np.mean(y_true)
    std_true  = np.std(y_true)
    event_mask = y_true >= (mean_true + 2 * std_true)
    if std_true > 1e-6 and event_mask.sum() > 0:
        event_capture = float(np.mean(y_pred[event_mask] > mean_true))
    else:
        event_capture = float("nan")

    row = {
        "rmse":           float(np.sqrt(np.mean((y_true - y_pred) ** 2))),
        "mz_alpha":       float(lr.intercept_),
        "mz_beta":        float(lr.coef_[0]),
        "mz_r2":          float(lr.score(y_pred.reshape(-1, 1), y_true)),
        "qlike":          qlike,
        "event_capture":  event_capture,
        "n_predictions":  len(y_true),
    }

    # Quantile cols (y_pred_q15, y_pred_q85, etc.)
    for col in pred_df.columns:
        if not col.startswith("y_pred_q"):
            continue
        try:
            tau_pct = int(col.replace("y_pred_q", ""))
        except ValueError:
            continue
        tau = tau_pct / 100.0
        q_vals = pred_df[col].values.astype(float)
        valid = np.isfinite(q_vals) & (q_vals > 0)
        if valid.sum() > 20:
            q  = np.clip(q_vals[valid], 1e-6, None)
            yt = y_true[valid]
            diff    = yt - q
            pinball = np.where(diff >= 0, tau * diff, (tau - 1) * diff)
            row[f"pinball_q{tau_pct}"] = float(np.mean(pinball))
            row[f"coverage_q{tau_pct}"] = float(np.mean(yt > q))

    return row


def assemble(tickers: list, horizons: list = HORIZONS, verbose: bool = True):
    all_pred_frames = []
    all_metrics = []
    missing = []

    for ticker in tickers:
        for h in horizons:
            path = RESULTS_DIR / f"predictions_{ticker}_H{h}.csv"
            if not path.exists():
                missing.append(f"{ticker}_H{h}")
                continue
            df = pd.read_csv(path)
            df["ticker"]  = ticker
            df["horizon"] = h
            all_pred_frames.append(df)

            metrics = _compute_metrics(df, h)
            metrics["ticker"]  = ticker
            metrics["horizon"] = h
            all_metrics.append(metrics)

        if verbose:
            print(f"  {ticker}: OK")

    if missing:
        print(f"\n[WARN] {len(missing)} missing files skipped: {missing}")

    if not all_pred_frames:
        print("[ERROR] No prediction files found. Check RESULTS_DIR.")
        return

    combined = pd.concat(all_pred_frames, ignore_index=True)
    out_pred = RESULTS_DIR / "all_predictions.csv"
    combined.to_csv(out_pred, index=False)
    print(f"\n[OK] all_predictions.csv written: {len(combined):,} rows, {combined['ticker'].nunique()} tickers")

    summary = pd.DataFrame(all_metrics)
    col_order = ["ticker", "horizon", "rmse", "mz_alpha", "mz_beta", "mz_r2",
                 "qlike", "event_capture", "n_predictions"]
    # add any quantile cols that appeared
    extra_cols = [c for c in summary.columns if c not in col_order]
    summary = summary[[c for c in col_order if c in summary.columns] + extra_cols]
    out_br = RESULTS_DIR / "backtest_results.csv"
    summary.to_csv(out_br, index=False)
    print(f"[OK] backtest_results.csv written: {len(summary)} rows")

    # Quick portfolio summary
    for h in horizons:
        sub = summary[summary["horizon"] == h]
        if sub.empty:
            continue
        print(f"\n  H={h:3d}: N={len(sub):3d} | mean_beta={sub['mz_beta'].mean():.3f} "
              f"| med_beta={sub['mz_beta'].median():.3f} "
              f"| mean_R2={sub['mz_r2'].mean():.3f} "
              f"| mean_RMSE={sub['rmse'].mean():.4f}")
        q_col = "coverage_q15"
        if q_col in sub.columns:
            print(f"          coverage_q15={sub[q_col].mean():.3f} "
                  f"(target=0.85, i.e. 85pct of y_true > floor)")


def main():
    parser = argparse.ArgumentParser(description="Assemble all_predictions + backtest_results from per-ticker CSVs")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Explicit ticker list (default: 91-ticker production universe)")
    parser.add_argument("--exclude", nargs="+", default=None,
                        help="Tickers to exclude from default list")
    args = parser.parse_args()

    tickers = args.tickers if args.tickers else list(DEFAULT_TICKERS)
    if args.exclude:
        tickers = [t for t in tickers if t not in args.exclude]

    print(f"Assembling results for {len(tickers)} tickers x {HORIZONS} horizons...")
    assemble(tickers)


if __name__ == "__main__":
    main()
