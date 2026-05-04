"""
regime_trail.py — Slug-trail visualization of ticker drift through regime space.

Each ticker traces a path through the (beta_mkt, beta_mz) plane at quarterly
snapshots over the last N quarters. The most recent point is the head; older
points fade and shrink. Direction = where the ticker is heading; speed =
distance between consecutive snapshots.

Conceptual frame:
  - Trail entirely inside Q3 (low mkt beta, low MZ beta): structurally calm name.
  - Trail crossing from Q3 → Q1 (low mkt beta, MZ beta drifting > 1.0):
    "stealth event-risk emerging" — the model is starting to miss vol that
    standard market metrics don't see.
  - Trail crossing from Q4 → Q2 (over-forecast → under-forecast on a high-beta
    name): regime change in name-specific shock clustering.

Inputs:
  - model/pipeline/results/predictions_{TICKER}.csv  (long-form, all horizons)
  - data_cache/ohlcv parquet                         (for rolling beta_mkt)

For each (ticker, quarter_end) we compute:
  beta_mkt_252d = cov(r_t, r_spy) / var(r_spy) over the 252 BDays ending at quarter_end
  beta_mz_h21   = OLS slope of y_true on y_pred over predictions ending at quarter_end
                  using a rolling 252-BDay tail of OOS predictions

Outputs:
  model/pipeline/results/regime_trail/{TICKER}_trail.csv   per-quarter coordinates
  model/pipeline/results/regime_trail/{TICKER}_trail.png   slug-trail figure
  model/pipeline/results/regime_trail/regime_trail_overview.png   corpus overlay

Run:
    python -m model.pipeline.analysis.regime_trail --ticker AAPL
    python -m model.pipeline.analysis.regime_trail --all
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe

from ..config import load_config
from ..data_loader import ParquetStore
from ..utils import DECIMAL_PRECISION, round_for_output


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "regime_trail"

N_SNAPSHOTS = 24       # 24 monthly snapshots = 2 years of trail
BETA_WINDOW_BD = 252   # 1 year rolling for both beta_mkt and beta_mz
HORIZON_PRIMARY = 21


def snapshot_dates(end_date: pd.Timestamp, n: int) -> list[pd.Timestamp]:
    """Last n monthly-end snapshots on or before end_date (most recent last).

    Monthly density makes the slug-trail visible — quarterly was too sparse
    to read direction at a glance.
    """
    ends = pd.date_range(end=end_date, periods=n, freq="ME")
    return list(ends)


def beta_mkt_at(closes: pd.DataFrame, ticker: str, asof: pd.Timestamp,
                window_bd: int = BETA_WINDOW_BD, mkt: str = "SPY") -> float:
    """Rolling-window market beta as of a specific date."""
    if ticker not in closes.columns or mkt not in closes.columns:
        return np.nan
    sub = closes.loc[:asof].tail(window_bd + 1)
    if len(sub) < window_bd:
        return np.nan
    rt = np.log(sub[ticker] / sub[ticker].shift(1)).dropna()
    rm = np.log(sub[mkt] / sub[mkt].shift(1)).dropna()
    common = rt.index.intersection(rm.index)
    if len(common) < window_bd - 5:
        return np.nan
    rt, rm = rt.loc[common], rm.loc[common]
    cov = np.cov(rt, rm, ddof=1)[0, 1]
    var = rm.var(ddof=1)
    return float(cov / var) if var > 0 else np.nan


def beta_mz_at(preds: pd.DataFrame, asof: pd.Timestamp, horizon: int,
               window_bd: int = BETA_WINDOW_BD) -> tuple[float, float, int]:
    """OLS MZ beta on a rolling tail of predictions ending at asof."""
    sub = preds[(preds["horizon"] == horizon) & (preds["date"] <= asof)].copy()
    sub = sub.sort_values("date").tail(window_bd)
    if len(sub) < 60:
        return (np.nan, np.nan, len(sub))
    y_true = np.log(sub["y_true"].clip(lower=1e-6))
    y_pred = np.log(sub["y_pred"].clip(lower=1e-6))
    # OLS y_true = alpha + beta * y_pred
    cov = np.cov(y_true, y_pred, ddof=1)[0, 1]
    var = y_pred.var(ddof=1)
    if var == 0 or not np.isfinite(var):
        return (np.nan, np.nan, len(sub))
    beta = cov / var
    alpha = y_true.mean() - beta * y_pred.mean()
    return (float(alpha), float(beta), len(sub))


def build_trail(ticker: str, closes: pd.DataFrame,
                preds: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """One row per quarter-end snapshot.

    If `preds` is provided, use it directly (corpus-mode where one CSV holds
    all tickers). Otherwise read from per-ticker `predictions_{ticker}.csv`.
    """
    if preds is None:
        pred_path = RESULTS_DIR / f"predictions_{ticker}.csv"
        if not pred_path.exists():
            return None
        preds = pd.read_csv(pred_path, parse_dates=["date"])
    if preds.empty:
        return None
    last_pred_date = preds["date"].max()
    qs = snapshot_dates(last_pred_date, N_SNAPSHOTS)

    rows = []
    for q in qs:
        bmkt = beta_mkt_at(closes, ticker, q)
        alpha, bmz, n = beta_mz_at(preds, q, horizon=HORIZON_PRIMARY)
        rows.append({
            "ticker": ticker,
            "asof": q.date(),
            "beta_mkt": bmkt,
            "beta_mz_h21": bmz,
            "mz_alpha_h21": alpha,
            "n_preds": n,
        })
    return pd.DataFrame(rows)


def plot_trail(trail: pd.DataFrame, out_path: Path) -> None:
    """Slug-trail figure for a single ticker."""
    if trail.empty or trail[["beta_mkt", "beta_mz_h21"]].isna().all().any():
        return

    fig, ax = plt.subplots(figsize=(10, 8))

    bm = trail["beta_mkt"].values
    bz = trail["beta_mz_h21"].values
    n = len(trail)
    valid = (~np.isnan(bm)) & (~np.isnan(bz))
    if valid.sum() < 2:
        plt.close(fig)
        return

    # Quadrant guides
    ax.axhline(1.0, color="gray", linewidth=0.7, alpha=0.6)
    ax.axvline(1.0, color="gray", linewidth=0.7, alpha=0.6)

    # Set extents to give room for labels
    pad = 0.3
    xmin, xmax = np.nanmin(bm) - pad, np.nanmax(bm) + pad
    ymin, ymax = np.nanmin(bz) - pad, np.nanmax(bz) + pad
    ax.set_xlim(min(xmin, -0.2), max(xmax, 2.0))
    ax.set_ylim(min(ymin, 0.0), max(ymax, 1.6))

    # Quadrant background tinting
    ax.axhspan(1.0, ax.get_ylim()[1], xmin=0, xmax=(1.0 - ax.get_xlim()[0]) /
               (ax.get_xlim()[1] - ax.get_xlim()[0]), color="#d62728", alpha=0.06)
    ax.axhspan(1.0, ax.get_ylim()[1],
               xmin=(1.0 - ax.get_xlim()[0]) / (ax.get_xlim()[1] - ax.get_xlim()[0]),
               xmax=1.0, color="#ff7f0e", alpha=0.06)
    ax.axhspan(ax.get_ylim()[0], 1.0, xmin=0,
               xmax=(1.0 - ax.get_xlim()[0]) / (ax.get_xlim()[1] - ax.get_xlim()[0]),
               color="#2ca02c", alpha=0.06)
    ax.axhspan(ax.get_ylim()[0], 1.0,
               xmin=(1.0 - ax.get_xlim()[0]) / (ax.get_xlim()[1] - ax.get_xlim()[0]),
               xmax=1.0, color="#1f77b4", alpha=0.06)

    # Trail: heavy line with color gradient (viridis: dark=old, bright=new)
    pts = trail[valid].reset_index(drop=True)
    nv = len(pts)
    cmap = plt.get_cmap("viridis")
    colors = [cmap(i / max(nv - 1, 1)) for i in range(nv)]
    sizes = np.linspace(20, 180, nv)

    # Heavy connecting line, colored by recency at each segment
    for i in range(nv - 1):
        ax.plot(pts["beta_mkt"].iloc[i:i + 2], pts["beta_mz_h21"].iloc[i:i + 2],
                color=colors[i + 1], linewidth=2.2, alpha=0.85, zorder=3,
                solid_capstyle="round")

    # Scatter dots colored by recency (with white edge for clarity)
    for i in range(nv):
        ax.scatter(pts["beta_mkt"].iloc[i], pts["beta_mz_h21"].iloc[i],
                   s=sizes[i], c=[colors[i]], edgecolor="white",
                   linewidth=1.0, zorder=5)

    # Bold ring around most-recent point
    ax.scatter(pts["beta_mkt"].iloc[-1], pts["beta_mz_h21"].iloc[-1],
               s=320, facecolors="none", edgecolor="black", linewidth=2.5,
               zorder=6)

    # Arrow showing direction of last move
    if nv >= 2:
        x0, y0 = pts["beta_mkt"].iloc[-2], pts["beta_mz_h21"].iloc[-2]
        x1, y1 = pts["beta_mkt"].iloc[-1], pts["beta_mz_h21"].iloc[-1]
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="->", color="black",
                                    lw=2.5, mutation_scale=20),
                    zorder=7)

    # Colorbar legend — communicates the recency gradient clearly
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=nv - 1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02, aspect=30)
    cbar.set_ticks([0, nv // 2, nv - 1])
    cbar.set_ticklabels([str(pts["asof"].iloc[0]),
                         str(pts["asof"].iloc[nv // 2]),
                         str(pts["asof"].iloc[-1])])
    cbar.set_label("Snapshot date", fontsize=9)

    # Label oldest and newest with quarter labels
    ax.annotate(f"  {pts['asof'].iloc[0]}", (pts["beta_mkt"].iloc[0],
                pts["beta_mz_h21"].iloc[0]), fontsize=8, color="#666",
                xytext=(6, -8), textcoords="offset points")
    ax.annotate(f"  {pts['asof'].iloc[-1]} (current)",
                (pts["beta_mkt"].iloc[-1], pts["beta_mz_h21"].iloc[-1]),
                fontsize=10, fontweight="bold",
                xytext=(8, 6), textcoords="offset points",
                path_effects=[pe.withStroke(linewidth=2, foreground="white")])

    # Quadrant labels
    xl, yl = ax.get_xlim(), ax.get_ylim()
    ax.text(xl[0] + 0.02 * (xl[1] - xl[0]), yl[1] - 0.04 * (yl[1] - yl[0]),
            "Q1: Stealth event-risk", fontsize=10, color="#d62728",
            fontweight="bold", verticalalignment="top")
    ax.text(xl[1] - 0.02 * (xl[1] - xl[0]), yl[1] - 0.04 * (yl[1] - yl[0]),
            "Q2: Idiosync + systematic", fontsize=10, color="#ff7f0e",
            fontweight="bold", horizontalalignment="right",
            verticalalignment="top")
    ax.text(xl[0] + 0.02 * (xl[1] - xl[0]), yl[0] + 0.04 * (yl[1] - yl[0]),
            "Q3: Genuinely calm", fontsize=10, color="#2ca02c",
            fontweight="bold")
    ax.text(xl[1] - 0.02 * (xl[1] - xl[0]), yl[0] + 0.04 * (yl[1] - yl[0]),
            "Q4: Mega-cap buffer", fontsize=10, color="#1f77b4",
            fontweight="bold", horizontalalignment="right")

    ticker = trail["ticker"].iloc[0]
    ax.set_xlabel("Market beta (252d rolling, vs SPY)")
    ax.set_ylabel(f"MZ beta H={HORIZON_PRIMARY} (rolling 252d on OOS predictions)")
    ax.set_title(f"{ticker} — Regime trail, {N_SNAPSHOTS} monthly snapshots\n"
                 "(viridis: dark=oldest, bright=newest, arrow=last move)")
    ax.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[REGIME_TRAIL] {ticker}: wrote {out_path.name}")


def plot_corpus_overlay(all_trails: list[pd.DataFrame], out_path: Path) -> None:
    """All tickers' trails overlaid on one canvas — corpus-level drift map."""
    fig, ax = plt.subplots(figsize=(14, 10))

    ax.axhline(1.0, color="gray", linewidth=0.8, alpha=0.6)
    ax.axvline(1.0, color="gray", linewidth=0.8, alpha=0.6)

    for trail in all_trails:
        if trail.empty:
            continue
        valid = trail.dropna(subset=["beta_mkt", "beta_mz_h21"])
        if len(valid) < 2:
            continue
        # Faint trail
        ax.plot(valid["beta_mkt"], valid["beta_mz_h21"], color="gray",
                linewidth=0.6, alpha=0.25)
        # Current dot, labeled
        last = valid.iloc[-1]
        ax.scatter(last["beta_mkt"], last["beta_mz_h21"], s=30,
                   color="black", alpha=0.7, edgecolor="white", linewidth=0.4)
        ax.annotate(last["ticker"], (last["beta_mkt"], last["beta_mz_h21"]),
                    fontsize=6, alpha=0.75, xytext=(2, 2),
                    textcoords="offset points")

    ax.set_xlabel("Market beta (252d rolling, vs SPY)")
    ax.set_ylabel(f"MZ beta H={HORIZON_PRIMARY} (rolling 252d)")
    ax.set_title(f"Corpus regime trails — {N_SNAPSHOTS} monthly snapshots of drift, current dots labeled")
    ax.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[REGIME_TRAIL] Wrote corpus overlay {out_path.name}")


def process_ticker(ticker: str, closes: pd.DataFrame,
                   preds: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trail = build_trail(ticker, closes, preds=preds)
    if trail is None:
        print(f"[REGIME_TRAIL] {ticker}: no predictions, skipping.")
        return None
    trail = round_for_output(trail, DECIMAL_PRECISION)
    csv_path = OUT_DIR / f"{ticker}_trail.csv"
    trail.to_csv(csv_path, index=False)
    plot_trail(trail, OUT_DIR / f"{ticker}_trail.png")
    return trail


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker", help="Single ticker")
    g.add_argument("--all", action="store_true", help="All tickers in config")
    g.add_argument("--from-corpus", help="Path to corpus CSV (e.g. all_predictions_cal.csv) "
                   "with columns including ticker, date, y_true, y_pred, horizon")
    args = ap.parse_args()

    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    ohlcv = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last")
    closes = ohlcv.pivot(index="date", columns="ticker", values="prc").ffill()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.ticker:
        process_ticker(args.ticker, closes)
    elif args.from_corpus:
        corpus_path = Path(args.from_corpus)
        if not corpus_path.is_absolute():
            corpus_path = REPO_ROOT / corpus_path
        print(f"[REGIME_TRAIL] Loading corpus predictions from {corpus_path.name}...")
        df = pd.read_csv(corpus_path, parse_dates=["date"])
        all_trails = []
        for t, g in df.groupby("ticker", observed=True):
            trail = process_ticker(t, closes, preds=g)
            if trail is not None:
                all_trails.append(trail)
        if all_trails:
            plot_corpus_overlay(all_trails, OUT_DIR / "regime_trail_overview.png")
    else:
        all_trails = []
        for t in dc.tickers:
            trail = process_ticker(t, closes)
            if trail is not None:
                all_trails.append(trail)
        if all_trails:
            plot_corpus_overlay(all_trails, OUT_DIR / "regime_trail_overview.png")


if __name__ == "__main__":
    main()
