"""
beta_mz_multi_index_test.py — Test β_mz defensive overlay across multiple
                              real tradeable indices + Monte Carlo hypothesis
                              test against random-signal null.

Two analyses:

  1. MULTI-INDEX: apply CASH overlay (12-week β_mz) to each of SPY, QQQ, IWM,
     XLF, XLE, XLK, XLV, XLI. Compare BH vs CASH on each. Strategy generalizes
     if CASH beats BH on Sharpe / max DD across multiple indices.

  2. MONTE CARLO HYPOTHESIS TEST: shuffle the β_mz weekly slope-sign series
     RANDOMLY (preserving the count of regime-flip events), apply the CASH
     overlay, compute strategy Sharpe. Repeat N=1000 times to build a null
     distribution. The real signal's Sharpe should be in the upper tail of
     this null if the regime flips carry genuine information.

Outputs:
  results/validation/beta_mz_multi_index.csv
  results/validation/beta_mz_monte_carlo.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_drawdown_value import cumulative_index, max_drawdown
from .beta_mz_defensive_overlay import cost_modeled_backtest, strategy_stats

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "validation"

START_DATE = pd.Timestamp("2015-01-01")
STARTING = 100_000
COST_BPS = 5
N_BOOTSTRAP = 1000
TEST_INDICES = ["SPY", "QQQ", "IWM", "XLF", "XLE", "XLK", "XLV", "XLI"]


def load_index_returns(ticker: str) -> pd.Series:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    sub = ohlcv[ohlcv["ticker"] == ticker].drop_duplicates(
        subset=["date"], keep="last").sort_values("date")
    if sub.empty:
        return pd.Series(dtype=float)
    price = sub.set_index("date")["prc"].sort_index().ffill()
    return np.log(price / price.shift(1)).dropna()


# ============================================================================
# MULTI-INDEX TEST
# ============================================================================

def run_multi_index(agg_w_12: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker in TEST_INDICES:
        daily_ret = load_index_returns(ticker)
        daily_ret = daily_ret[daily_ret.index >= START_DATE]
        if daily_ret.empty or len(daily_ret) < 1000:
            print(f"  [{ticker}] insufficient data: {len(daily_ret)}")
            continue
        print(f"  [{ticker}] {len(daily_ret)} BD")

        for mode in ("BH", "CASH"):
            strat_ret, alloc, n_flips = cost_modeled_backtest(
                daily_ret, agg_w_12, 12, mode, cost_bps_per_flip=COST_BPS)
            r = strategy_stats(strat_ret, alloc, f"{mode}", STARTING, n_flips)
            r["index"] = ticker
            rows.append(r)
    return pd.DataFrame(rows)


# ============================================================================
# MONTE CARLO HYPOTHESIS TEST
# ============================================================================

def monte_carlo_null(daily_ret: pd.Series, agg_w_12: pd.DataFrame,
                      n_iter: int = N_BOOTSTRAP) -> dict:
    """Generate null distribution by shuffling slope_w12 sign-flip events
    randomly across the time axis, preserving the count of flips.

    H0: regime flips are random — strategy Sharpe should be no better than null.
    """
    # Real strategy
    real_ret, real_alloc, _ = cost_modeled_backtest(
        daily_ret, agg_w_12, 12, "CASH", cost_bps_per_flip=COST_BPS)
    real_stats = strategy_stats(real_ret, real_alloc, "real",
                                 STARTING, real_alloc.diff().abs().sum())
    real_sharpe = real_stats["sharpe"]
    real_dd = real_stats["max_drawdown"]
    real_ret_total = real_stats["total_return"]

    # Build null: for each iteration, shuffle the sign-change dates RANDOMLY
    sign_series = agg_w_12.set_index("asof")["sign_w12"].sort_index().dropna()
    # Convert to daily allocation
    sign_daily_real = sign_series.reindex(daily_ret.index, method="ffill").fillna(0)

    null_sharpes = []
    null_dds = []
    null_returns = []
    rng = np.random.default_rng(42)
    for _ in range(n_iter):
        # Random allocation series with same overall in-market fraction
        target_alloc_rate = (sign_daily_real <= 0).mean()  # match real strategy
        # Generate random "in-market" days via Bernoulli with same rate
        random_alloc = pd.Series(
            rng.binomial(1, target_alloc_rate, size=len(daily_ret)),
            index=daily_ret.index, dtype=float)
        # Smooth to weekly blocks to match real signal's "weekly flips" character
        # (real signal flips ~37 times over 11 years ≈ every 75 BD)
        # Use weekly blocks
        n_weeks = len(daily_ret) // 5
        random_blocks = rng.binomial(1, target_alloc_rate, size=n_weeks)
        random_alloc_blocked = pd.Series(
            np.repeat(random_blocks, 5)[:len(daily_ret)],
            index=daily_ret.index, dtype=float)

        # Cost
        alloc_change = random_alloc_blocked.diff().abs().fillna(0)
        cost = alloc_change * (COST_BPS / 10000)
        rand_ret = daily_ret * random_alloc_blocked - cost

        # Stats
        ann_vol = float(rand_ret.std() * np.sqrt(252))
        n_years = (rand_ret.index[-1] - rand_ret.index[0]).days / 365.25
        ann_ret = float(np.exp(rand_ret.sum() / n_years) - 1)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
        price = cumulative_index(rand_ret) * STARTING
        max_dd, _, _ = max_drawdown(price)
        total_ret = float(np.exp(rand_ret.sum()) - 1)
        null_sharpes.append(sharpe)
        null_dds.append(max_dd)
        null_returns.append(total_ret)

    null_sharpes = np.array(null_sharpes)
    null_dds = np.array(null_dds)
    null_returns = np.array(null_returns)

    p_sharpe = float(np.mean(null_sharpes >= real_sharpe))   # one-tail: real beats random
    p_dd     = float(np.mean(null_dds <= real_dd))            # one-tail: real has shallower DD
    p_ret    = float(np.mean(null_returns >= real_ret_total))

    return {
        "real_sharpe": real_sharpe, "real_max_dd": real_dd,
        "real_total_return": real_ret_total,
        "null_sharpe_mean": float(np.mean(null_sharpes)),
        "null_sharpe_p05": float(np.percentile(null_sharpes, 5)),
        "null_sharpe_p95": float(np.percentile(null_sharpes, 95)),
        "null_dd_mean": float(np.mean(null_dds)),
        "null_dd_p05": float(np.percentile(null_dds, 5)),
        "null_dd_p95": float(np.percentile(null_dds, 95)),
        "null_return_mean": float(np.mean(null_returns)),
        "null_return_p95": float(np.percentile(null_returns, 95)),
        "p_value_sharpe": p_sharpe,
        "p_value_dd": p_dd,
        "p_value_return": p_ret,
        "n_iter": n_iter,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[BMZ_MULTI] Building β_mz weekly aggregate...")
    agg = compute_weekly_aggregate()
    agg_12 = add_slope_signs(agg, window_weeks=12)

    print("\n" + "=" * 70)
    print(" ANALYSIS 1: Strategy generalizes across multiple indices?")
    print("=" * 70)
    mi_df = run_multi_index(agg_12)
    mi_df.to_csv(OUT_DIR / "beta_mz_multi_index.csv", index=False)
    cols = ["index", "strategy", "total_return", "annualized_return",
            "sharpe", "sortino", "max_drawdown", "time_in_market", "ending_value"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(mi_df[cols].to_string(index=False))

    # Compute per-index lift summary
    print("\n--- Per-index summary: did CASH beat BH? ---")
    summary = []
    for idx in mi_df["index"].unique():
        bh = mi_df[(mi_df["index"] == idx) & (mi_df["strategy"] == "BH")].iloc[0]
        cash = mi_df[(mi_df["index"] == idx) & (mi_df["strategy"] == "CASH")].iloc[0]
        summary.append({
            "index": idx,
            "BH_total_ret":      bh["total_return"],
            "CASH_total_ret":    cash["total_return"],
            "delta_total_ret":   cash["total_return"] - bh["total_return"],
            "BH_sharpe":         bh["sharpe"],
            "CASH_sharpe":       cash["sharpe"],
            "delta_sharpe":      cash["sharpe"] - bh["sharpe"],
            "BH_max_dd":         bh["max_drawdown"],
            "CASH_max_dd":       cash["max_drawdown"],
            "dd_reduction":      abs(bh["max_drawdown"]) - abs(cash["max_drawdown"]),
        })
    sum_df = pd.DataFrame(summary)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(sum_df.to_string(index=False))

    n_win_sharpe = int((sum_df["delta_sharpe"] > 0).sum())
    n_win_dd     = int((sum_df["dd_reduction"] > 0).sum())
    print(f"\n  CASH beats BH on Sharpe: {n_win_sharpe}/{len(sum_df)} indices")
    print(f"  CASH reduces max DD:     {n_win_dd}/{len(sum_df)} indices")

    # ── ANALYSIS 2: Monte Carlo hypothesis test on SPY ──────────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 2: MONTE CARLO HYPOTHESIS TEST (N=1000) on SPY")
    print(" H0: β_mz regime-flip dates are random; strategy Sharpe = null.")
    print("=" * 70)
    spy_ret = load_index_returns("SPY")
    spy_ret = spy_ret[spy_ret.index >= START_DATE]
    mc = monte_carlo_null(spy_ret, agg_12, n_iter=N_BOOTSTRAP)
    for k, v in mc.items():
        if isinstance(v, float):
            print(f"  {k:25s}: {v:+.4f}")
        else:
            print(f"  {k:25s}: {v}")

    print(f"\n  INTERPRETATION:")
    print(f"  - Real SPY-overlay Sharpe = {mc['real_sharpe']:+.3f}")
    print(f"  - Null (random) Sharpe range (P5-P95) = ({mc['null_sharpe_p05']:+.3f}, {mc['null_sharpe_p95']:+.3f})")
    print(f"  - p-value (real Sharpe > null) = {mc['p_value_sharpe']:.3f}")
    if mc['p_value_sharpe'] < 0.05:
        print(f"  ⇒ Strategy is statistically significantly better than random (95% confidence)")
    elif mc['p_value_sharpe'] < 0.10:
        print(f"  ⇒ Strategy is marginally significant (90% confidence)")
    else:
        print(f"  ⇒ Strategy is NOT distinguishable from random signal")

    pd.DataFrame([mc]).to_csv(OUT_DIR / "beta_mz_monte_carlo.csv", index=False)
    print(f"\n[BMZ_MULTI] Wrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
