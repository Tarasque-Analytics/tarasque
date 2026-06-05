"""
beta_mz_pre2020_test.py — Re-run the multi-index + overlay-variants test on
                          PRE-2020 data only (2015-01-01 to 2019-12-31).

Motivation: the full backtest includes COVID (March 2020 crash) and the 2022
inflation shock, which are HUGE vol events that the signal correctly caught.
There's a real concern that the strategy's edge is concentrated in these few
mega-events. Re-running on a "boring" 2015-2019 sample tells us whether the
signal works in NORMAL markets too, not just black-swan-driven backtest wins.

If pre-2020 results still show Sharpe improvement, the signal is robust to
the absence of mega-shocks. If it falls apart, the strategy is essentially
a COVID-and-2022-trade and we should pitch it that way (still useful, but
with different positioning).

Outputs:
  results/validation/beta_mz_pre2020.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_drawdown_value import cumulative_index, max_drawdown
from .beta_mz_multi_index_test import load_index_returns
from .beta_mz_short_overlay import simulate, stats, STRATEGIES

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

PRE_2020_START = pd.Timestamp("2015-01-01")
PRE_2020_END   = pd.Timestamp("2019-12-31")
FLIP_COST_BPS = 5
BORROW_COST_BPS_ANNUAL = 50
STARTING = 100_000


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[BMZ_PRE2020] Eval window: {PRE_2020_START.date()} -> {PRE_2020_END.date()}")
    print(f"[BMZ_PRE2020] (Excludes COVID 2020 + 2022 inflation shock)")

    print("\n[BMZ_PRE2020] Building β_mz weekly aggregate...")
    agg = compute_weekly_aggregate()
    agg_12 = add_slope_signs(agg, window_weeks=12)

    rows = []
    for ticker in ("SPY", "QQQ", "IWM"):
        daily_ret = load_index_returns(ticker)
        # Restrict to pre-2020 evaluation window
        daily_ret = daily_ret[(daily_ret.index >= PRE_2020_START) &
                               (daily_ret.index <= PRE_2020_END)]
        if daily_ret.empty:
            continue
        print(f"\n[{ticker}] {len(daily_ret)} BD in pre-2020 window")
        for name, spec in STRATEGIES.items():
            strat_ret, l_a, s_a, n_flips = simulate(
                daily_ret, agg_12, spec, FLIP_COST_BPS, BORROW_COST_BPS_ANNUAL)
            r = stats(strat_ret, l_a, s_a, name, STARTING, n_flips)
            r["index"] = ticker
            rows.append(r)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "beta_mz_pre2020.csv", index=False)

    for ticker in df["index"].unique():
        print(f"\n{'=' * 80}")
        print(f" {ticker} PRE-2020 (2015-2019): overlay variants vs BH")
        print(f"{'=' * 80}")
        sub = df[df["index"] == ticker]
        cols = ["strategy", "total_return", "annualized_return", "sharpe",
                "sortino", "max_drawdown", "ending_value"]
        with pd.option_context("display.width", 200,
                               "display.float_format", lambda v: f"{v:+.3f}"):
            print(sub[cols].to_string(index=False))

        bh = sub[sub.strategy == "BH"].iloc[0]
        print(f"\n  vs BH (${bh['ending_value']:,.0f}, Sharpe {bh['sharpe']:+.3f}, DD {bh['max_drawdown']:+.3f}):")
        for s in ("CASH", "HALF", "LONG_SHORT_70_30", "LONG_SHORT_50_50",
                  "LONG_SHORT_30_70", "FULL_FLIP"):
            r = sub[sub.strategy == s].iloc[0]
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
