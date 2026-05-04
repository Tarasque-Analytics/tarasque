"""
wedge_price_panel.py — Two-panel visualization: price history + EWMA of VRP wedge.

VRP wedge = iv_atm_30d - rv_TARGET (volatility risk premium).
- Wedge > 0: options market is pricing in MORE vol than realized (premium for hedging)
- Wedge < 0: options market UNDER-pricing realized vol (rare; usually after surprise spikes)

EWMA at multiple decay rates surfaces:
- 21d EWMA: tactical/recent shifts
- 63d EWMA: regime changes
- 126d EWMA: structural baseline

Pattern hypotheses to look for:
1. Wedge expansion BEFORE price drawdown → options market sniffs risk first
2. Wedge compression DURING rally → realized vol catches up to elevated IV
3. Sustained negative wedge → IV materially under-pricing risk (entry signal?)

Outputs:
  model/pipeline/results/wedge_panels/{TICKER}_wedge_panel.png

Run:
    python -m model.pipeline.analysis.wedge_price_panel --ticker AAPL
    python -m model.pipeline.analysis.wedge_price_panel --tickers AAPL TSLA KO NVDA
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from ..config import load_config
from ..data_loader import ParquetStore


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS / "wedge_panels"
EWMA_SPANS = (21, 63, 126)


def load_ticker_panel(ticker: str) -> Optional[pd.DataFrame]:
    """Join price (from OHLCV) + vrp_wedge (from predictions) on date index."""
    pred_path = RESULTS / f"predictions_{ticker}.csv"
    if not pred_path.exists():
        # Try v9 SSD canary stacked file
        ssd_combined = RESULTS / "v9_canary_predictions.csv"
        if ssd_combined.exists():
            df = pd.read_csv(ssd_combined, parse_dates=["date"])
            df = df[(df["ticker"] == ticker) & (df["horizon"] == 21)]
        else:
            print(f"[WEDGE] No predictions found for {ticker}")
            return None
    else:
        df = pd.read_csv(pred_path, parse_dates=["date"])
        df = df[df["horizon"] == 21]

    if df.empty or "vrp_wedge" not in df.columns:
        print(f"[WEDGE] {ticker}: no H=21 predictions or no vrp_wedge column")
        return None

    df = df.sort_values("date").reset_index(drop=True)
    df = df[["date", "y_true", "y_pred", "vrp_wedge"]].dropna(subset=["vrp_wedge"])
    if len(df) < 100:
        return None

    # Bring in closing price from OHLCV
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv", tickers=[ticker])
    if ohlcv.empty:
        print(f"[WEDGE] {ticker}: no OHLCV in cache")
        return None
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = (ohlcv[ohlcv["ticker"] == ticker][["date", "prc"]]
             .rename(columns={"prc": "close"})
             .sort_values("date"))
    df = df.merge(ohlcv, on="date", how="left")
    return df


def add_ewma(df: pd.DataFrame) -> pd.DataFrame:
    for span in EWMA_SPANS:
        df[f"wedge_ewma_{span}d"] = df["vrp_wedge"].ewm(span=span, adjust=False).mean()
    return df


def find_wedge_extremes(df: pd.DataFrame, ewma_col: str = "wedge_ewma_21d",
                         z_threshold: float = 2.0) -> pd.DataFrame:
    """Mark dates where the wedge EWMA is >z_threshold standard deviations from its mean."""
    s = df[ewma_col]
    z = (s - s.expanding(min_periods=252).mean()) / s.expanding(min_periods=252).std()
    df = df.copy()
    df["wedge_z"] = z
    df["extreme_high"] = z > z_threshold
    df["extreme_low"] = z < -z_threshold
    return df


def plot_panel(ticker: str, df: pd.DataFrame, out_path: Path) -> None:
    """3-panel: price, wedge EWMAs, wedge z-score with extremes marked."""
    fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True,
                              gridspec_kw={"height_ratios": [3, 2, 1.5]})

    # Panel 1: closing price
    ax1 = axes[0]
    ax1.plot(df["date"], df["close"], color="black", linewidth=1.0,
             label=f"{ticker} close")
    ax1.set_ylabel("Price ($)")
    ax1.set_title(f"{ticker} — Price + EWMA of VRP Wedge", fontsize=13)
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Panel 2: wedge + EWMAs
    ax2 = axes[1]
    ax2.plot(df["date"], df["vrp_wedge"], color="lightgray", linewidth=0.5,
             alpha=0.6, label="raw wedge")
    colors = {"21": "#1f77b4", "63": "#ff7f0e", "126": "#2ca02c"}
    for span in EWMA_SPANS:
        col = f"wedge_ewma_{span}d"
        ax2.plot(df["date"], df[col], color=colors[str(span)], linewidth=1.5,
                 alpha=0.85, label=f"EWMA {span}d")
    ax2.axhline(0, color="black", linewidth=0.7, alpha=0.5)
    ax2.set_ylabel("VRP wedge\n(IV - RV)")
    ax2.legend(loc="upper left", fontsize=9, ncol=4)
    ax2.grid(True, alpha=0.3)

    # Panel 3: z-score with extremes
    ax3 = axes[2]
    if "wedge_z" in df.columns:
        ax3.plot(df["date"], df["wedge_z"], color="purple", linewidth=0.9,
                 label="21d EWMA z-score")
        ax3.axhline(2.0, color="red", linestyle="--", alpha=0.4, linewidth=0.7)
        ax3.axhline(-2.0, color="red", linestyle="--", alpha=0.4, linewidth=0.7)
        ax3.axhline(0, color="black", linewidth=0.5, alpha=0.5)
        # Mark extreme dates with vertical lines
        for _, r in df[df["extreme_high"]].iterrows():
            ax3.axvline(r["date"], color="red", alpha=0.15, linewidth=0.5)
        for _, r in df[df["extreme_low"]].iterrows():
            ax3.axvline(r["date"], color="green", alpha=0.15, linewidth=0.5)
    ax3.set_ylabel("Wedge z-score")
    ax3.set_xlabel("Date")
    ax3.legend(loc="upper left", fontsize=9)
    ax3.grid(True, alpha=0.3)

    for ax in axes:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"[WEDGE] {ticker}: wrote {out_path.name}")


def analyze_pattern(ticker: str, df: pd.DataFrame) -> dict:
    """Compute lead/lag stats: does wedge change predict price movement?"""
    df = df.copy()
    df["close_ret_21d_fwd"] = df["close"].pct_change(21).shift(-21)
    df["close_dd_42d_fwd"] = (df["close"].rolling(42).min().shift(-42) /
                                df["close"] - 1)
    df["wedge_chg_21d"] = df["wedge_ewma_21d"].diff(21)
    sub = df.dropna(subset=["close_ret_21d_fwd", "wedge_chg_21d"])
    if len(sub) < 100:
        return {}
    # Correlation between wedge change and forward return
    corr_ret = sub["wedge_chg_21d"].corr(sub["close_ret_21d_fwd"])
    corr_dd = sub.dropna(subset=["close_dd_42d_fwd"])
    corr_dd_val = (corr_dd["wedge_chg_21d"].corr(corr_dd["close_dd_42d_fwd"])
                   if len(corr_dd) > 100 else float("nan"))
    # Forward returns conditioned on wedge in top/bottom decile
    p10, p90 = sub["wedge_ewma_21d"].quantile([0.10, 0.90]).values
    high_ret = sub.loc[sub["wedge_ewma_21d"] > p90, "close_ret_21d_fwd"].mean()
    low_ret = sub.loc[sub["wedge_ewma_21d"] < p10, "close_ret_21d_fwd"].mean()
    base_ret = sub["close_ret_21d_fwd"].mean()
    return {
        "ticker": ticker,
        "n_obs": len(sub),
        "corr_wedge_chg_to_fwd_ret_21d": float(corr_ret),
        "corr_wedge_chg_to_fwd_dd_42d": float(corr_dd_val),
        "fwd_ret_when_wedge_top_decile": float(high_ret),
        "fwd_ret_when_wedge_bottom_decile": float(low_ret),
        "fwd_ret_baseline": float(base_ret),
        "spread_top_minus_bottom": float(high_ret - low_ret),
    }


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker", help="Single ticker")
    g.add_argument("--tickers", nargs="+", help="Multiple tickers")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tickers = [args.ticker] if args.ticker else args.tickers

    pattern_rows = []
    for tk in tickers:
        df = load_ticker_panel(tk)
        if df is None:
            continue
        df = add_ewma(df)
        df = find_wedge_extremes(df)
        plot_panel(tk, df, OUT_DIR / f"{tk}_wedge_panel.png")
        stats = analyze_pattern(tk, df)
        if stats:
            pattern_rows.append(stats)

    if pattern_rows:
        summary = pd.DataFrame(pattern_rows)
        out = OUT_DIR / "wedge_pattern_summary.csv"
        summary.to_csv(out, index=False)
        print()
        print("=== Wedge -> forward-return pattern stats ===")
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
