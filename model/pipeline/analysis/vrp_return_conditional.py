"""
vrp_return_conditional.py — Conditional VRP distribution given recent return percentile.

The hypothesis (Bollerslev, Tauchen & Zhou 2009 variant):
  Given that the last N days of returns fall in percentile bucket X:
    - Low VRP + high recent return  → momentum continuation setup
      (market hasn't priced in vol despite the move; room for continuation)
    - High VRP + high recent return → mean reversion / vol compression setup
      (market is fearful after the move; classic overshoot / vol premium)

Outputs
-------
  model/pipeline/results/vrp_conditional/vrp_return_conditional.png  — visualization
  model/pipeline/results/vrp_conditional/vrp_return_conditional.json — precomputed for frontend

Usage
-----
  python -m model.pipeline.analysis.vrp_return_conditional
  python -m model.pipeline.analysis.vrp_return_conditional --return-window 5
  python -m model.pipeline.analysis.vrp_return_conditional --tickers AAPL JPM XOM
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from ..utils import DECIMAL_PRECISION, round_json_dict

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "model/pipeline/results"
OUT_DIR     = RESULTS_DIR / "vrp_conditional"
OHLCV_DIR   = Path("D:/Tarasque_DB/ohlcv")
PREDS_CSV   = RESULTS_DIR / "all_predictions.csv"

# Return percentile buckets (quintiles)
BUCKET_LABELS = ["Q1\n(0–20%)", "Q2\n(20–40%)", "Q3\n(40–60%)", "Q4\n(60–80%)", "Q5\n(80–100%)"]
N_BUCKETS     = 5
VRP_TERCILES  = ["Low VRP", "Mid VRP", "High VRP"]


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def _load_returns(tickers: List[str]) -> pd.DataFrame:
    """Load CRSP 'ret' column for all tickers, return wide DataFrame."""
    frames = []
    missing = []
    for t in tickers:
        p = OHLCV_DIR / f"ticker={t}"
        files = list(p.rglob("*.parquet")) if p.exists() else []
        if not files:
            missing.append(t)
            continue
        df = pd.read_parquet(files[0], columns=["date", "ret"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")["ret"].rename(t)
        frames.append(df)

    if missing:
        print(f"[VRP-COND] Warning: no OHLCV data for {missing}")

    if not frames:
        return pd.DataFrame()

    wide = pd.concat(frames, axis=1).sort_index()
    # CRSP ret is total return (not log). Convert to log return.
    wide = np.log(1 + wide.clip(lower=-0.99))
    return wide


def load_data(
    tickers: Optional[List[str]],
    return_windows: List[int],
    horizon: int = 21,
) -> pd.DataFrame:
    """
    Merge predictions (vrp_wedge, y_true) with prior-N-day cumulative log returns.

    Returns a DataFrame with columns:
      ticker, date, vrp_wedge, y_true_rv (forward RV, annualized),
      ret_5d, ret_21d, ret_Xd_quintile, vrp_tercile
    """
    print("[VRP-COND] Loading predictions...")
    preds = pd.read_csv(PREDS_CSV, parse_dates=["date"])
    preds = preds[preds["horizon"] == horizon].copy()
    if tickers:
        preds = preds[preds["ticker"].isin(tickers)]

    preds["y_true_rv"] = np.exp(preds["y_true"])   # log → annualized vol

    active_tickers = sorted(preds["ticker"].unique())
    print(f"[VRP-COND] Tickers: {active_tickers}  Rows: {len(preds)}")

    print("[VRP-COND] Loading OHLCV returns...")
    ret_wide = _load_returns(active_tickers)
    if ret_wide.empty:
        raise RuntimeError("No OHLCV return data found.")

    # Compute rolling cumulative log returns
    rows = []
    for window in return_windows:
        cum_ret = ret_wide.rolling(window).sum()   # sum of log returns = cum log return
        # Melt to long
        melted = cum_ret.reset_index().melt(id_vars="date", var_name="ticker",
                                            value_name=f"ret_{window}d")
        rows.append(melted.set_index(["date", "ticker"]))

    returns_long = pd.concat(rows, axis=1).reset_index()

    # Merge with predictions on date + ticker
    merged = preds.merge(returns_long, on=["date", "ticker"], how="inner")
    merged = merged.dropna(subset=["vrp_wedge"] + [f"ret_{w}d" for w in return_windows])

    print(f"[VRP-COND] Merged rows: {len(merged)}")
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# BUCKET ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def assign_buckets(df: pd.DataFrame, return_window: int) -> pd.DataFrame:
    """Assign quintile bucket for the given return window and VRP tercile."""
    col = f"ret_{return_window}d"
    df = df.copy()

    # Return quintile: rank within the *entire* dataset (cross-ticker percentile)
    df["ret_quintile"] = pd.qcut(
        df[col], q=N_BUCKETS, labels=False, duplicates="drop"
    )

    # VRP tercile
    df["vrp_tercile"] = pd.qcut(
        df["vrp_wedge"], q=3, labels=False, duplicates="drop"
    )

    return df


def compute_conditional_stats(df: pd.DataFrame, return_window: int) -> dict:
    """
    Compute conditional stats:
      1. VRP distribution per return quintile
      2. Forward realized vol per (return quintile × VRP tercile)
      3. Count per bucket
    """
    df = assign_buckets(df, return_window)
    stats = {}

    # ── VRP distribution per return quintile ──────────────────────────────────
    vrp_by_ret = []
    for q in range(N_BUCKETS):
        sub = df[df["ret_quintile"] == q]["vrp_wedge"].dropna()
        if len(sub) < 5:
            continue
        vrp_by_ret.append({
            "bucket": q,
            "label": BUCKET_LABELS[q],
            "count": int(len(sub)),
            "vrp_mean": float(sub.mean()),
            "vrp_median": float(sub.median()),
            "vrp_p25": float(sub.quantile(0.25)),
            "vrp_p75": float(sub.quantile(0.75)),
            "vrp_p10": float(sub.quantile(0.10)),
            "vrp_p90": float(sub.quantile(0.90)),
        })
    stats["vrp_by_return_quintile"] = vrp_by_ret

    # ── Forward vol per (return quintile × VRP tercile) ───────────────────────
    heat = []
    for q in range(N_BUCKETS):
        for v in range(3):
            sub = df[(df["ret_quintile"] == q) & (df["vrp_tercile"] == v)]["y_true_rv"].dropna()
            if len(sub) < 5:
                continue
            heat.append({
                "ret_bucket": q,
                "vrp_bucket": v,
                "ret_label": BUCKET_LABELS[q],
                "vrp_label": VRP_TERCILES[v],
                "count": int(len(sub)),
                "fwd_vol_mean": float(sub.mean()),
                "fwd_vol_median": float(sub.median()),
                "fwd_vol_p25": float(sub.quantile(0.25)),
                "fwd_vol_p75": float(sub.quantile(0.75)),
            })
    stats["fwd_vol_by_ret_vrp"] = heat

    # ── Signal test: high-return + low-VRP vs high-return + high-VRP ──────────
    hi_ret = df[df["ret_quintile"] == 4]  # top quintile returns
    lo_vrp_hi_ret = hi_ret[hi_ret["vrp_tercile"] == 0]["y_true_rv"].dropna()
    hi_vrp_hi_ret = hi_ret[hi_ret["vrp_tercile"] == 2]["y_true_rv"].dropna()

    if len(lo_vrp_hi_ret) > 5 and len(hi_vrp_hi_ret) > 5:
        stats["signal_test"] = {
            "hi_ret_lo_vrp_fwd_vol": float(lo_vrp_hi_ret.mean()),
            "hi_ret_hi_vrp_fwd_vol": float(hi_vrp_hi_ret.mean()),
            "hi_ret_lo_vrp_count": int(len(lo_vrp_hi_ret)),
            "hi_ret_hi_vrp_count": int(len(hi_vrp_hi_ret)),
            "vol_diff_pct": float(
                (hi_vrp_hi_ret.mean() - lo_vrp_hi_ret.mean()) / lo_vrp_hi_ret.mean() * 100
            ),
        }

    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def plot_conditional(
    df: pd.DataFrame,
    stats_5d: dict,
    stats_21d: dict,
    out_path: Path,
) -> None:
    """4-panel figure: VRP box plots by return quintile (5d + 21d) + heatmaps."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        print("[VRP-COND] matplotlib not available — skipping plot")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        "VRP Conditional Distribution — Given Recent Return Percentile Bucket\n"
        "H=21 | Pooled cross-ticker",
        fontsize=13, y=0.98
    )

    bucket_colors = plt.cm.RdYlGn(np.linspace(0.15, 0.85, N_BUCKETS))

    for ax_row, (window, stats) in enumerate([(5, stats_5d), (21, stats_21d)]):
        # ── Left panel: VRP distribution by return quintile (box plot) ────────
        ax = axes[ax_row][0]
        df_w = assign_buckets(df, window)
        plot_data = [
            df_w[df_w["ret_quintile"] == q]["vrp_wedge"].dropna().values
            for q in range(N_BUCKETS)
        ]
        bp = ax.boxplot(
            plot_data,
            patch_artist=True,
            medianprops=dict(color="black", linewidth=2),
            whiskerprops=dict(linewidth=1.2),
            flierprops=dict(marker=".", alpha=0.2, markersize=3),
        )
        for patch, color in zip(bp["boxes"], bucket_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.axhline(0, color="grey", linestyle="--", linewidth=0.8, alpha=0.5)
        ax.set_title(f"{window}d Return Quintile → VRP Distribution", fontsize=11)
        ax.set_xlabel(f"Prior {window}d Return Bucket")
        ax.set_ylabel("VRP Wedge (IV – RV)")
        short_labels = [f"Q{q+1}" for q in range(N_BUCKETS)]
        ax.set_xticklabels(short_labels)

        # Annotate median VRP per bucket
        for i, entry in enumerate(stats["vrp_by_return_quintile"]):
            ax.text(i + 1, entry["vrp_p75"] * 1.05, f'{entry["vrp_median"]:.3f}',
                    ha="center", fontsize=8, color="navy")

        # ── Right panel: Heatmap of forward vol (return × VRP tercile) ────────
        ax = axes[ax_row][1]
        heat_data = np.full((3, N_BUCKETS), np.nan)
        for entry in stats["fwd_vol_by_ret_vrp"]:
            v = entry["vrp_bucket"]
            r = entry["ret_bucket"]
            heat_data[v, r] = entry["fwd_vol_mean"]

        im = ax.imshow(
            heat_data,
            aspect="auto",
            cmap="YlOrRd",
            interpolation="nearest",
        )
        fig.colorbar(im, ax=ax, label="Mean Forward RV (annualized)")

        ax.set_title(f"{window}d Return × VRP → Forward Vol (H=21)", fontsize=11)
        ax.set_xlabel(f"Prior {window}d Return Bucket")
        ax.set_ylabel("VRP Tercile")
        ax.set_xticks(range(N_BUCKETS))
        ax.set_xticklabels([f"Q{q+1}" for q in range(N_BUCKETS)])
        ax.set_yticks(range(3))
        ax.set_yticklabels(VRP_TERCILES, fontsize=9)

        # Cell text
        for v in range(3):
            for r in range(N_BUCKETS):
                val = heat_data[v, r]
                if not np.isnan(val):
                    ax.text(r, v, f"{val:.3f}", ha="center", va="center",
                            fontsize=9, color="white" if val > heat_data[~np.isnan(heat_data)].mean() else "black")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[VRP-COND] Plot saved -> {out_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="VRP conditional distribution analysis"
    )
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Filter to specific tickers (default: all)")
    parser.add_argument("--horizon", type=int, default=21,
                        help="Prediction horizon for y_true (default: 21)")
    args = parser.parse_args()

    tickers = args.tickers

    df = load_data(tickers, return_windows=[5, 21], horizon=args.horizon)

    print("\n[VRP-COND] Computing conditional stats for 5d and 21d windows...")
    stats_5d  = compute_conditional_stats(df, return_window=5)
    stats_21d = compute_conditional_stats(df, return_window=21)

    # ── Print summary ─────────────────────────────────────────────────────────
    for window, stats in [(5, stats_5d), (21, stats_21d)]:
        print(f"\n{'='*60}")
        print(f"  VRP by {window}d Return Quintile (pooled, H={args.horizon})")
        print(f"{'='*60}")
        print(f"  {'Bucket':<12} {'N':>6}  {'VRP median':>12}  {'VRP mean':>10}  {'VRP p25-p75':>14}")
        print(f"  {'-'*58}")
        for e in stats["vrp_by_return_quintile"]:
            print(f"  Q{e['bucket']+1} {e['label'].replace(chr(10),''):>10}  "
                  f"{e['count']:>6}  "
                  f"{e['vrp_median']:>12.4f}  "
                  f"{e['vrp_mean']:>10.4f}  "
                  f"[{e['vrp_p25']:.3f}, {e['vrp_p75']:.3f}]")

        if "signal_test" in stats:
            st = stats["signal_test"]
            print(f"\n  Signal: High return (Q5) + Low VRP -> fwd vol = {st['hi_ret_lo_vrp_fwd_vol']:.4f}  (n={st['hi_ret_lo_vrp_count']})")
            print(f"  Signal: High return (Q5) + High VRP -> fwd vol = {st['hi_ret_hi_vrp_fwd_vol']:.4f}  (n={st['hi_ret_hi_vrp_count']})")
            sign = "+" if st['vol_diff_pct'] > 0 else ""
            print(f"  -> High-VRP after strong run = {sign}{st['vol_diff_pct']:.1f}% higher forward vol")
            print(f"    (Positive = VRP predicts MORE vol after strong run -> mean reversion setup)")

    # ── Save JSON ─────────────────────────────────────────────────────────────
    out_json = OUT_DIR / "vrp_return_conditional.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "horizon": args.horizon,
            "tickers": (args.tickers or "all"),
            "n_rows": int(len(df)),
            "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
            "bucket_labels": [lb.replace("\n", " ") for lb in BUCKET_LABELS],
            "vrp_tercile_labels": VRP_TERCILES,
        },
        "window_5d": stats_5d,
        "window_21d": stats_21d,
    }
    payload = round_json_dict(payload, DECIMAL_PRECISION)
    with open(out_json, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n[VRP-COND] JSON saved -> {out_json}")

    # ── Plot ──────────────────────────────────────────────────────────────────
    plot_conditional(
        df, stats_5d, stats_21d,
        out_path=OUT_DIR / "vrp_return_conditional.png",
    )


if __name__ == "__main__":
    main()
