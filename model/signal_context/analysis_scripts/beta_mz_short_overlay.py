"""
beta_mz_short_overlay.py — Test active SHORT positioning during heating regimes
                           vs the passive CASH overlay.

User's idea: instead of going to cash during heating signals, go 70/30 long/short
(net 40% exposure). Actively bet the market will drop, not just sit out.

Three new strategies tested on SPY:
  LONG_SHORT_70_30:  long when cooling; 70% long / 30% short when heating
  LONG_SHORT_50_50:  long when cooling; 50% long / 50% short when heating (market-neutral hedging)
  LONG_SHORT_30_70:  long when cooling; 30% long / 70% short when heating (aggressive)
  FULL_FLIP:         long when cooling; 100% short when heating (max aggressive)

For each: standard metrics + comparison vs CASH overlay.

Adds borrow cost assumption: 50 bps annualized on the short notional (typical
for liquid US large-caps). For SPY specifically, ~30-40 bps is more realistic
but 50 is a conservative estimate.

Outputs:
  results/validation/beta_mz_short_overlay.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_drawdown_value import cumulative_index, max_drawdown
from .beta_mz_multi_index_test import load_index_returns

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

START_DATE = pd.Timestamp("2015-01-01")
STARTING = 100_000
FLIP_COST_BPS = 5                  # transaction cost per allocation change
BORROW_COST_BPS_ANNUAL = 50        # short borrow fee (annualized, applied daily)

# Strategy specs: (long_alloc_cooling, short_alloc_cooling,
#                  long_alloc_heating, short_alloc_heating)
STRATEGIES = {
    "BH":              (1.0, 0.0, 1.0, 0.0),     # always 100% long
    "CASH":            (1.0, 0.0, 0.0, 0.0),     # cooling: long, heating: cash
    "HALF":            (1.0, 0.0, 0.5, 0.0),     # cooling: long, heating: 50% long
    "LONG_SHORT_70_30":(1.0, 0.0, 0.7, 0.3),     # heating: 70L / 30S = net 40
    "LONG_SHORT_50_50":(1.0, 0.0, 0.5, 0.5),     # heating: 50L / 50S = market-neutral
    "LONG_SHORT_30_70":(1.0, 0.0, 0.3, 0.7),     # heating: 30L / 70S = net -40
    "FULL_FLIP":       (1.0, 0.0, 0.0, 1.0),     # heating: 100% short
}


def simulate(daily_ret: pd.Series, agg_w_12: pd.DataFrame,
              spec: tuple, cost_bps: float, borrow_bps_annual: float) -> tuple:
    """Apply strategy with both long/short allocations + costs."""
    long_cool, short_cool, long_heat, short_heat = spec
    sign_series = agg_w_12.set_index("asof")["sign_w12"].sort_index()
    sign_daily = sign_series.reindex(daily_ret.index, method="ffill")

    # cooling = slope ≤ 0; heating = slope > 0
    is_heating = (sign_daily > 0).astype(float)
    is_cooling = 1 - is_heating

    long_alloc  = is_cooling * long_cool  + is_heating * long_heat
    short_alloc = is_cooling * short_cool + is_heating * short_heat

    # Daily strategy return:
    #   long leg: long_alloc * daily_ret
    #   short leg: -short_alloc * daily_ret
    #   borrow cost on short notional: -short_alloc * (borrow_bps / 252)
    daily_borrow_drag = short_alloc * (borrow_bps_annual / 10000) / 252
    strat_ret = long_alloc * daily_ret - short_alloc * daily_ret - daily_borrow_drag

    # Transaction costs on allocation changes (both legs)
    alloc_change = (long_alloc.diff().abs() + short_alloc.diff().abs()).fillna(0)
    cost_drag = alloc_change * (cost_bps / 10000)
    strat_ret_net = strat_ret - cost_drag

    return strat_ret_net, long_alloc, short_alloc, alloc_change.sum()


def stats(strat_ret: pd.Series, long_alloc: pd.Series, short_alloc: pd.Series,
           name: str, starting: float, n_flips: float) -> dict:
    price = cumulative_index(strat_ret) * starting
    total_log_ret = float(strat_ret.sum())
    total_simple_ret = float(np.exp(total_log_ret) - 1)
    n_years = (strat_ret.index[-1] - strat_ret.index[0]).days / 365.25
    ann_ret = float(np.exp(total_log_ret / n_years) - 1) if n_years > 0 else np.nan
    ann_vol = float(strat_ret.std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    down = strat_ret[strat_ret < 0]
    sortino_vol = float(down.std() * np.sqrt(252)) if len(down) else np.nan
    sortino = ann_ret / sortino_vol if sortino_vol and sortino_vol > 0 else np.nan
    max_dd, _, _ = max_drawdown(price)
    return {
        "strategy": name, "total_return": total_simple_ret,
        "annualized_return": ann_ret, "annualized_vol": ann_vol,
        "sharpe": sharpe, "sortino": sortino, "max_drawdown": max_dd,
        "avg_long_alloc": float(long_alloc.mean()),
        "avg_short_alloc": float(short_alloc.mean()),
        "n_alloc_flips": float(n_flips),
        "ending_value": float(price.iloc[-1]),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[BMZ_SHORT] Building β_mz weekly aggregate...")
    agg = compute_weekly_aggregate()
    agg_12 = add_slope_signs(agg, window_weeks=12)

    rows = []
    for ticker in ("SPY", "QQQ", "IWM"):
        print(f"\n[BMZ_SHORT] === {ticker} ===")
        daily_ret = load_index_returns(ticker)
        daily_ret = daily_ret[daily_ret.index >= START_DATE]
        if daily_ret.empty:
            continue
        for name, spec in STRATEGIES.items():
            strat_ret, l_a, s_a, n_flips = simulate(
                daily_ret, agg_12, spec, FLIP_COST_BPS, BORROW_COST_BPS_ANNUAL)
            r = stats(strat_ret, l_a, s_a, name, STARTING, n_flips)
            r["index"] = ticker
            rows.append(r)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "beta_mz_short_overlay.csv", index=False)

    for ticker in df["index"].unique():
        print(f"\n{'=' * 80}")
        print(f" {ticker}: long/short variants vs BH, CASH, HALF")
        print(f" cost: {FLIP_COST_BPS} bps/flip · short borrow: {BORROW_COST_BPS_ANNUAL} bps/yr")
        print(f"{'=' * 80}")
        sub = df[df["index"] == ticker]
        cols = ["strategy", "total_return", "annualized_return", "sharpe",
                "sortino", "max_drawdown", "avg_long_alloc", "avg_short_alloc",
                "n_alloc_flips", "ending_value"]
        with pd.option_context("display.width", 200,
                               "display.float_format", lambda v: f"{v:+.3f}"):
            print(sub[cols].to_string(index=False))

        bh = sub[sub.strategy == "BH"].iloc[0]
        print(f"\n  vs BH ending value (${bh['ending_value']:,.0f}, Sharpe {bh['sharpe']:+.3f}, DD {bh['max_drawdown']:+.3f}):")
        for s in ("CASH", "HALF", "LONG_SHORT_70_30", "LONG_SHORT_50_50",
                  "LONG_SHORT_30_70", "FULL_FLIP"):
            r = sub[sub.strategy == s]
            if r.empty:
                continue
            r = r.iloc[0]
            delta_v = r["ending_value"] - bh["ending_value"]
            delta_s = r["sharpe"] - bh["sharpe"]
            delta_dd = abs(bh["max_drawdown"]) - abs(r["max_drawdown"])
            print(f"    {s:18s}: ${r['ending_value']:>11,.0f}  "
                  f"(Δ ${delta_v:>+10,.0f})  ΔSharpe {delta_s:+.3f}  "
                  f"DDreduction {delta_dd:+.3f}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
