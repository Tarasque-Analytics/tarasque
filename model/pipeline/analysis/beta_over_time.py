"""
beta_over_time.py — Rolling MZ beta time series per ticker.

For each ticker we have predictions for, compute the OLS MZ beta on a rolling
252-BDay window of OOS predictions, stepped monthly. Plot beta vs time per
horizon with the [0.7, 1.3] target band shaded.

This answers: is the model's calibration stable, drifting, or improving over time?
A trail-into-band signal would mean the model is auto-correcting as it ingests
new data; a trail-out-of-band signal means structural drift that won't fix itself.

Inputs:
  predictions_{TICKER}.csv  (preferred — long-form)
  OR slice from all_predictions_cal.csv via --from-corpus

Outputs:
  model/pipeline/results/beta_over_time/{TICKER}_beta_ts.png
  model/pipeline/results/beta_over_time/{TICKER}_beta_ts.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "beta_over_time"

WINDOW_BD = 252
STEP = "ME"   # monthly snapshot
TARGET_BAND = (0.7, 1.3)


def rolling_mz(preds: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """One row per month-end snapshot: (asof, beta, alpha, r2, n)."""
    sub = preds[preds["horizon"] == horizon].sort_values("date").reset_index(drop=True)
    if sub.empty:
        return pd.DataFrame()
    end = sub["date"].max()
    start = sub["date"].min() + pd.Timedelta(days=380)  # need at least 1y warmup
    grid = pd.date_range(start=start, end=end, freq=STEP)
    rows = []
    for d in grid:
        window = sub[(sub["date"] <= d)].tail(WINDOW_BD)
        if len(window) < 60:
            continue
        y_t = np.log(window["y_true"].clip(lower=1e-6).values)
        y_p = np.log(window["y_pred"].clip(lower=1e-6).values)
        if np.std(y_p) == 0:
            continue
        beta = np.cov(y_t, y_p, ddof=1)[0, 1] / np.var(y_p, ddof=1)
        alpha = y_t.mean() - beta * y_p.mean()
        r2 = float(np.corrcoef(y_t, y_p)[0, 1] ** 2)
        rows.append({
            "asof": d.date(),
            "horizon": horizon,
            "beta": float(beta),
            "alpha": float(alpha),
            "r2": r2,
            "n": int(len(window)),
        })
    return pd.DataFrame(rows)


def plot_beta_ts(ticker: str, dfs: dict[int, pd.DataFrame], out_path: Path) -> None:
    """One panel per horizon, beta vs time, target band shaded."""
    horizons = sorted(dfs.keys())
    fig, axes = plt.subplots(len(horizons), 1, figsize=(13, 3.0 * len(horizons)),
                             sharex=True)
    if len(horizons) == 1:
        axes = [axes]
    colors = {21: "#1f77b4", 63: "#ff7f0e", 126: "#2ca02c"}

    for ax, h in zip(axes, horizons):
        df = dfs[h]
        if df.empty:
            ax.text(0.5, 0.5, f"no data H={h}", transform=ax.transAxes,
                    ha="center", va="center")
            continue
        df["asof_dt"] = pd.to_datetime(df["asof"])
        ax.fill_between(df["asof_dt"], TARGET_BAND[0], TARGET_BAND[1],
                        color="green", alpha=0.10,
                        label=f"target band [{TARGET_BAND[0]}, {TARGET_BAND[1]}]")
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6,
                   label="ideal β=1.0")
        ax.plot(df["asof_dt"], df["beta"], color=colors.get(h, "black"),
                linewidth=2.0, marker="o", markersize=3, label=f"β H={h}")

        # Highlight current value
        ax.scatter(df["asof_dt"].iloc[-1], df["beta"].iloc[-1], s=140,
                   facecolor="white", edgecolor=colors.get(h, "black"),
                   linewidth=2.0, zorder=5)
        ax.annotate(f"  current β={df['beta'].iloc[-1]:.2f}",
                    (df["asof_dt"].iloc[-1], df["beta"].iloc[-1]),
                    fontsize=10, fontweight="bold",
                    xytext=(8, 0), textcoords="offset points",
                    verticalalignment="center")

        ax.set_ylabel(f"MZ β (H={h})")
        ax.set_ylim(min(0, df["beta"].min() - 0.1),
                    max(2.0, df["beta"].max() + 0.1))
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.25)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    axes[-1].set_xlabel("Date")
    fig.suptitle(f"{ticker} — MZ β over time (rolling {WINDOW_BD}d window, monthly steps)",
                 fontsize=13, y=0.995)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[BETA_TS] {ticker}: wrote {out_path.name}")


def process_ticker(ticker: str, preds: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    horizons = sorted(preds["horizon"].unique())
    dfs = {}
    all_rows = []
    for h in horizons:
        df = rolling_mz(preds, h)
        if not df.empty:
            df.insert(0, "ticker", ticker)
            dfs[int(h)] = df
            all_rows.append(df)
    if not all_rows:
        return
    full = pd.concat(all_rows, ignore_index=True)
    full = round_for_output(full, DECIMAL_PRECISION)
    full.to_csv(OUT_DIR / f"{ticker}_beta_ts.csv", index=False)
    plot_beta_ts(ticker, dfs, OUT_DIR / f"{ticker}_beta_ts.png")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker", help="Single ticker (reads predictions_{TICKER}.csv)")
    g.add_argument("--from-corpus", help="Path to corpus CSV with all tickers stacked")
    args = ap.parse_args()

    if args.ticker:
        path = RESULTS_DIR / f"predictions_{args.ticker}.csv"
        if not path.exists():
            print(f"[BETA_TS] {path} not found.")
            return
        preds = pd.read_csv(path, parse_dates=["date"])
        process_ticker(args.ticker, preds)
    else:
        path = Path(args.from_corpus)
        if not path.is_absolute():
            path = REPO_ROOT / path
        df = pd.read_csv(path, parse_dates=["date"])
        for tk, g in df.groupby("ticker", observed=True):
            process_ticker(tk, g)


if __name__ == "__main__":
    main()
