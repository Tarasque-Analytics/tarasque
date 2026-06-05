"""
vrp_forward_premium_buckets.py -- What do VRP percentiles mean for forward vol,
                                  are the buckets statistically real, and are there
                                  RETURNS implications?

Signal: forward VRP = IV - E[RV] (E[RV]=model y_pred), EWMA span 21 (the validated
premium). Per (ticker, date).

PART A  Decile buckets -> mean forward realized vol + mean forward 21-BD stock
        return. The "what does the Nth percentile mean" table (pooled deciles).
PART B  Significance, done HONESTLY despite overlapping 21-BD windows + cross-stock
        correlation: collapse to a per-DATE cross-sectional long-short spread
        (top decile minus bottom decile that day), then HAC (Newey-West) test the
        mean of that daily series. Plus Kruskal-Wallis omnibus across deciles.
PART C  Returns implications: same within-date top-minus-bottom decile applied to
        forward 21-BD returns -> is high-VRP a long or a short? significant?

Forward stock returns come from OHLCV closes (not in predictions).

Output: results/validation/vrp_fwd_premium_buckets_*.csv
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as sps

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ..config import load_config
from ..data_loader import ParquetStore
from .beta_mz_deep_dive import RESULTS_DIR
from .vrp_forward_premium_test import build_panel, H

OUT_DIR = RESULTS_DIR / "validation"
EWMA_SPAN = 21
HAC_LAGS = 42       # >2x the 21-BD overlap horizon


def hac_mean(s: pd.Series, lags: int = HAC_LAGS) -> tuple:
    x = s.dropna().to_numpy(float)
    if len(x) < 30:
        return (np.nan, np.nan, np.nan, len(x))
    res = sm.OLS(x, np.ones((len(x), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return (float(res.params[0]), float(res.tvalues[0]), float(res.pvalues[0]), len(x))


def add_forward_returns(panel: pd.DataFrame) -> pd.DataFrame:
    dc, _, _ = load_config()
    oh = ParquetStore(dc.base_dir).load("ohlcv")
    oh["date"] = pd.to_datetime(oh["date"], format="mixed")
    px = oh.drop_duplicates(["date", "ticker"]).pivot(index="date", columns="ticker",
                                                       values="prc").sort_index().ffill()
    fwd = np.log(px.shift(-H) / px)            # forward 21-BD log return
    fwd = fwd.stack().rename("fwd_ret").reset_index()
    fwd.columns = ["date", "ticker", "fwd_ret"]
    return panel.merge(fwd, on=["date", "ticker"], how="left")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_BKT] Building panel + EWMA forward VRP + forward returns...")
    p = build_panel()
    p = p[np.isfinite(p["fwd_vrp"])].sort_values(["ticker", "date"]).reset_index(drop=True)
    p["fv"] = p.groupby("ticker")["fwd_vrp"].transform(
        lambda s: s.ewm(span=EWMA_SPAN, adjust=False).mean())
    p = add_forward_returns(p)
    p = p.dropna(subset=["fv", "y_true"])      # need signal + forward vol
    print(f"  {len(p):,} rows, {p['ticker'].nunique()} tickers, "
          f"{p['date'].min().date()} -> {p['date'].max().date()}")

    # ── PART A: DECILE BUCKETS (pooled) -> forward vol + forward return ──────
    print("\n" + "=" * 82)
    print(" PART A: forward VRP decile -> forward realized vol + forward 21-BD return")
    print("=" * 82)
    p["decile"] = pd.qcut(p["fv"], 10, labels=False, duplicates="drop")
    g = p.groupby("decile").agg(
        n=("fv", "size"),
        vrp_mean=("fv", "mean"),
        fwd_vol_mean=("y_true", "mean"),
        fwd_vol_med=("y_true", "median"),
        fwd_ret_mean=("fwd_ret", "mean"),
        fwd_ret_hit=("fwd_ret", lambda s: float((s > 0).mean())),
    ).reset_index()
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.4f}"):
        print(g.to_string(index=False))
    sp_vol = sps.spearmanr(p["decile"], p["y_true"]).correlation
    sp_ret = sps.spearmanr(p["decile"], p["fwd_ret"], nan_policy="omit").correlation
    print(f"\n  monotonicity (Spearman decile vs): forward vol {sp_vol:+.3f} | "
          f"forward return {sp_ret:+.3f}")
    print(f"  D10 vs D1: forward vol {g.loc[9,'fwd_vol_mean']:.3f} vs {g.loc[0,'fwd_vol_mean']:.3f} "
          f"(spread {g.loc[9,'fwd_vol_mean']-g.loc[0,'fwd_vol_mean']:+.3f} vol pts) | "
          f"forward ret {g.loc[9,'fwd_ret_mean']:+.4f} vs {g.loc[0,'fwd_ret_mean']:+.4f}")
    g.to_csv(OUT_DIR / "vrp_fwd_premium_buckets_deciles.csv", index=False)

    # ── PART B: SIGNIFICANCE (honest, overlap-aware) ─────────────────────────
    print("\n" + "=" * 82)
    print(" PART B: are the buckets statistically real? (overlap-aware)")
    print("=" * 82)
    # within-date cross-sectional deciles -> daily top-minus-bottom spread
    p["xs_dec"] = p.groupby("date")["fv"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 10, labels=False, duplicates="drop")
        if s.notna().sum() >= 10 else np.nan)
    daily = p.dropna(subset=["xs_dec"]).groupby("date").apply(
        lambda d: pd.Series({
            "vol_spread": d.loc[d.xs_dec == 9, "y_true"].mean() - d.loc[d.xs_dec == 0, "y_true"].mean(),
            "ret_spread": d.loc[d.xs_dec == 9, "fwd_ret"].mean() - d.loc[d.xs_dec == 0, "fwd_ret"].mean(),
        }), include_groups=False)
    m, t, pv, n = hac_mean(daily["vol_spread"])
    print(f"  VOL: within-date D10-D1 forward-vol spread = {m:+.4f} vol pts  "
          f"HAC t={t:+.2f}  p={pv:.4g}  (n={n} days)")
    # Kruskal-Wallis omnibus across pooled deciles (caveat: ignores overlap; supportive only)
    groups = [grp["y_true"].dropna().to_numpy() for _, grp in p.groupby("decile")]
    kw = sps.kruskal(*groups)
    print(f"  VOL: Kruskal-Wallis across 10 deciles H={kw.statistic:,.0f}  p={kw.pvalue:.2e} "
          f"(omnibus, overlap-inflated -> supportive only)")
    print(f"  -> buckets are {'STATISTICALLY REAL for vol' if pv < 0.01 else 'not clearly significant'} "
          f"(HAC test is the honest one)")

    # ── PART C: RETURNS IMPLICATIONS ─────────────────────────────────────────
    print("\n" + "=" * 82)
    print(" PART C: returns implications (within-date D10-D1 forward 21-BD return)")
    print("=" * 82)
    mr, tr, pvr, nr = hac_mean(daily["ret_spread"])
    ann = mr * (252 / H)
    hit = float((daily["ret_spread"] > 0).mean())
    sd = daily["ret_spread"].std()
    ir = (mr / sd * np.sqrt(252 / H)) if sd and sd > 0 else np.nan
    direction = "HIGH-VRP OUTPERFORMS (long high / short low)" if mr > 0 else \
                "HIGH-VRP UNDERPERFORMS (short high / long low)"
    print(f"  D10-D1 forward 21-BD return = {mr:+.4f} ({mr*100:+.2f}%) per 21 BD  "
          f"HAC t={tr:+.2f}  p={pvr:.4g}  (n={nr} days)")
    print(f"  annualized long-short ~ {ann*100:+.1f}%/yr  | approx IR {ir:+.2f}  | "
          f"days LS>0 {hit:.0%}")
    if pvr < 0.05:
        print(f"  -> SIGNIFICANT return implication: {direction}")
    else:
        print(f"  -> no significant cross-sectional return implication "
              f"(point estimate: {direction.split('(')[0].strip()})")
    # also pooled decile return monotonicity already in Part A (sp_ret)
    daily.to_csv(OUT_DIR / "vrp_fwd_premium_buckets_daily_spread.csv")

    print("\n[VRP_BKT] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
