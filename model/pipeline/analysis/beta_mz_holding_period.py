"""
beta_mz_holding_period.py -- Optimal holding period for the directional bet.

The slope sign-change signal fires a DIRECTIONAL bet:
  up->down (cooling onset)  -> LONG the index  (calm coming, vol mean-reverts down)
  down->up (heating onset)  -> SHORT the index (stress coming)

We've always measured forward outcomes at a fixed 21-BD horizon. This sweeps the
HOLDING PERIOD h over 21..50 BD and asks: where is profit maximized?

For each signal event we compute the forward log return from entry (first bar on
/after the event Friday) to entry+h, scaled by direction (long=+ret, short=-ret).
Reported per (index, direction, h):
  - mean PnL per signal       (raw expected profit)
  - per-signal Sharpe = mean/std  (risk-adjusted -- the honest "ideal hold")
  - return-per-day = mean/h       (time efficiency; favors shorter holds if PnL plateaus)
  - hit rate, n

We separate by direction because the signal is ASYMMETRIC (up->down is the
reliable / robust leg; down->up is noisier / COVID-magnified).

Outputs:
  results/validation/beta_mz_holding_period.csv
  signal_context/charts/beta_mz_holding_period.png
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_drawdown_value import cumulative_index, forward_window_metrics
from .beta_mz_multi_index_test import load_index_returns

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"
CHART_DIR = REPO_ROOT / "model" / "signal_context" / "charts"

START_DATE = pd.Timestamp("2015-01-01")
HOLD_DAYS = list(range(21, 51))          # sweep 21..50 BD inclusive
INDICES = ["SPY", "QQQ", "IWM", "XLF"]
CANONICAL_W = 12


def signal_events(agg_12: pd.DataFrame) -> pd.DataFrame:
    """Return sign-change events with direction + bet sign (+1 long / -1 short)."""
    ev = agg_12[agg_12["sign_change_w12"]].copy()
    def _dir(r):
        if r["sign_lag_w12"] < 0 and r["sign_w12"] > 0:
            return "down->up (heating)"
        if r["sign_lag_w12"] > 0 and r["sign_w12"] < 0:
            return "up->down (cooling)"
        return ""
    ev["direction"] = ev.apply(_dir, axis=1)
    ev = ev[ev["direction"] != ""].copy()
    # cooling -> LONG (+1); heating -> SHORT (-1)
    ev["bet"] = np.where(ev["direction"] == "up->down (cooling)", 1.0, -1.0)
    return ev[["asof", "direction", "bet"]]


def sweep_index(ticker: str, events: pd.DataFrame) -> pd.DataFrame:
    daily_ret = load_index_returns(ticker)
    daily_ret = daily_ret[daily_ret.index >= START_DATE]
    if daily_ret.empty:
        return pd.DataFrame()
    price = cumulative_index(daily_ret)

    rows = []
    for direction in ("up->down (cooling)", "down->up (heating)", "BOTH"):
        ev = events if direction == "BOTH" else events[events["direction"] == direction]
        for h in HOLD_DAYS:
            pnls = []
            for _, e in ev.iterrows():
                m = forward_window_metrics(price, e["asof"], h)
                r = m.get("log_ret", np.nan)
                if np.isfinite(r):
                    pnls.append(e["bet"] * r)
            pnls = np.array(pnls, dtype=float)
            if len(pnls) < 5:
                continue
            mean = float(pnls.mean())
            std = float(pnls.std(ddof=1)) if len(pnls) > 1 else np.nan
            rows.append({
                "index": ticker, "direction": direction, "hold_bd": h,
                "n": len(pnls), "mean_pnl": mean, "median_pnl": float(np.median(pnls)),
                "std_pnl": std, "hit_rate": float((pnls > 0).mean()),
                "per_signal_sharpe": mean / std if std and std > 0 else np.nan,
                "ret_per_day_bp": mean / h * 1e4,
            })
    return pd.DataFrame(rows)


def argmax_report(df: pd.DataFrame, ticker: str):
    sub = df[df["index"] == ticker]
    print(f"\n  --- {ticker}: profit-maximizing hold within 21-50 BD ---")
    for direction in ("up->down (cooling)", "down->up (heating)", "BOTH"):
        d = sub[sub["direction"] == direction]
        if d.empty:
            continue
        best_mean = d.loc[d["mean_pnl"].idxmax()]
        best_sharpe = d.loc[d["per_signal_sharpe"].idxmax()]
        print(f"    {direction:22s} (n~{int(d['n'].median())}):")
        print(f"       max mean PnL  @ h={int(best_mean['hold_bd']):2d} BD: "
              f"{best_mean['mean_pnl']:+.3%}  (hit {best_mean['hit_rate']:.0%}, "
              f"Sharpe {best_mean['per_signal_sharpe']:+.2f})")
        print(f"       max Sharpe    @ h={int(best_sharpe['hold_bd']):2d} BD: "
              f"{best_sharpe['per_signal_sharpe']:+.2f}  "
              f"(mean {best_sharpe['mean_pnl']:+.3%}, hit {best_sharpe['hit_rate']:.0%})")


def make_chart(df: pd.DataFrame):
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    spy = df[df["index"] == "SPY"]
    colors = {"up->down (cooling)": "#2e7d32", "down->up (heating)": "#c62828",
              "BOTH": "#1565c0"}
    # left: mean PnL vs hold
    for direction in ("up->down (cooling)", "down->up (heating)", "BOTH"):
        d = spy[spy["direction"] == direction]
        if d.empty:
            continue
        axes[0].plot(d["hold_bd"], d["mean_pnl"] * 100, marker="o", ms=3,
                     color=colors[direction], label=direction)
        bm = d.loc[d["mean_pnl"].idxmax()]
        axes[0].scatter([bm["hold_bd"]], [bm["mean_pnl"] * 100], s=90,
                        edgecolor="black", facecolor=colors[direction], zorder=5)
    axes[0].axhline(0, color="gray", lw=0.8)
    axes[0].set_title("SPY: mean PnL per signal vs holding period")
    axes[0].set_xlabel("holding period (business days)")
    axes[0].set_ylabel("mean directional PnL (%)")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)
    # right: per-signal Sharpe vs hold
    for direction in ("up->down (cooling)", "down->up (heating)", "BOTH"):
        d = spy[spy["direction"] == direction]
        if d.empty:
            continue
        axes[1].plot(d["hold_bd"], d["per_signal_sharpe"], marker="o", ms=3,
                     color=colors[direction], label=direction)
    axes[1].axhline(0, color="gray", lw=0.8)
    axes[1].set_title("SPY: per-signal Sharpe (mean/std) vs holding period")
    axes[1].set_xlabel("holding period (business days)")
    axes[1].set_ylabel("per-signal Sharpe")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    out = CHART_DIR / "beta_mz_holding_period.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"\n[BMZ_HOLD] Chart -> {out}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[BMZ_HOLD] Building weekly aggregate + signal events...")
    agg = compute_weekly_aggregate()
    agg_12 = add_slope_signs(agg, window_weeks=CANONICAL_W)
    events = signal_events(agg_12)
    n_long = int((events["bet"] > 0).sum())
    n_short = int((events["bet"] < 0).sum())
    print(f"  {len(events)} events: {n_long} cooling/LONG, {n_short} heating/SHORT")

    all_df = []
    for ticker in INDICES:
        d = sweep_index(ticker, events)
        if not d.empty:
            all_df.append(d)
    df = pd.concat(all_df, ignore_index=True)
    df.to_csv(OUT_DIR / "beta_mz_holding_period.csv", index=False)

    print("\n" + "=" * 76)
    print(" PROFIT-MAXIMIZING HOLDING PERIOD (directional bet, 21-50 BD sweep)")
    print(" cooling->LONG, heating->SHORT | gross log returns, no costs")
    print("=" * 76)
    for ticker in INDICES:
        if (df["index"] == ticker).any():
            argmax_report(df, ticker)

    # SPY full curve so the shape is visible (every 3rd BD to keep it short)
    print("\n  SPY mean PnL by holding period (every 3 BD):")
    spy = df[df["index"] == "SPY"]
    for direction in ("up->down (cooling)", "down->up (heating)", "BOTH"):
        d = spy[spy["direction"] == direction]
        if d.empty:
            continue
        pts = "  ".join(f"h{int(r.hold_bd)}={r.mean_pnl*100:+.2f}%"
                        for r in d.itertuples() if int(r.hold_bd) % 3 == 0)
        print(f"    {direction:22s}: {pts}")

    make_chart(df)
    print(f"\n[BMZ_HOLD] Wrote CSV to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
