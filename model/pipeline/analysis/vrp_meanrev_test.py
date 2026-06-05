"""
vrp_meanrev_test.py -- Does the forward VRP have mean-reversion preemptive
                       prediction power for IV, RV, or itself?

Tests:
  1. AUTOCORRELATION profile of fwd_premium_ewma_21d at lags {5,10,21,42,63,126}
     (the decay = mean-reversion time scale; half-life of the premium).
  2. CONDITIONAL REVERSION: bucket dates by current own-percentile quintile
     (trailing 252-BD), measure avg own-percentile h BD later. If mean-reverting,
     extremes drift toward P50.
  3. COMPONENT DECOMPOSITION: when at Q5 (wide VRP), what shrinks the premium
     over the next h BD?  delta_VRP = delta_IV - delta_forecast.
  4. FORECASTING POWER for IV change: regression of delta_IV(t -> t+h) on
     current own-VRP-percentile. Negative coef = high VRP preemptively predicts
     IV compression.
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

LAGS = [5, 10, 21, 42, 63, 126]
ROLLING = 252
MIN_PERIODS = 63
HAC_LAGS = 42
START_DATE = pd.Timestamp("2015-01-01")


def trailing_pct(s: pd.Series, window: int = ROLLING,
                  min_periods: int = MIN_PERIODS) -> pd.Series:
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: (float((x[:-1] <= x[-1]).sum()) + 0.5) / len(x), raw=True)


def hac_t(y: pd.Series, x: pd.Series, lags: int = HAC_LAGS) -> dict:
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(d) < 50:
        return {"beta": np.nan, "t": np.nan, "p": np.nan, "n": 0}
    res = sm.OLS(d["y"].to_numpy(float),
                 sm.add_constant(d["x"].to_numpy(float))).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"alpha": float(res.params[0]), "beta": float(res.params[1]),
            "t": float(res.tvalues[1]), "p": float(res.pvalues[1]),
            "n": int(len(d))}


def load_panel() -> pd.DataFrame:
    rows = []
    for f in sorted(WEBAPP_DIR.glob("predictions_*.csv")):
        tk = f.stem.replace("predictions_", "")
        try:
            df = pd.read_csv(f, parse_dates=["date"],
                             usecols=["date", "iv_atm_30d", "pfv_cal_21",
                                      "fwd_premium_ewma_21d", "fwd_premium_21d"])
        except Exception:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        df["ticker"] = tk
        rows.append(df)
    p = pd.concat(rows, ignore_index=True)
    return p[p["date"] >= START_DATE].copy()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[VRP_MR] Loading panel + computing trailing own-percentiles...")
    p = load_panel()
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    p["own_pct"] = p.groupby("ticker")["fwd_premium_ewma_21d"].transform(trailing_pct)
    p["own_pct_raw"] = p.groupby("ticker")["fwd_premium_21d"].transform(trailing_pct)
    print(f"  {len(p):,} (ticker,date) rows | tickers {p['ticker'].nunique()}")

    # Forward-shifted columns
    for h in LAGS:
        p[f"vrp_t+{h}"]   = p.groupby("ticker")["fwd_premium_ewma_21d"].shift(-h)
        p[f"vrp_raw_t+{h}"] = p.groupby("ticker")["fwd_premium_21d"].shift(-h)
        p[f"pct_t+{h}"]   = p.groupby("ticker")["own_pct"].shift(-h)
        p[f"iv_t+{h}"]    = p.groupby("ticker")["iv_atm_30d"].shift(-h)
        p[f"fcst_t+{h}"]  = p.groupby("ticker")["pfv_cal_21"].shift(-h)

    # ── 1. AUTOCORRELATION PROFILE ───────────────────────────────────────────
    print("\n" + "=" * 82)
    print(" 1. AUTOCORRELATION PROFILE of fwd_premium_ewma_21d (per-ticker median)")
    print("    (autocorr = 1.0 means no mean-reversion; 0.0 = full reversion)")
    print("=" * 82)
    rows_ac = []
    print(f"  {'lag (BD)':<10}{'median':>9}{'mean':>9}{'p25':>9}{'p75':>9}{'~half-life (BD)':>20}")
    for h in LAGS:
        ac = p.groupby("ticker")["fwd_premium_ewma_21d"].apply(
            lambda s: s.autocorr(lag=h) if s.notna().sum() > h + 30 else np.nan
        ).dropna()
        if ac.empty: continue
        # estimated AR(1) half-life implied by median autocorr at this lag
        med = ac.median()
        hl = (-np.log(2) / np.log(med)) * h if 0 < med < 1 else float('inf') if med >= 1 else 0
        print(f"  {h:<10}{med:>+9.3f}{ac.mean():>+9.3f}{ac.quantile(.25):>+9.3f}"
              f"{ac.quantile(.75):>+9.3f}{hl:>20.1f}")
        rows_ac.append({"lag": h, "median_autocorr": float(med), "half_life_BD": float(hl)})
    pd.DataFrame(rows_ac).to_csv(OUT_DIR / "vrp_mr_autocorr.csv", index=False)

    # ── 2. CONDITIONAL REVERSION (quintile transition) ──────────────────────
    print("\n" + "=" * 82)
    print(" 2. CONDITIONAL REVERSION -- where does a stock's own-percentile go?")
    print("    Mean own-percentile h BD later, conditional on starting quintile:")
    print("=" * 82)
    p["q_now"] = pd.cut(p["own_pct"], bins=[-0.01,.2,.4,.6,.8,1.01],
                        labels=["Q1","Q2","Q3","Q4","Q5"])
    work = p.dropna(subset=["own_pct", "q_now"]).copy()
    print(f"  {'starting':<10}{'now':>7}" + "".join(f"{'t+'+str(h):>9}" for h in LAGS))
    for q in ["Q1","Q2","Q3","Q4","Q5"]:
        sub = work[work["q_now"] == q]
        if sub.empty: continue
        row = f"  {q:<10}{sub['own_pct'].mean():>7.2f}"
        for h in LAGS:
            future = sub[f"pct_t+{h}"].dropna()
            row += f"{future.mean():>9.2f}" if len(future) > 0 else f"{'NaN':>9}"
        print(row)
    print("  (Q5 starts ~0.90, Q1 starts ~0.10; convergence to ~0.50 = mean-reversion)")

    # ── 3. COMPONENT DECOMPOSITION (what shrinks the VRP?) ──────────────────
    print("\n" + "=" * 82)
    print(" 3. COMPONENT DECOMPOSITION -- when VRP is at extreme, what compresses it?")
    print("    For Q5-starters, conditional mean delta over t->t+h:")
    print("=" * 82)
    q5 = work[work["q_now"] == "Q5"].copy()
    q1 = work[work["q_now"] == "Q1"].copy()
    print(f"  {'horizon':<10}{'d_VRP_Q5':>12}{'d_IV_Q5':>10}{'d_Fcst_Q5':>12}"
          f"{'  ||  ':<8}{'d_VRP_Q1':>12}{'d_IV_Q1':>10}{'d_Fcst_Q1':>12}")
    for h in LAGS:
        dvrp_5 = (q5[f"vrp_t+{h}"] - q5["fwd_premium_ewma_21d"]).mean()
        div_5  = (q5[f"iv_t+{h}"]   - q5["iv_atm_30d"]).mean()
        df_5   = (q5[f"fcst_t+{h}"] - q5["pfv_cal_21"]).mean()
        dvrp_1 = (q1[f"vrp_t+{h}"] - q1["fwd_premium_ewma_21d"]).mean()
        div_1  = (q1[f"iv_t+{h}"]   - q1["iv_atm_30d"]).mean()
        df_1   = (q1[f"fcst_t+{h}"] - q1["pfv_cal_21"]).mean()
        print(f"  {h:<10}{dvrp_5*100:>+11.2f}pp{div_5*100:>+9.2f}pp{df_5*100:>+11.2f}pp"
              f"{'   ||':<8}{dvrp_1*100:>+11.2f}pp{div_1*100:>+9.2f}pp{df_1*100:>+11.2f}pp")
    print("  (Q5 = starts WIDE; negative d_VRP = compression. Decomp: delta_VRP = delta_IV - delta_Forecast)")

    # ── 4. REGRESSION delta_IV(t -> t+h) on current own_pct ──────────────────
    print("\n" + "=" * 82)
    print(" 4. PREEMPTIVE IV-CHANGE PREDICTION -- regress delta_IV on current VRP percentile")
    print("    (negative beta = wide VRP today predicts IV compression by t+h)")
    print("=" * 82)
    print(f"  {'horizon':<10}{'beta':>10}{'t (HAC)':>11}{'p':>10}{'n':>10}{'  verdict'}")
    for h in LAGS:
        d_iv = p[f"iv_t+{h}"] - p["iv_atm_30d"]
        d_vrp = p[f"vrp_t+{h}"] - p["fwd_premium_ewma_21d"]
        res_iv = hac_t(d_iv, p["own_pct"])
        res_vrp = hac_t(d_vrp, p["own_pct"])
        v = ("compresses IV" if res_iv["p"] < 0.05 and res_iv["beta"] < 0
             else "no IV effect")
        print(f"  d_IV @ t+{h:<3} beta {res_iv['beta']:>+8.4f}  t {res_iv['t']:>+6.2f}  "
              f"p {res_iv['p']:>7.3g}  n {res_iv['n']:>7,d}   {v}")
        vv = ("VRP mean-reverts" if res_vrp["p"] < 0.05 and res_vrp["beta"] < 0
              else "no VRP self-reversion at this lag")
        print(f"  d_VRP @ t+{h:<3}beta {res_vrp['beta']:>+8.4f}  t {res_vrp['t']:>+6.2f}  "
              f"p {res_vrp['p']:>7.3g}  n {res_vrp['n']:>7,d}   {vv}")
        print()

    print("[VRP_MR] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
