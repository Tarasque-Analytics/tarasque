"""
beta_mz_inflection_test.py -- Does the SECOND derivative of universe beta_mz
                              (curvature / inflection points) warn earlier than
                              the first-derivative slope sign-changes we already use?

The canonical signal fires on slope_w12 SIGN CHANGES (first derivative crossing
zero) -- i.e. at LOCAL EXTREMA of mean_bmz (a trough = down->up = heating onset;
a peak = up->down = cooling onset).

An INFLECTION point is where the second derivative (curvature) changes sign:
  - concave->convex (curv neg->pos): the DECLINE stops accelerating and starts
    decelerating. Geometrically this PRECEDES the trough -> should LEAD a
    down->up (heating) slope crossing.
  - convex->concave (curv pos->neg): the RISE stops accelerating -> PRECEDES the
    peak -> should LEAD an up->down (cooling) slope crossing.

Hypothesis: inflections give earlier warning than slope sign-changes. Cost: the
2nd derivative is noisier, so expect MORE events and possibly lower precision.

We estimate curvature with a rolling quadratic fit y = a*x^2 + b*x + c over a
W-week window; sign(a) is the concavity. Sign changes of a = inflection events.

Outputs:
  results/validation/beta_mz_inflection_events.csv
  results/validation/beta_mz_inflection_leadtime.csv
  results/validation/beta_mz_inflection_robustness.csv
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from .beta_mz_deep_dive import compute_weekly_aggregate, add_slope_signs, load_spy_vol
from .beta_mz_drawdown_value import (
    load_universe_equal_weighted_index, cumulative_index, forward_window_metrics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

CURV_WINDOWS = [8, 12, 16]      # weeks, for the rolling quadratic
CANONICAL_W = 12
FWD_HORIZONS = (21, 42)
MAX_LEAD_BD = 60                # an inflection counts as a "precursor" if within 60 BD


def add_curvature(agg: pd.DataFrame, window_weeks: int) -> pd.DataFrame:
    """Rolling quadratic fit; sign of leading coefficient = concavity.
    Detect sign changes = inflection events."""
    def _curv(s):
        if s.isna().any() or len(s) < window_weeks:
            return np.nan
        x = np.arange(len(s), dtype=float)
        # 2*a is the second derivative; sign(a) is what we key on
        return float(np.polyfit(x, s.values, 2)[0])

    out = agg.copy()
    c = f"curv_w{window_weeks}"
    out[c] = out["mean_bmz"].rolling(window_weeks, min_periods=window_weeks).apply(
        _curv, raw=False)
    out[f"curv_sign_w{window_weeks}"] = np.sign(out[c])
    out[f"curv_sign_lag_w{window_weeks}"] = out[f"curv_sign_w{window_weeks}"].shift(1)
    out[f"inflection_w{window_weeks}"] = (
        (out[f"curv_sign_w{window_weeks}"] != out[f"curv_sign_lag_w{window_weeks}"])
        & out[f"curv_sign_w{window_weeks}"].notna()
        & out[f"curv_sign_lag_w{window_weeks}"].notna()
    )
    return out


def fwd_vol_max(spy_vol: pd.Series, d: pd.Timestamp, h: int) -> float:
    i = spy_vol.index.searchsorted(d, side="left")
    if i + h >= len(spy_vol):
        return np.nan
    return float(spy_vol.iloc[i:i + h].max())


def classify_inflection(lag_sign, sign) -> str:
    if lag_sign < 0 and sign > 0:
        return "concave->convex (pre-heating)"
    if lag_sign > 0 and sign < 0:
        return "convex->concave (pre-cooling)"
    return ""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[BMZ_INFL] Building weekly aggregate + SPY vol + EW universe...")
    agg = compute_weekly_aggregate()
    spy_vol = load_spy_vol()
    ew_price = cumulative_index(
        load_universe_equal_weighted_index().loc[lambda s: s.index >= "2015-01-01"])

    agg_slope = add_slope_signs(agg, window_weeks=CANONICAL_W)

    # ── ANALYSIS 1: forward vol + DD lift of inflection events (canonical W) ──
    aggc = add_curvature(agg, CANONICAL_W)
    infl = aggc[aggc[f"inflection_w{CANONICAL_W}"]].copy()
    infl["type"] = infl.apply(
        lambda r: classify_inflection(r[f"curv_sign_lag_w{CANONICAL_W}"],
                                      r[f"curv_sign_w{CANONICAL_W}"]), axis=1)

    for h in FWD_HORIZONS:
        infl[f"fwd_vol_h{h}"] = infl["asof"].apply(lambda d: fwd_vol_max(spy_vol, d, h))
        infl[f"fwd_dd_h{h}"] = infl["asof"].apply(
            lambda d: forward_window_metrics(ew_price, d, h).get("max_dd", np.nan))

    # baseline = non-inflection valid dates
    valid = aggc.dropna(subset=[f"curv_w{CANONICAL_W}"])
    nonev = valid[~valid[f"inflection_w{CANONICAL_W}"]]
    base = {}
    for h in FWD_HORIZONS:
        bv = nonev["asof"].apply(lambda d: fwd_vol_max(spy_vol, d, h)).dropna()
        bd = nonev["asof"].apply(
            lambda d: forward_window_metrics(ew_price, d, h).get("max_dd", np.nan)).dropna()
        base[f"vol_h{h}"] = float(bv.mean())
        base[f"dd_h{h}"] = float(bd.mean())

    print("\n" + "=" * 76)
    print(f" ANALYSIS 1: inflection events (curvature W={CANONICAL_W}w) forward outcomes")
    print("=" * 76)
    print(f"  baseline (non-inflection): "
          + "  ".join(f"fwd_vol_h{h}={base[f'vol_h{h}']:.3f}" for h in FWD_HORIZONS))
    print(f"  baseline (non-inflection): "
          + "  ".join(f"fwd_dd_h{h}={base[f'dd_h{h}']:+.3f}" for h in FWD_HORIZONS))

    summ_rows = []
    for typ in ("concave->convex (pre-heating)", "convex->concave (pre-cooling)"):
        sub = infl[infl["type"] == typ]
        if sub.empty:
            continue
        row = {"type": typ, "n_events": len(sub)}
        for h in FWD_HORIZONS:
            v = sub[f"fwd_vol_h{h}"].dropna()
            d = sub[f"fwd_dd_h{h}"].dropna()
            row[f"vol_h{h}_mean"] = float(v.mean()) if len(v) else np.nan
            row[f"vol_h{h}_lift"] = float(v.mean() / base[f"vol_h{h}"]) if len(v) else np.nan
            row[f"dd_h{h}_mean"] = float(d.mean()) if len(d) else np.nan
            row[f"dd_h{h}_pct_gt10"] = float((d < -0.10).mean()) if len(d) else np.nan
        summ_rows.append(row)
    summ = pd.DataFrame(summ_rows)
    with pd.option_context("display.width", 220, "display.float_format",
                           lambda v: f"{v:+.3f}"):
        print(summ.to_string(index=False))

    print("\n  Reference -- slope SIGN-CHANGE events (the signal we already use):")
    du = agg_slope[agg_slope["sign_change_w12"] & (agg_slope["sign_lag_w12"] < 0)
                   & (agg_slope["sign_w12"] > 0)]
    ud = agg_slope[agg_slope["sign_change_w12"] & (agg_slope["sign_lag_w12"] > 0)
                   & (agg_slope["sign_w12"] < 0)]
    for label, ev in [("down->up (heating)", du), ("up->down (cooling)", ud)]:
        vh = ev["asof"].apply(lambda d: fwd_vol_max(spy_vol, d, 42)).dropna()
        lift = vh.mean() / base["vol_h42"] if len(vh) else np.nan
        print(f"    {label:22s}: n={len(ev):2d}  fwd_vol_h42 lift {lift:+.3f}")

    # ── ANALYSIS 2: LEAD TIME -- do inflections precede slope sign-changes? ──
    print("\n" + "=" * 76)
    print(" ANALYSIS 2: LEAD TIME -- inflection precedes matching slope sign-change?")
    print("=" * 76)
    pairs = [
        ("down->up (heating)", du, "concave->convex (pre-heating)"),
        ("up->down (cooling)", ud, "convex->concave (pre-cooling)"),
    ]
    lead_rows = []
    for slope_label, slope_ev, infl_type in pairs:
        infl_dates = infl[infl["type"] == infl_type]["asof"].sort_values().tolist()
        for _, se in slope_ev.iterrows():
            d_s = se["asof"]
            prior = [di for di in infl_dates if di <= d_s]
            if not prior:
                lead_rows.append({"slope_event": d_s.date().isoformat(),
                                  "slope_type": slope_label, "infl_date": None,
                                  "lead_bd": np.nan})
                continue
            di = prior[-1]
            lead = int(np.busday_count(di.date(), d_s.date()))
            lead_rows.append({"slope_event": d_s.date().isoformat(),
                              "slope_type": slope_label,
                              "infl_date": di.date().isoformat(),
                              "lead_bd": lead})
    lead_df = pd.DataFrame(lead_rows)
    with pd.option_context("display.width", 200, "display.float_format",
                           lambda v: f"{v:.1f}"):
        print(lead_df.to_string(index=False))

    print("\n  Lead-time summary (only precursors within "
          f"{MAX_LEAD_BD} BD count as 'the' precursor):")
    for slope_label in lead_df["slope_type"].unique():
        sub = lead_df[(lead_df["slope_type"] == slope_label)
                      & lead_df["lead_bd"].notna()
                      & (lead_df["lead_bd"] <= MAX_LEAD_BD)
                      & (lead_df["lead_bd"] >= 0)]
        n_total = int((lead_df["slope_type"] == slope_label).sum())
        if sub.empty:
            print(f"    {slope_label:22s}: 0/{n_total} had an inflection precursor "
                  f"within {MAX_LEAD_BD} BD")
            continue
        lb = sub["lead_bd"].astype(float)
        print(f"    {slope_label:22s}: {len(sub)}/{n_total} preceded by inflection  "
              f"| lead BD mean {lb.mean():.1f} median {lb.median():.1f} "
              f"(min {lb.min():.0f} max {lb.max():.0f})")

    # ── ANALYSIS 3: robustness of inflection signal across curvature windows ──
    print("\n" + "=" * 76)
    print(" ANALYSIS 3: robustness across curvature windows (event counts + vol lift)")
    print("=" * 76)
    rob_rows = []
    for w in CURV_WINDOWS:
        aw = add_curvature(agg, w)
        ev = aw[aw[f"inflection_w{w}"]].copy()
        ev["type"] = ev.apply(
            lambda r: classify_inflection(r[f"curv_sign_lag_w{w}"],
                                          r[f"curv_sign_w{w}"]), axis=1)
        vbase = aw.dropna(subset=[f"curv_w{w}"])
        vbase = vbase[~vbase[f"inflection_w{w}"]]["asof"].apply(
            lambda d: fwd_vol_max(spy_vol, d, 42)).dropna().mean()
        for typ in ("concave->convex (pre-heating)", "convex->concave (pre-cooling)"):
            sub = ev[ev["type"] == typ]
            vh = sub["asof"].apply(lambda d: fwd_vol_max(spy_vol, d, 42)).dropna()
            rob_rows.append({
                "curv_window_w": w, "type": typ, "n_events": len(sub),
                "fwd_vol_h42_mean": float(vh.mean()) if len(vh) else np.nan,
                "fwd_vol_h42_lift": float(vh.mean() / vbase) if len(vh) and vbase else np.nan,
            })
    rob = pd.DataFrame(rob_rows)
    with pd.option_context("display.width", 200, "display.float_format",
                           lambda v: f"{v:+.3f}"):
        print(rob.to_string(index=False))

    # save
    infl_out = infl[["asof", "type", f"curv_w{CANONICAL_W}"]
                    + [f"fwd_vol_h{h}" for h in FWD_HORIZONS]
                    + [f"fwd_dd_h{h}" for h in FWD_HORIZONS]].copy()
    infl_out.to_csv(OUT_DIR / "beta_mz_inflection_events.csv", index=False)
    lead_df.to_csv(OUT_DIR / "beta_mz_inflection_leadtime.csv", index=False)
    rob.to_csv(OUT_DIR / "beta_mz_inflection_robustness.csv", index=False)
    print(f"\n[BMZ_INFL] Wrote 3 CSVs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
