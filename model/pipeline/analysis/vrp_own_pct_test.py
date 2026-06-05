"""
vrp_own_pct_test.py -- Own-stock-history percentile of fwd_premium_ewma_21d.

Different signal from vrp_rank_test (which was cross-sectional). Here each
(ticker, date) gets its percentile in its OWN trailing 252-BD history. Asks:
when a stock's VRP is unusually high FOR THAT STOCK (regardless of where other
stocks sit), what predicts its forward return / vol?

Hypothesis from prior reflexive-wedge work: central quintile shows ~normal
forward-return distribution, tail quintiles (Q1, Q5) show fatter tails.

  1. Per ticker, trailing 252-BD percentile of fwd_premium_ewma_21d (causal)
  2. Quintile cut Q1-Q5 per (ticker, date)
  3. Per quintile: distribution shape of forward 21-BD return + vol
     (mean, median, std, skew, excess kurtosis, P5/P95)
  4. Long-short Q5-Q1 within-date spread series, HAC test
  5. Time stability 2015-20 vs 2021-26
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

REPO_ROOT = Path(__file__).resolve().parents[3]
WEBAPP_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "webapp_export" / "tickers"
OUT_DIR    = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

HOLD = 21
ROLLING = 252
MIN_PERIODS = 63
SPLIT_DATE = pd.Timestamp("2020-12-31")
START_DATE = pd.Timestamp("2015-01-01")
HAC_LAGS = 42


def hac_mean(s: pd.Series, lags: int = HAC_LAGS) -> dict:
    x = s.dropna().to_numpy(float)
    if len(x) < 30:
        return {"mean": np.nan, "t": np.nan, "p": np.nan, "n": int(len(x))}
    res = sm.OLS(x, np.ones((len(x), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"mean": float(res.params[0]), "t": float(res.tvalues[0]),
            "p": float(res.pvalues[0]), "n": int(len(x))}


def trailing_pct_rank(s: pd.Series, window: int = ROLLING,
                       min_periods: int = MIN_PERIODS) -> pd.Series:
    """Fraction of trailing-window values <= current value. Causal."""
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: float((x[:-1] <= x[-1]).sum() + 0.5) / len(x), raw=True
    )


def load_panel() -> pd.DataFrame:
    rows = []
    for f in sorted(WEBAPP_DIR.glob("predictions_*.csv")):
        tk = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "close", "rv", "fwd_premium_ewma_21d"])
        except Exception:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["ticker"] = tk
        df["fwd_ret_21"] = np.log(df["close"].shift(-HOLD) / df["close"])
        rows.append(df)
    p = pd.concat(rows, ignore_index=True)
    return p[p["date"] >= START_DATE].copy()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_OWN] Loading panel + computing trailing-252BD own-percentile...")
    p = load_panel()
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    p["own_pct"] = p.groupby("ticker")["fwd_premium_ewma_21d"].transform(trailing_pct_rank)
    print(f"  {len(p):,} (ticker,date) rows | non-null own_pct: "
          f"{p['own_pct'].notna().sum():,}")

    # Quintile bucket on own_pct
    p["quintile"] = pd.cut(p["own_pct"], bins=[-0.01, .2, .4, .6, .8, 1.01],
                            labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    work = p.dropna(subset=["quintile", "rv", "fwd_ret_21"]).copy()

    # ── 1. DISTRIBUTION SHAPE PER QUINTILE ───────────────────────────────────
    print("\n" + "=" * 86)
    print(" 1. FORWARD 21-BD STOCK RETURN distribution per OWN-percentile quintile")
    print("=" * 86)
    print(f"  {'Q':<4}{'n':>8}{'mean':>10}{'med':>10}{'std':>10}{'skew':>9}"
          f"{'kurt':>9}{'P5':>10}{'P95':>10}{'hit':>8}")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        r = work.loc[work.quintile == q, "fwd_ret_21"].to_numpy(float)
        r = r[np.isfinite(r)]
        if len(r) < 30:
            continue
        print(f"  {q:<4}{len(r):>8,d}{r.mean():>+10.4f}{np.median(r):>+10.4f}"
              f"{r.std():>10.4f}{sps.skew(r):>+9.2f}{sps.kurtosis(r):>+9.2f}"
              f"{np.percentile(r,5):>+10.4f}{np.percentile(r,95):>+10.4f}"
              f"{float((r>0).mean()):>8.0%}")
    print("  (excess kurtosis: 0 = normal; positive = fat tails / leptokurtic)")

    # ── 2. FORWARD VOL per quintile ──────────────────────────────────────────
    print("\n" + "=" * 86)
    print(" 2. FORWARD 21-BD REALIZED VOL distribution per quintile")
    print("=" * 86)
    print(f"  {'Q':<4}{'n':>8}{'mean':>10}{'med':>10}{'std':>10}{'skew':>9}{'kurt':>9}"
          f"{'P5':>10}{'P95':>10}")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        v = work.loc[work.quintile == q, "rv"].to_numpy(float)
        v = v[np.isfinite(v)]
        if len(v) < 30:
            continue
        print(f"  {q:<4}{len(v):>8,d}{v.mean():>+10.4f}{np.median(v):>+10.4f}"
              f"{v.std():>10.4f}{sps.skew(v):>+9.2f}{sps.kurtosis(v):>+9.2f}"
              f"{np.percentile(v,5):>+10.4f}{np.percentile(v,95):>+10.4f}")

    # ── 3. WITHIN-DATE Q5-Q1 LONG-SHORT SPREAD (HAC) ─────────────────────────
    print("\n" + "=" * 86)
    print(" 3. WITHIN-DATE Q5-Q1 LONG-SHORT (each stock in its own historical regime)")
    print("=" * 86)
    daily = work.groupby("date").apply(
        lambda d: pd.Series({
            "vol_spread": d.loc[d.quintile == "Q5", "rv"].mean() -
                          d.loc[d.quintile == "Q1", "rv"].mean(),
            "ret_spread": d.loc[d.quintile == "Q5", "fwd_ret_21"].mean() -
                          d.loc[d.quintile == "Q1", "fwd_ret_21"].mean(),
        }), include_groups=False).dropna()
    rv_h = hac_mean(daily["vol_spread"])
    rt_h = hac_mean(daily["ret_spread"])
    print(f"  VOL  Q5-Q1: {rv_h['mean']*100:+.2f} pp   HAC t={rv_h['t']:+.2f}  "
          f"p={rv_h['p']:.4g}  (n={rv_h['n']} days)")
    print(f"  RET  Q5-Q1: {rt_h['mean']*100:+.3f}% per 21BD   HAC t={rt_h['t']:+.2f}  "
          f"p={rt_h['p']:.4g}")
    if np.isfinite(rt_h["mean"]) and rt_h["mean"] != 0:
        ann = rt_h["mean"] * (252 / HOLD)
        sd = daily["ret_spread"].std()
        ir = (rt_h["mean"] / sd * np.sqrt(252 / HOLD)) if sd > 0 else np.nan
        verdict = ("SIGNIFICANT" if rt_h["p"] < 0.05 else
                   "marginal" if rt_h["p"] < 0.15 else "not significant")
        direction = "OWN-high outperforms" if rt_h["mean"] > 0 else "OWN-high UNDERperforms"
        print(f"  annualized LS: {ann*100:+.1f}%/yr  IR {ir:+.2f}  days LS>0 "
              f"{float((daily['ret_spread']>0).mean()):.0%}  -> {verdict} ({direction})")

    # ── 4. TIME STABILITY ────────────────────────────────────────────────────
    print("\n" + "=" * 86)
    print(" 4. TIME STABILITY 2015-2020 vs 2021-2026")
    print("=" * 86)
    for label, mask in [("2015-2020", daily.index <= SPLIT_DATE),
                        ("2021-2026", daily.index >  SPLIT_DATE)]:
        sub = daily[mask]
        rv_s = hac_mean(sub["vol_spread"]); rt_s = hac_mean(sub["ret_spread"])
        print(f"  {label}: VOL Q5-Q1 {rv_s['mean']*100:+.2f} pp (t={rv_s['t']:+.2f}) | "
              f"RET Q5-Q1 {rt_s['mean']*100:+.3f}% (t={rt_s['t']:+.2f}, p={rt_s['p']:.3g})")

    # ── 5. TAIL-SHAPE COMPARISON Q3 vs (Q1,Q5) ───────────────────────────────
    print("\n" + "=" * 86)
    print(" 5. TAIL-SHAPE check -- central quintile normal vs extremes fat-tailed?")
    print("=" * 86)
    q1 = work.loc[work.quintile == "Q1", "fwd_ret_21"].dropna().to_numpy(float)
    q3 = work.loc[work.quintile == "Q3", "fwd_ret_21"].dropna().to_numpy(float)
    q5 = work.loc[work.quintile == "Q5", "fwd_ret_21"].dropna().to_numpy(float)
    for nm, arr in [("Q1 (own-LOW )", q1), ("Q3 (own-MID )", q3), ("Q5 (own-HIGH)", q5)]:
        ek = sps.kurtosis(arr)
        sk = sps.skew(arr)
        jb_stat, jb_p = sps.jarque_bera(arr) if len(arr) > 7 else (np.nan, np.nan)
        tail_share = float(((arr < np.percentile(arr, 5)) |
                             (arr > np.percentile(arr, 95))).mean())  # by def = 10%
        # Compare to normal: ratio of (P99-P1) range to a hypothetical Gaussian P99-P1 of same std
        rng_99 = np.percentile(arr, 99) - np.percentile(arr, 1)
        gauss_99 = 2 * 2.326 * arr.std()
        fat_ratio = rng_99 / gauss_99 if gauss_99 > 0 else np.nan
        print(f"  {nm}: n={len(arr):>6,d}  skew {sk:+.2f}  excess-kurt {ek:+.2f}  "
              f"JB p={jb_p:.2e}  P99-P1 vs Gaussian: {fat_ratio:.2f}x  "
              f"(>1.0 = fatter than normal)")
    print("  (Jarque-Bera tests normality. P99-P1 / Gaussian-equivalent: 1.0=Gaussian, "
          ">1.0=fatter, <1.0=thinner)")

    daily.to_csv(OUT_DIR / "vrp_own_pct_daily_spread.csv")
    print("\n[VRP_OWN] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
