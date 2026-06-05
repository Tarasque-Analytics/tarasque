"""
vrp_forward_premium_battery.py -- Full IC + robustness battery on the FORWARD VRP
                                  (IV - E[RV]) and its EWMA, as a vol-forecast-derived
                                  RISK/ANALYTICS signal.

Established (vrp_forward_premium_test): IV - E[RV] behaves like a real premium
(95% positive, widens in stress, ex-post confirmed) and predicts forward RV better
than the reflexive wedge (pooled IC +0.52 vs +0.30).

This battery, mirroring what we did for beta_mz:
  PART 1  EWMA span sweep -- does smoothing help (reflexive went +0.33 raw -> +0.40
          EWMA)? Want a plateau, not a spike.
  PART 2  IC battery: pooled / per-ticker / regime-conditional / temporal-split /
          quintile-lift, comparing reflexive wedge vs raw fwd-VRP vs EWMA fwd-VRP.
  PART 3  Premium integrity: does the EWMA still stay positive + widen in stress?
  PART 4  Slope conditional: does the premium's DIRECTION (widening vs narrowing)
          add over its level?
  PART 5  Cross-sectional robustness: per-ticker IC distribution + random-ticker
          subset bootstrap (is the IC broad-based or a few names?).

Reconstruction (no OptionMetrics needed): IV = vrp_wedge + y_true.shift(21);
fwd_vrp = IV - y_pred.  All causal at time t; y_true(t) is the future target.

Output: results/validation/vrp_fwd_premium_battery_*.csv
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
from .vrp_forward_premium_test import build_panel, H

OUT_DIR = RESULTS_DIR / "validation"
SPLIT_DATE = pd.Timestamp("2020-12-31")
SPANS = [1, 5, 10, 21, 42, 63]      # 1 = raw (no smoothing)


def spearman(a: pd.Series, b: pd.Series) -> float:
    d = pd.concat([a, b], axis=1).dropna()
    return float(d.iloc[:, 0].corr(d.iloc[:, 1], method="spearman")) if len(d) > 30 else np.nan


def per_ticker_ic(df: pd.DataFrame, col: str) -> pd.Series:
    return df.groupby("ticker")[[col, "y_true"]].apply(
        lambda d: d[col].corr(d["y_true"], method="spearman") if len(d) > 30 else np.nan).dropna()


def add_regime(panel: pd.DataFrame) -> pd.DataFrame:
    sv = load_spy_vol().sort_index()
    q33, q66 = sv.quantile([0.33, 0.66])
    pos = np.clip(sv.index.searchsorted(panel["date"].values, "right") - 1, 0, len(sv) - 1)
    v = sv.to_numpy()[pos]
    panel = panel.assign(spy_vol=v)
    panel["regime"] = np.where(v <= q33, "calm", np.where(v <= q66, "normal", "stress"))
    return panel


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_BAT] Assembling panel...")
    p = build_panel()
    p = p[np.isfinite(p["vrp_wedge"]) & np.isfinite(p["iv"]) & np.isfinite(p["fwd_vrp"])]
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    p = add_regime(p)
    ht_all = p.dropna(subset=["y_true"])
    print(f"  {len(p):,} rows, {p['ticker'].nunique()} tickers; {len(ht_all):,} with forward target")

    # ── PART 1: EWMA SPAN SWEEP ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" PART 1: EWMA span sweep on forward VRP (pooled + per-ticker IC vs fwd RV)")
    print("=" * 80)
    print(f"  {'span':>5} {'pooled_IC':>11} {'perTicker_med':>14} {'%tick_IC>.1':>12}")
    rows1 = []
    for span in SPANS:
        col = f"fv_{span}"
        p[col] = p.groupby("ticker")["fwd_vrp"].transform(
            lambda s: s.ewm(span=span, adjust=False).mean()) if span > 1 else p["fwd_vrp"]
        ht = p.dropna(subset=["y_true"])
        pic = spearman(ht[col], ht["y_true"])
        ptic = per_ticker_ic(ht, col)
        rows1.append({"span": span, "pooled_ic": pic, "per_ticker_median": float(ptic.median()),
                      "pct_tickers_ic_gt_0.1": float((ptic > 0.1).mean())})
        print(f"  {span:>5} {pic:>+11.3f} {ptic.median():>+14.3f} {float((ptic>0.1).mean()):>11.0%}")
    sweep = pd.DataFrame(rows1)
    sweep.to_csv(OUT_DIR / "vrp_fwd_premium_battery_ewma_sweep.csv", index=False)
    best_span = int(sweep.loc[sweep["pooled_ic"].idxmax(), "span"])
    core = sweep[sweep["span"].isin([10, 21, 42])]["pooled_ic"]
    print(f"  best span={best_span} | core(10/21/42) IC range {core.min():.3f}-{core.max():.3f} "
          f"-> {'PLATEAU' if core.max()-core.min()<0.05 else 'check'}")

    EW = f"fv_{best_span}"   # chosen EWMA column

    # ── PART 2: IC BATTERY ───────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(f" PART 2: IC battery -- reflexive wedge vs raw fwd-VRP vs EWMA(span={best_span})")
    print("=" * 80)
    sigs = {"reflexive_wedge": "vrp_wedge", "fwd_vrp_raw": "fwd_vrp", f"fwd_vrp_ewma{best_span}": EW}
    rows2 = []
    for name, col in sigs.items():
        ht = p.dropna(subset=["y_true"])
        pooled = spearman(ht[col], ht["y_true"])
        ptic = per_ticker_ic(ht, col)
        ic_calm = spearman(ht[ht.regime == "calm"][col], ht[ht.regime == "calm"]["y_true"])
        ic_norm = spearman(ht[ht.regime == "normal"][col], ht[ht.regime == "normal"]["y_true"])
        ic_strs = spearman(ht[ht.regime == "stress"][col], ht[ht.regime == "stress"]["y_true"])
        ic_h1 = spearman(ht[ht.date <= SPLIT_DATE][col], ht[ht.date <= SPLIT_DATE]["y_true"])
        ic_h2 = spearman(ht[ht.date > SPLIT_DATE][col], ht[ht.date > SPLIT_DATE]["y_true"])
        # quintile lift on forward RV
        ht2 = ht.copy()
        ht2["q"] = pd.qcut(ht2[col], 5, labels=False, duplicates="drop")
        qmean = ht2.groupby("q")["y_true"].mean()
        lift = float(qmean.iloc[-1] - qmean.iloc[0]) if len(qmean) >= 2 else np.nan
        rows2.append({"signal": name, "pooled_ic": pooled, "per_ticker_med": float(ptic.median()),
                      "ic_calm": ic_calm, "ic_normal": ic_norm, "ic_stress": ic_strs,
                      "ic_2015_20": ic_h1, "ic_2021_26": ic_h2,
                      "q5_minus_q1_fwdvol": lift})
    bat = pd.DataFrame(rows2)
    with pd.option_context("display.width", 220, "display.float_format", lambda v: f"{v:+.3f}"):
        print(bat.to_string(index=False))
    bat.to_csv(OUT_DIR / "vrp_fwd_premium_battery_ic.csv", index=False)

    # ── PART 3: PREMIUM INTEGRITY UNDER EWMA ─────────────────────────────────
    print("\n" + "=" * 80)
    print(f" PART 3: premium integrity of EWMA(span={best_span}) -- sign + stress widening")
    print("=" * 80)
    g = p.groupby("regime")[EW].agg(["size", "mean", lambda s: float((s > 0).mean())])
    g.columns = ["n", "mean", "pct_pos"]
    g = g.reindex(["calm", "normal", "stress"])
    with pd.option_context("display.float_format", lambda v: f"{v:+.4f}"):
        print(g.to_string())
    print(f"  overall %positive {float((p[EW]>0).mean()):.1%}  | stress-calm widening "
          f"{g.loc['stress','mean']-g.loc['calm','mean']:+.4f} "
          f"({'WIDENS (premium-like)' if g.loc['stress','mean']>g.loc['calm','mean'] else 'narrows'})")

    # ── PART 4: SLOPE CONDITIONAL ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" PART 4: slope conditional -- does premium DIRECTION add over level?")
    print("=" * 80)
    p["fv_slope"] = p.groupby("ticker")[EW].transform(lambda s: s.diff(10))   # 10-BD premium change
    ht = p.dropna(subset=["y_true", "fv_slope"])
    ic_level = spearman(ht[EW], ht["y_true"])
    ic_slope = spearman(ht["fv_slope"], ht["y_true"])
    # combined rank
    htc = ht.copy()
    htc["combo"] = htc[EW].rank() + htc["fv_slope"].rank()
    ic_combo = spearman(htc["combo"], htc["y_true"])
    print(f"  IC(level, fwd RV)        : {ic_level:+.3f}")
    print(f"  IC(slope/widening, fwd RV): {ic_slope:+.3f}")
    print(f"  IC(level+slope combined) : {ic_combo:+.3f}  -> "
          f"{'slope ADDS' if ic_combo > ic_level + 0.02 else 'slope does NOT add over level'}")

    # ── PART 5: CROSS-SECTIONAL ROBUSTNESS ───────────────────────────────────
    print("\n" + "=" * 80)
    print(" PART 5: cross-sectional robustness (is the IC broad-based?)")
    print("=" * 80)
    ptic = per_ticker_ic(p.dropna(subset=["y_true"]), EW)
    print(f"  per-ticker IC: median {ptic.median():+.3f}  p25 {ptic.quantile(.25):+.3f}  "
          f"p75 {ptic.quantile(.75):+.3f}  %positive {float((ptic>0).mean()):.0%}  "
          f"%|IC|>0.1 {float((ptic.abs()>0.1).mean()):.0%}  (n={len(ptic)} tickers)")
    rng = np.random.default_rng(11)
    tickers = p["ticker"].unique()
    ht = p.dropna(subset=["y_true"])
    boot = []
    for _ in range(40):
        sub = rng.choice(tickers, 30, replace=False)
        h = ht[ht["ticker"].isin(sub)]
        boot.append(spearman(h[EW], h["y_true"]))
    boot = np.array(boot)
    print(f"  random 30-ticker subset pooled IC: mean {boot.mean():+.3f}  "
          f"p5 {np.percentile(boot,5):+.3f}  p95 {np.percentile(boot,95):+.3f}")
    pd.DataFrame({"per_ticker_ic": ptic}).to_csv(
        OUT_DIR / "vrp_fwd_premium_battery_perticker.csv")

    print("\n[VRP_BAT] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
