"""
vrp_rank_test.py -- What does the CROSS-SECTIONAL RANK of fwd_premium_ewma_21d
                    predict, and does the rank carry info beyond the level?

We previously ran pooled-decile tests (vrp_forward_premium_buckets) that mixed
cross-section and time. This test isolates the WITHIN-DATE cross-section:
"today which name has the richest VRP among the universe, and what does that
mean for that name's forward vol / forward return."

  1. Cross-sectional rank tercile per date -> forward 21-BD realized vol
     and forward 21-BD stock return. HAC long-short on the day-level spread.
  2. Rank persistence: autocorrelation of per-stock rank at lags {5,21,63} BD
     (how sticky is "this name is high-VRP-rank"?).
  3. Rank-CHANGE signal: when a stock JUMPS up in rank by N percentile points,
     what does that predict for its own forward vol / return?
  4. Time-stability: 2015-2020 vs 2021-2026 halves.
  5. Raw vs EWMA: does smoothing the rank give a cleaner cross-sectional signal?
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

REPO_ROOT = Path(__file__).resolve().parents[3]
WEBAPP_DIR = REPO_ROOT / "model" / "pipeline" / "results" / "webapp_export" / "tickers"
OUT_DIR    = REPO_ROOT / "model" / "pipeline" / "results" / "validation"

HOLD = 21
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


def load_panel() -> pd.DataFrame:
    rows = []
    for f in sorted(WEBAPP_DIR.glob("predictions_*.csv")):
        tk = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "close", "rv",
                                      "fwd_premium_21d", "fwd_premium_ewma_21d"])
        except Exception:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["ticker"] = tk
        df["fwd_ret_21"] = np.log(df["close"].shift(-HOLD) / df["close"])
        rows.append(df)
    p = pd.concat(rows, ignore_index=True)
    p = p[(p["date"] >= START_DATE)].copy()
    return p


def cross_section_pct_rank(p: pd.DataFrame, col: str) -> pd.Series:
    """Per-date percentile rank across the universe in [0, 1]."""
    return p.groupby("date")[col].rank(method="average", pct=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_RANK] Loading per-ticker panel from webapp_export...")
    p = load_panel()
    print(f"  {len(p):,} (ticker,date) rows | {p['ticker'].nunique()} tickers | "
          f"{p['date'].min().date()} -> {p['date'].max().date()}")

    p["rank_ewma"] = cross_section_pct_rank(p, "fwd_premium_ewma_21d")
    p["rank_raw"]  = cross_section_pct_rank(p, "fwd_premium_21d")

    # ── 1. TERCILE → FORWARD VOL + RETURN (within-date cross-section) ────────
    print("\n" + "=" * 80)
    print(" 1. CROSS-SECTIONAL TERCILE of fwd_premium_ewma_21d -> forward outcomes")
    print("=" * 80)
    p["tercile"] = pd.cut(p["rank_ewma"], bins=[-0.01, 1/3, 2/3, 1.01],
                          labels=["LOW", "MID", "HIGH"])
    g = p.dropna(subset=["rv", "fwd_ret_21"]).groupby("tercile", observed=True).agg(
        n=("rank_ewma", "size"),
        fwd_vol_mean=("rv", "mean"),
        fwd_vol_med=("rv", "median"),
        fwd_ret_mean=("fwd_ret_21", "mean"),
        fwd_ret_hit=("fwd_ret_21", lambda s: float((s > 0).mean())),
    )
    with pd.option_context("display.float_format", lambda v: f"{v:+.4f}"):
        print(g.to_string())

    # within-date long-short spread series, HAC
    print("\n  Day-level cross-sectional spreads (HIGH minus LOW within each date):")
    daily = p.dropna(subset=["tercile", "rv", "fwd_ret_21"]).groupby("date").apply(
        lambda d: pd.Series({
            "vol_spread": d.loc[d.tercile == "HIGH", "rv"].mean() -
                          d.loc[d.tercile == "LOW", "rv"].mean(),
            "ret_spread": d.loc[d.tercile == "HIGH", "fwd_ret_21"].mean() -
                          d.loc[d.tercile == "LOW", "fwd_ret_21"].mean(),
        }), include_groups=False)
    rv_h = hac_mean(daily["vol_spread"])
    rt_h = hac_mean(daily["ret_spread"])
    print(f"  VOL  HIGH-LOW spread: {rv_h['mean']:+.4f} ({rv_h['mean']*100:+.2f} pp)   "
          f"HAC t={rv_h['t']:+.2f} p={rv_h['p']:.4g}  (n={rv_h['n']} days)")
    print(f"  RET  HIGH-LOW spread: {rt_h['mean']:+.4f} ({rt_h['mean']*100:+.2f}% per 21BD)   "
          f"HAC t={rt_h['t']:+.2f} p={rt_h['p']:.4g}")
    if rt_h["p"] < 0.05:
        direction = "HIGH-VRP names OUTPERFORM" if rt_h['mean'] > 0 else "HIGH-VRP names UNDERPERFORM"
        print(f"  -> SIGNIFICANT cross-sectional return effect: {direction}")
    else:
        sign = "high>low" if rt_h['mean'] > 0 else "low>high"
        print(f"  -> NOT significant on returns (point estimate: {sign})")

    # annualize the LS
    ann = rt_h["mean"] * (252 / HOLD)
    sd = daily["ret_spread"].std()
    ir = (rt_h["mean"] / sd * np.sqrt(252 / HOLD)) if sd and sd > 0 else np.nan
    print(f"  annualized LS: {ann*100:+.1f}%/yr  approx IR {ir:+.2f}  "
          f"days LS>0 {float((daily['ret_spread']>0).mean()):.0%}")

    # ── 2. RANK PERSISTENCE (autocorrelation of per-stock rank) ──────────────
    print("\n" + "=" * 80)
    print(" 2. RANK PERSISTENCE -- is being high-VRP-rank a sticky state?")
    print("=" * 80)
    for lag in (5, 21, 63):
        ac = p.groupby("ticker")["rank_ewma"].apply(
            lambda s: s.autocorr(lag=lag) if s.notna().sum() > lag + 30 else np.nan
        ).dropna()
        print(f"  lag={lag:3d} BD autocorr of rank_ewma: median {ac.median():+.3f}  "
              f"mean {ac.mean():+.3f}  p25 {ac.quantile(.25):+.3f}  "
              f"p75 {ac.quantile(.75):+.3f}  (n={len(ac)} tickers)")
    # raw vs EWMA comparison
    for lag in (5, 21):
        ac_raw = p.groupby("ticker")["rank_raw"].apply(
            lambda s: s.autocorr(lag=lag) if s.notna().sum() > lag + 30 else np.nan
        ).dropna()
        ac_ewma = p.groupby("ticker")["rank_ewma"].apply(
            lambda s: s.autocorr(lag=lag) if s.notna().sum() > lag + 30 else np.nan
        ).dropna()
        print(f"  raw vs EWMA rank stickiness at lag {lag} BD: "
              f"raw {ac_raw.median():+.3f}  EWMA {ac_ewma.median():+.3f}")

    # ── 3. RANK-CHANGE signal (Δrank → forward vol/return) ───────────────────
    print("\n" + "=" * 80)
    print(" 3. RANK-CHANGE signal -- does Δrank predict forward outcomes?")
    print("=" * 80)
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    p["drank_21"] = p.groupby("ticker")["rank_ewma"].diff(21)
    chk = p.dropna(subset=["drank_21", "rv", "fwd_ret_21"]).copy()
    # cut Δrank into terciles
    chk["drank_tercile"] = pd.qcut(chk["drank_21"], 3,
                                    labels=["DECLINING", "FLAT", "RISING"], duplicates="drop")
    g3 = chk.groupby("drank_tercile", observed=True).agg(
        n=("drank_21", "size"),
        delta_rank_mean=("drank_21", "mean"),
        fwd_vol_mean=("rv", "mean"),
        fwd_ret_mean=("fwd_ret_21", "mean"),
        fwd_ret_hit=("fwd_ret_21", lambda s: float((s > 0).mean())),
    )
    with pd.option_context("display.float_format", lambda v: f"{v:+.4f}"):
        print(g3.to_string())
    print("  (Δrank over 21 BD: did the stock's VRP-rank rise or fall within its universe?)")

    # ── 4. TIME STABILITY ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 4. TIME STABILITY 2015-2020 vs 2021-2026")
    print("=" * 80)
    for label, mask in [("2015-2020", p["date"] <= SPLIT_DATE),
                        ("2021-2026", p["date"] >  SPLIT_DATE)]:
        sub_day = daily[daily.index <= SPLIT_DATE] if label == "2015-2020" \
                  else daily[daily.index > SPLIT_DATE]
        rvh = hac_mean(sub_day["vol_spread"])
        rth = hac_mean(sub_day["ret_spread"])
        print(f"  {label}: VOL spread {rvh['mean']*100:+.2f} pp (t={rvh['t']:+.2f}, p={rvh['p']:.3g})  "
              f"| RET spread {rth['mean']*100:+.3f}%/21BD (t={rth['t']:+.2f}, p={rth['p']:.3g})")

    # ── 5. RAW vs EWMA RANK comparison on the same outcome test ──────────────
    print("\n" + "=" * 80)
    print(" 5. RAW vs EWMA rank -- does smoothing give a cleaner cross-sectional signal?")
    print("=" * 80)
    p["tercile_raw"] = pd.cut(p["rank_raw"], bins=[-0.01, 1/3, 2/3, 1.01],
                               labels=["LOW", "MID", "HIGH"])
    daily_raw = p.dropna(subset=["tercile_raw", "rv", "fwd_ret_21"]).groupby("date").apply(
        lambda d: pd.Series({
            "vol_spread": d.loc[d.tercile_raw == "HIGH", "rv"].mean() -
                          d.loc[d.tercile_raw == "LOW", "rv"].mean(),
            "ret_spread": d.loc[d.tercile_raw == "HIGH", "fwd_ret_21"].mean() -
                          d.loc[d.tercile_raw == "LOW", "fwd_ret_21"].mean(),
        }), include_groups=False)
    rv_raw = hac_mean(daily_raw["vol_spread"])
    rt_raw = hac_mean(daily_raw["ret_spread"])
    print(f"  RAW:   VOL spread {rv_raw['mean']*100:+.2f} pp (t={rv_raw['t']:+.2f})  "
          f"RET spread {rt_raw['mean']*100:+.3f}%/21BD (t={rt_raw['t']:+.2f}, p={rt_raw['p']:.3g})")
    print(f"  EWMA:  VOL spread {rv_h['mean']*100:+.2f} pp (t={rv_h['t']:+.2f})  "
          f"RET spread {rt_h['mean']*100:+.3f}%/21BD (t={rt_h['t']:+.2f}, p={rt_h['p']:.3g})")

    g.to_csv(OUT_DIR / "vrp_rank_tercile_outcomes.csv")
    daily.to_csv(OUT_DIR / "vrp_rank_daily_spread.csv")
    print("\n[VRP_RANK] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
