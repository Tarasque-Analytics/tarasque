"""
signal_strength.py — Model output percentile tracker and tail signal precision analysis.

The key insight: calibration of quantile coverage is the wrong metric for risk.
The right metric is: when the ensemble prediction is at the top of its own historical
output distribution, how often does realized vol also spike? That's the signal's
actual precision on tail events — what you'd use to argue it's actionable.

Two analyses
------------
1. Output percentile CDF per ticker
   Rolling empirical CDF of y_pred. For any new prediction, its percentile in
   the historical distribution is the "model signal strength" indicator.
   Non-linear risk scaling: flat until P70, then accelerates to P95+.

2. Conditional tail precision
   Given ensemble output in top quintile (P80+), what fraction of subsequent
   realized vols exceeded a threshold (e.g. 1.5× rolling median)?
   This is the number that makes a noisy signal actionable.

Outputs
-------
  model/pipeline/results/signal_strength/signal_strength.png
  model/pipeline/results/signal_strength/signal_strength.json

Usage
-----
  python -m model.pipeline.analysis.signal_strength
  python -m model.pipeline.analysis.signal_strength --horizon 21 --threshold 1.5
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PREDS_CSV = ROOT / "model/pipeline/results/all_predictions.csv"
OUT_DIR   = ROOT / "model/pipeline/results/signal_strength"

# Non-linear risk scaling: maps output percentile [0,1] → risk multiplier [0,1].
# Flat below P60, then convex acceleration toward the tail.
# At P90 → ~0.65 risk weight; at P95 → ~0.85; at P99 → ~0.97.
def percentile_to_risk_weight(p: float) -> float:
    """Non-linear mapping from output percentile to risk scaling weight."""
    if p < 0.60:
        return 0.0           # below P60: no elevated signal
    elif p < 0.80:
        return (p - 0.60) / 0.20 * 0.30   # linear ramp: 0.0 → 0.30
    else:
        # Convex acceleration: P80 → 0.30, P95 → 0.85, P99 → 0.97
        x = (p - 0.80) / 0.20  # normalise [0.80, 1.00] → [0, 1]
        return 0.30 + 0.70 * (x ** 1.5)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════════════════════

def load_predictions(horizon: int) -> pd.DataFrame:
    df = pd.read_csv(PREDS_CSV, parse_dates=["date"])
    df = df[df["horizon"] == horizon].copy()
    df["y_true_rv"] = np.exp(df["y_true"])      # log → annualized vol
    df["y_pred_rv"] = df["y_pred"]              # already annualized
    df = df.sort_values(["ticker", "date"])
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OUTPUT PERCENTILE CDF
# ═══════════════════════════════════════════════════════════════════════════════

def compute_output_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (ticker, date), compute the prediction's percentile within
    the historical distribution of predictions for that ticker up to that date.

    Uses expanding window so there's no lookahead: the CDF at date T only
    uses predictions from dates < T.
    """
    frames = []
    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)
        pcts = np.full(len(grp), np.nan)
        for i in range(1, len(grp)):
            hist = grp["y_pred_rv"].iloc[:i].values
            curr = grp["y_pred_rv"].iloc[i]
            pcts[i] = float(np.mean(hist <= curr))
        grp["output_pct"] = pcts
        grp["risk_weight"] = grp["output_pct"].apply(
            lambda p: percentile_to_risk_weight(p) if not np.isnan(p) else np.nan
        )
        frames.append(grp)
    return pd.concat(frames, ignore_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CONDITIONAL TAIL PRECISION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_tail_precision(
    df: pd.DataFrame,
    rv_threshold_mult: float = 1.5,
    signal_pct: float = 0.80,
) -> Dict:
    """
    For each ticker: given ensemble output was in the top (1-signal_pct) of its
    own distribution, what fraction of realized vols exceeded rv_threshold_mult
    × rolling median realized vol?

    Returns dict of precision stats per ticker + pooled.
    """
    df = compute_output_percentiles(df)
    df = df.dropna(subset=["output_pct"])

    # Rolling median realized vol per ticker (63-day window) as baseline
    frames = []
    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("date").copy()
        grp["rv_rolling_median"] = grp["y_true_rv"].rolling(63, min_periods=21).median()
        grp["rv_elevated"] = grp["y_true_rv"] > rv_threshold_mult * grp["rv_rolling_median"]
        frames.append(grp)
    df = pd.concat(frames, ignore_index=True).dropna(subset=["rv_rolling_median"])

    results = {}

    # Per-ticker precision
    ticker_stats = []
    for ticker, grp in df.groupby("ticker"):
        hi_signal = grp[grp["output_pct"] >= signal_pct]
        lo_signal = grp[grp["output_pct"] <  signal_pct]

        if len(hi_signal) < 10:
            continue

        hi_precision = float(hi_signal["rv_elevated"].mean())
        lo_precision = float(lo_signal["rv_elevated"].mean()) if len(lo_signal) > 0 else np.nan
        lift = hi_precision / lo_precision if lo_precision and lo_precision > 0 else np.nan

        ticker_stats.append({
            "ticker":         ticker,
            "n_hi_signal":    int(len(hi_signal)),
            "n_lo_signal":    int(len(lo_signal)),
            "hi_precision":   hi_precision,    # P(rv elevated | signal)
            "base_precision": lo_precision,    # P(rv elevated | no signal)
            "lift":           lift,            # hi_precision / base_precision
        })

    results["ticker_precision"] = sorted(ticker_stats, key=lambda x: -x.get("lift", 0))

    # Pooled precision
    hi_pool = df[df["output_pct"] >= signal_pct]
    lo_pool = df[df["output_pct"] <  signal_pct]
    pool_hi  = float(hi_pool["rv_elevated"].mean())
    pool_lo  = float(lo_pool["rv_elevated"].mean())
    results["pooled"] = {
        "signal_threshold_pct":  signal_pct,
        "rv_threshold_mult":     rv_threshold_mult,
        "n_hi_signal":           int(len(hi_pool)),
        "n_lo_signal":           int(len(lo_pool)),
        "hi_precision":          pool_hi,
        "base_precision":        pool_lo,
        "lift":                  pool_hi / pool_lo if pool_lo > 0 else np.nan,
    }

    return results, df


# ═══════════════════════════════════════════════════════════════════════════════
# VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def plot_signal_strength(df_with_pct: pd.DataFrame, precision: Dict, out_path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        print("[SIGNAL] matplotlib not available — skipping plot")
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Model Output Signal Strength Analysis", fontsize=13)

    # ── Panel 1: Empirical CDF of y_pred per ticker (pooled) ─────────────────
    ax = axes[0]
    for ticker, grp in df_with_pct.groupby("ticker"):
        vals = np.sort(grp["y_pred_rv"].dropna().values)
        cdf  = np.arange(1, len(vals) + 1) / len(vals)
        ax.plot(vals, cdf, alpha=0.5, linewidth=1, label=ticker)
    ax.set_title("Empirical CDF of Ensemble Predictions", fontsize=10)
    ax.set_xlabel("Ensemble Predicted Vol (annualized)")
    ax.set_ylabel("Percentile")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.legend(fontsize=7, ncol=2)
    ax.axhline(0.80, color="red",    linestyle="--", linewidth=0.8, alpha=0.6, label="P80")
    ax.axhline(0.95, color="darkred",linestyle="--", linewidth=0.8, alpha=0.6, label="P95")

    # ── Panel 2: Non-linear risk scaling curve ────────────────────────────────
    ax = axes[1]
    ps = np.linspace(0, 1, 500)
    ws = [percentile_to_risk_weight(p) for p in ps]
    ax.plot(ps, ws, color="darkred", linewidth=2)
    ax.fill_between(ps, ws, alpha=0.15, color="red")
    ax.set_title("Non-linear Risk Scaling: Output Percentile → Weight", fontsize=10)
    ax.set_xlabel("Model Output Percentile")
    ax.set_ylabel("Risk Weight")
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    for p_ref, label in [(0.80, "P80\n0.30"), (0.90, "P90\n~0.57"), (0.95, "P95\n~0.80")]:
        w = percentile_to_risk_weight(p_ref)
        ax.axvline(p_ref, color="grey", linestyle=":", linewidth=0.8)
        ax.text(p_ref + 0.005, w + 0.03, label, fontsize=8, color="grey")
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.05, 1.05)

    # ── Panel 3: Precision lift per ticker ────────────────────────────────────
    ax = axes[2]
    stats = precision["ticker_precision"]
    if stats:
        tickers  = [s["ticker"] for s in stats]
        hi_prec  = [s["hi_precision"]   for s in stats]
        lo_prec  = [s["base_precision"] for s in stats]
        x = np.arange(len(tickers))
        w = 0.35
        bars_hi = ax.bar(x - w/2, hi_prec, w, label=f"P(rv elevated | signal>=P{int(precision['pooled']['signal_threshold_pct']*100)})", color="firebrick", alpha=0.8)
        bars_lo = ax.bar(x + w/2, lo_prec, w, label="P(rv elevated | no signal)", color="steelblue", alpha=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(tickers, fontsize=8, rotation=45, ha="right")
        ax.set_ylabel("P(realized vol > 1.5× median)")
        ax.set_title(f"Tail Precision: Signal vs No-Signal (H={df_with_pct['horizon'].iloc[0]})", fontsize=10)
        ax.legend(fontsize=8)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))

        # Annotate lift
        for i, s in enumerate(stats):
            if s["lift"] and not np.isnan(s["lift"]):
                ax.text(i, s["hi_precision"] + 0.01, f"{s['lift']:.1f}×",
                        ha="center", fontsize=8, color="darkred", fontweight="bold")

    # Pooled stats annotation
    p = precision["pooled"]
    fig.text(0.98, 0.02,
             f"Pooled: {p['hi_precision']:.1%} precision | {p['lift']:.2f}× lift | "
             f"n={p['n_hi_signal']} signal obs",
             ha="right", fontsize=8, color="dimgrey")

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[SIGNAL] Plot saved -> {out_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Model output signal strength analysis")
    parser.add_argument("--horizon",   type=int,   default=21,  help="Horizon (default 21)")
    parser.add_argument("--threshold", type=float, default=1.5, help="RV elevation multiplier (default 1.5)")
    parser.add_argument("--signal",    type=float, default=0.80, help="Output pct threshold for 'hi signal' (default 0.80)")
    args = parser.parse_args()

    print(f"[SIGNAL] Loading predictions for H={args.horizon}...")
    df = load_predictions(args.horizon)
    print(f"[SIGNAL] {len(df)} rows, {df.ticker.nunique()} tickers")

    print("[SIGNAL] Computing output percentiles (expanding window)...")
    precision, df_pct = compute_tail_precision(
        df,
        rv_threshold_mult=args.threshold,
        signal_pct=args.signal,
    )

    # ── Print results ──────────────────────────────────────────────────────────
    p = precision["pooled"]
    print(f"\n{'='*60}")
    print(f"  POOLED SIGNAL PRECISION  (H={args.horizon}, threshold={args.threshold}x, signal>=P{int(args.signal*100)})")
    print(f"{'='*60}")
    print(f"  Signal fires: {p['n_hi_signal']} obs  |  No signal: {p['n_lo_signal']} obs")
    print(f"  P(rv elevated | signal):    {p['hi_precision']:.1%}")
    print(f"  P(rv elevated | no signal): {p['base_precision']:.1%}")
    print(f"  Lift:                       {p['lift']:.2f}×")

    print(f"\n  Per-ticker precision (sorted by lift):\n")
    print(f"  {'Ticker':<8} {'Hi-signal N':>12} {'Hi precision':>14} {'Base':>8} {'Lift':>8}")
    print(f"  {'-'*56}")
    for s in precision["ticker_precision"]:
        lift_str = f"{s['lift']:.2f}×" if s["lift"] and not np.isnan(s["lift"]) else "n/a"
        print(f"  {s['ticker']:<8} {s['n_hi_signal']:>12} {s['hi_precision']:>14.1%} "
              f"{s['base_precision']:>8.1%} {lift_str:>8}")

    # Risk scaling examples
    print(f"\n  Risk scaling (non-linear):")
    for p_ex in [0.70, 0.80, 0.85, 0.90, 0.95, 0.99]:
        w = percentile_to_risk_weight(p_ex)
        print(f"    P{int(p_ex*100):02d} -> {w:.2f} risk weight  "
              f"({'no signal' if w == 0 else 'reduce' if w < 0.5 else 'elevated' if w < 0.8 else 'HIGH'})")

    # ── Save JSON ──────────────────────────────────────────────────────────────
    out_json = OUT_DIR / "signal_strength.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)

    # Build CDF lookup table per ticker for frontend
    cdf_tables = {}
    for ticker, grp in df_pct.groupby("ticker"):
        vals = np.sort(grp["y_pred_rv"].dropna().values)
        if len(vals) == 0:
            continue
        pcts = np.linspace(0, 1, 101)
        quantile_vals = np.quantile(vals, pcts)
        cdf_tables[ticker] = {
            "percentiles": [round(p, 2) for p in pcts.tolist()],
            "vol_values":  [round(v, 5) for v in quantile_vals.tolist()],
        }

    payload = {
        "meta": {
            "horizon": args.horizon,
            "signal_threshold_pct": args.signal,
            "rv_threshold_mult": args.threshold,
        },
        "pooled":           precision["pooled"],
        "ticker_precision": precision["ticker_precision"],
        "cdf_tables":       cdf_tables,
        "risk_scaling": {
            str(int(p * 100)): round(percentile_to_risk_weight(p), 4)
            for p in np.linspace(0, 1, 101)
        },
    }
    with open(out_json, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n[SIGNAL] JSON saved -> {out_json}")

    plot_signal_strength(
        df_pct,
        precision,
        out_path=OUT_DIR / "signal_strength.png",
    )


if __name__ == "__main__":
    main()
