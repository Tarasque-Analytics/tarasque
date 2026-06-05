"""
vrp_premium_share_test.py -- Of the displayed forward VRP, how much is REAL
                             premium vs forecast bias / noise?

Decomposition (algebraic identity per observation):
  model_premium(t) = IV(t) - y_pred(t)
  expost_premium(t) = IV(t) - y_true(t)              # uses realized fwd vol
  forecast_bias(t) = y_true(t) - y_pred(t)            # model error
  => model_premium = expost_premium + forecast_bias

Two questions:
  1. LEVEL share -- of the AVERAGE model premium, what fraction is the true average
     premium (= mean ex-post premium) vs systematic forecast bias?
  2. VARIATION share -- of the VARIANCE of model premium, what fraction is true
     premium variation vs forecast-error noise?

Plus:
  - HAC significance: is the average ex-post premium robustly > 0?
  - Regime breakdown of the true premium (calm/normal/stress).
  - Predictability R^2: how much of ex-post premium variation is captured by
    state variables (regime + IV level + trailing realized)? = systematic share.
  - Per-stock breadth: is the premium broad-based?
  - Concrete answer to the user's "0.25 me vs 0.30 market = 0.05 displayed" example.
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

from .beta_mz_deep_dive import load_spy_vol, RESULTS_DIR
from .vrp_forward_premium_test import build_panel

OUT_DIR = RESULTS_DIR / "validation"
HAC_LAGS = 42


def hac_mean(s: pd.Series, lags: int = HAC_LAGS) -> dict:
    x = s.dropna().to_numpy(float)
    if len(x) < 30:
        return {"mean": np.nan, "t": np.nan, "p": np.nan, "n": len(x)}
    res = sm.OLS(x, np.ones((len(x), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"mean": float(res.params[0]), "t": float(res.tvalues[0]),
            "p": float(res.pvalues[0]), "n": len(x)}


def add_regime(panel: pd.DataFrame) -> pd.DataFrame:
    sv = load_spy_vol().sort_index()
    q33, q66 = sv.quantile([0.33, 0.66])
    pos = np.clip(sv.index.searchsorted(panel["date"].values, "right") - 1, 0, len(sv) - 1)
    panel = panel.assign(spy_vol=sv.to_numpy()[pos])
    panel["regime"] = np.where(panel["spy_vol"] <= q33, "calm",
                        np.where(panel["spy_vol"] <= q66, "normal", "stress"))
    return panel


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_SHARE] Assembling panel...")
    p = build_panel()
    p = p[np.isfinite(p["iv"]) & np.isfinite(p["y_pred"]) & np.isfinite(p["y_true"])].copy()
    p["model_prem"] = p["iv"] - p["y_pred"]
    p["expost_prem"] = p["iv"] - p["y_true"]
    p["forecast_bias"] = p["y_true"] - p["y_pred"]
    p = add_regime(p)
    print(f"  {len(p):,} rows, {p['ticker'].nunique()} tickers, "
          f"{p['date'].min().date()} -> {p['date'].max().date()}")

    # ── 1. LEVEL DECOMPOSITION ───────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 1. LEVEL DECOMPOSITION (means in vol points)")
    print("=" * 80)
    m_mod = float(p["model_prem"].mean())
    m_exp = float(p["expost_prem"].mean())
    m_fb = float(p["forecast_bias"].mean())
    print(f"  mean model premium     (IV - y_pred)  : {m_mod:+.4f}  ({m_mod*100:+.2f} vol pts)")
    print(f"  mean ex-post premium   (IV - y_true)  : {m_exp:+.4f}  ({m_exp*100:+.2f} vol pts)  <- TRUE")
    print(f"  mean forecast bias     (y_true - y_pred): {m_fb:+.4f}  ({m_fb*100:+.2f} vol pts)")
    print(f"  identity check: expost + bias = {m_exp + m_fb:+.4f}  (should equal model {m_mod:+.4f})")
    share_lvl = m_exp / m_mod if m_mod != 0 else np.nan
    print(f"\n  => of the average displayed premium, {share_lvl:.0%} is TRUE PREMIUM, "
          f"{1-share_lvl:.0%} is model-bias inflation")

    # ── 2. SIGNIFICANCE of the true premium ──────────────────────────────────
    print("\n" + "=" * 80)
    print(" 2. SIGNIFICANCE -- is the true premium robustly > 0?")
    print("=" * 80)
    daily_exp = p.groupby("date")["expost_prem"].mean()
    h = hac_mean(daily_exp)
    print(f"  cross-sectional daily mean ex-post premium: HAC t = {h['t']:+.2f}, "
          f"p = {h['p']:.4g}, mean {h['mean']:+.4f}  (n={h['n']} days)")
    pos_share = float((p["expost_prem"] > 0).mean())
    pos_dates = float((daily_exp > 0).mean())
    print(f"  observation-level % positive: {pos_share:.1%}  | "
          f"day-level % positive: {pos_dates:.1%}")
    if h["p"] < 0.001 and m_exp > 0:
        print("  => TRUE PREMIUM IS REAL (positive, massively significant)")

    # ── 3. VARIANCE DECOMPOSITION ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 3. VARIATION SHARE -- of model-premium VARIANCE, what's premium vs noise?")
    print("=" * 80)
    v_mod = float(p["model_prem"].var())
    v_exp = float(p["expost_prem"].var())
    v_fb = float(p["forecast_bias"].var())
    cov_ef = float(p["expost_prem"].cov(p["forecast_bias"]))
    # identity: var(model) = var(expost) + var(bias) + 2*cov(expost, bias)
    print(f"  var(model_prem)         = {v_mod:.5f}")
    print(f"  var(expost_prem)        = {v_exp:.5f}   ({v_exp/v_mod:.0%} of model var)")
    print(f"  var(forecast_bias)      = {v_fb:.5f}   ({v_fb/v_mod:.0%} of model var)")
    print(f"  2*cov(expost,bias)      = {2*cov_ef:.5f}   (overlap term)")
    print(f"  identity check: sum     = {v_exp+v_fb+2*cov_ef:.5f}  (== var(model))")
    corr_ef = float(p["expost_prem"].corr(p["forecast_bias"]))
    print(f"  corr(expost, bias)      = {corr_ef:+.3f}")
    print(f"\n  => what we DISPLAY = mix of {v_exp/v_mod:.0%} true-premium variance + "
          f"{v_fb/v_mod:.0%} forecast-error variance + overlap")

    # ── 4. SYSTEMATIC SHARE: predictability of ex-post premium ───────────────
    print("\n" + "=" * 80)
    print(" 4. SYSTEMATIC SHARE -- how much ex-post-premium variation is PREDICTABLE")
    print("    (R^2 of premium vs state variables)")
    print("=" * 80)
    X = pd.get_dummies(p[["regime"]], drop_first=True).astype(float)
    X["iv_level"] = p["iv"].astype(float)
    X["rv_trailing"] = p["rv_trailing"].astype(float)
    X = sm.add_constant(X).dropna()
    y = p.loc[X.index, "expost_prem"].astype(float)
    res = sm.OLS(y.to_numpy(), X.to_numpy()).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    print(f"  predictors: regime_dummies + iv_level + rv_trailing  (n={len(y):,})")
    print(f"  R^2  = {res.rsquared:.3f}   adj R^2 = {res.rsquared_adj:.3f}")
    print(f"  => {res.rsquared:.0%} of ex-post premium variation is SYSTEMATIC "
          f"(captured by these state vars)")
    print(f"  => {1-res.rsquared:.0%} is irreducible noise (random vol realization + unmodeled)")

    # ── 5. REGIME BREAKDOWN ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 5. PREMIUM by REGIME (mean ex-post premium, vol points)")
    print("=" * 80)
    g = p.groupby("regime")["expost_prem"].agg(["count", "mean"]).reindex(["calm","normal","stress"])
    g.columns = ["n", "mean_prem"]
    for r in ["calm", "normal", "stress"]:
        dr = p[p["regime"] == r].groupby("date")["expost_prem"].mean()
        h = hac_mean(dr, lags=21)
        print(f"  {r:7s}: mean {g.loc[r,'mean_prem']:+.4f}  ({g.loc[r,'mean_prem']*100:+.2f} vol pts)  "
              f"HAC t {h['t']:+.2f}  n={g.loc[r,'n']:,}")

    # ── 6. PER-STOCK BREADTH ─────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 6. PER-STOCK BREADTH (is the premium broad-based?)")
    print("=" * 80)
    pt = p.groupby("ticker")["expost_prem"].mean()
    print(f"  per-stock mean ex-post premium: median {pt.median():+.4f}  "
          f"p25 {pt.quantile(.25):+.4f}  p75 {pt.quantile(.75):+.4f}")
    print(f"  breadth: {float((pt > 0).mean()):.0%} of {len(pt)} tickers have positive avg premium  "
          f"| {float((pt > 0.03).mean()):.0%} above 3 vol pts")

    # ── 7. CONCRETE ANSWER to user's example ─────────────────────────────────
    print("\n" + "=" * 80)
    print(" 7. ANSWER to 'I say 0.25, market says 0.30, displayed = 0.05'")
    print("=" * 80)
    example_displayed = 0.05
    bias_adj = example_displayed * share_lvl
    print(f"  displayed = 0.05 vol pts (5%)")
    print(f"  using level share ({share_lvl:.0%}): expected true premium ~ {bias_adj:+.4f}  "
          f"({bias_adj*100:+.2f} vol pts)")
    print(f"  expected model bias inflation         ~ {example_displayed*(1-share_lvl):+.4f}  "
          f"({example_displayed*(1-share_lvl)*100:+.2f} vol pts)")
    print(f"  ON ANY SINGLE OBSERVATION the true component has wide uncertainty "
          f"(forecast-error std ~ {p['forecast_bias'].std():.3f} vol pts);")
    print(f"  these splits hold IN EXPECTATION across many observations.")
    print(f"  In a STRESS regime, expected true premium component scales up to "
          f"~{g.loc['stress','mean_prem']/m_exp * bias_adj:+.4f} on the same 0.05 displayed.")

    p[["ticker","date","iv","y_pred","y_true","model_prem","expost_prem",
       "forecast_bias","regime"]].to_csv(OUT_DIR / "vrp_premium_share.csv", index=False)
    print("\n[VRP_SHARE] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
