"""
beta_mz_drawdown_value.py — How much drawdown could the β_mz signal have helped
                            an equal-weighted-universe index investor avoid?

Treats the 93-ticker corpus as an equal-weighted index fund. Then asks:

  1. Historical drawdown profile — what's the max DD on this index? When?
  2. Per-event impact — at each down→up signal event, what was the forward
     drawdown over next 21/42/63 BD?
  3. Strategy simulation — three defensive overlays:
        BH:       buy and hold (baseline)
        CASH:     go to 100% cash on down→up, back to long on up→down
        HALF:     go to 50% cash on down→up, back to 100% on up→down
     For each: total return, annualized return, max DD, Sharpe, Sortino,
     time-in-market.
  4. Net dollar comparison — if you put $100k in 2015, what's the ending
     value under each strategy?

Uses 24-week smoothing (per deep dive: strongest signal). Tests 12-week too.

Outputs:
  results/validation/beta_mz_strategy_backtest.csv
  results/validation/beta_mz_per_event_dd.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

START_DATE = pd.Timestamp("2015-01-01")
STARTING_CAPITAL = 100_000  # $100k starting portfolio for the dollar comparison
SLOPE_WINDOWS = [12, 24]  # test both


def load_universe_equal_weighted_index() -> pd.Series:
    """Construct equal-weighted daily return index from 93-ticker universe."""
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    ohlcv = store.load("ohlcv")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"], format="mixed")
    closes = ohlcv.drop_duplicates(subset=["date", "ticker"], keep="last") \
                   .pivot(index="date", columns="ticker", values="prc").ffill()
    # Use the 93 corpus tickers — filter from the config
    tickers = [t for t in dc.tickers if t in closes.columns]
    print(f"  [INDEX] {len(tickers)} of {len(dc.tickers)} universe tickers in closes")
    px = closes[tickers].copy()
    daily_ret = np.log(px / px.shift(1))
    # Equal weight each day across non-NaN tickers
    ew_ret = daily_ret.mean(axis=1, skipna=True).dropna()
    return ew_ret


def cumulative_index(daily_log_ret: pd.Series) -> pd.Series:
    """Convert daily log returns to cumulative price index (starts at 1.0)."""
    return np.exp(daily_log_ret.cumsum())


def max_drawdown(price: pd.Series) -> tuple:
    """Max drawdown over a price series. Returns (max_dd, start_date, end_date)."""
    running_max = price.cummax()
    dd = (price / running_max) - 1
    end = dd.idxmin()
    start = price.loc[:end].idxmax()
    return float(dd.min()), start, end


def forward_window_metrics(price: pd.Series, start_date: pd.Timestamp,
                            h_bd: int) -> dict:
    """Forward h-BD log return, max DD, peak DD date."""
    idx = price.index.searchsorted(start_date, side="left")
    if idx + h_bd >= len(price):
        return {"log_ret": np.nan, "max_dd": np.nan, "dd_end_date": None}
    window = price.iloc[idx:idx + h_bd + 1]
    if window.empty:
        return {"log_ret": np.nan, "max_dd": np.nan, "dd_end_date": None}
    start_price = window.iloc[0]
    end_price = window.iloc[-1]
    log_ret = float(np.log(end_price / start_price))
    running_max = window.cummax()
    dd = (window / running_max) - 1
    return {"log_ret": log_ret, "max_dd": float(dd.min()),
            "dd_end_date": str(dd.idxmin().date())}


def simulate_strategy(daily_ret: pd.Series, agg_w: pd.DataFrame,
                       window: int, mode: str) -> tuple:
    """
    mode = 'BH' (buy-and-hold), 'CASH' (long when slope ≥0, flat when <0),
           'HALF' (long when slope ≥0, 50% when <0).
    Uses the slope sign from agg_w[f'sign_w{window}'] to decide allocation.
    Returns (strategy daily ret series, allocation series).
    """
    # Build allocation series: for each date, look up the most recent slope sign
    sign_col = f"sign_w{window}"
    slope_series = agg_w.set_index("asof")[sign_col].sort_index()
    # Forward-fill weekly sign into daily allocation
    dates = daily_ret.index
    sign_daily = slope_series.reindex(dates, method="ffill")

    if mode == "BH":
        alloc = pd.Series(1.0, index=dates)
    elif mode == "CASH":
        # When slope ≥ 0 (heating), STAY LONG. When slope < 0 (cooling, after
        # an up→down event), go to cash. WAIT — that's backwards.
        # Per analysis: down→up event = forward vol UP. So we want to derisk
        # AFTER a down→up event = WHEN SLOPE GOES POSITIVE. Stay invested when
        # slope is negative (cooling = safe).
        # So: cash when slope > 0, long when slope ≤ 0.
        alloc = (sign_daily <= 0).astype(float)
    elif mode == "HALF":
        alloc = pd.Series(1.0, index=dates)
        alloc[sign_daily > 0] = 0.5
    else:
        raise ValueError(mode)
    strat_ret = daily_ret * alloc
    return strat_ret, alloc


def strategy_stats(strat_ret: pd.Series, alloc: pd.Series,
                    name: str, starting: float) -> dict:
    price = cumulative_index(strat_ret) * starting
    total_log_ret = float(strat_ret.sum())
    total_simple_ret = float(np.exp(total_log_ret) - 1)
    n_years = (strat_ret.index[-1] - strat_ret.index[0]).days / 365.25
    ann_ret = float(np.exp(total_log_ret / n_years) - 1) if n_years > 0 else np.nan
    ann_vol = float(strat_ret.std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    # Sortino (downside-only vol)
    down = strat_ret[strat_ret < 0]
    sortino_vol = float(down.std() * np.sqrt(252)) if len(down) else np.nan
    sortino = ann_ret / sortino_vol if sortino_vol and sortino_vol > 0 else np.nan
    max_dd, dd_s, dd_e = max_drawdown(price)
    time_in_mkt = float(alloc.mean())
    return {
        "strategy": name,
        "total_return": total_simple_ret,
        "annualized_return": ann_ret,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "max_dd_date": str(dd_e.date()),
        "time_in_market": time_in_mkt,
        "ending_value": float(price.iloc[-1]),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[BMZ_DD] Loading equal-weighted universe index...")
    daily_ret = load_universe_equal_weighted_index()
    daily_ret = daily_ret[daily_ret.index >= START_DATE]
    print(f"  {len(daily_ret)} trading days, {daily_ret.index.min().date()} -> {daily_ret.index.max().date()}")

    price = cumulative_index(daily_ret) * STARTING_CAPITAL

    # Baseline: max DD across the full period
    bh_dd, bh_dd_s, bh_dd_e = max_drawdown(price)
    print(f"\n  Buy-and-hold max DD: {bh_dd:.1%}  ({bh_dd_s.date()} -> {bh_dd_e.date()})")

    print("\n[BMZ_DD] Building β_mz weekly aggregate...")
    agg = compute_weekly_aggregate()

    # ── Per-event DD analysis (24-week canonical) ────────────────────────
    print("\n" + "=" * 70)
    print(" PER-EVENT FORWARD DRAWDOWN (24-week β_mz, equal-weighted universe)")
    print("=" * 70)
    agg_24 = add_slope_signs(agg, window_weeks=24)
    du_events = agg_24[
        agg_24["sign_change_w24"] & (agg_24["sign_lag_w24"] < 0) & (agg_24["sign_w24"] > 0)
    ]
    ud_events = agg_24[
        agg_24["sign_change_w24"] & (agg_24["sign_lag_w24"] > 0) & (agg_24["sign_w24"] < 0)
    ]

    event_rows = []
    for direction, events in [("down->up", du_events), ("up->down", ud_events)]:
        for _, ev in events.iterrows():
            for h in (21, 42, 63):
                m = forward_window_metrics(price, ev["asof"], h)
                event_rows.append({
                    "event_date": ev["asof"].date().isoformat(),
                    "direction": direction,
                    "horizon_bd": h,
                    **m,
                })
    ev_df = pd.DataFrame(event_rows)
    ev_df.to_csv(OUT_DIR / "beta_mz_per_event_dd.csv", index=False)

    # Summary table
    print("\nDown->up events (universe forward log return + max DD):")
    du_sum = ev_df[ev_df.direction == "down->up"].groupby("horizon_bd").agg(
        n=("log_ret", "count"),
        mean_log_ret=("log_ret", "mean"),
        mean_max_dd=("max_dd", "mean"),
        worst_max_dd=("max_dd", "min"),
        pct_with_dd_gt_10=("max_dd", lambda s: (s < -0.10).mean()),
    ).reset_index()
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(du_sum.to_string(index=False))

    print("\nUp->down events (control — should show no drawdown stress):")
    ud_sum = ev_df[ev_df.direction == "up->down"].groupby("horizon_bd").agg(
        n=("log_ret", "count"),
        mean_log_ret=("log_ret", "mean"),
        mean_max_dd=("max_dd", "mean"),
        worst_max_dd=("max_dd", "min"),
        pct_with_dd_gt_10=("max_dd", lambda s: (s < -0.10).mean()),
    ).reset_index()
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(ud_sum.to_string(index=False))

    # ── Strategy backtest at both windows ────────────────────────────────
    print("\n" + "=" * 70)
    print(" STRATEGY BACKTEST: buy-and-hold vs defensive overlay")
    print("=" * 70)
    rows = []
    for w in SLOPE_WINDOWS:
        agg_w = add_slope_signs(agg, window_weeks=w)
        for mode in ("BH", "CASH", "HALF"):
            strat_ret, alloc = simulate_strategy(daily_ret, agg_w, w, mode)
            r = strategy_stats(strat_ret, alloc, f"{mode}_w{w}", STARTING_CAPITAL)
            rows.append(r)
    strat_df = pd.DataFrame(rows)
    strat_df.to_csv(OUT_DIR / "beta_mz_strategy_backtest.csv", index=False)
    cols = ["strategy", "total_return", "annualized_return", "annualized_vol",
            "sharpe", "sortino", "max_drawdown", "time_in_market", "ending_value"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(strat_df[cols].to_string(index=False))

    print("\n" + "=" * 70)
    print(" $100K STARTING — ending values comparison")
    print("=" * 70)
    bh = strat_df[strat_df.strategy == "BH_w12"].iloc[0]
    cash24 = strat_df[strat_df.strategy == "CASH_w24"].iloc[0]
    half24 = strat_df[strat_df.strategy == "HALF_w24"].iloc[0]
    cash12 = strat_df[strat_df.strategy == "CASH_w12"].iloc[0]
    print(f"  Buy-and-hold       : ${bh['ending_value']:>12,.0f}   max DD {bh['max_drawdown']:.1%}")
    print(f"  CASH overlay (24w) : ${cash24['ending_value']:>12,.0f}   max DD {cash24['max_drawdown']:.1%}   (in mkt {cash24['time_in_market']:.0%})")
    print(f"  CASH overlay (12w) : ${cash12['ending_value']:>12,.0f}   max DD {cash12['max_drawdown']:.1%}   (in mkt {cash12['time_in_market']:.0%})")
    print(f"  HALF overlay (24w) : ${half24['ending_value']:>12,.0f}   max DD {half24['max_drawdown']:.1%}   (in mkt {half24['time_in_market']:.0%})")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
