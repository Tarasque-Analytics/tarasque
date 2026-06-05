"""
beta_mz_defensive_overlay.py — Rigorous testing of β_mz as a defensive
                               overlay signal.

Four analyses:

  1. IC against forward RETURN + DRAWDOWN (not just vol). Defensive overlay
     cares about avoiding losses, not predicting vol level per se.

  2. MULTI-SIGNAL COMBINATION: β_mz + HY spread + yield curve + breakeven
     trend. Does combining macro signals with β_mz improve early-warning
     hit rate for forward drawdowns > 10% over 42 BD?

  3. COST-MODELED BACKTEST: same CASH overlay as before, but charge 5 bps
     per allocation flip (= 10 bps round trip). Does the strategy still
     beat buy-and-hold after realistic transaction costs?

  4. SUBPERIOD ANALYSIS: do the strategy stats hold across distinct market
     regimes?
       calm:    2015-2019
       COVID:   2020
       infl:    2021-2026

Outputs:
  results/validation/beta_mz_defensive_overlay.csv
  results/validation/beta_mz_subperiod.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_drawdown_value import (
    load_universe_equal_weighted_index, cumulative_index,
    max_drawdown, forward_window_metrics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "model" / "pipeline" / "results"
OUT_DIR = RESULTS_DIR / "validation"

START_DATE = pd.Timestamp("2015-01-01")
STARTING_CAPITAL = 100_000
COST_PER_FLIP_BPS = 5      # 5 bps per allocation change (10 bps round trip)
SUBPERIODS = [
    ("calm",  pd.Timestamp("2015-01-01"), pd.Timestamp("2019-12-31")),
    ("covid", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")),
    ("infl",  pd.Timestamp("2021-01-01"), pd.Timestamp("2026-05-26")),
]


# ============================================================================
# DATA: macro signals (already in FRED cache)
# ============================================================================

def load_macro() -> pd.DataFrame:
    dc, _, _ = load_config()
    store = ParquetStore(dc.base_dir)
    fred = store.load("fred")
    fred["date"] = pd.to_datetime(fred["date"], format="mixed")
    macro = fred.set_index("date").sort_index()
    # Derived signals
    macro["yield_curve"] = macro["treasury_10y"] - macro["treasury_3mo"]
    # Z-scores against rolling 252 BD for each
    for col in ["hy_spread", "yield_curve", "breakeven_5y", "dollar_index",
                "inflation_forward_5y5y"]:
        if col in macro.columns:
            rmean = macro[col].rolling(252, min_periods=63).mean()
            rstd  = macro[col].rolling(252, min_periods=63).std()
            macro[f"{col}_z"] = (macro[col] - rmean) / rstd.replace(0, np.nan)
    return macro


# ============================================================================
# ANALYSIS 1: IC vs forward return + drawdown
# ============================================================================

def ic_against_returns(daily_ret: pd.Series, agg_w: pd.DataFrame) -> pd.DataFrame:
    """For each date with valid β_mz level + slope, compute forward log
    return and max drawdown over next h BD on the equal-weighted universe.
    Then Spearman IC of each predictor vs each outcome."""
    price = cumulative_index(daily_ret)
    rows = []
    agg_w = agg_w.dropna(subset=["mean_bmz", "slope_w12"]).copy()

    for h in (21, 42, 63):
        fwd_ret = []
        fwd_dd = []
        fwd_vol = []
        valid = []
        for d in agg_w["asof"]:
            m = forward_window_metrics(price, d, h)
            if np.isfinite(m.get("log_ret", np.nan)):
                fwd_ret.append(m["log_ret"])
                fwd_dd.append(m["max_dd"])
                # Quick fwd vol calc
                idx = price.index.searchsorted(d, side="left")
                if idx + h < len(price):
                    log_ret_window = np.log(price.iloc[idx:idx+h+1]).diff().dropna().values
                    fwd_vol.append(float(np.std(log_ret_window) * np.sqrt(252)) if len(log_ret_window) > 5 else np.nan)
                else:
                    fwd_vol.append(np.nan)
                valid.append(d)

        sub = agg_w[agg_w["asof"].isin(valid)].copy()
        sub = sub.set_index("asof").loc[valid]
        sub[f"fwd_ret_h{h}"] = fwd_ret
        sub[f"fwd_dd_h{h}"]  = fwd_dd
        sub[f"fwd_vol_h{h}"] = fwd_vol

        for predictor in ("mean_bmz", "slope_w12"):
            for outcome in (f"fwd_ret_h{h}", f"fwd_dd_h{h}", f"fwd_vol_h{h}"):
                clean = sub[[predictor, outcome]].dropna()
                if len(clean) < 50:
                    continue
                ic = float(clean[predictor].corr(clean[outcome], method="spearman"))
                rows.append({"predictor": predictor, "outcome": outcome,
                             "horizon": h, "n": len(clean), "ic": ic})
    return pd.DataFrame(rows)


# ============================================================================
# ANALYSIS 2: Multi-signal combination — does adding macro improve hit rate?
# ============================================================================

def multi_signal_hit_rate(daily_ret: pd.Series, agg_w: pd.DataFrame,
                           macro: pd.DataFrame) -> pd.DataFrame:
    """Define 'shock event' = forward 42-BD max DD < -10% on universe.
    Test hit rates of various single-signal and combined-signal triggers."""
    price = cumulative_index(daily_ret)
    panel = agg_w[["asof", "mean_bmz", "slope_w12"]].copy()
    panel.index = panel["asof"]

    # Forward outcome: did a 10% drawdown happen in next 42 BD?
    panel["fwd_dd_42"] = panel["asof"].apply(
        lambda d: forward_window_metrics(price, d, 42).get("max_dd", np.nan))
    panel["shock"] = (panel["fwd_dd_42"] < -0.10).astype(int)

    # Attach macro z-scores
    macro_cols = [c for c in macro.columns if c.endswith("_z")]
    panel = panel.join(macro[macro_cols], how="left").ffill()

    # Per-signal triggers
    signals = {
        "beta_mz_level_low":     panel["mean_bmz"] < panel["mean_bmz"].quantile(0.30),
        "beta_mz_slope_positive": panel["slope_w12"] > 0,
        "hy_spread_high":         panel.get("hy_spread_z") > 1.0 if "hy_spread_z" in panel.columns else None,
        "yield_curve_low":        panel.get("yield_curve_z") < -1.0 if "yield_curve_z" in panel.columns else None,
        "breakeven_high":         panel.get("breakeven_5y_z") > 1.0 if "breakeven_5y_z" in panel.columns else None,
    }
    signals = {k: v for k, v in signals.items() if v is not None}

    rows = []
    for name, trigger in signals.items():
        sub = panel[trigger.fillna(False) & panel["shock"].notna()]
        if sub.empty:
            continue
        n_trig = int(trigger.fillna(False).sum())
        n_shock_in_trig = int(sub["shock"].sum())
        hit_rate = n_shock_in_trig / n_trig if n_trig else np.nan
        base_rate = panel["shock"].mean()
        lift = hit_rate / base_rate if base_rate else np.nan
        rows.append({"signal": name, "n_trigger_dates": n_trig,
                     "n_shocks_caught": n_shock_in_trig,
                     "hit_rate": hit_rate, "base_rate": base_rate,
                     "lift_over_base": lift})

    # Combined signal: β_mz LEVEL low AND HY spread Z > 1
    if "hy_spread_z" in panel.columns:
        combo_a = (panel["mean_bmz"] < panel["mean_bmz"].quantile(0.30)) & \
                   (panel["hy_spread_z"] > 1.0)
        sub = panel[combo_a.fillna(False) & panel["shock"].notna()]
        if not sub.empty:
            n_trig = int(combo_a.fillna(False).sum())
            n_caught = int(sub["shock"].sum())
            hit = n_caught / n_trig if n_trig else np.nan
            rows.append({
                "signal": "beta_mz_low_AND_hy_spread_high",
                "n_trigger_dates": n_trig, "n_shocks_caught": n_caught,
                "hit_rate": hit, "base_rate": panel["shock"].mean(),
                "lift_over_base": hit / panel["shock"].mean() if panel["shock"].mean() else np.nan,
            })

    # Combined: β_mz LEVEL low OR HY high (broader net)
    if "hy_spread_z" in panel.columns:
        combo_b = (panel["mean_bmz"] < panel["mean_bmz"].quantile(0.30)) | \
                   (panel["hy_spread_z"] > 1.0)
        sub = panel[combo_b.fillna(False) & panel["shock"].notna()]
        if not sub.empty:
            n_trig = int(combo_b.fillna(False).sum())
            n_caught = int(sub["shock"].sum())
            hit = n_caught / n_trig if n_trig else np.nan
            rows.append({
                "signal": "beta_mz_low_OR_hy_spread_high",
                "n_trigger_dates": n_trig, "n_shocks_caught": n_caught,
                "hit_rate": hit, "base_rate": panel["shock"].mean(),
                "lift_over_base": hit / panel["shock"].mean() if panel["shock"].mean() else np.nan,
            })

    return pd.DataFrame(rows)


# ============================================================================
# ANALYSIS 3: Cost-modeled backtest
# ============================================================================

def cost_modeled_backtest(daily_ret: pd.Series, agg_w: pd.DataFrame,
                           window: int, mode: str,
                           cost_bps_per_flip: float) -> tuple:
    """Same as simulate_strategy but charges cost_bps on every allocation
    change (entry into or exit from cash)."""
    sign_col = f"sign_w{window}"
    if sign_col not in agg_w.columns:
        agg_w = add_slope_signs(agg_w, window)
    slope_series = agg_w.set_index("asof")[sign_col].sort_index()
    sign_daily = slope_series.reindex(daily_ret.index, method="ffill")

    if mode == "BH":
        alloc = pd.Series(1.0, index=daily_ret.index)
    elif mode == "CASH":
        alloc = (sign_daily <= 0).astype(float)
    elif mode == "HALF":
        alloc = pd.Series(1.0, index=daily_ret.index)
        alloc[sign_daily > 0] = 0.5
    else:
        raise ValueError(mode)

    # Cost on allocation changes
    alloc_change = alloc.diff().abs().fillna(0)
    cost_drag = alloc_change * (cost_bps_per_flip / 10000)
    strat_ret_net = (daily_ret * alloc) - cost_drag
    return strat_ret_net, alloc, alloc_change.sum()


def strategy_stats(strat_ret: pd.Series, alloc: pd.Series, name: str,
                    starting: float, n_flips: float) -> dict:
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
        "time_in_market": float(alloc.mean()),
        "n_alloc_flips": float(n_flips),
        "ending_value": float(price.iloc[-1]),
    }


# ============================================================================
# ANALYSIS 4: Subperiod analysis
# ============================================================================

def subperiod_analysis(daily_ret: pd.Series, agg_w_12: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, start, end in SUBPERIODS:
        sub_ret = daily_ret[(daily_ret.index >= start) & (daily_ret.index <= end)]
        if sub_ret.empty:
            continue
        for mode in ("BH", "CASH"):
            strat_ret, alloc, n_flips = cost_modeled_backtest(
                sub_ret, agg_w_12, 12, mode, cost_bps_per_flip=COST_PER_FLIP_BPS)
            r = strategy_stats(strat_ret, alloc, f"{mode}_{label}",
                               STARTING_CAPITAL, n_flips)
            r["subperiod"] = label
            rows.append(r)
    return pd.DataFrame(rows)


# ============================================================================
# MAIN
# ============================================================================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[BMZ_DEF] Loading universe + β_mz aggregate + macro...")
    daily_ret = load_universe_equal_weighted_index()
    daily_ret = daily_ret[daily_ret.index >= START_DATE]
    agg = compute_weekly_aggregate()
    agg_12 = add_slope_signs(agg, window_weeks=12)
    macro = load_macro()

    # ── ANALYSIS 1: IC vs return/drawdown ────────────────────────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 1: β_mz IC vs forward RETURN + DRAWDOWN + VOL")
    print("=" * 70)
    ic_df = ic_against_returns(daily_ret, agg_12)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(ic_df.to_string(index=False))

    # ── ANALYSIS 2: Multi-signal combination ─────────────────────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 2: Single signal vs combined signal HIT RATES")
    print(" (Shock = forward 42-BD max DD < -10% on equal-weight universe)")
    print("=" * 70)
    multi_df = multi_signal_hit_rate(daily_ret, agg_12, macro)
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:.3f}"):
        print(multi_df.to_string(index=False))

    # ── ANALYSIS 3: Cost-modeled backtest ────────────────────────────────
    print("\n" + "=" * 70)
    print(f" ANALYSIS 3: Cost-modeled backtest @ {COST_PER_FLIP_BPS} bps/flip")
    print("=" * 70)
    rows = []
    for window in (12, 24):
        agg_win = add_slope_signs(agg, window_weeks=window)
        for mode in ("BH", "CASH", "HALF"):
            strat_ret, alloc, n_flips = cost_modeled_backtest(
                daily_ret, agg_win, window, mode,
                cost_bps_per_flip=COST_PER_FLIP_BPS)
            r = strategy_stats(strat_ret, alloc, f"{mode}_w{window}",
                               STARTING_CAPITAL, n_flips)
            rows.append(r)
    cost_df = pd.DataFrame(rows)
    cols = ["strategy", "total_return", "annualized_return", "sharpe",
            "sortino", "max_drawdown", "time_in_market", "n_alloc_flips",
            "ending_value"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(cost_df[cols].to_string(index=False))

    # ── ANALYSIS 4: Subperiod analysis ───────────────────────────────────
    print("\n" + "=" * 70)
    print(" ANALYSIS 4: SUBPERIOD analysis (calm 15-19 / COVID 20 / infl 21-26)")
    print("=" * 70)
    sub_df = subperiod_analysis(daily_ret, agg_12)
    cols = ["strategy", "subperiod", "annualized_return", "sharpe",
            "max_drawdown", "ending_value"]
    with pd.option_context("display.width", 200,
                           "display.float_format", lambda v: f"{v:+.3f}"):
        print(sub_df[cols].to_string(index=False))

    # Save
    ic_df.to_csv(OUT_DIR / "beta_mz_ic_vs_returns.csv", index=False)
    multi_df.to_csv(OUT_DIR / "beta_mz_multi_signal.csv", index=False)
    cost_df.to_csv(OUT_DIR / "beta_mz_cost_modeled.csv", index=False)
    sub_df.to_csv(OUT_DIR / "beta_mz_subperiod.csv", index=False)
    print(f"\n[BMZ_DEF] Wrote 4 CSVs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
