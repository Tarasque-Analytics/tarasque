"""
vrp_forward_premium_test.py -- Does the FORWARD VRP behave like a real premium?

We established the shipped feature is REFLEXIVE: vrp_wedge = IV - rv_21d_trailing.
A real variance risk premium is FORWARD: VRP = IV - E[RV] (risk-neutral minus
physical expectation). This platform can build the forward version because it has
E[RV] = the model forecast (y_pred).

RECONSTRUCTION (consistent with the pipeline's own definitions, no OptionMetrics
needed): the h=21 target y_true(t) = rv_21d.shift(-21) = realized vol over
[t+1, t+21]. Therefore trailing rv_21d(t) = y_true(t-21). Hence:
    IV(t)        = vrp_wedge(t) + y_true(t-21)
    forward_VRP  = IV - E[RV] = vrp_wedge(t) + y_true(t-21) - y_pred(t)

Three premium diagnostics (vs the reflexive wedge as control):
  1. SIGN      -- a true VRP is predominantly POSITIVE (options are expensive).
  2. STRESS    -- a true VRP WIDENS in stress (Test C: reflexive wedge did NOT).
  3. IC        -- predictive IC for forward RV, pooled + regime-conditional.

Also reports the model's forecast BIAS, since an over-predicting E[RV] mechanically
compresses (and can flip negative) the forward premium.

Output: results/validation/vrp_forward_premium.csv
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .beta_mz_deep_dive import RESULTS_DIR, load_spy_vol

OUT_DIR = RESULTS_DIR / "validation"
H = 21


def build_panel() -> pd.DataFrame:
    rows = []
    for f in sorted(RESULTS_DIR.glob("predictions_*.csv")):
        ticker = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "y_true", "y_pred", "vrp_wedge", "horizon"])
        except Exception:
            continue
        d = df[df["horizon"] == H].drop(columns=["horizon"]).sort_values("date")
        if len(d) < 60:
            continue
        d["rv_trailing"] = d["y_true"].shift(H)             # trailing rv_21d(t) = y_true(t-21)
        d["iv"] = d["vrp_wedge"] + d["rv_trailing"]          # reconstruct IV
        d["fwd_vrp"] = d["iv"] - d["y_pred"]                 # IV - E[RV]
        d["ticker"] = ticker
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[FWD_VRP] Assembling panel (reconstructing IV from wedge + trailing rv)...")
    p = build_panel()
    p = p[np.isfinite(p["vrp_wedge"]) & np.isfinite(p["iv"]) & np.isfinite(p["fwd_vrp"])]
    print(f"  {len(p):,} (ticker,date) rows, {p['ticker'].nunique()} tickers, "
          f"{p['date'].min().date()} -> {p['date'].max().date()}")

    # ── VALIDATION: IV plausibility + reproduce reflexive wedge IC (~+0.40) ──
    print("\n" + "=" * 78)
    print(" VALIDATION (reconstruction sanity)")
    print("=" * 78)
    iv = p["iv"]
    print(f"  reconstructed IV: mean {iv.mean():.3f}  median {iv.median():.3f}  "
          f"p1 {iv.quantile(.01):.3f}  p99 {iv.quantile(.99):.3f}  %>0 {float((iv>0).mean()):.1%}")
    has_t = p.dropna(subset=["y_true"])
    ic_reflexive = float(has_t["vrp_wedge"].corr(has_t["y_true"], method="spearman"))
    print(f"  IC(reflexive vrp_wedge, forward RV) = {ic_reflexive:+.3f}  "
          f"(should reproduce the established ~+0.40)")
    if iv.quantile(.01) > 0 and 0.10 < iv.median() < 0.80:
        print("  -> IV range plausible; reconstruction alignment OK")
    else:
        print("  -> WARNING: IV range implausible; check shift alignment")

    # ── BIAS: does the model over-predict (compressing the premium)? ─────────
    fe = (has_t["y_true"] - has_t["y_pred"])     # realized - forecast; <0 => over-predict
    bias_vs_trailing = float((p["y_pred"] - p["rv_trailing"]).mean())
    print(f"\n  forecast bias: mean(realized - E[RV]) = {fe.mean():+.4f}  "
          f"({'OVER-predicts' if fe.mean()<0 else 'under-predicts'} forward RV)")
    print(f"  mean(E[RV] - rv_trailing) = {bias_vs_trailing:+.4f}  "
          f"(how much the forecast sits above trailing realized)")

    # ── DIAGNOSTIC 1: SIGN ───────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" DIAGNOSTIC 1: SIGN (a true premium is predominantly positive)")
    print("=" * 78)
    print(f"  reflexive wedge (IV - rv_trailing): mean {p['vrp_wedge'].mean():+.4f}  "
          f"%>0 {float((p['vrp_wedge']>0).mean()):.1%}")
    print(f"  forward VRP    (IV - E[RV])       : mean {p['fwd_vrp'].mean():+.4f}  "
          f"%>0 {float((p['fwd_vrp']>0).mean()):.1%}")

    # ── DIAGNOSTIC 2: STRESS WIDENING ────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" DIAGNOSTIC 2: does the premium WIDEN in stress? (Test C: reflexive did NOT)")
    print("=" * 78)
    spy_vol = load_spy_vol()
    q33, q66 = spy_vol.quantile([0.33, 0.66])
    sv = spy_vol.sort_index()
    pos = sv.index.searchsorted(p["date"].values, side="right") - 1
    pos = np.clip(pos, 0, len(sv) - 1)
    vals = sv.to_numpy()[pos]
    p = p.assign(spy_vol=vals)
    p["regime"] = np.where(p["spy_vol"] <= q33, "calm",
                    np.where(p["spy_vol"] <= q66, "normal", "stress"))
    g = p.groupby("regime").agg(
        n=("fwd_vrp", "size"),
        reflexive_mean=("vrp_wedge", "mean"),
        forward_vrp_mean=("fwd_vrp", "mean"),
        forward_vrp_pos=("fwd_vrp", lambda s: float((s > 0).mean())),
    ).reindex(["calm", "normal", "stress"])
    with pd.option_context("display.float_format", lambda v: f"{v:+.4f}"):
        print(g.to_string())
    wid_fwd = g.loc["stress", "forward_vrp_mean"] - g.loc["calm", "forward_vrp_mean"]
    wid_ref = g.loc["stress", "reflexive_mean"] - g.loc["calm", "reflexive_mean"]
    print(f"\n  stress - calm widening:  forward VRP {wid_fwd:+.4f}   "
          f"reflexive wedge {wid_ref:+.4f}")
    print(f"  -> forward VRP {'WIDENS' if wid_fwd>0 else 'NARROWS'} in stress "
          f"(premium-like = widens)")

    # ── DIAGNOSTIC 3: IC for forward RV, pooled + regime-conditional ─────────
    print("\n" + "=" * 78)
    print(" DIAGNOSTIC 3: predictive IC for forward RV (pooled + by regime)")
    print("=" * 78)
    ht = p.dropna(subset=["y_true"])
    ic_fwd = float(ht["fwd_vrp"].corr(ht["y_true"], method="spearman"))
    ic_ref = float(ht["vrp_wedge"].corr(ht["y_true"], method="spearman"))
    ic_iv = float(ht["iv"].corr(ht["y_true"], method="spearman"))
    print(f"  pooled IC:  reflexive wedge {ic_ref:+.3f} | forward VRP {ic_fwd:+.3f} | "
          f"raw IV {ic_iv:+.3f}")
    print(f"  (corr reflexive vs forward = "
          f"{p['vrp_wedge'].corr(p['fwd_vrp']):+.3f})")
    print("\n  regime-conditional IC (does forward VRP STRENGTHEN in stress?):")
    for reg in ["calm", "normal", "stress"]:
        sub = ht[ht["regime"] == reg]
        if len(sub) < 50:
            continue
        icf = float(sub["fwd_vrp"].corr(sub["y_true"], method="spearman"))
        icr = float(sub["vrp_wedge"].corr(sub["y_true"], method="spearman"))
        print(f"    {reg:7s} (n={len(sub):,}): reflexive {icr:+.3f}  |  forward VRP {icf:+.3f}")

    # per-ticker median IC
    def _mic(col):
        v = ht.groupby("ticker").apply(
            lambda d: d[col].corr(d["y_true"], method="spearman") if len(d) > 30 else np.nan)
        return float(v.median())
    print(f"\n  per-ticker median IC: reflexive {_mic('vrp_wedge'):+.3f}  |  "
          f"forward VRP {_mic('fwd_vrp'):+.3f}")

    # ── VERDICT ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(" VERDICT")
    print("=" * 78)
    pos_share = float((p["fwd_vrp"] > 0).mean())
    premium_like = (pos_share > 0.6) and (wid_fwd > 0)
    print(f"  predominantly positive: {pos_share:.0%}  | widens in stress: {wid_fwd>0}")
    print(f"  => forward VRP {'BEHAVES like a premium' if premium_like else 'does NOT cleanly behave like a premium'}")
    print(f"  => as a forward-RV predictor it is {'comparable to' if abs(ic_fwd-ic_ref)<0.05 else ('weaker than' if ic_fwd<ic_ref else 'stronger than')} the reflexive wedge "
          f"({ic_fwd:+.3f} vs {ic_ref:+.3f})")

    p[["ticker", "date", "iv", "rv_trailing", "y_pred", "y_true", "vrp_wedge",
       "fwd_vrp", "spy_vol", "regime"]].to_csv(OUT_DIR / "vrp_forward_premium.csv", index=False)
    print(f"\n[FWD_VRP] Wrote panel to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
