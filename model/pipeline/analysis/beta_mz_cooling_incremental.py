"""
beta_mz_cooling_incremental.py -- Does the COOLING-leg long signal add incremental
                                  risk-adjusted return over HY-spread-based sizing?

Test A asked whether beta_mz beats HY at DRAWDOWN prediction (the heating /
tail-insurance leg) -- the leg we already knew was marginal. HY won.

This tests the leg that's actually good: the UP->DOWN (cooling) long mean-reversion
harvest -- 79% hit, COVID-robust. The question that decides whether the good part
of this signal is INDEPENDENT or REDUNDANT with credit spreads:

    Sized by HY spread, does adding the beta_mz cooling signal raise the Sharpe
    of the long leg?

Both signals are built IDENTICALLY so the comparison is about the signal, not the
construction: weekly (W-FRI) series, 12-week slope, "calm onset" = slope sign
change from + to - . For beta_mz that's UP->DOWN (models stop under-predicting).
For HY that's spread widening -> tightening (credit stress easing).

Four pieces of evidence:
  1. Head-to-head Sharpe: beta_mz-long overlay vs HY-long overlay (same form).
  2. SPANNING REGRESSION  R_bmz = a + b*R_HY + e  (HAC errors). a>0 & significant
     => beta_mz long-timing is NOT spanned by HY => independent. a~0 => redundant.
  3. Conditional split: beta_mz cooling-event forward returns when HY AGREES (also
     calm) vs DISAGREES. Edge surviving when HY disagrees => independent.
  4. Combined (union) vs HY-alone Sharpe.

Outputs:
  results/validation/beta_mz_cooling_incremental.csv         -- overlay Sharpe table
  results/validation/beta_mz_cooling_spanning.csv            -- spanning + conditional
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs
from .beta_mz_defensive_overlay import load_macro
from .beta_mz_drawdown_value import (
    load_universe_equal_weighted_index, cumulative_index, max_drawdown,
    forward_window_metrics,
)
from .beta_mz_multi_index_test import load_index_returns

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

START_DATE = pd.Timestamp("2015-01-01")
STARTING = 100_000
COST_BPS = 5
HOLD_BD = 40                 # validated optimal cooling-leg hold (holding_period test)
HAC_LAGS = 40                # overlapping 40-BD holds -> autocorrelation
INDICES = ["SPY", "EW_UNIVERSE", "QQQ", "IWM", "XLF"]


# ----------------------------------------------------------------------------
# Build identically-constructed weekly slope-sign frames for beta_mz and HY
# ----------------------------------------------------------------------------

def hy_weekly_frame(macro: pd.DataFrame) -> pd.DataFrame:
    """HY spread resampled to W-FRI, columns (asof, mean_bmz) so we can reuse
    add_slope_signs unchanged. 'mean_bmz' here just means 'the weekly value'."""
    hy = macro["hy_spread"].resample("W-FRI").last().ffill().dropna()
    hyz = macro["hy_spread_z"].resample("W-FRI").last().ffill()
    df = pd.DataFrame({"asof": hy.index, "mean_bmz": hy.values})
    df["hy_z"] = hyz.reindex(hy.index).values
    return df.reset_index(drop=True)


def calm_mask_daily(weekly_signed: pd.DataFrame, dates: pd.DatetimeIndex,
                     mode: str) -> pd.Series:
    """Daily boolean: is the regime 'calm'?
    mode='slope' -> slope_w12 <= 0 ; mode='level' -> hy_z <= 0 (HY only)."""
    if mode == "slope":
        s = weekly_signed.set_index("asof")["sign_w12"].sort_index()
        daily = s.reindex(dates, method="ffill")
        return (daily <= 0)
    elif mode == "level":
        s = weekly_signed.set_index("asof")["hy_z"].sort_index()
        daily = s.reindex(dates, method="ffill")
        return (daily <= 0)
    raise ValueError(mode)


def overlay_returns(index_ret: pd.Series, calm: pd.Series,
                    cost_bps: float = COST_BPS) -> tuple[pd.Series, pd.Series]:
    """Long when calm, cash otherwise. Returns (net daily ret, alloc)."""
    alloc = calm.reindex(index_ret.index).fillna(False).astype(float)
    cost = alloc.diff().abs().fillna(0) * (cost_bps / 1e4)
    return index_ret * alloc - cost, alloc


def sharpe_stats(strat_ret: pd.Series, alloc: pd.Series, name: str) -> dict:
    price = cumulative_index(strat_ret) * STARTING
    n_years = (strat_ret.index[-1] - strat_ret.index[0]).days / 365.25
    ann_ret = float(np.exp(strat_ret.sum() / n_years) - 1) if n_years > 0 else np.nan
    ann_vol = float(strat_ret.std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    mdd, _, _ = max_drawdown(price)
    return {"strategy": name, "ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "max_drawdown": mdd,
            "time_in_market": float(alloc.mean()), "ending_value": float(price.iloc[-1])}


def events_calm_onset(signed: pd.DataFrame) -> list[pd.Timestamp]:
    """'Calm onset' = slope sign change from + to - (slope_lag>0, slope<0)."""
    ev = signed[signed["sign_change_w12"] & (signed["sign_lag_w12"] > 0)
                & (signed["sign_w12"] < 0)]
    return ev["asof"].sort_values().tolist()


def event_hold_mask(events: list, dates: pd.DatetimeIndex, hold_bd: int) -> pd.Series:
    """Daily mask: long for hold_bd BD after each event (entry = first day >= event)."""
    mask = pd.Series(False, index=dates)
    arr = np.array(dates)
    for d in events:
        i = dates.searchsorted(d, side="left")
        if i >= len(dates):
            continue
        j = min(i + hold_bd, len(dates) - 1)
        mask.iloc[i:j + 1] = True
    return mask


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[BMZ_INC] Building beta_mz + HY weekly slope frames (identical construction)...")
    agg = compute_weekly_aggregate()
    bmz = add_slope_signs(agg, window_weeks=12)
    macro = load_macro()
    hy = add_slope_signs(hy_weekly_frame(macro), window_weeks=12)
    # carry hy_z through add_slope_signs (it preserves extra cols)
    if "hy_z" not in hy.columns:
        hy = hy.merge(hy_weekly_frame(macro)[["asof", "hy_z"]], on="asof", how="left")

    # ── PART 1: head-to-head long/cash overlay Sharpe across indices ──────────
    print("\n" + "=" * 80)
    print(" PART 1: long/cash overlay Sharpe -- beta_mz cooling vs HY-spread sizing")
    print(" (long when calm regime, cash otherwise; identical 12wk-slope construction)")
    print("=" * 80)
    rows = []
    for tk in INDICES:
        idx_ret = (load_universe_equal_weighted_index() if tk == "EW_UNIVERSE"
                   else load_index_returns(tk))
        idx_ret = idx_ret[idx_ret.index >= START_DATE]
        if idx_ret.empty:
            continue
        dates = idx_ret.index
        bmz_calm = calm_mask_daily(bmz, dates, "slope")
        hy_calm_s = calm_mask_daily(hy, dates, "slope")
        hy_calm_l = calm_mask_daily(hy, dates, "level")
        variants = {
            "BH": pd.Series(True, index=dates),
            "beta_mz_cool": bmz_calm,
            "HY_slope": hy_calm_s,
            "HY_level": hy_calm_l,
        }
        for name, calm in variants.items():
            r, a = overlay_returns(idx_ret, calm)
            st = sharpe_stats(r, a, name)
            st["index"] = tk
            rows.append(st)
    tbl = pd.DataFrame(rows)
    for tk in tbl["index"].unique():
        sub = tbl[tbl["index"] == tk]
        print(f"\n  {tk}:")
        cols = ["strategy", "ann_return", "sharpe", "max_drawdown",
                "time_in_market", "ending_value"]
        with pd.option_context("display.width", 200,
                               "display.float_format", lambda v: f"{v:+.3f}"):
            print(sub[cols].to_string(index=False))
    tbl.to_csv(OUT_DIR / "beta_mz_cooling_incremental.csv", index=False)

    # ── PART 2: SPANNING REGRESSION on SPY (the decisive test) ────────────────
    print("\n" + "=" * 80)
    print(" PART 2: SPANNING REGRESSION (SPY)  R_bmz = a + b*R_HY + e  [HAC]")
    print("  a>0 & significant => beta_mz cooling NOT spanned by HY => INDEPENDENT")
    print("=" * 80)
    spy = load_index_returns("SPY")
    spy = spy[spy.index >= START_DATE]
    dates = spy.index
    r_bmz, a_bmz = overlay_returns(spy, calm_mask_daily(bmz, dates, "slope"))
    span_rows = []
    for hy_mode, label in [("slope", "HY_slope"), ("level", "HY_level")]:
        r_hy, a_hy = overlay_returns(spy, calm_mask_daily(hy, dates, hy_mode))
        df = pd.concat([r_bmz.rename("bmz"), r_hy.rename("hy")], axis=1).dropna()
        yv = df["bmz"].to_numpy(dtype=float)
        xv = sm.add_constant(df["hy"].to_numpy(dtype=float))
        res = sm.OLS(yv, xv).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
        alpha_d, beta = res.params
        t_alpha = res.tvalues[0]
        p_alpha = res.pvalues[0]
        ann_alpha = float(alpha_d * 252)
        resid_vol_ann = float(np.std(res.resid, ddof=2) * np.sqrt(252))
        ir = ann_alpha / resid_vol_ann if resid_vol_ann > 0 else np.nan
        alloc_corr = float(pd.Series(a_bmz.values).corr(pd.Series(a_hy.values)))
        ret_corr = float(df["bmz"].corr(df["hy"]))
        print(f"\n  vs {label}:")
        print(f"    alpha (annualized) : {ann_alpha:+.2%}   t={t_alpha:+.2f}  p={p_alpha:.3f}")
        print(f"    beta               : {beta:+.3f}")
        print(f"    information ratio  : {ir:+.3f}")
        print(f"    alloc correlation  : {alloc_corr:+.3f}   ret corr: {ret_corr:+.3f}")
        verdict = ("INDEPENDENT (adds incremental risk-adj return)" if (p_alpha < 0.05 and ann_alpha > 0)
                   else "marginal" if (p_alpha < 0.15 and ann_alpha > 0)
                   else "REDUNDANT / spanned")
        print(f"    => {verdict}")
        span_rows.append({"benchmark": label, "ann_alpha": ann_alpha, "t_alpha": t_alpha,
                          "p_alpha": p_alpha, "beta": beta, "info_ratio": ir,
                          "alloc_corr": alloc_corr, "ret_corr": ret_corr})

    # ── PART 3: CONDITIONAL SPLIT -- does beta_mz work when HY DISAGREES? ─────
    print("\n" + "=" * 80)
    print(" PART 3: beta_mz cooling-event fwd-40BD SPY return, split by HY agreement")
    print("  (HY agrees = HY also calm [slope<=0] at the event date)")
    print("=" * 80)
    price = cumulative_index(spy)
    bmz_events = events_calm_onset(bmz)
    hy_sign = hy.set_index("asof")["sign_w12"].sort_index()
    cond_rows = []
    agree, disagree = [], []
    for d in bmz_events:
        m = forward_window_metrics(price, d, HOLD_BD)
        r = m.get("log_ret", np.nan)
        if not np.isfinite(r):
            continue
        hy_state = hy_sign.reindex([d], method="ffill").iloc[0]
        (agree if (pd.notna(hy_state) and hy_state <= 0) else disagree).append(r)
    for label, arr in [("HY agrees (also calm)", agree),
                       ("HY disagrees (not calm)", disagree)]:
        a = np.array(arr, dtype=float)
        if len(a) == 0:
            print(f"  {label:26s}: n=0")
            continue
        print(f"  {label:26s}: n={len(a):2d}  mean {a.mean():+.2%}  "
              f"median {np.median(a):+.2%}  hit {np.mean(a > 0):.0%}  "
              f"per-bet Sharpe {a.mean()/a.std(ddof=1) if len(a)>1 and a.std()>0 else float('nan'):+.2f}")
        cond_rows.append({"hy_state": label, "n": len(a), "mean_ret": float(a.mean()),
                          "median_ret": float(np.median(a)), "hit_rate": float(np.mean(a > 0))})

    # ── PART 4: COMBINED (union) vs HY-alone Sharpe (SPY) ─────────────────────
    print("\n" + "=" * 80)
    print(" PART 4: combined (long if EITHER calm) vs HY-alone vs beta_mz-alone (SPY)")
    print("=" * 80)
    bmz_calm = calm_mask_daily(bmz, dates, "slope")
    for hy_mode, label in [("slope", "HY_slope"), ("level", "HY_level")]:
        hy_calm = calm_mask_daily(hy, dates, hy_mode)
        union = (bmz_calm.reindex(dates).fillna(False) | hy_calm.reindex(dates).fillna(False))
        r_u, a_u = overlay_returns(spy, union)
        r_h, a_h = overlay_returns(spy, hy_calm)
        s_u = sharpe_stats(r_u, a_u, f"UNION(bmz|{label})")
        s_h = sharpe_stats(r_h, a_h, label)
        print(f"\n  {label}: Sharpe {s_h['sharpe']:+.3f} (in-mkt {s_h['time_in_market']:.0%})"
              f"  ->  +beta_mz UNION: Sharpe {s_u['sharpe']:+.3f} "
              f"(in-mkt {s_u['time_in_market']:.0%})  delta {s_u['sharpe']-s_h['sharpe']:+.3f}")

    pd.DataFrame(span_rows).to_csv(OUT_DIR / "beta_mz_cooling_spanning.csv", index=False)
    print(f"\n[BMZ_INC] Wrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
